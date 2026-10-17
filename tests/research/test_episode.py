"""Episode runner and schedulers: evidence assembly, ablation switches, byte limit, one full episode each."""
import dataclasses

import pytest

from research.bea import diagnosis as D
from research.bea import episode as E
from research.bea import harness as H
from research.bea import schedulers as S
from research.bea.scoring import score


@pytest.fixture(scope="module")
def hb_episode():
    spec = H.draw_episode(31, "test", "HB", cycle="pulse_coast")
    spec = dataclasses.replace(spec, fault=dataclasses.replace(spec.fault, size=0.3, onset_s=25.0))
    return H.run_vehicle(spec)


def _view_with_segment(ep, t0, t1):
    acc = H.Access(ep)
    first, _ = acc.advance(t1 + 15.0)
    clk = ep.spec.link.clock
    eta = acc.request(H.Request("buffer", ("motion", "currents", "cmd", "wheel"), clk.local(t0), clk.local(t1)))
    later, resp = acc.advance(eta + 0.01)
    summaries = first + later
    r = resp[0]
    seg = E.Segment(clk.local(t0), clk.local(t1), r.request.channels, 1, r.records)
    return E.View(acc.now_local(), summaries, [seg], 0, clk.local(t0), None, None, 0.005, 0, 200000, False, [], None)


def test_summary_is_not_used_where_frames_cover_the_time(hb_episode):
    clk = hb_episode.spec.link.clock
    view = _view_with_segment(hb_episode, 40.0, 50.0)
    blocks, desc = E.evidence_blocks(view, clk.local(35.0), clk.local(60.0), E.Study())
    summary_blocks = [b for b in blocks if b.name in ("R1s", "R2s")]
    for b in summary_blocks:                       # no summary sample inside the frame segment
        assert not any(clk.local(40.0) + 0.5 < t < clk.local(50.0) - 0.5 for t in b.times)
    blocks2, _ = E.evidence_blocks(view, clk.local(35.0), clk.local(60.0), E.Study(), double_count=True)
    assert sum(b.n for b in blocks2) > sum(b.n for b in blocks)        # the ablation does count them twice


def test_timing_ablation_drops_the_timing_hypothesis(hb_episode):
    view = _view_with_segment(hb_episode, 40.0, 50.0)
    blocks, _ = E.evidence_blocks(view, view.segments[0].t0, view.segments[0].t1, E.Study())
    d = D.diagnose_blocks(blocks, D.EngineConfig(timing=False), 0.005, source="frames")
    assert "HT" not in d.J
    d2 = D.diagnose_blocks(blocks, D.EngineConfig(), 0.005, source="frames")
    assert "HT" in d2.J


def test_ambiguity_ablation_keeps_every_hypothesis_open(hb_episode):
    rc = E.RunConfig()
    view = _view_with_segment(hb_episode, 40.0, 50.0)
    view.current = D.Diagnosis("supported", ("HB",), {}, {}, 1, (), {}, 0.005, (0, 1), "")
    assert S.AmbiguityDirected(rc).open_set(view) == ("HB",)
    assert S.AmbiguityDirectedNoAmbiguity(rc).open_set(view) == S.HYPS


@pytest.mark.parametrize("make", [S.FixedLow, S.AmbiguityDirected])
def test_a_bias_episode_end_to_end(hb_episode, make):
    rc = E.RunConfig()
    res = E.run_episode(hb_episode, make(rc), rc)
    sc = score(res, hb_episode.spec.fault.onset_s)
    assert sc["category"] in ("correct", "unresolved_incl")
    assert res["bytes"] <= rc.byte_budget
    if make is S.FixedLow:
        assert res["bytes"] == 0 and res["requests"] == 0          # the summary only


def test_requests_never_exceed_the_byte_limit(hb_episode):
    rc = E.RunConfig(byte_budget=20000)
    res = E.run_episode(hb_episode, S.FixedHigh(rc), rc)
    assert res["bytes"] <= 20000 + 200                              # estimate against actual framing
