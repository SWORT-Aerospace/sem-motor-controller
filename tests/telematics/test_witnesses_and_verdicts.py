"""Cross-domain witnesses, advisory conclusions, common cause and evidence receipts (HOST-TESTED, synthetic inputs).

What these tests show: the relations apply only in their declared contexts, never compare non-admissible or
non-simultaneous evidence, report an inconsistency without naming a fault, localize only with two independent
agreeing witnesses, call a common cause supported only with direct evidence of a disturbance, and leave a receipt
from which every conclusion can be reconstructed. They are about the analysis code, not the vehicle.
"""
import dataclasses

from host.assurance import verdicts, witnesses as W
from host.telematics import evidence, lineage
from host.telematics import context as C
from host.telematics.evidence import Evidence
from host.telematics.measurement import Measurement

T = 50_000_000
PARAMS = {"wheel.circumference_m": 1.5, "wheel.ppr": 8, "drivetrain.gear_ratio": 10.0, "drivetrain.freewheel": False,
          "vehicle.coast_decel_mps2": 0.15}


def ev(signal, value, t=T, unc=10_000, validity="valid"):
    from host.telematics import signals
    meas = Measurement(1, signal.split(".")[0], signal, value if validity in ("valid", "unverified") else None,
                       signals.lookup(signal).unit, t, None, unc, None, validity, "test")
    return evidence.assess(signal, meas, T)


def derived(sig, v, src, t=T, unc=400_000):
    return Evidence(sig, "VALID", v, "m/s^2", None, t, unc, 0, src, "test", None, tuple(sorted(lineage.raw_sources(sig))))


def ctx(mode="CRUISE", speed=6.0, effort=True):
    return C.Context(mode, "test", speed, "gnss.speed", 0.0, "speed derivative", effort, {})


def snapshot(wl=6.0, wr=6.0, g=6.0):
    return {"wheel.wheel_l.speed": ev("wheel.wheel_l.speed", wl), "wheel.wheel_r.speed": ev("wheel.wheel_r.speed", wr),
            "gnss.speed": ev("gnss.speed", g), "gnss.speed_acc": ev("gnss.speed_acc", 0.08),
            "imu.gz": ev("imu.gz", 0.0), "ctrl.motor_speed": ev("ctrl.motor_speed", g / (1.5 / 6.283185307) * 10.0),
            "ctrl.dc_voltage": ev("ctrl.dc_voltage", 48.0), "ctrl.dc_current": ev("ctrl.dc_current", 3.0),
            "imu.ax": ev("imu.ax", 0.0)}


RELS = W.relation_set(["wheel_l", "wheel_r"], [], (("wheel_l", "wheel_r"),))


def evaluate(snap, c=None, params=PARAMS):
    c = c or ctx()
    return [W.evaluate(r, snap, c, {**params, "_ctx": c, "_now_s": T / 1e6, "_prev": {}}) for r in RELS]


def by_id(obs):
    return {o.relation: o for o in obs}


# ---------------------------------------------------------------- relation discipline
def test_every_relation_declares_contexts_tolerance_and_causes_and_names_no_fault():
    for r in RELS + [W.thermal_rate("temp.motor_case")]:
        d = r.definition()
        assert d["valid_contexts"] and d["tolerance"] and "PROVISIONAL" in d["tolerance"] and d["causes"]
        assert set(d["valid_contexts"]) <= set(C.MODES)
        assert not any(w in " ".join(d["causes"]).lower() for w in verdicts.FORBIDDEN_LABELS)
    assert W.set_hash(RELS) == W.set_hash(W.relation_set(["wheel_l", "wheel_r"], [], (("wheel_l", "wheel_r"),)))


def test_agreeing_sources_are_consistent_in_cruise_and_inapplicable_outside_their_context():
    o = by_id(evaluate(snapshot()))
    assert o["B1:wheel_l"].result == o["B3:wheel_l-wheel_r"].result == o["B2:wheel_l"].result == "CONSISTENT"
    o = by_id(evaluate(snapshot(), ctx("STOPPED", 0.0, False)))
    assert o["B1:wheel_l"].result == "INAPPLICABLE" and "STOPPED" in o["B1:wheel_l"].detail
    o = by_id(evaluate(snapshot(), ctx("STARTUP", None, None)))
    assert all(x.result in ("INAPPLICABLE", "INSUFFICIENT_EVIDENCE") for x in o.values())


def test_a_non_admissible_input_gives_insufficient_evidence_with_its_state_kept():
    s = snapshot()
    s["gnss.speed"] = ev("gnss.speed", 6.0, t=T - 5_000_000)                     # stale
    s["wheel.wheel_r.speed"] = ev("wheel.wheel_r.speed", None, validity="no_evidence")
    o = by_id(evaluate(s))
    assert o["B1:wheel_l"].result == "INSUFFICIENT_EVIDENCE" and o["B1:wheel_l"].rejected["gnss.speed"][0] == "STALE"
    assert o["B3:wheel_l-wheel_r"].rejected["wheel.wheel_r.speed"][0] == "UNKNOWN"
    assert "wheel.wheel_l.speed" in o["B1:wheel_l"].admitted


def test_unknown_parameters_and_unsimultaneous_inputs_are_not_compared():
    o = by_id(evaluate(snapshot(), params={**PARAMS, "drivetrain.gear_ratio": None}))
    assert o["B2:wheel_l"].result == "INSUFFICIENT_EVIDENCE" and "gear_ratio" in o["B2:wheel_l"].detail
    s = snapshot()
    s["gnss.speed"] = ev("gnss.speed", 6.0, t=T - 400_000)                       # fresh but 400 ms apart
    o = by_id(evaluate(s))
    assert o["B1:wheel_l"].result == "INSUFFICIENT_EVIDENCE" and "simultaneous" in o["B1:wheel_l"].detail
    s = snapshot()
    s["gnss.speed"] = ev("gnss.speed", 6.0, unc=None)                            # no timestamp bound
    o = by_id(evaluate(s))
    assert o["B1:wheel_l"].rejected["gnss.speed"][0] == "TIMING_UNCERTAIN"


def test_mode_dependent_validity_of_the_drivetrain_relation():
    p = {**PARAMS, "drivetrain.freewheel": True}
    o = by_id(evaluate(snapshot(), ctx("CRUISE", 6.0, False), p))
    assert o["B2:wheel_l"].result == "INAPPLICABLE" and "freewheel" in o["B2:wheel_l"].detail
    o = by_id(evaluate(snapshot(), ctx("CRUISE", 6.0, True), p))
    assert o["B2:wheel_l"].result == "CONSISTENT"


def test_effort_relation_needs_motion_and_effort():
    s = snapshot()
    s["imu.ax"] = ev("imu.ax", -0.9)
    s["ctrl.dc_current"] = ev("ctrl.dc_current", 4.0)
    o = by_id(evaluate(s, ctx("UNKNOWN", 4.0, True)))
    assert o["A1"].result == "INCONSISTENT" and "dragging brake" in " ".join(o["A1"].causes_if_inconsistent)
    o = by_id(evaluate(s, ctx("UNKNOWN", 0.5, True)))                             # below the speed floor
    assert o["A1"].result == "INAPPLICABLE"
    s["ctrl.dc_current"] = ev("ctrl.dc_current", 0.5)                             # 24 W: below the effort floor
    assert by_id(evaluate(s, ctx("UNKNOWN", 4.0, True)))["A1"].result == "INAPPLICABLE"


def test_imu_and_wheel_acceleration_are_compared_over_the_same_window():
    r = W.imu_vs_wheel_accel()
    s = {"accel.from_imu": derived("accel.from_imu", -0.85, "imu"),
         "accel.from_wheel": derived("accel.from_wheel", -0.9, "wheel")}
    c = ctx("UNKNOWN", 4.0, True)
    assert W.evaluate(r, s, c, {"_ctx": c}).result == "CONSISTENT"
    s["accel.from_imu"] = derived("accel.from_imu", -2.1, "imu")
    assert W.evaluate(r, s, c, {"_ctx": c}).result == "INCONSISTENT"
    s["accel.from_imu"] = derived("accel.from_imu", -0.85, "imu", unc=900_000)    # window too wide
    assert W.evaluate(r, s, c, {"_ctx": c}).result == "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------- conclusions: ambiguity and localization
def test_an_inconsistency_is_ambiguous_with_its_candidates_and_never_a_fault():
    obs = evaluate(snapshot(wl=5.1))
    concl = [verdicts.from_observation(o) for o in obs]
    amb = [c for c in concl if c.verdict == "AMBIGUOUS"]
    assert {c.subject for c in amb} >= {"B1:wheel_l", "B3:wheel_l-wheel_r", "B2:wheel_l"}
    for c in amb:
        assert c.candidates and "cause not isolated" in c.statement
        assert not any(w in c.statement.lower() for w in verdicts.FORBIDDEN_LABELS)
    assert all(c.verdict in verdicts.VERDICTS for c in concl)


def test_localization_needs_two_independent_witnesses_that_agree():
    loc = verdicts.localize(evaluate(snapshot(wl=5.1)))
    assert [c.subject for c in loc] == ["wheel.wheel_l.speed"] and loc[0].verdict == "AMBIGUOUS"
    assert "not isolated" in loc[0].statement and any("circumference" in x for x in loc[0].candidates)
    # one witness only (GNSS gone): an inconsistency, but nothing localized
    s = snapshot(wl=5.1)
    s["gnss.speed"] = ev("gnss.speed", None, validity="invalid")
    obs = [o for o in evaluate(s) if not o.relation.startswith("B2")]
    assert verdicts.localize(obs) == []
    # the two witnesses disagree with each other too: no localization
    assert verdicts.localize(evaluate(snapshot(wl=5.1, wr=7.0))) == []


def test_relations_of_different_quantities_never_localize():
    s = snapshot()
    s["imu.ax"] = ev("imu.ax", -0.9)
    s["ctrl.dc_current"] = ev("ctrl.dc_current", 4.0)
    obs = evaluate(s, ctx("UNKNOWN", 4.0, True))
    assert by_id(obs)["A1"].result == "INCONSISTENT"
    assert verdicts.localize(obs) == []


# ---------------------------------------------------------------- common cause (family C)
def test_simultaneous_loss_is_supported_only_with_direct_disturbance_evidence():
    onsets = [(T, "gnss", "gnss.speed", "STALE"), (T + 200_000, "imu", "imu.ax", "STALE")]
    out = verdicts.common_cause(onsets, 1_000_000, [])
    assert len(out) == 1 and out[0].verdict == "AMBIGUOUS" and "independent causes" in out[0].candidates
    out = verdicts.common_cause(onsets, 1_000_000, [(T + 100_000, "power:unit_supply", "reset cause BOR")])
    assert out[0].verdict == "SUPPORTED" and "power:unit_supply" in out[0].statement
    # a disturbance on a path the two do not share supports nothing
    out = verdicts.common_cause(onsets, 1_000_000, [(T, "bus:i2c1", "TEMP bus error")])
    assert out[0].verdict == "AMBIGUOUS"


def test_a_source_that_kept_working_exonerates_the_paths_it_shares():
    onsets = [(T, "gnss", "gnss.speed", "STALE"), (T + 100_000, "wheel", "wheel.wheel_l.speed", "UNKNOWN")]
    out = verdicts.common_cause(onsets, 1_000_000, [], lambda a, b: {"imu.ax", "batt.current"})
    assert out[0].verdict == "AMBIGUOUS" and "exonerated" in out[0].statement
    assert "no shared path of the model remains" in out[0].statement
    # one source alone is never a common-cause event
    assert verdicts.common_cause([(T, "gnss", "gnss.speed", "STALE")], 1_000_000, []) == []


# ---------------------------------------------------------------- receipts
META = {"schema_version": 1, "relation_set": W.set_hash(RELS), "data_class": "SIMULATED", "run_id": "TEST-B0001"}


def _receipt(snap):
    c = ctx()
    obs = evaluate(snap, c)
    concl = [verdicts.from_observation(o) for o in obs] + verdicts.localize(obs)
    return verdicts.receipt(T, c.as_dict(), {s: e.as_dict() for s, e in snap.items()}, obs, concl, META)


def test_a_receipt_answers_why_and_is_complete():
    r = _receipt(snapshot(wl=5.1))
    assert verdicts.receipt_problems(r) == []
    assert r["advisory_only"] is True and r["data_class"] == "SIMULATED"
    assert "localized to the evidence path of wheel.wheel_l.speed" in r["reason"]
    for o in r["observations"]:
        for s in [o["subject"]] + o["witnesses"]:
            assert s in o["admitted"] or s in o["rejected"]


def test_receipt_problems_finds_what_a_receipt_lacks():
    r = _receipt(snapshot(wl=5.1))
    assert verdicts.receipt_problems({k: v for k, v in r.items() if k != "context"}) == ["missing context"]
    bad = dict(r, advisory_only=False)
    assert "not marked advisory" in verdicts.receipt_problems(bad)
    bad = dict(r, observations=[dict(r["observations"][0], admitted={}, rejected={})] + r["observations"][1:])
    assert any("neither admitted nor rejected" in p for p in verdicts.receipt_problems(bad))
    c = dict(r["conclusions"][0], statement="motor fault detected")
    assert any("names a fault" in p for p in verdicts.receipt_problems(dict(r, conclusions=[c])))
    c = dict(r["conclusions"][0], basis=["X9"])
    assert any("cites relations" in p for p in verdicts.receipt_problems(dict(r, conclusions=[c])))


def test_conclusion_is_frozen_and_serialisable():
    c = verdicts.from_observation(evaluate(snapshot())[0])
    assert dataclasses.is_dataclass(c) and c.as_dict()["verdict"] in verdicts.VERDICTS
