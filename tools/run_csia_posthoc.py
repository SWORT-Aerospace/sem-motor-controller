#!/usr/bin/env python3
"""POST-HOC analysis (added AFTER the pre-registered evaluation was run).

Question raised by the first evaluation run: the V3/V3v residual monitors use a
3-tick debounce, the frozen CSIA adapter does not. How much of the
false-alarm difference is the debounce alone? This tool does NOT modify any
frozen file (adapter, generators, harness) and does NOT change the
pre-registered results in docs/generated/csia_evaluation_synthetic.md. It
re-runs the SAME held-out scenarios with two extra wrappers:

  CSIA+deb3   frozen adapter, an alarm (and a suspect) is reported only after
              it has persisted for 3 consecutive ticks
  V3v-deb1    V3v without debounce (threshold as calibrated, debounce 1)

Because these variants were defined after seeing evaluation results, they are
exploratory: they indicate a direction for the next development iteration,
whose effect must then be measured on a NEW held-out set.

    python3 tools/run_csia_posthoc.py [--jobs N]  -> docs/generated/csia_posthoc_synthetic.md
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from host.csia_adapter import eval_set as ES  # noqa: E402
from host.csia_adapter import evaluation as EV  # noqa: E402
from tools.run_csia_evaluation import _pct, _f  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Debounced:
    """Wrap a monitor: report a node only after it has been implicated (or
    suspected) for n consecutive ticks."""

    def __init__(self, inner, n, name):
        self.inner, self.n, self.name = inner, n, name
        self.imp, self.sus = {}, {}

    def ingest(self, a, s):
        self.inner.ingest(a, s)

    def tick(self, t):
        o = self.inner.tick(t)
        for d, cur in ((self.imp, o.implicated), (self.sus, o.suspects)):
            for k in list(d):
                if k not in cur:
                    del d[k]
            for k in cur:
                d[k] = d.get(k, 0) + 1
        imp = frozenset(k for k, c in self.imp.items() if c >= self.n)
        sus = frozenset(k for k, c in self.sus.items() if c >= self.n)
        return EV.Out(sus, imp | sus, o.eligible)


def _work(args):
    scn, lam = args
    data = ES.generate(scn)
    base = EV.Csia()
    ms = [base, Debounced(EV.Csia(), 3, "CSIA+deb3"),
          EV.Residual("V3v-deb1", "calibrated", True, "vote", lam["V3v"], debounce=1),
          EV.Residual("V3v", "calibrated", True, "vote", lam["V3v"], debounce=3)]
    outs = EV.run_stream(data, scn.duration_s, ms)
    elig = [(t, o.eligible) for t, o in outs["CSIA"]]
    return scn.seed, EV.score(outs, scn, elig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    pre = json.loads((ROOT / "docs" / "generated" / "csia_evaluation_synthetic.json").read_text())
    lam = pre["calibration"]["residual_lambda"]
    scns = ES.build_eval_set()
    with mp.Pool(a.jobs) as pool:
        res = dict(pool.map(_work, [(s, lam) for s in scns], chunksize=1))
    names = ["CSIA", "CSIA+deb3", "V3v", "V3v-deb1"]
    L = ["# CSIA post-hoc analysis: debounce confound - SYNTHETIC, EXPLORATORY", "",
         "> Added **after** the pre-registered held-out evaluation (`csia_evaluation_synthetic.md`), to separate the "
         "effect of a 3-tick debounce from the rest of the method. The frozen files are not modified. Results are "
         "exploratory: any adapter change motivated by them must be evaluated on a new held-out set.", "",
         "| monitor | false-alarm episodes / h | false attributions / h | missed / faults | correctly attributed | "
         "misattributed | detection latency median / p90 s |", "|---|---|---|---|---|---|---|"]
    out = {}
    for m in names:
        rows = [res[s.seed][m] for s in scns]
        flt = [res[s.seed][m] for s in scns if s.fault]
        h = sum(r["op_s"] for r in rows) / 3600
        fa = sum(r["fa_episodes"] for r in rows)
        faa = sum(r["fa_attr_episodes"] for r in rows)
        d = {"fa_per_h": fa / h, "fa": fa, "fa_attr_per_h": faa / h, "missed": sum(not r["detected"] for r in flt),
             "attributed": sum(r["attributed"] for r in flt), "mis": sum(r["misattributed"] for r in flt),
             "lat": (_pct([r["lat_detect_s"] for r in flt], 0.5), _pct([r["lat_detect_s"] for r in flt], 0.9)),
             "n": len(flt)}
        out[m] = d
        L.append(f"| {m} | {d['fa_per_h']:.2f} ({fa}) | {d['fa_attr_per_h']:.2f} | {d['missed']} / {d['n']} | "
                 f"{d['attributed']} | {d['mis']} | {_f(d['lat'][0])} / {_f(d['lat'][1])} |")
    L += ["", "Reading: compare CSIA with CSIA+deb3 (debounce added to CSIA) and V3v with V3v-deb1 (debounce removed "
          "from the residual vote). The rows for CSIA and V3v reproduce the pre-registered run on the same scenarios.", ""]
    (ROOT / "docs" / "generated" / "csia_posthoc_synthetic.md").write_text("\n".join(L))
    (ROOT / "docs" / "generated" / "csia_posthoc_synthetic.json").write_text(json.dumps(out, indent=1))
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
