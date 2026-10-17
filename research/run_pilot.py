"""Development pilot: calibration on the calibration split, then every scheduler on the development split.

    python3 research/run_pilot.py calibrate --episodes 40     # fault-free calibration episodes
    python3 research/run_pilot.py dev --per-kind 12           # all schedulers, paired, development episodes

Seeds: development 100000 + i, calibration 200000 + i. The final split is generated only from the
pre-registration commit (research/run_final.py). Results go to research/generated/pilot/; they are
development results, used to choose the protocol, never to report the final comparison.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import multiprocessing as mp
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.bea import diagnosis as D  # noqa: E402
from research.bea import episode as E  # noqa: E402
from research.bea import harness as H  # noqa: E402
from research.bea import schedulers as S  # noqa: E402
from research.bea.scoring import score  # noqa: E402

OUT = ROOT / "research" / "generated" / "pilot"
CAL_FILE = OUT / "calibration.json"
SEED_BASE = {"dev": 100000, "cal": 200000}
DEV_KINDS = ("none", "none", "HB", "HT", "HL", "HL_grade", "HU_gain")
SCHEDULERS = ("A", "B", "C", "D", "E", "F")


def make_scheduler(name: str, rc: E.RunConfig, d_budget: int, seed: int):
    return {"A": lambda: S.FixedLow(rc), "B": lambda: S.FixedHigh(rc), "C": lambda: S.EventCapture(rc),
            "D": lambda: S.RandomBursts(rc, d_budget, seed), "E": lambda: S.InformationGain(rc),
            "F": lambda: S.AmbiguityDirected(rc)}[name]()


def load_config() -> E.RunConfig:
    if not CAL_FILE.exists():
        return E.RunConfig()
    return E.RunConfig(engine=D.engine_from_calibration(json.loads(CAL_FILE.read_text())["engine"]))


# ----------------------------------------------------------------------------- calibration
def _cal_worker(args) -> dict:
    i, eng = args
    spec = H.draw_episode(SEED_BASE["cal"] + i, "cal", "none")
    ep = H.run_vehicle(spec)
    rc = E.RunConfig(engine=eng)
    D.RECORD = []
    for name in ("A", "B", "D", "F"):
        E.run_episode(ep, make_scheduler(name, rc, 60000, i), rc)
    rec, D.RECORD = D.RECORD, None
    return {"i": i, "records": rec}


SOURCES = ("summary", "frames")


def calibrate(n: int, procs: int) -> dict:
    """Two passes on fault-free calibration episodes (rules fixed before the development pilot is scored):

    1. with unit scales: each relationship's factor, per evidence source, is sqrt(median of J / n) of its
       share of the normal-operation fit over the windows it appears in (at least 5 samples);
    2. with those factors: kappa_h = max(10.83, 1.1 x largest per-episode maximum of J_H0 - J_h) and the
       consistency threshold z = max(3, 1.1 x largest per-episode maximum z score of normal operation),
       each per evidence source (10.83 is the chi-square(1) 0.999 point)."""
    t0 = time.time()
    with mp.Pool(procs) as pool:
        out1 = pool.map(_cal_worker, [(i, D.EngineConfig()) for i in range(n)])
    ratios: dict = {}
    for o in out1:
        for r in o["records"]:
            for name, (j, m) in r["by_block"].items():
                if m >= 5:
                    ratios.setdefault((r["source"], name), []).append(j / m)
    rel = {src: {name: round(math.sqrt(float(np.median(v))), 4) for (s_, name), v in sorted(ratios.items()) if s_ == src}
           for src in SOURCES}
    eng = D.engine_from_calibration({"rel_scale": rel, "kappa_summary": {}, "kappa_frames": {}})
    with mp.Pool(procs) as pool:
        out = pool.map(_cal_worker, [(i, eng) for i in range(n)])
    kappa, zc = {}, {}
    for src in SOURCES:
        kappa[src] = {}
        for h in ("HB", "HT", "HL", "HL_grade"):
            per_ep = [max(max(r["dJ"].get(h, 0.0), 0.0) for r in o["records"] if r["source"] == src)
                      for o in out if any(r["source"] == src for r in o["records"])]
            kappa[src][h] = round(max(10.83, 1.1 * max(per_ep)) if per_ep else 10.83, 2)
        per_ep = [max(r["z0"] for r in o["records"] if r["source"] == src)
                  for o in out if any(r["source"] == src for r in o["records"])]
        zc[src] = round(max(3.0, 1.1 * max(per_ep)) if per_ep else 3.0, 2)
    recs = [r for o in out for r in o["records"]]
    res = {"episodes": n, "windows": len(recs),
           "windows_per_relationship": {f"{s_}/{name}": len(v) for (s_, name), v in sorted(ratios.items())},
           "engine": {"noise_scale": 1.0, "rel_scale": rel, "z_frames": zc["frames"], "z_summary": zc["summary"],
                      "kappa_summary": kappa["summary"], "kappa_frames": kappa["frames"]},
           "rule": calibrate.__doc__.split("\n\n", 1)[1].strip(),
           "seconds": round(time.time() - t0)}
    OUT.mkdir(parents=True, exist_ok=True)
    CAL_FILE.write_text(json.dumps(res, indent=1) + "\n")
    return res


# ----------------------------------------------------------------------------- baseline calibration
def _base_worker(i: int) -> dict:
    from research.bea import baselines as BL
    from research.bea.relations import Study
    from research.run_final import window_blocks
    spec = H.draw_episode(SEED_BASE["cal"] + i, "cal", "none")
    ep = H.run_vehicle(spec)
    st = Study()
    rc = load_config()
    clk = spec.link.clock
    blocks = {src: D.calibrate_blocks(window_blocks(ep, 45.0, 70.0, st, src), rc.engine, src) for src in ("frames", "summary")}
    return {"frames": BL.residual_statistics(blocks["frames"], rc.engine.noise_scale),
            "summary": BL.residual_statistics(blocks["summary"], rc.engine.noise_scale),
            "stream": (spec.duration_s, BL.adapter_stream(ep.log, st.motor.kt, clk.local(spec.duration_s)))}


def calibrate_baselines(n: int, procs: int) -> dict:
    """Aligned-residual thresholds and the frozen monitors' calibration, on fault-free calibration episodes."""
    from research.bea import baselines as BL
    t0 = time.time()
    with mp.Pool(procs) as pool:
        out = pool.map(_base_worker, range(n))
    rc = load_config()
    thr = {src: BL.calibrate_aligned([o[src] for o in out]) for src in ("frames", "summary")}
    fm = BL.FrozenMonitors.calibrate([o["stream"] for o in out[: min(n, 12)]])
    cal = json.loads(CAL_FILE.read_text())
    cal["aligned_thresholds"] = thr
    cal["frozen_monitors"] = {"e6": dict(fm.e6.__dict__), "lam": fm.lam, "trust_thr": fm.trust_thr,
                              "report": {k: v for k, v in fm.report.items() if k != "e6"}, "e6_fit": fm.report["e6"]}
    cal["baseline_seconds"] = round(time.time() - t0)
    CAL_FILE.write_text(json.dumps(cal, indent=1, default=float) + "\n")
    return cal


# ----------------------------------------------------------------------------- development runs
def _dev_worker(args) -> list:
    i, kind, names, d_budget = args
    spec = H.draw_episode(SEED_BASE["dev"] + i, "dev", kind)
    ep = H.run_vehicle(spec)
    rc = load_config()
    out = []
    for name in names:
        t0 = time.time()
        res = E.run_episode(ep, make_scheduler(name, rc, d_budget, i), rc)
        sc = score(res, spec.fault.onset_s, rc.imu_available)
        out.append({"i": i, "kind": kind, "cycle": spec.cycle, "size": spec.fault.size, "scheduler": name,
                    **{k: res[k] for k in ("outcome", "hypotheses", "bytes", "requests", "cpu_s")},
                    **sc, "wall_s": round(time.time() - t0, 2), "reason": res["reason"][:200]})
    return out


def dev(per_kind: int, procs: int) -> list:
    jobs = [(k * 1000 + j, kind, ("A", "B", "C", "E", "F"), 0)
            for k, kind in enumerate(DEV_KINDS) for j in range(per_kind)]
    with mp.Pool(procs) as pool:
        rows = [r for part in pool.map(_dev_worker, jobs) for r in part]
    f_bytes = [r["bytes"] for r in rows if r["scheduler"] == "F"]
    d_budget = int(np.mean(f_bytes)) if f_bytes else 60000
    jobs = [(i, kind, ("D",), d_budget) for (i, kind, _n, _b) in jobs]
    with mp.Pool(procs) as pool:
        rows += [r for part in pool.map(_dev_worker, jobs) for r in part]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (OUT / "dev_summary.md").write_text(summarise(rows, d_budget))
    return rows


def summarise(rows: list, d_budget: int) -> str:
    cats = ("correct", "wrong", "unresolved_incl", "unresolved_excl", "no_fit", "missed", "undecided")
    L = ["# Development pilot (not the final evaluation)", "",
         f"Development split only; thresholds from the calibration split. D's byte budget is matched to F's mean: {d_budget} B.", ""]
    for sch in SCHEDULERS:
        rs = [r for r in rows if r["scheduler"] == sch]
        if not rs:
            continue
        L += [f"## Scheduler {sch}", "", "| Truth | n | " + " | ".join(cats) + " | mean bytes | median decision delay [s] |",
              "|---|---|" + "---|" * (len(cats) + 2)]
        for truth in ("HB", "HT", "HL", "HU"):
            g = [r for r in rs if r["truth"] == truth]
            if not g:
                continue
            dd = [r["decide_delay_s"] for r in g if r["decide_delay_s"] is not None]
            L.append(f"| {truth} | {len(g)} | " + " | ".join(str(sum(r["category"] == c for r in g)) for c in cats)
                     + f" | {np.mean([r['bytes'] for r in g]):.0f} | {np.median(dd) if dd else float('nan'):.1f} |")
        h0 = [r for r in rs if r["truth"] == "H0"]
        if h0:
            L.append(f"| H0 | {len(h0)} | false alarms {sum(r['category'] != 'clean' for r in h0)}, with a wrong "
                     f"supported cause {sum(r['category'] == 'false_alarm_wrong' for r in h0)} | | | | | | "
                     f"| {np.mean([r['bytes'] for r in h0]):.0f} | |")
        L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=("calibrate", "calibrate-baselines", "dev"))
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--per-kind", type=int, default=12)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args()
    if a.stage == "calibrate":
        print(json.dumps(calibrate(a.episodes, a.procs), indent=1))
    elif a.stage == "calibrate-baselines":
        print(json.dumps(calibrate_baselines(a.episodes, a.procs), indent=1, default=float))
    else:
        rows = dev(a.per_kind, a.procs)
        print((OUT / "dev_summary.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
