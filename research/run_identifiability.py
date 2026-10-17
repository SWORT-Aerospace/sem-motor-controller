"""Run the identifiability study (gate 1) and write its generated results.

    python3 research/run_identifiability.py            # writes research/generated/identifiability.{json,md}
    python3 research/run_identifiability.py --check    # recomputes and compares with the committed JSON

Every number is a noise-free separation d in noise standard deviations (see
research/bea/identifiability.py), computed on synthetic trajectories. The
written analysis is research/IDENTIFIABILITY.md.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from research.bea import identifiability as I  # noqa: E402

OUT = ROOT / "research" / "generated"
NOMINAL = {"HB": 0.2, "HT": 0.1, "HL": 3.0, "HL_grade": 0.01, "HL_wind": 3.0}
UNITS = {"HB": "A", "HT": "s", "HL": "N", "HL_grade": "rad", "HL_wind": "m/s"}
LADDER = (0.25, 0.5, 1.0, 2.0, 4.0)
PAIRS = (("HB", "H0"), ("HT", "H0"), ("HL", "H0"), ("HB", "HT"), ("HB", "HL"), ("HT", "HL"), ("HL", "HL_grade"))
EVIDENCE_ORDER = ("summary_2Hz", "frames_100Hz", "frames_imu")


def r(x: float, n: int = 3) -> float:
    if x == 0 or not math.isfinite(x):
        return x
    return round(x, max(0, n - 1 - int(math.floor(math.log10(abs(x))))))


def min_separable(W, h: str, g: str, level: str) -> dict:
    """Smallest ladder size of h at which d(h -> g) >= SEPARABLE_SIGMA, or why there is none.

    status: "separable" (min_size; at_floor when the smallest rung already separates),
    "no_signature" (h leaves no trace in these records), "collinear" (g reproduces h
    exactly at 4 times nominal), "not_separable" (d < threshold up to 4 times nominal)."""
    d_nom = I.separation(W, h, NOMINAL[h], g, level)
    for i, f in enumerate(LADDER):
        d = I.separation(W, h, NOMINAL[h] * f, g, level)
        if d >= I.SEPARABLE_SIGMA:
            return {"status": "separable", "min_size": r(NOMINAL[h] * f), "at_floor": i == 0, "d_nominal": r(d_nom)}
    big = NOMINAL[h] * LADDER[-1]
    if not I.np.any(I.truth_residual(W, h, big)):
        status = "no_signature"
    elif I.is_collinear(W, h, big, g, level):
        status = "collinear"
    else:
        status = "not_separable"
    return {"status": status, "min_size": None, "d_nominal": r(d_nom), "d_max": r(d)}


def matrix(trs, st) -> list[dict]:
    rows = []
    for cond, tr in trs.items():
        windows = {ev: I.whiten(I.build_window(tr, st, I.EVIDENCE[ev][0])) for ev in EVIDENCE_ORDER}
        for h, g in PAIRS:
            row = {"pair": f"{h}-{g}", "condition": cond, "results": {}}
            for ev, W in windows.items():
                for level in ("known", "uncertain"):
                    res = {"fwd": min_separable(W, h, g, level)}
                    if g != "H0":
                        res["rev"] = min_separable(W, g, h, level)
                    row["results"][f"{ev}/{level}"] = res
            rows.append(row)
    return rows


def cases(trs, st) -> dict:
    out = {}
    # A: every pair separable on a pulse-and-coast window with the full-rate frames.
    W = I.whiten(I.build_window(trs["pulse_coast"], st, I.EVIDENCE["frames_100Hz"][0]))
    out["A"] = {f"{h}->{g}": r(I.separation(W, h, NOMINAL[h], g, "known"))
                for h in ("HB", "HT", "HL") for g in ("H0", "HB", "HT", "HL") if g != h}
    # B: not separable with the available evidence.
    B = {}
    for fs in (2.0, 10.0, 100.0):
        Wc = I.whiten(I.build_window(trs["cruise"], st, {"R1": fs}))
        B[f"cruise HT->H0 R1 at {fs:g} Hz, size 0.4 s"] = r(I.separation(Wc, "HT", 0.4, "H0", "known"))
    Wr = I.whiten(I.build_window(trs["ramp"], st, I.EVIDENCE["frames_100Hz"][0]))
    for f in (1.0, 4.0):
        B[f"ramp HB->H0 frames, size {0.2 * f:g} A"] = r(I.separation(Wr, "HB", 0.2 * f, "H0", "known"))
    Wi = I.whiten(I.build_window(trs["cruise"], st, I.EVIDENCE["frames_imu"][0]))
    B["cruise HL->HL_wind frames+IMU, 3 N"] = r(I.separation(Wi, "HL", 3.0, "HL_wind", "known"))
    B["cruise HL_wind->HL frames+IMU, 3 m/s"] = r(I.separation(Wi, "HL_wind", 3.0, "HL", "known"))
    out["B"] = B
    # C: additional synchronised records resolve B.
    C = {}
    Wo = I.whiten(I.build_window(trs["onset"], st, I.EVIDENCE["frames_100Hz"][0]))
    C["onset (ramp plus 5 s of buffered cruise) HB->H0 frames, 0.2 A"] = r(I.separation(Wo, "HB", 0.2, "H0", "known"))
    C["pulse_coast (coast segment) HB->H0 frames, 0.2 A"] = out["A"]["HB->H0"]
    for ev in ("summary_2Hz", "frames_100Hz"):
        Wk = I.whiten(I.build_window(trs["coast"], st, I.EVIDENCE[ev][0]))
        C[f"coast HL->H0 {ev}, 3 N"] = r(I.separation(Wk, "HL", 3.0, "H0", "known"))
    out["C"] = C
    # D: higher rate does not resolve (exact collinearity).
    D = {}
    for cond in ("cruise", "pulse_coast", "coast"):
        for fs in (2.0, 10.0):
            Wd = I.whiten(I.build_window(trs[cond], st, {"R1": fs, "R2": fs, "R3": fs, "R4": fs}))
            D[f"{cond} HL->HL_grade at {fs:g} Hz, 12 N"] = r(I.separation(Wd, "HL", 12.0, "HL_grade", "known"))
            D[f"{cond} HL_grade->HL at {fs:g} Hz, 0.04 rad"] = r(I.separation(Wd, "HL_grade", 0.04, "HL", "known"))
        Wd = I.whiten(I.build_window(trs[cond], st, {"R1": 100.0, "R2": 100.0, "R3": 100.0}))
        D[f"{cond} HL->HL_grade at 100 Hz (no wheel counts), 12 N"] = r(I.separation(Wd, "HL", 12.0, "HL_grade", "known"))
    out["D"] = D
    # E: an independent measurement is required.
    E = {}
    for cond in ("cruise", "coast"):
        Wi = I.whiten(I.build_window(trs[cond], st, I.EVIDENCE["frames_imu"][0]))
        for level in ("known", "uncertain"):
            E[f"{cond} HL->HL_grade frames+IMU ({level} IMU bias)"] = min_separable(Wi, "HL", "HL_grade", level)
            E[f"{cond} HL_grade->HL frames+IMU ({level} IMU bias)"] = min_separable(Wi, "HL_grade", "HL", level)
    for cond in ("cruise", "pulse_coast"):
        rels = I.EVIDENCE["frames_100Hz"][0]
        Wi = I.whiten(I.build_window(trs[cond], st, rels, torque_source="ibatt"))
        Wq = I.whiten(I.build_window(trs[cond], st, rels, torque_source="iq"))
        E[f"{cond} HB->HL, torque from bus current (dependent)"] = r(I.separation(Wi, "HB", 0.2, "HL", "known"))
        E[f"{cond} HB->HL, torque from phase currents (independent)"] = r(I.separation(Wq, "HB", 0.2, "HL", "known"))
    out["E"] = E
    return out


def timing_kinds(trs, st) -> list[dict]:
    rows = []
    for cond in ("onset", "pulse_coast", "sine"):
        for fs in (100.0, 10.0):
            for tk, tp in (("delay", 0.04), ("lag", 0.04), ("boxcar", 0.08)):
                for ak in I.TIMING_KINDS:
                    if ak != tk:
                        rows.append({"condition": cond, "fs_Hz": fs, "true": f"{tk}({tp:g} s)", "alternative": ak,
                                     "d": r(I.timing_kind_distance(trs[cond], st, fs, tk, tp, ak))})
    return rows


def conditions(trs) -> dict:
    out = {}
    for k, tr in trs.items():
        dP = I.np.abs(I.np.gradient(tr.P, 1.0 / I.TRUTH_HZ))
        out[k] = {"duration_s": r(tr.t[-1]), "v_mps": [r(tr.v.min()), r(tr.v.max())], "P_W": [r(tr.P.min()), r(tr.P.max())],
                  "I_max_A": r(tr.I.max()), "dPdt_max_W_s": r(dP.max()), "drive_fraction": r(tr.drive.mean())}
    return out


def compute() -> dict:
    st = I.Study()
    trs = {k: I.simulate(k, st) for k in I.CONDITIONS}
    return {"nominal_sizes": NOMINAL, "units": UNITS, "ladder": LADDER, "threshold_sigma": I.SEPARABLE_SIGMA,
            "nuisance": I.NUISANCE, "timing_bound_s": I.TIMING, "conditions": conditions(trs),
            "cases": cases(trs, st), "timing_kinds": timing_kinds(trs, st), "matrix": matrix(trs, st)}


def _cell(res: dict, h: str) -> str:
    if res["status"] == "separable":
        return ("<= " if res["at_floor"] else "") + f"{res['min_size']:g}"
    return {"no_signature": "no signature", "collinear": "collinear",
            "not_separable": f"> {NOMINAL[h] * LADDER[-1]:g}"}[res["status"]]


def _num(v) -> str:
    return "0 (round-off)" if isinstance(v, float) and abs(v) < 0.01 else f"{v:g}"


def render(data: dict) -> str:
    L = ["# Identifiability study: generated results", "",
         "Generated by `python3 research/run_identifiability.py`; do not edit. Analysis: [`../IDENTIFIABILITY.md`](../IDENTIFIABILITY.md).",
         "All values are synthetic: noise-free separations d in noise standard deviations, threshold "
         f"d >= {data['threshold_sigma']:g}.", "", "## Operating conditions", "",
         "| Condition | Duration [s] | Speed [m/s] | Inverter power [W] | Max current [A] | Max dP/dt [W/s] | Drive fraction |",
         "|---|---|---|---|---|---|---|"]
    for k, c in data["conditions"].items():
        L.append(f"| {k} | {c['duration_s']:g} | {c['v_mps'][0]:g} to {c['v_mps'][1]:g} | {c['P_W'][0]:g} to {c['P_W'][1]:g} | "
                 f"{c['I_max_A']:g} | {c['dPdt_max_W_s']:g} | {c['drive_fraction']:g} |")
    L += ["", "## Cases A to E", ""]
    for case, vals in data["cases"].items():
        L += [f"**Case {case}.**", "", "| Quantity | d or smallest separable size |", "|---|---|"]
        for k, v in vals.items():
            if isinstance(v, dict):
                v = (f"smallest size {_cell(v, k.split()[1].split('->')[0])}" if v["status"] == "separable"
                     else _cell(v, k.split()[1].split("->")[0])) + f"; d at nominal {_num(v['d_nominal'])}"
            else:
                v = _num(v)
            L.append(f"| {k} | {v} |")
        L.append("")
    L += ["## Timing kinds on the power balance (R1 alone)", "",
          "| Condition | Rate [Hz] | True | Alternative | d |", "|---|---|---|---|---|"]
    for t in data["timing_kinds"]:
        L.append(f"| {t['condition']} | {t['fs_Hz']:g} | {t['true']} | {t['alternative']} | {_num(t['d'])} |")
    nom = ", ".join(f"{h} {v:g} {data['units'][h]}" for h, v in data["nominal_sizes"].items())
    L += ["", "## Full matrix", "",
          f"Smallest size of the first hypothesis at which d >= {data['threshold_sigma']:g} against the second "
          f"(\"fwd\") and the reverse (\"rev\"), from the ladder {', '.join(f'{x:g}' for x in data['ladder'])} times "
          f"nominal ({nom}). \"<= x\": the smallest rung already separates. \"no signature\": the first hypothesis leaves "
          f"no trace in these records. \"collinear\": the second reproduces the first exactly at 4 times nominal. "
          f"\"> x\": not separable up to 4 times nominal.", ""]
    hdr = "| Pair | Condition | " + " | ".join(f"{ev} {lvl}" for ev in EVIDENCE_ORDER for lvl in ("known", "uncertain")) + " |"
    L += [hdr, "|---|---|" + "---|" * (2 * len(EVIDENCE_ORDER))]
    for row in data["matrix"]:
        h, g = row["pair"].split("-", 1)
        cells = []
        for ev in EVIDENCE_ORDER:
            for lvl in ("known", "uncertain"):
                res = row["results"][f"{ev}/{lvl}"]
                c = "fwd " + _cell(res["fwd"], h)
                if "rev" in res:
                    c += "; rev " + _cell(res["rev"], g)
                cells.append(c)
        L.append(f"| {row['pair']} | {row['condition']} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"


def _close(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return [f"{path}: keys differ"]
        return [m for k in a for m in _close(a[k], b[k], f"{path}/{k}")]
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return [f"{path}: lengths differ"]
        return [m for i, (x, y) in enumerate(zip(a, b)) for m in _close(x, y, f"{path}[{i}]")]
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not math.isclose(float(a), float(b), rel_tol=2e-2, abs_tol=0.15):
            return [f"{path}: {a} != {b}"]
        return []
    return [] if a == b else [f"{path}: {a} != {b}"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    data = json.loads(json.dumps(compute()))
    if args.check:
        old = json.loads((OUT / "identifiability.json").read_text())
        diff = _close(data, old)
        md_ok = (OUT / "identifiability.md").read_text() == render(old)
        for m in diff[:20]:
            print("DIFF", m)
        if not md_ok:
            print("DIFF identifiability.md is not the rendering of the committed JSON")
        print(f"check {'OK' if not diff and md_ok else 'FAILED'} ({time.time() - t0:.0f} s)")
        return 0 if not diff and md_ok else 1
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "identifiability.json").write_text(json.dumps(data, indent=1) + "\n")
    (OUT / "identifiability.md").write_text(render(data))
    print(f"wrote {OUT.relative_to(ROOT)}/identifiability.json and .md ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
