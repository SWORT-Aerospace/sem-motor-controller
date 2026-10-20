"""Cross-domain witness relations (shadow, advisory).

A relation tests one claim about the vehicle with evidence from different sources: "the left wheel speed agrees
with GNSS speed", "electrical effort is accompanied by a mechanical response". Each relation declares:

  valid_contexts   the vehicle contexts (host/telematics/context.py) in which the physics behind it holds;
                   outside them the result is INAPPLICABLE, never a verdict
  inputs           the signals it reads; any input that is not VALID makes the result INSUFFICIENT_EVIDENCE,
                   with each rejected input and its state kept
  parameters       the vehicle parameters it needs (gear ratio, wheel circumference, coast-down deceleration);
                   unknown parameters make it INSUFFICIENT_EVIDENCE, not a guess
  tolerance        PROVISIONAL: from the sensors' stated resolution and judgement, to be replaced by bench and
                   vehicle data (research/vehicle_validation/); no tolerance here is a finding
  causes           what could produce an inconsistency; a relation never names one of them as the cause

Results: CONSISTENT, INCONSISTENT, INAPPLICABLE (context or regime), INSUFFICIENT_EVIDENCE (inputs or parameters).
Families: A electrical-mechanical, B motor and vehicle motion, C power domain (verdicts.common_cause), D thermal.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Callable, Optional

from host.telematics import lineage
from host.telematics.context import Context
from host.telematics.evidence import Evidence, timing_problem

RESULTS = ("CONSISTENT", "INCONSISTENT", "INAPPLICABLE", "INSUFFICIENT_EVIDENCE")
# physics that holds whenever the vehicle moves (not only at steady speed); the relation checks that an admissible
# speed above the floor is known, so UNKNOWN here means "moving, but not steady, or effort unknown"
MOVING = ("LAUNCH", "CRUISE", "COAST", "UNKNOWN")


def _moving(p: dict) -> Optional[str]:
    ctx: Context = p["_ctx"]
    floor = p.get("speed_floor_mps", 1.0)
    if ctx.speed_mps is None or ctx.speed_mps < floor:
        return f"no admissible speed above {floor} m/s ({ctx.reason})"
    return None


@dataclasses.dataclass(frozen=True)
class Observation:
    relation: str
    family: str
    claim: str
    subject: str
    witnesses: tuple[str, ...]
    result: str
    detail: str
    residual: Optional[float]
    tolerance: Optional[float]
    admitted: dict                  # signal -> value used
    rejected: dict                  # signal -> [state, reason]
    context: str
    causes_if_inconsistent: tuple[str, ...]
    independence: dict              # witness -> lineage.Independence.as_dict(): distinct sensors, shared paths and
                                    # parameters (a shared dependency is a caveat, not an exclusion)
    compared: str = ""              # the quantity actually compared for the subject (lineage item), when it differs
    timing_basis: dict = dataclasses.field(default_factory=dict)   # input -> basis of its timestamp bound

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["witnesses"], d["causes_if_inconsistent"] = list(self.witnesses), list(self.causes_if_inconsistent)
        return d


@dataclasses.dataclass(frozen=True)
class Relation:
    id: str
    family: str
    claim: str
    subject: str
    witnesses: tuple[str, ...]
    valid_contexts: tuple[str, ...]
    parameters: tuple[str, ...]
    tolerance: str
    causes: tuple[str, ...]
    fn: Callable[[dict, dict], tuple[str, str, Optional[float], Optional[float]]]
    timing_tol_us: int = 250_000     # each input's timestamp bound, and their mutual alignment (PROVISIONAL)
    compared: str = ""               # lineage item of the subject's compared quantity (B2: speed.from_motor)

    def definition(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in dataclasses.asdict(self).items()
                if k != "fn"}


def evaluate(rel: Relation, ev: dict[str, Evidence], ctx: Context, params: dict) -> Observation:
    inputs = (rel.subject,) + rel.witnesses
    admitted = {s: ev[s].value for s in inputs if s in ev and ev[s].admissible}
    rejected = {s: [ev[s].state if s in ev else "MISSING", ev[s].reason if s in ev else "not in the snapshot"]
                for s in inputs if s not in admitted}
    indep = {}
    for w in rel.witnesses:
        try:
            indep[w] = lineage.independence(rel.compared or rel.subject, w).as_dict()
        except KeyError:
            indep[w] = {"distinct_sensors": None, "caveats": ["no lineage entry: what the two share is unknown"]}

    def obs(result, detail, residual=None, tol=None):
        timing = {s: ev[s].t_unc_basis for s in inputs if s in ev}
        return Observation(rel.id, rel.family, rel.claim, rel.subject, rel.witnesses, result, detail, residual, tol,
                           admitted, rejected, ctx.mode, rel.causes, indep, rel.compared or rel.subject, timing)

    # timing: a value whose time is not bounded within the relation's tolerance is not admissible for it, and
    # values are compared only if their times are that close (not because the same loop handled them). A bound that
    # is only assumed counts for simulated data alone (`_accept_assumed_timing`, set by the review from the run's
    # data class); for a bench or vehicle run it is no bound at all.
    accept = bool(params.get("_accept_assumed_timing", False))
    for s in list(admitted):
        e = ev[s]
        why = timing_problem(e.t_unc_us, e.t_unc_basis, rel.timing_tol_us, accept)
        if why:
            del admitted[s]
            rejected[s] = ["TIMING_UNCERTAIN", why]
    if ctx.mode not in rel.valid_contexts:
        return obs("INAPPLICABLE", f"context {ctx.mode} not in {list(rel.valid_contexts)} ({ctx.reason})")
    if rejected:
        return obs("INSUFFICIENT_EVIDENCE", "inputs not admissible: " +
                   ", ".join(f"{s} {st}" for s, (st, _r) in sorted(rejected.items())))
    times = [ev[s].t_ref_us for s in admitted if ev[s].t_ref_us is not None]
    if times and max(times) - min(times) > rel.timing_tol_us:
        return obs("INSUFFICIENT_EVIDENCE", f"inputs {max(times) - min(times)} us apart > {rel.timing_tol_us} us: "
                   "not comparable as simultaneous")
    unknown = [p for p in rel.parameters if params.get(p) is None]
    if unknown:
        return obs("INSUFFICIENT_EVIDENCE", "parameters unknown: " + ", ".join(unknown))
    not_indep = [w for w, i in indep.items() if i["distinct_sensors"] is False]
    if not_indep:
        return obs("INSUFFICIENT_EVIDENCE", "witness shares a raw source with the subject: " + ", ".join(not_indep))
    result, detail, residual, tol = rel.fn(admitted, {**params, "_ctx": ctx})
    return obs(result, detail, residual, tol)


# ---------------------------------------------------------------- relation functions (all tolerances PROVISIONAL)
def _speed_agree(rel_tol: float, abs_tol: float, extra_key: Optional[str] = None):
    def fn(a: dict, p: dict):
        keys = list(a)
        subj, wit = a[keys[0]], a[keys[1]]
        extra = a.get(extra_key, 0.0) if extra_key else 0.0
        if wit < p.get("speed_floor_mps", 1.0):
            return "INAPPLICABLE", f"speed {wit:.2f} m/s below the floor", None, None
        tol = max(rel_tol * abs(wit), abs_tol) + extra
        r = subj - wit
        res = "CONSISTENT" if abs(r) <= tol else "INCONSISTENT"
        return res, f"{keys[0]} {subj:.3f} vs {keys[1]} {wit:.3f}: {r:+.3f} (tolerance {tol:.3f})", r, tol
    return fn


def wheel_vs_gnss(channel: str) -> Relation:
    s = f"wheel.{channel}.speed"
    return Relation(
        f"B1:{channel}", "B", f"{s} agrees with GNSS speed", s, ("gnss.speed", "gnss.speed_acc"), ("CRUISE",), (),
        "max(5 % of GNSS speed, 0.3 m/s) + the GNSS speed accuracy (PROVISIONAL)",
        ("wheel circumference or pulses-per-revolution parameter", "wheel slip or lock", "Hall edges lost or extra",
         "GNSS multipath or low accuracy", "time misalignment of the two streams"),
        _speed_agree(0.05, 0.3, "gnss.speed_acc"))


def wheel_pair(a: str, b: str) -> Relation:
    sa, sb = f"wheel.{a}.speed", f"wheel.{b}.speed"

    def fn(adm, p):
        gz = adm.get("imu.gz")
        if gz is not None and abs(gz) > p.get("straight_gz_rad_s", 0.05):
            return "INAPPLICABLE", f"yaw rate {gz:.3f} rad/s: cornering (track width not used)", None, None
        return _speed_agree(0.05, 0.2)({sa: adm[sa], sb: adm[sb]}, p)
    return Relation(f"B3:{a}-{b}", "B", f"{sa} agrees with {sb} on a straight", sa, (sb, "imu.gz"), ("CRUISE",), (),
                    "max(5 %, 0.2 m/s) while |yaw rate| <= 0.05 rad/s (PROVISIONAL)",
                    ("different circumferences", "slip", "cornering not detected", "Hall edges lost or extra"), fn)


def motor_vs_wheel(channel: str) -> Relation:
    s = f"wheel.{channel}.speed"

    def fn(adm, p):
        ctx: Context = p["_ctx"]
        if not ctx.effort and p.get("drivetrain.freewheel"):
            return "INAPPLICABLE", "no propulsion effort: a freewheel may be overrunning", None, None
        wheel_r = p["wheel.circumference_m"] / (2 * 3.141592653589793)
        v_motor = adm["ctrl.motor_speed"] * wheel_r / p["drivetrain.gear_ratio"]
        return _speed_agree(0.05, 0.3)({"speed.from_motor": v_motor, s: adm[s]}, p)
    return Relation(f"B2:{channel}", "B", f"ctrl.motor_speed through the drivetrain agrees with {s}",
                    "ctrl.motor_speed", (s,), ("CRUISE", "LAUNCH"),
                    ("drivetrain.gear_ratio", "wheel.circumference_m", "drivetrain.freewheel"),
                    "max(5 %, 0.3 m/s) (PROVISIONAL)",
                    ("gear ratio or circumference parameter", "the controller's speed estimate", "wheel slip",
                     "freewheel overrunning", "Hall edges lost or extra"), fn, compared="speed.from_motor")


def imu_vs_wheel_accel() -> Relation:
    def fn(adm, p):
        why = _moving(p)
        if why:
            return "INAPPLICABLE", why, None, None
        a_imu, a_w = adm["accel.from_imu"], adm["accel.from_wheel"]
        tol = 0.3 + p.get("grade_allowance_mps2", 0.5)
        r = a_imu - a_w
        return ("CONSISTENT" if abs(r) <= tol else "INCONSISTENT"), \
            f"IMU mean {a_imu:+.3f} vs wheel derivative {a_w:+.3f} over the same window: {r:+.3f} (tolerance " \
            f"{tol:.2f}, grade unknown)", r, tol
    return Relation("B4", "B", "IMU longitudinal acceleration agrees with the wheel-speed derivative",
                    "accel.from_imu", ("accel.from_wheel",), MOVING, (),
                    "0.3 m/s^2 + 0.5 m/s^2 for the unknown road grade, while moving above 1 m/s; both over the same "
                    "window of about 1 s (PROVISIONAL)",
                    ("road grade", "IMU mounting or offset", "wheel-speed derivative noise", "time misalignment"), fn,
                    timing_tol_us=600_000)


def effort_vs_response() -> Relation:
    def fn(adm, p):
        why = _moving(p)
        if why:
            return "INAPPLICABLE", why, None, None
        pw = adm["ctrl.dc_voltage"] * adm["ctrl.dc_current"]
        a = adm["imu.ax"]
        if pw < p.get("effort_min_W", 50.0):
            return "INAPPLICABLE", f"electrical power {pw:.0f} W below the effort floor", None, None
        lim = -p["vehicle.coast_decel_mps2"] - 0.2
        return ("CONSISTENT" if a >= lim else "INCONSISTENT"), \
            f"power {pw:.0f} W with a {a:+.2f} m/s^2 (limit {lim:+.2f}: coast-down plus 0.2)", a - lim, 0.2
    return Relation("A1", "A", "electrical effort is accompanied by a mechanical response", "ctrl.dc_current",
                    ("ctrl.dc_voltage", "imu.ax"), MOVING, ("vehicle.coast_decel_mps2",),
                    "deceleration no stronger than the coast-down deceleration + 0.2 m/s^2 while power >= 50 W and "
                    "moving above 1 m/s (PROVISIONAL)",
                    ("higher load (grade, wind, a dragging brake)", "driver braking (no brake signal is received)",
                     "drivetrain loss or slip", "controller current or voltage measurement", "IMU mounting or offset",
                     "time misalignment"), fn)


def response_without_effort() -> Relation:
    def fn(adm, p):
        pw = adm["ctrl.dc_voltage"] * adm["ctrl.dc_current"]
        a = adm["imu.ax"]
        if a <= p.get("unpowered_accel_mps2", 0.3):
            return "CONSISTENT", f"a {a:+.2f} m/s^2 needs no explanation", None, None
        res = "CONSISTENT" if pw >= p.get("effort_min_W", 50.0) else "INCONSISTENT"
        return res, f"a {a:+.2f} m/s^2 with electrical power {pw:.0f} W", pw, p.get("effort_min_W", 50.0)
    return Relation("A2", "A", "an acceleration is accompanied by electrical effort", "imu.ax",
                    ("ctrl.dc_voltage", "ctrl.dc_current"), MOVING, (),
                    "acceleration above 0.3 m/s^2 with less than 50 W (PROVISIONAL); evaluated in any moving context",
                    ("downhill grade", "push or tow", "IMU mounting or offset", "controller data late or missing",
                     "current measurement offset"), fn)


def thermal_rate(signal: str, max_rate_c_per_s: float = 2.0) -> Relation:
    def fn(adm, p):
        prev = p.get("_prev", {}).get(signal)
        if prev is None or p["_now_s"] - prev[0] < 1.0:
            return "INAPPLICABLE", "no earlier admissible reading at least 1 s before", None, None
        rate = (adm[signal] - prev[1]) / (p["_now_s"] - prev[0])
        return ("CONSISTENT" if abs(rate) <= max_rate_c_per_s else "INCONSISTENT"), \
            f"{signal} changes at {rate:+.2f} degC/s (limit {max_rate_c_per_s})", rate, max_rate_c_per_s
    return Relation(f"D1:{signal}", "D", f"{signal} changes at a physically plausible rate", signal, (),
                    ("STARTUP", "STOPPED", "LAUNCH", "CRUISE", "COAST", "UNKNOWN"), (),
                    f"|dT/dt| <= {max_rate_c_per_s} degC/s over at least 1 s (PROVISIONAL; depends on mounting)",
                    ("sensor or contact", "bus read error", "an actual thermal event"), fn, timing_tol_us=2_000_000)


def relation_set(wheel_channels: list[str], temp_signals: list[str], pairs: tuple = ()) -> list[Relation]:
    rels = []
    for ch in wheel_channels:
        rels += [wheel_vs_gnss(ch), motor_vs_wheel(ch)]
    rels += [imu_vs_wheel_accel()] if wheel_channels else []
    rels += [wheel_pair(a, b) for a, b in pairs]
    rels += [effort_vs_response(), response_without_effort()]
    rels += [thermal_rate(s) for s in temp_signals]
    return rels


def set_hash(rels: list[Relation]) -> str:
    return "rel-" + hashlib.sha256(json.dumps([r.definition() for r in rels], sort_keys=True).encode()).hexdigest()[:12]
