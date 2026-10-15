#!/usr/bin/env python3
"""Held-out evaluation + ablation of the CSIA vehicle adapter (SYNTHETIC, shadow mode).

    python3 tools/run_csia_evaluation.py [--smoke] [--jobs N]

1. Verifies the development-set freeze manifest (docs/csia/DEV_SET_FREEZE.json):
   adapter, development generator, baselines and evaluation code must hash to
   the frozen values, so results cannot silently come from a re-tuned adapter.
2. Calibrates the baseline thresholds on the frozen DEVELOPMENT nominal run only.
3. Runs every monitor on the held-out set (host/csia_adapter/eval_set.py).
4. Writes docs/generated/csia_evaluation_synthetic.{md,json}.

--smoke runs a tiny set with seeds outside the evaluation range (harness check only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import pathlib
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from host.csia_adapter import eval_set as ES  # noqa: E402
from host.csia_adapter import evaluation as EV  # noqa: E402
from host.csia_adapter.synthetic import Scenario, generate as dev_generate  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FROZEN = ["host/csia_adapter/adapter.py", "host/csia_adapter/synthetic.py", "host/csia_adapter/baselines.py",
          "host/csia_adapter/eval_set.py", "host/csia_adapter/evaluation.py", "third_party/csia-trust-layer.lock"]
MANIFEST = ROOT / "docs" / "csia" / "DEV_SET_FREEZE.json"
MONITOR_ORDER = ["B1", "V0", "V1", "V2", "V3", "V3v", "CSIA", "TRUST", "B1+CSIA"]
DESCR = {"B1": "range / NaN / freshness", "V0": "naive residuals, no gates", "V1": "naive residuals + gates",
         "V2": "calibrated residuals, no gates", "V3": "calibrated residuals + gates (alarms only)",
         "V3v": "V3 + majority-vote attribution", "CSIA": "frozen adapter (V3 + corroboration attribution)",
         "TRUST": "TrustCore belief threshold", "B1+CSIA": "B1 freshness/range + CSIA"}


def file_hashes():
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FROZEN}


def _work(args):
    scn, lam, trust_thr = args
    data = ES.generate(scn)
    ms = EV.make_monitors(lam, trust_thr)
    outs = EV.run_stream(data, scn.duration_s, ms)
    elig = [(t, o.eligible) for t, o in outs["CSIA"]]
    return scn.seed, EV.score(outs, scn, elig)


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(math.ceil(q * len(xs))) - 1)]


def aggregate(results, scns):
    by_seed = dict(results)
    agg = {}
    for m in MONITOR_ORDER:
        rows = [by_seed[s.seed][m] for s in scns]
        nom = [by_seed[s.seed][m] for s in scns if s.fault is None]
        flt = [(s, by_seed[s.seed][m]) for s in scns if s.fault is not None]
        op_h = sum(r["op_s"] for r in rows) / 3600.0
        nom_h = sum(r["op_s"] for r in nom) / 3600.0
        fa = sum(r["fa_episodes"] for r in rows)
        fa_nom = sum(r["fa_episodes"] for r in nom)
        faa = sum(r["fa_attr_episodes"] for r in rows)
        a = {"op_hours": op_h, "nominal_hours": nom_h, "fa_episodes": fa, "fa_per_h": fa / op_h,
             "fa_upper95_per_h": (3.0 if fa == 0 else None) and 3.0 / op_h if fa == 0 else None,
             "fa_nominal_episodes": fa_nom, "fa_attr_episodes": faa, "fa_attr_per_h": faa / op_h,
             "n_faults": len(flt),
             "missed": sum(1 for _s, r in flt if not r["detected"]),
             "attributed": sum(1 for _s, r in flt if r["attributed"]),
             "misattributed": sum(1 for _s, r in flt if r["misattributed"]),
             "lat_detect_med": _pct([r["lat_detect_s"] for _s, r in flt], 0.5),
             "lat_detect_p90": _pct([r["lat_detect_s"] for _s, r in flt], 0.9),
             "lat_attr_med": _pct([r["lat_attr_s"] for _s, r in flt], 0.5),
             "lat_elig_med": _pct([r["lat_detect_after_eligible_s"] for _s, r in flt], 0.5),
             "lat_elig_p90": _pct([r["lat_detect_after_eligible_s"] for _s, r in flt], 0.9),
             "ambiguous_med": _pct([r["ambiguous_fraction"] for _s, r in flt], 0.5)}
        fan = {}
        for r in rows:
            for k2, v2 in r["fa_by_nodes"].items():
                fan[k2] = fan.get(k2, 0) + v2
        a["fa_by_nodes"] = dict(sorted(fan.items(), key=lambda kv: -kv[1])[:6])
        kinds = {}
        for s, r in flt:
            k = kinds.setdefault(s.fault.kind, {"n": 0, "det": 0, "attr": 0, "mis": 0, "lat": [], "elig": [],
                                                "unobs": [], "never_elig": 0, "wrong": set()})
            k["n"] += 1
            k["det"] += r["detected"]
            k["attr"] += r["attributed"]
            k["mis"] += r["misattributed"]
            k["lat"].append(r["lat_detect_s"])
            k["elig"].append(r["first_eligible_s"])
            k["unobs"].append(r["unobservable_s"] / r["fault_s"])
            k["never_elig"] += r["first_eligible_s"] is None
            k["wrong"] |= set(r["wrong_nodes"])
        a["by_kind"] = {k: {"n": v["n"], "detected": v["det"], "attributed": v["attr"], "misattributed": v["mis"],
                            "lat_detect_med": _pct(v["lat"], 0.5), "first_eligible_med": _pct(v["elig"], 0.5),
                            "unobservable_frac_med": _pct(v["unobs"], 0.5), "never_eligible": v["never_elig"],
                            "wrong_nodes": sorted(v["wrong"])} for k, v in kinds.items()}
        agg[m] = a
    return agg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--write-manifest", action="store_true", help="(freeze step only) record current hashes")
    a = ap.parse_args()
    hashes = file_hashes()
    if a.write_manifest:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps({"frozen_files_sha256": hashes,
                                        "dev_set": {"generator": "host/csia_adapter/synthetic.py", "seed": 7,
                                                    "duration_s": 120.0,
                                                    "faults": "tools/run_csia_study.py FAULTS (6, fixed)"},
                                        "eval_set": {"generator": "host/csia_adapter/eval_set.py",
                                                     "builder": "build_eval_set(24, 5, 300, 240)",
                                                     "seeds": "nominal 1000-1023, faults 2000-2069"}}, indent=1))
        print("manifest written")
        return 0
    man = json.loads(MANIFEST.read_text())["frozen_files_sha256"]
    drift = {f: (man.get(f), h) for f, h in hashes.items() if man.get(f) != h}
    if drift and not a.smoke:
        print("FREEZE VIOLATION: files changed since the freeze:", ", ".join(drift))
        return 2
    t0 = time.time()
    dev = dev_generate(Scenario())
    lam, dev_alarms, trust_thr = EV.calibrate_on_dev(dev, Scenario().duration_s)
    if a.smoke:
        scns = [ES.make_scenario(9000, 120.0, None), ES.make_scenario(9001, 160.0, "gnss_drift"),
                ES.make_scenario(9002, 160.0, "rotor_dropout")]
    else:
        scns = ES.build_eval_set()
    with mp.Pool(a.jobs) as pool:
        results = pool.map(_work, [(s, lam, trust_thr) for s in scns], chunksize=1)
    agg = aggregate(results, scns)
    out = {"label": "SYNTHETIC held-out evaluation", "calibration": {"residual_lambda": lam,
                                                                      "dev_nominal_alarm_ticks": dev_alarms,
                                                                      "trust_thresholds": trust_thr},
           "n_scenarios": len(scns), "n_nominal": sum(1 for s in scns if s.fault is None),
           "runtime_s": round(time.time() - t0, 1), "aggregate": agg, "frozen_files_sha256": hashes,
           "smoke": a.smoke}
    name = "csia_evaluation_smoke" if a.smoke else "csia_evaluation_synthetic"
    gen = ROOT / "docs" / "generated"
    (gen / f"{name}.json").write_text(json.dumps(out, indent=1, default=lambda x: sorted(x) if isinstance(x, set) else str(x)))
    write_md(out, gen / f"{name}.md")
    print(json.dumps({m: {k: agg[m][k] for k in ("fa_per_h", "missed", "attributed", "misattributed",
                                                  "lat_detect_med")} for m in MONITOR_ORDER}, indent=1, default=str))
    return 0


def _f(x, nd=1):
    return "—" if x is None else f"{x:.{nd}f}"


def write_md(out, path):
    agg = out["aggregate"]
    cal = out["calibration"]
    any_m = agg["CSIA"]
    L = ["# CSIA held-out evaluation and ablation - SYNTHETIC", "",
         "> Synthetic sensors, synthetic faults, shadow mode. **Not vehicle evidence.** Generated by "
         "`tools/run_csia_evaluation.py`; protocol in `docs/csia/EVALUATION_PROTOCOL.md`. The adapter, the development "
         "generator, the baselines and this harness were frozen before the evaluation set was run "
         "(`docs/csia/DEV_SET_FREEZE.json`).", "",
         f"Held-out set: {out['n_scenarios']} scenarios ({out['n_nominal']} fault-free, "
         f"{out['n_scenarios'] - out['n_nominal']} with one fault each), {any_m['op_hours']:.2f} h of operation "
         f"outside fault windows ({any_m['nominal_hours']:.2f} h in fault-free scenarios). Unseen seeds; randomised "
         "pulse bands, standing starts after stops, long coasts, hills of ±2.5 %, corners, GNSS degradation and "
         "outages; faults with random onset, duration and magnitude, including drifts, dropouts and kinds absent "
         "from the development set.", "",
         "## Calibration (development nominal run only)", "",
         "| monitor | residual threshold λ | alarm ticks on dev nominal at that λ |", "|---|---|---|"]
    for k, v in cal["residual_lambda"].items():
        L.append(f"| {k} | {v:g} | {cal['dev_nominal_alarm_ticks'][k]} |")
    L += [f"| CSIA (frozen, λ_fail 9) | — | {cal['dev_nominal_alarm_ticks']['CSIA']} |",
          "", "TRUST thresholds (dev-nominal minimum − 0.02): " +
          ", ".join(f"{n} {v:.3f}" for n, v in cal["trust_thresholds"].items()), "",
          "## Summary", "",
          "| monitor | what it is | false-alarm episodes / h (all) | false attributions / h | missed / faults | "
          "correctly attributed | misattributed | detection latency median / p90 s | latency after evidence "
          "became eligible, median / p90 s | median ambiguous fraction |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for m in MONITOR_ORDER:
        a = agg[m]
        fa = f"{a['fa_per_h']:.2f}" + (f" (0 observed; 95 % upper {a['fa_upper95_per_h']:.2f})"
                                        if a["fa_episodes"] == 0 else f" ({a['fa_episodes']} episodes)")
        L.append(f"| {m} | {DESCR[m]} | {fa} | {a['fa_attr_per_h']:.2f} | {a['missed']} / {a['n_faults']} | "
                 f"{a['attributed']} | {a['misattributed']} | {_f(a['lat_detect_med'])} / {_f(a['lat_detect_p90'])} | "
                 f"{_f(a['lat_elig_med'])} / {_f(a['lat_elig_p90'])} | {_f(a['ambiguous_med'], 2)} |")
    L += ["", "False-alarm episodes by implicated nodes (top 6):", ""]
    for m in MONITOR_ORDER:
        L.append(f"* {m}: " + (", ".join(f"`{k}` {v}" for k, v in agg[m]["fa_by_nodes"].items()) or "none"))
    L += ["", "Definitions: an alarm is any reported problem (attributed or ambiguous). A false alarm is an alarm episode "
          f"outside a fault window [onset, end + {EV.GRACE_S:.0f} s]. Detection = an alarm implicating the faulty "
          "node inside the window. Attribution = that node named alone as the suspect. Misattribution = any other "
          "node named as suspect inside the window. Eligible = at least one relationship involving the faulty node "
          "passes the frozen adapter's regime gates with fresh inputs. Unobservable = time inside the fault with no "
          "eligible relationship for that node, during which no relationship-based method can see the fault.", "",
          "## Per fault kind (CSIA adapter; detections by every monitor in the last column)", "",
          "| fault kind | n | CSIA detected / attributed / misattributed | CSIA wrong nodes | median latency s | "
          "median first eligible s | median unobservable fraction | never eligible | detected by B1 / V0 / V3 / V3v / TRUST / B1+CSIA |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, v in agg["CSIA"]["by_kind"].items():
        others = " / ".join(str(agg[m]["by_kind"][k]["detected"]) for m in ("B1", "V0", "V3", "V3v", "TRUST", "B1+CSIA"))
        L.append(f"| {k} | {v['n']} | {v['detected']} / {v['attributed']} / {v['misattributed']} | "
                 f"{', '.join(v['wrong_nodes']) or '—'} | {_f(v['lat_detect_med'])} | {_f(v['first_eligible_med'])} | "
                 f"{_f(v['unobservable_frac_med'], 2)} | {v['never_eligible']} | {others} |")
    L += ["", f"Runtime {out['runtime_s']} s on this host. SYNTHETIC; the vehicle-validation gate "
          "(VALIDATION_PLAN.md §6) still requires ≥ 10 h of in-vehicle shadow data.", ""]
    path.write_text("\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
