"""Final evaluation: generated and run once, after the pre-registration commit.

    python3 research/run_final.py --commit <full hash of the pre-registration commit>

Every choice comes from research/preregistration.json, committed before any final episode existed:
the episode counts, the budgets, the frozen calibration, the endpoints and the analysis. This script:

  1. refuses to run unless every frozen file still has the SHA-256 recorded in the manifest, and the
     given commit is the one that added the manifest;
  2. derives the final seeds from that commit's hash, so no final episode can have influenced a choice;
  3. runs schedulers A to F on the same episodes (paired), the diagnostic comparison on identical
     records, and the ablations;
  4. writes research/generated/final/ (results.jsonl, compare.jsonl, summary.md, stats.json).
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import multiprocessing as mp
import os
import pathlib
import subprocess
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.bea import baselines as BL  # noqa: E402
from research.bea import diagnosis as D  # noqa: E402
from research.bea import episode as E  # noqa: E402
from research.bea import harness as H  # noqa: E402
from research.bea import schedulers as S  # noqa: E402
from research.bea.relations import Study, build_window  # noqa: E402
from research.bea.scoring import confidence, coverage_at_risk, score, selective  # noqa: E402

MANIFEST = ROOT / "research" / "preregistration.json"
OUT = ROOT / "research" / "generated" / "final"
FRAME_CHANNELS = ("motion", "currents", "cmd", "wheel")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_freeze(man: dict, commit: str) -> None:
    bad = [p for p, h in man["frozen_sha256"].items() if sha256(ROOT / p) != h]
    if bad:
        raise SystemExit(f"frozen files changed since pre-registration: {bad}")
    added = subprocess.run(["git", "log", "--diff-filter=A", "--format=%H", "--", str(MANIFEST.relative_to(ROOT))],
                           cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not added or added[-1] != commit:
        raise SystemExit(f"{commit} is not the commit that added the manifest ({added[-1] if added else 'none'})")


def seeds(commit: str, n: int, salt: str) -> list[int]:
    return [int(hashlib.sha256(f"{commit}:{salt}:{i}".encode()).hexdigest()[:12], 16) for i in range(n)]


def config(man: dict) -> E.RunConfig:
    eng = D.engine_from_calibration(man["calibration"])
    return E.RunConfig(engine=eng, byte_budget=man["budgets"]["byte_budget"], deadline_s=man["budgets"]["deadline_s"],
                       decide_after_s=man["budgets"]["decide_after_s"])


def make_variant(name: str, rc: E.RunConfig, d_budget: int, seed: int) -> tuple:
    """(scheduler, run configuration) for a scheduler A to F or an ablation of F."""
    if name == "F_notiming":
        rc = dataclasses.replace(rc, engine=dataclasses.replace(rc.engine, timing=False))
        return S.AmbiguityDirected(rc), rc
    if name == "F_doublecount":
        rc = dataclasses.replace(rc, double_count=True)
        return S.AmbiguityDirected(rc), rc
    if name == "F_noamb":
        return S.AmbiguityDirectedNoAmbiguity(rc), rc
    if name == "D":
        return S.RandomBursts(rc, d_budget, seed), rc
    return {"A": S.FixedLow, "B": S.FixedHigh, "C": S.EventCapture, "E": S.InformationGain,
            "F": S.AmbiguityDirected}[name](rc), rc


def episode_rows(ep, spec, names: list, rc: E.RunConfig, d_budget: int, seed: int) -> list:
    """Every scheduler and ablation on one episode (the same records for all: paired)."""
    rows = []
    for name in names:
        sch, rc_i = make_variant(name, rc, d_budget, seed % 100000)
        t0 = time.time()
        res = E.run_episode(ep, sch, rc_i)
        rows.append({"seed": seed, "kind": spec.fault.kind, "cycle": spec.cycle, "size": spec.fault.size, "scheduler": name,
                     **{k: res[k] for k in ("outcome", "hypotheses", "bytes", "requests", "cpu_s", "J")},
                     "confidence": confidence(res), **score(res, spec.fault.onset_s, rc.imu_available),
                     "wall_s": round(time.time() - t0, 2), "reason": res["reason"][:300]})
    return rows


# ----------------------------------------------------------------------------- workers
def _episode_worker(args) -> dict:
    seed, kind, split, man = args
    spec = H.draw_episode(seed, split, kind)
    ep = H.run_vehicle(spec)
    rc = config(man)
    rows = episode_rows(ep, spec, man["schedulers"] + man["ablations"]["schedulers"], rc,
                        man["budgets"]["d_budget_bytes"], seed)
    comp = compare_on_identical_records(ep, man, rc)
    return {"rows": rows, "compare": {"seed": seed, "kind": kind, **comp}}


def window_blocks(ep, t0: float, t1: float, st: Study, source: str):
    """Blocks from identical records for every engine: full-rate frames, or the summary, in [t0, t1]."""
    clk = ep.spec.link.clock
    if source == "frames":
        acc = H.Access(ep)
        acc.advance(t1 + 1.0)
        eta = acc.request(H.Request("buffer", FRAME_CHANNELS, clk.local(t0), clk.local(t1)))
        _, resp = acc.advance(eta + 0.01)
        sig = D.signals_from_frames(resp[0].records, clk.local(t0), clk.local(t1), st)
        return build_window(sig, st, {"R1": 100.0, "R2": 10.0, "R3": 100.0, "R4": 10.0}) if sig is not None else []
    msgs = [m for m in ep.summaries if clk.local(t0) <= m["t_local_ms"] / 1000.0 <= clk.local(t1)]
    sig = D.signals_from_summaries(msgs, st)
    return build_window(sig, st, E.SUMMARY_RELS) if sig is not None else []


def compare_on_identical_records(ep, man: dict, rc: E.RunConfig) -> dict:
    st = Study()
    t0, t1 = man["compare"]["window_s"]
    out = {}
    fm = BL.FrozenMonitors(**_frozen_from_manifest(man))
    clk = ep.spec.link.clock
    stream = BL.adapter_stream(ep.log, st.motor.kt, clk.local(t1))
    for name, r in fm.run(stream, clk.local(t0), clk.local(t1)).items():
        out[name] = r
    for source in ("frames", "summary"):
        blocks = D.calibrate_blocks(window_blocks(ep, t0, t1, st, source), rc.engine, source)
        timing = 0.005 if source == "frames" else None
        d = D.diagnose_blocks(blocks, rc.engine, timing, source=source)
        out[f"reference/{source}"] = {"outcome": d.outcome, "hypotheses": d.hypotheses}
        out[f"MHT/{source}"] = {k: v for k, v in BL.mht(blocks, timing_s=timing, noise_scale=rc.engine.noise_scale,
                                                         p_accept=man["compare"]["mht_p_accept"],
                                                         prior_h0=man["calibration"]["mht_prior_h0"][source]).items()
                                if not k.startswith("posterior")}
        al = BL.aligned_residual(blocks, man["calibration"]["aligned_thresholds"][source], rc.engine.noise_scale)
        out[f"aligned/{source}"] = {"outcome": al["outcome"], "hypotheses": al["hypotheses"]}
    return out


def _frozen_from_manifest(man: dict) -> dict:
    from host.csia_adapter.adapter_v2 import E6Model
    f = man["calibration"]["frozen_monitors"]
    return {"e6": E6Model(**f["e6"]), "lam": f["lam"], "trust_thr": f["trust_thr"], "report": {}}


# ----------------------------------------------------------------------------- statistics
CATS = ("correct", "wrong", "unresolved_incl", "unresolved_excl", "no_fit", "missed", "undecided")


def bootstrap_diff(a: np.ndarray, b: np.ndarray, n: int = 4000, seed: int = 1) -> tuple:
    """Paired difference of means (a - b) over episodes, with a percentile bootstrap 95 % interval."""
    if len(a) == 0:
        return math.nan, math.nan, math.nan
    rng = np.random.default_rng(seed)
    d = a - b
    idx = rng.integers(0, len(d), (n, len(d)))
    boots = d[idx].mean(axis=1)
    return float(d.mean()), float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))


def _risk_cov(R: dict, ids: list, cov: float, risk: float) -> tuple:
    conf = [R[s]["confidence"] for s in ids]
    wrong = [R[s]["category"] == "wrong" for s in ids]
    return selective(conf, wrong, len(ids), cov), coverage_at_risk(conf, wrong, len(ids), risk)


def matched(A: dict, B: dict, common: list, target_risk: float, n_boot: int, seed: int = 2) -> dict:
    """Risk at matched coverage (the lower of the two coverages: the more confident decisions of the
    scheduler that commits more often are compared with all decisions of the other) and coverage at the
    pre-registered risk, each as a paired difference a - b with a bootstrap 95 % interval over episodes."""
    if not common:
        return {"matched_coverage": math.nan, "risk_diff": math.nan, "risk_diff_ci": [math.nan, math.nan],
                "target_risk": target_risk, "coverage_diff": math.nan, "coverage_diff_ci": [math.nan, math.nan], "n": 0}

    def stat(ids):
        cov = min(sum(A[s]["category"] in ("correct", "wrong") for s in ids),
                  sum(B[s]["category"] in ("correct", "wrong") for s in ids)) / len(ids)
        ra, ca = _risk_cov(A, ids, cov, target_risk)
        rb, cb = _risk_cov(B, ids, cov, target_risk)
        return cov, ra - rb, ca - cb
    cov, dr, dc = stat(common)
    rng = np.random.default_rng(seed)
    boots = np.array([stat([common[i] for i in rng.integers(0, len(common), len(common))]) for _ in range(n_boot)])
    q = lambda col: [float(np.nanquantile(boots[:, col], p)) for p in (0.025, 0.975)]
    return {"matched_coverage": cov, "risk_diff": dr, "risk_diff_ci": q(1), "target_risk": target_risk,
            "coverage_diff": dc, "coverage_diff_ci": q(2), "n": len(common)}


def analyse(rows: list, comp: list, man: dict) -> dict:
    stats = {"schedulers": {}, "pairs": {}, "compare": {}}
    faults = [r for r in rows if r["truth"] in ("HB", "HT", "HL")]
    for sch in sorted({r["scheduler"] for r in rows}):
        f = [r for r in faults if r["scheduler"] == sch]
        h0 = [r for r in rows if r["scheduler"] == sch and r["truth"] == "H0"]
        hu = [r for r in rows if r["scheduler"] == sch and r["truth"] == "HU"]
        sup = [r for r in f if r["category"] in ("correct", "wrong")]
        stats["schedulers"][sch] = {
            "n_fault": len(f), **{c: sum(r["category"] == c for r in f) for c in CATS},
            "coverage": len(sup) / len(f) if f else math.nan,
            "risk": sum(r["category"] == "wrong" for r in sup) / len(sup) if sup else math.nan,
            "true_in_set": sum(r["true_in_set"] for r in f) / len(f) if f else math.nan,
            "mean_set_size": float(np.mean([r["set_size"] for r in f])) if f else math.nan,
            "false_alarms_per_clean_hour": sum(r["category"] != "clean" for r in h0) / (len(h0) * 90.0 / 3600.0) if h0 else math.nan,
            "wrong_cause_on_clean": sum(r["category"] == "false_alarm_wrong" for r in h0),
            "unmodelled_reported_no_fit": sum(r["category"] == "correct" for r in hu), "n_unmodelled": len(hu),
            "mean_bytes": float(np.mean([r["bytes"] for r in rows if r["scheduler"] == sch])),
            "median_decide_delay_s": float(np.median([r["decide_delay_s"] for r in f if r["decide_delay_s"] is not None]))
            if any(r["decide_delay_s"] is not None for r in f) else math.nan,
            "median_cpu_s": float(np.median([r["cpu_s"] for r in rows if r["scheduler"] == sch])),
            "by_truth": {t: {c: sum(r["category"] == c for r in f if r["truth"] == t) for c in CATS}
                         for t in ("HB", "HT", "HL")},
        }
    for a, b in man["analysis"]["paired"]:
        A = {r["seed"]: r for r in faults if r["scheduler"] == a}
        Bd = {r["seed"]: r for r in faults if r["scheduler"] == b}
        common = sorted(set(A) & set(Bd))
        for metric in ("correct", "wrong"):
            x = np.array([A[s]["category"] == metric for s in common], float)
            y = np.array([Bd[s]["category"] == metric for s in common], float)
            stats["pairs"][f"{a}-{b}/{metric}"] = dict(zip(("diff", "lo", "hi"), bootstrap_diff(x, y)), n=len(common))
        x = np.array([A[s]["bytes"] for s in common], float)
        y = np.array([Bd[s]["bytes"] for s in common], float)
        stats["pairs"][f"{a}-{b}/bytes"] = dict(zip(("diff", "lo", "hi"), bootstrap_diff(x, y)), n=len(common))
        stats["pairs"][f"{a}-{b}/matched"] = matched(A, Bd, common, man["analysis"]["target_risk"],
                                                     man["analysis"]["bootstrap_resamples"])
    truth_of = {"none": "H0", "HB": "HB", "HT": "HT", "HL": "HL", "HL_grade": "HL", "HU_gain": "HU"}
    engines = sorted({k for c in comp for k in c if "/" in k or k in ("R3v", "CSIA2")} - {"seed", "kind"})
    for eng in engines:
        cats = {}
        for c in comp:
            t = truth_of.get(c["kind"], "multiple")
            o = c[eng]
            hyps = tuple(o["hypotheses"])
            if t == "H0":
                cat = "clean" if o["outcome"] in ("consistent", "insufficient") else "false_alarm"
            elif t == "HU":
                cat = "correct" if o["outcome"] == "no_fit" else "wrong" if o["outcome"] == "supported" else "other"
            elif o["outcome"] == "supported":
                cat = "correct" if hyps[0] == t else "wrong"
            elif o["outcome"] == "unresolved":
                cat = "unresolved_incl" if t in hyps else "unresolved_excl"
            else:
                cat = {"consistent": "missed", "insufficient": "missed"}.get(o["outcome"], o["outcome"])
            cats.setdefault(t, {}).setdefault(cat, 0)
            cats[t][cat] += 1
        stats["compare"][eng] = cats
    return stats


# ----------------------------------------------------------------------------- pre-registered endpoints
def wilson(k: int, n: int, z: float = 1.959964) -> tuple:
    """Wilson score 95 % interval of a proportion k / n (episodes are independent draws)."""
    if n == 0:
        return math.nan, math.nan
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, c - h), min(1.0, c + h)


def compare_category(c: dict, eng: str) -> str:
    """Category of one engine's outcome on one episode's identical records (evaluator only)."""
    t = {"none": "H0", "HB": "HB", "HT": "HT", "HL": "HL", "HL_grade": "HL", "HU_gain": "HU"}[c["kind"]]
    o = c[eng]
    hyps = tuple(o["hypotheses"])
    if t == "H0":
        return "clean" if o["outcome"] in ("consistent", "insufficient") else "false_alarm"
    if t == "HU":
        return "correct" if o["outcome"] == "no_fit" else "wrong" if o["outcome"] == "supported" else "other"
    if o["outcome"] == "supported":
        return "correct" if hyps[0] == t else "wrong"
    if o["outcome"] == "unresolved":
        return "unresolved_incl" if t in hyps else "unresolved_excl"
    return {"consistent": "missed", "insufficient": "missed"}.get(o["outcome"], o["outcome"])


def endpoints(rows: list, comp: list, man: dict) -> list:
    """Every endpoint of the manifest, evaluated mechanically against its pre-registered criterion."""
    n_boot, seed = man["analysis"]["bootstrap_resamples"], man["analysis"]["bootstrap_seed"]
    truths = {"faults": ("HB", "HT", "HL"), "HT": ("HT",), "HU": ("HU",), "H0": ("H0",)}
    by = {}
    for r in rows:
        by.setdefault(r["scheduler"], {})[r["seed"]] = r
    out = []
    for e in man["endpoints"]:
        res = {"id": e["id"], "question": e["question"], "criterion": e["criterion"]}
        if e["kind"] == "paired":
            A, B = by[e["a"]], by[e["b"]]
            ids = sorted(k for k in set(A) & set(B) if A[k]["truth"] in truths[e["episodes"]])
            for metric in e["metrics"]:
                f = (lambda r: float(r["bytes"])) if metric == "bytes" else (lambda r, m=metric: float(r["category"] == m))
                d, lo, hi = bootstrap_diff(np.array([f(A[k]) for k in ids]), np.array([f(B[k]) for k in ids]), n_boot, seed)
                res[metric] = {"diff": d, "lo": lo, "hi": hi, "n": len(ids)}
        elif e["kind"] == "paired_engines":
            ids = [c for c in comp if c["kind"] in e["kinds"]]
            x = np.array([compare_category(c, e["a"]) == "correct" for c in ids], float)
            y = np.array([compare_category(c, e["b"]) == "correct" for c in ids], float)
            d, lo, hi = bootstrap_diff(x, y, n_boot, seed)
            res["correct"] = {"diff": d, "lo": lo, "hi": hi, "n": len(ids)}
        elif e["kind"] == "proportion":
            R = [r for r in by[e["scheduler"]].values() if r["truth"] in truths[e["episodes"]]]
            if e.get("among") == "supported":
                R = [r for r in R if r["category"] in ("correct", "wrong")]
            k = sum(r["category"] in e["categories"] for r in R)
            lo, hi = wilson(k, len(R))
            res["proportion"] = {"k": k, "n": len(R), "p": k / len(R) if R else math.nan, "lo": lo, "hi": hi}
        res["met"] = _criterion(e["criterion"], res)
        out.append(res)
    return out


def _criterion(c: dict, res: dict):
    """A criterion is a list of tests on interval bounds, all of which must hold; None means descriptive."""
    if not c:
        return None
    ok = True
    for t in c:
        v = res[t["of"]][t["bound"]]
        ok &= bool(v > t["value"]) if t["op"] == ">" else bool(v < t["value"])
    return ok


def render(stats: dict, man: dict, meta: dict) -> str:
    L = ["# Final evaluation results", "",
         f"Generated by `research/run_final.py` from pre-registration commit `{meta['commit']}`; do not edit.",
         "Synthetic host simulation only: no result here is a vehicle or bench measurement.",
         f"Episodes: {meta['episodes']}; wall time {meta['seconds']} s.", "",
         "## Pre-registered endpoints", "",
         "Each criterion was fixed in `research/PREREGISTRATION.md` before any final episode existed; "
         "\"descriptive\" endpoints carry no criterion.", "",
         "| Endpoint | question | estimate (95 % interval) | criterion | met |", "|---|---|---|---|---|"]
    for e in stats["endpoints"]:
        parts = []
        for k in ("correct", "wrong", "bytes"):
            if k in e:
                v = e[k]
                fmt = "{:+.0f}" if k == "bytes" else "{:+.3f}"
                parts.append(f"{k} {fmt.format(v['diff'])} [{fmt.format(v['lo'])}, {fmt.format(v['hi'])}], n {v['n']}")
        if "proportion" in e:
            v = e["proportion"]
            parts.append(f"{v['k']}/{v['n']} = {v['p']:.3f} [{v['lo']:.3f}, {v['hi']:.3f}]")
        crit = "; ".join(f"{t['of']} {t['bound']} {t['op']} {t['value']:g}" for t in e["criterion"]) or "descriptive"
        met = "descriptive" if e["met"] is None else ("yes" if e["met"] else "no")
        L.append(f"| {e['id']} | {e['question']} | {'; '.join(parts)} | {crit} | {met} |")
    L += ["", "## Schedulers (same diagnostic engine, paired episodes)", "",
         "| Scheduler | fault episodes | correct | wrong | unresolved (true in set) | unresolved (true not in set) | no fit | missed | undecided | coverage | risk | false alarms per clean hour | wrong cause on clean | unmodelled reported as no fit | mean bytes | median decision delay [s] |",
         "|---|" + "---|" * 15]
    for sch, s in stats["schedulers"].items():
        L.append(f"| {sch} | {s['n_fault']} | " + " | ".join(str(s[c]) for c in CATS) +
                 f" | {s['coverage']:.2f} | {s['risk']:.2f} | {s['false_alarms_per_clean_hour']:.1f} | {s['wrong_cause_on_clean']} | "
                 f"{s['unmodelled_reported_no_fit']}/{s['n_unmodelled']} | {s['mean_bytes']:.0f} | {s['median_decide_delay_s']:.1f} |")
    L += ["", "By true cause (correct / wrong / missed):", "", "| Scheduler | HB | HT | HL |", "|---|---|---|---|"]
    for sch, s in stats["schedulers"].items():
        b = s["by_truth"]
        L.append(f"| {sch} | " + " | ".join(f"{b[t]['correct']} / {b[t]['wrong']} / {b[t]['missed']}" for t in ("HB", "HT", "HL")) + " |")
    L += ["", "## Paired differences (bootstrap 95 % intervals over episodes)", "", "| Comparison | difference | interval | n |",
          "|---|---|---|---|"]
    for k, v in stats["pairs"].items():
        if k.endswith("/matched"):
            continue
        L.append(f"| {k} | {v['diff']:+.3f} | [{v['lo']:+.3f}, {v['hi']:+.3f}] | {v['n']} |")
    L += ["", "Risk at matched coverage, and coverage at the pre-registered risk "
          f"({man['analysis']['target_risk']:g}), paired over fault episodes:", "",
          "| Comparison | matched coverage | risk difference | interval | coverage difference | interval |",
          "|---|---|---|---|---|---|"]
    for k, v in stats["pairs"].items():
        if k.endswith("/matched"):
            L.append(f"| {k[:-8]} | {v['matched_coverage']:.2f} | {v['risk_diff']:+.3f} | [{v['risk_diff_ci'][0]:+.3f}, "
                     f"{v['risk_diff_ci'][1]:+.3f}] | {v['coverage_diff']:+.3f} | [{v['coverage_diff_ci'][0]:+.3f}, "
                     f"{v['coverage_diff_ci'][1]:+.3f}] |")
    L += ["", "## Diagnostic engines on identical records", "",
          f"Records in {man['compare']['window_s'][0]:g} to {man['compare']['window_s'][1]:g} s of every episode (after every onset).", "",
          "| Engine | true cause | outcome counts |", "|---|---|---|"]
    for eng, by in stats["compare"].items():
        for t, cats in sorted(by.items()):
            L.append(f"| {eng} | {t} | " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())) + " |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", required=True)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    man = json.loads(MANIFEST.read_text())
    check_freeze(man, a.commit)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    jobs = []
    for kind, n in man["episodes"].items():
        jobs += [(s, kind, "final", man) for s in seeds(a.commit, n, kind)]
    t0 = time.time()
    with mp.Pool(a.procs) as pool:
        out = pool.map(_episode_worker, jobs, chunksize=1)
    rows = [r for o in out for r in o["rows"]]
    comp = [o["compare"] for o in out]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (OUT / "compare.jsonl").write_text("".join(json.dumps(c) + "\n" for c in comp))
    stats = analyse(rows, comp, man)
    stats["endpoints"] = endpoints(rows, comp, man)
    meta = {"commit": a.commit, "episodes": len(jobs), "seconds": round(time.time() - t0)}
    (OUT / "stats.json").write_text(json.dumps({"meta": meta, **stats}, indent=1, default=float) + "\n")
    (OUT / "summary.md").write_text(render(stats, man, meta))
    print((OUT / "summary.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
