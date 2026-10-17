#!/usr/bin/env python3
"""CSIA v2 evaluation (SYNTHETIC, shadow mode). Protocol: docs/csia/EVALUATION_PROTOCOL_v2.md.

    python3 tools/run_csia_evaluation_v2.py --dev       # development set; repeatable
    python3 tools/run_csia_evaluation_v2.py --freeze    # record hashes + dev calibration (commit before --eval)
    python3 tools/run_csia_evaluation_v2.py --eval      # untouched evaluation set, once

--eval refuses to run if any frozen file differs from docs/csia/V2_FREEZE.json
or if the evaluation results already exist. It uses the E6 model and the
thresholds recorded at the freeze, never a re-calibration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from host.csia_adapter import eval_set_v2 as ES2  # noqa: E402
from host.csia_adapter import evaluation as EV  # noqa: E402
from host.csia_adapter import evaluation_v2 as EV2  # noqa: E402
from host.csia_adapter.adapter_v2 import E6Model, calibrate_e6  # noqa: E402
from host.csia_adapter.synthetic import params  # noqa: E402
from tools import run_csia_evaluation as RE  # noqa: E402

FROZEN = ["host/csia_adapter/adapter.py", "host/csia_adapter/adapter_v2.py", "host/csia_adapter/synthetic.py",
          "host/csia_adapter/baselines.py", "host/csia_adapter/eval_set.py", "host/csia_adapter/eval_set_v2.py",
          "host/csia_adapter/evaluation.py", "host/csia_adapter/evaluation_v2.py", "tools/run_csia_evaluation.py",
          "tools/run_csia_evaluation_v2.py", "third_party/csia-trust-layer.lock", "docs/csia/EVALUATION_PROTOCOL_v2.md"]
FREEZE = ROOT / "docs" / "csia" / "V2_FREEZE.json"
OUT_EVAL = ROOT / "docs" / "generated" / "csia_v2_evaluation_synthetic"
OUT_DEV = ROOT / "docs" / "generated" / "csia_v2_development_synthetic"


def hashes():
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FROZEN}


def _work(args):
    scn, lam, trust_thr, e6 = args
    data = ES2.generate(scn)
    ms = EV2.make_monitors(lam, trust_thr, E6Model(**e6))
    outs, cpu, ticks = EV2.run_stream_timed(data, scn.duration_s, ms)
    elig = [(t, o.eligible) for t, o in outs["CSIA2"]]
    return scn.seed, EV.score(outs, scn, elig), cpu, ticks


def dev_calibration(jobs: int):
    dev = ES2.dev_set()
    nominal = [s for s in dev if s.fault is None]
    with mp.Pool(jobs) as pool:
        nom_data = pool.map(ES2.generate, nominal)
        kt = params().kt_Nm_per_A
        e6, fit = calibrate_e6(nom_data, kt)
        lam, info, trust_thr = EV2.calibrate(list(zip(nominal, nom_data)), e6, pool.map)
    return dev, nominal, nom_data, e6, fit, lam, info, trust_thr


def run_set(scns, lam, trust_thr, e6: E6Model, jobs):
    t0 = time.time()
    e6d = e6.__dict__
    with mp.Pool(jobs) as pool:
        res = pool.map(_work, [(s, lam, trust_thr, e6d) for s in scns])
    results = [(seed, sc) for seed, sc, _c, _n in res]
    cpu = {m: sum(c[m] for _s, _sc, c, _n in res) for m in EV2.MONITOR_ORDER}
    ticks = sum(n for *_x, n in res)
    RE.MONITOR_ORDER = EV2.MONITOR_ORDER        # RE.aggregate reads its module-level order
    agg = RE.aggregate(results, scns)
    for m in EV2.MONITOR_ORDER:
        agg[m]["coverage"] = (agg[m]["n_faults"] - agg[m]["missed"]) / agg[m]["n_faults"] if agg[m]["n_faults"] else None
        agg[m]["tick_ms_mean"] = 1e3 * cpu[m] / ticks
    return agg, time.time() - t0


def memory(nominal_scn, data, e6, lam, trust_thr):
    f = {"B1": lambda: EV2.Debounce(EV.B1()),
         "R3": lambda: EV2.Debounce(EV2.ResidualV2("R3", "none", lam, e6)),
         "R3v": lambda: EV2.Debounce(EV2.ResidualV2("R3v", "vote", lam, e6)),
         "CSIA1": lambda: EV2.Debounce(EV2.Csia1()), "CSIA2": lambda: EV2.Debounce(EV2.Csia2(e6)),
         "TRUST2": lambda: EV2.Debounce(EV2.Trust2(trust_thr, e6)), "B1+CSIA2": lambda: EV2.UnionV2(e6)}
    return {m: EV2.peak_memory_kib(f[m], data, min(nominal_scn.duration_s, 60.0)) for m in EV2.MONITOR_ORDER}


def decision(agg: dict) -> dict:
    """Pre-registered rule (protocol section 6): the adapter's increment over the
    simpler majority vote is supported only if it attributes at least 5 more
    faults, with at most 1 more misattribution and at most 1.0 more false-alarm
    episode per hour. The same rule judges TrustCore against R3v."""
    def inc(m):
        a, b = agg[m], agg["R3v"]
        d = {"more_attributed": a["attributed"] - b["attributed"],
             "more_misattributed": a["misattributed"] - b["misattributed"],
             "more_fa_per_h": a["fa_per_h"] - b["fa_per_h"]}
        d["supported"] = d["more_attributed"] >= 5 and d["more_misattributed"] <= 1 and d["more_fa_per_h"] <= 1.0
        return d
    return {"CSIA2_vs_R3v": inc("CSIA2"), "TRUST2_vs_R3v": inc("TRUST2"),
            "recommended": "CSIA2" if inc("CSIA2")["supported"] else "R3v"}


def report(agg, meta, title) -> str:
    L = [f"# {title}", "", "SYNTHETIC, shadow mode. Protocol: `docs/csia/EVALUATION_PROTOCOL_v2.md`. "
         "Every monitor passes through the same 3-tick node-level debounce.", "",
         f"Scenarios: {meta['n_scenarios']} ({meta['n_nominal']} fault-free), "
         f"{agg['B1']['op_hours']:.2f} h outside fault windows. Residual threshold lambda = {meta['lam']}. "
         f"E6 model: R = {meta['e6']['R_ohm']:.4f} ohm, c_sw = {meta['e6']['c_sw_W_per_A']:.3f} W/A, "
         f"P0 = {meta['e6']['p0_W']:.2f} W, s0 = {meta['e6']['s0_W']:.2f} W (fitted on development nominal data).", "",
         "| monitor | FA episodes / h (95 % upper if 0) | false attributions / h | coverage | correctly attributed | "
         "misattributed | median ambiguity | median latency s | median eligible-evidence latency s | host ms / tick | "
         "peak KiB |", "|---|---|---|---|---|---|---|---|---|---|---|"]

    def f(x, fmt="{:.2f}"):
        return "–" if x is None else fmt.format(x)
    for m in EV2.MONITOR_ORDER:
        a = agg[m]
        fa = f"{a['fa_per_h']:.1f}" + (f" (≤ {a['fa_upper95_per_h']:.2f})" if a["fa_episodes"] == 0 else "")
        L.append(f"| {m}: {EV2.DESCR[m]} | {fa} | {a['fa_attr_per_h']:.1f} | {a['coverage'] * 100:.0f} % | "
                 f"{a['attributed']} / {a['n_faults']} | {a['misattributed']} | {f(a['ambiguous_med'])} | "
                 f"{f(a['lat_detect_med'], '{:.1f}')} | {f(a['lat_elig_med'], '{:.1f}')} | {a['tick_ms_mean']:.3f} | "
                 f"{meta['memory_kib'][m]:.0f} |")
    L += ["", "False-alarm episodes by implicated nodes (top):", ""]
    for m in EV2.MONITOR_ORDER:
        L.append(f"* {m}: " + (", ".join(f"{k} {v}" for k, v in agg[m]["fa_by_nodes"].items()) or "none"))
    L += ["", "Per fault kind (CSIA2): detected / attributed / misattributed of n; median unobservable fraction of the "
          "fault window; scenarios never eligible.", "", "| kind | n | det | attr | mis | wrong nodes | "
          "unobservable | never eligible |", "|---|---|---|---|---|---|---|---|"]
    for k, v in agg["CSIA2"]["by_kind"].items():
        L.append(f"| {k} | {v['n']} | {v['detected']} | {v['attributed']} | {v['misattributed']} | "
                 f"{', '.join(v['wrong_nodes']) or '–'} | {f(v['unobservable_frac_med'])} | {v['never_eligible']} |")
    if "decision" in meta:
        d = meta["decision"]
        L += ["", "## Pre-registered decision (protocol section 6)", ""]
        for k in ("CSIA2_vs_R3v", "TRUST2_vs_R3v"):
            x = d[k]
            L.append(f"* {k}: {x['more_attributed']:+d} attributed, {x['more_misattributed']:+d} misattributed, "
                     f"{x['more_fa_per_h']:+.2f} FA/h -> increment {'SUPPORTED' if x['supported'] else 'NOT supported'}")
        L.append(f"* Recommended monitor: **{d['recommended']}**")
    L += ["", f"Runtime {meta['runtime_s']:.0f} s on this host. Host CPU and memory figures are x86-64 CPython, "
          "not target figures.", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dev", action="store_true")
    g.add_argument("--freeze", action="store_true")
    g.add_argument("--eval", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    a = ap.parse_args()

    if a.freeze:
        _dev, nominal, nom_data, e6, fit, lam, info, trust_thr = dev_calibration(a.jobs)
        FREEZE.write_text(json.dumps({
            "frozen_files_sha256": hashes(), "e6_model": e6.__dict__, "e6_fit_on_dev": fit, "lam": lam,
            "lam_info": info, "trust_thresholds": trust_thr,
            "dev_seeds": {"nominal": list(ES2.DEV_NOMINAL_SEEDS), "faults_from": ES2.DEV_FAULT_SEED0},
            "eval_seeds": {"nominal": list(ES2.EVAL_NOMINAL_SEEDS), "faults_from": ES2.EVAL_FAULT_SEED0,
                           "per_kind": 5},
            "note": "Written before any evaluation seed was generated. Commit this file before --eval."},
            indent=1, sort_keys=True))
        print(f"wrote {FREEZE.relative_to(ROOT)}: lam {lam}, E6 {fit}")
        return 0

    if a.dev:
        dev, nominal, nom_data, e6, fit, lam, info, trust_thr = dev_calibration(a.jobs)
        agg, rt = run_set(dev, lam, trust_thr, e6, a.jobs)
        meta = {"n_scenarios": len(dev), "n_nominal": len(nominal), "lam": lam, "e6": e6.__dict__, "e6_fit": fit,
                "runtime_s": rt, "memory_kib": memory(nominal[0], nom_data[0], e6, lam, trust_thr),
                "decision": decision(agg)}
        OUT_DEV.with_suffix(".json").write_text(json.dumps({"meta": meta, "aggregate": agg}, indent=1, default=str))
        OUT_DEV.with_suffix(".md").write_text(report(agg, meta, "CSIA v2: DEVELOPMENT set results (used for design)"))
        print(OUT_DEV.with_suffix(".md").read_text())
        return 0

    # --eval
    if not FREEZE.exists():
        print("no freeze manifest: run --freeze and commit it first")
        return 2
    fz = json.loads(FREEZE.read_text())
    bad = {f: h for f, h in hashes().items() if fz["frozen_files_sha256"].get(f) != h}
    if bad:
        print("frozen files changed since the freeze:", ", ".join(bad))
        return 2
    if OUT_EVAL.with_suffix(".json").exists():
        print(f"{OUT_EVAL.with_suffix('.json').relative_to(ROOT)} exists: the evaluation set is run once")
        return 2
    e6 = E6Model(**fz["e6_model"])
    lam, trust_thr = fz["lam"], fz["trust_thresholds"]
    scns = ES2.eval_set()
    agg, rt = run_set(scns, lam, trust_thr, e6, a.jobs)
    nominal = [s for s in scns if s.fault is None]
    meta = {"n_scenarios": len(scns), "n_nominal": len(nominal), "lam": lam, "e6": fz["e6_model"], "runtime_s": rt,
            "memory_kib": memory(nominal[0], ES2.generate(nominal[0]), e6, lam, trust_thr),
            "decision": decision(agg), "freeze_file": str(FREEZE.relative_to(ROOT))}
    OUT_EVAL.with_suffix(".json").write_text(json.dumps({"meta": meta, "aggregate": agg}, indent=1, default=str))
    OUT_EVAL.with_suffix(".md").write_text(report(agg, meta, "CSIA v2: EVALUATION set results (run once)"))
    print(OUT_EVAL.with_suffix(".md").read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
