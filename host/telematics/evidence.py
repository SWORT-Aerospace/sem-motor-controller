"""Explicit evidence states (telematics/schema/telemetry_schema.yaml, `evidence_states`).

A measurement (measurement.py) says what the source and the decoder found; an evidence assessment says what the
value may be used for at a given time, by a given consumer. Every assessment has exactly one state:

  VALID              admissible: decoded, in range, confirmed, fresh, timed well enough for the consumer
  SOURCE_UNVERIFIED  in range but not confirmed by the source's validity flag, or a bound
  OUT_OF_RANGE       outside the plausible range; value withheld
  TIMING_UNCERTAIN   a valid value whose time is not known within the consumer's tolerance
  STALE              older than the signal's freshness threshold
  MISSING            a supported signal that has not been received
  INVALID            marked invalid by the source, failed its check, or rejected by a plausibility rule
  UNSUPPORTED        the configuration cannot provide it (no adapter mapping, hardware or parameter missing)
  UNKNOWN            the source is present but the quantity cannot be determined (wheel with no edge)

Only VALID is admissible as evidence for a cross-domain witness. Nothing here turns a non-admissible value into
0, False or a bare NaN: the value is None and the reason says why.
"""
from __future__ import annotations

import dataclasses
import functools
from typing import Iterable, Optional

import yaml

from host.telematics import signals
from host.telematics.measurement import VALIDITY, Measurement

ADMISSIBLE = "VALID"


@functools.lru_cache(maxsize=1)
def schema() -> dict:
    return yaml.safe_load(signals.SCHEMA_PATH.read_text())


def states() -> tuple[str, ...]:
    return tuple(schema()["evidence_states"])


def state_of(validity: str) -> str:
    """The state a measurement validity (or a live-summary q) maps to."""
    return schema()["validity_to_state"][validity]


@functools.lru_cache(maxsize=None)
def _signal_entry(signal: str) -> Optional[dict]:
    reg = signals.lookup(signal)
    if reg is None:
        return None
    return next(e for e in schema()["signals"] if e["id"] == reg.id)


def expected_period_us(signal: str) -> Optional[int]:
    """The schema's expected sample period of a registry signal, or None when it states none."""
    e = _signal_entry(signal)
    r = e.get("expected_rate_hz") if e else None
    return int(round(1e6 / float(r))) if r else None


def lineage(signal: str) -> tuple[str, ...]:
    """Raw source items of a registry signal, channel-specific for wildcard signals (wheel.<ch>.speed ->
    wheel:<ch>.edges)."""
    e = _signal_entry(signal)
    if e is None:
        return ()
    raw = list(e["lineage"]["raw"])
    if "*" in e["id"]:
        ch = signal.split(".")[1]
        raw = [r.replace(":", f":{ch}.", 1) if ":" in r else r for r in raw]
    return tuple(raw)


@dataclasses.dataclass(frozen=True)
class Evidence:
    signal: str
    state: str
    value: Optional[float]
    unit: str
    reason: Optional[str]
    t_ref_us: Optional[int]
    t_unc_us: Optional[int]
    age_us: Optional[int]
    source: Optional[str]
    provenance: Optional[str]
    seq: Optional[int]
    lineage: tuple[str, ...]
    upper: Optional[float] = None
    record_id: Optional[int] = None

    @property
    def admissible(self) -> bool:
        return self.state == ADMISSIBLE

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["lineage"] = list(self.lineage)
        return d


def assess(signal: str, meas: Optional[Measurement], now_us: int, *, supported: bool = True,
           timing_tol_us: Optional[int] = None, unsupported_reason: str = "not provided by this configuration") \
        -> Evidence:
    """The evidence state of `signal` at `now_us` from its latest measurement (None: none received).

    `supported` False gives UNSUPPORTED whatever was received (a value for an unsupported signal would be a
    configuration error, not evidence). `timing_tol_us` is the consumer's tolerance on the timestamp: a VALID value
    whose uncertainty is unknown or larger becomes TIMING_UNCERTAIN."""
    reg = signals.lookup(signal)
    if reg is None:
        raise ValueError(f"unknown signal {signal!r}")
    lin = lineage(signal)
    if not supported:
        return Evidence(signal, "UNSUPPORTED", None, reg.unit, unsupported_reason, None, None, None, None, None,
                        None, lin)
    if meas is None:
        return Evidence(signal, "MISSING", None, reg.unit, "not received", None, None, None, None, None, None, lin)
    if meas.signal != signal:
        raise ValueError(f"measurement of {meas.signal} assessed as {signal}")
    st = state_of(meas.validity)
    age = meas.age_us(now_us)
    reason = None if st == "VALID" else f"{meas.validity}: {meas.provenance}"
    value = meas.value if st in ("VALID", "SOURCE_UNVERIFIED") else None
    if st in ("VALID", "SOURCE_UNVERIFIED") and age > reg.stale_s * 1e6:
        st, value, reason = "STALE", None, f"age {age} us > {int(reg.stale_s * 1e6)} us"
    if st == "VALID" and timing_tol_us is not None:
        if meas.t_unc_us is None:
            st, value, reason = "TIMING_UNCERTAIN", None, "no bound on the timestamp error"
        elif meas.t_unc_us > timing_tol_us:
            st, value, reason = "TIMING_UNCERTAIN", None, \
                f"timestamp uncertainty {meas.t_unc_us} us > tolerance {timing_tol_us} us"
    return Evidence(signal, st, value, reg.unit, reason, meas.t_ref_us, meas.t_unc_us, age, meas.source,
                    meas.provenance, meas.source_seq, lin, meas.upper, meas.record_id)


def supported_signals(adapter_map: Iterable[str], wheel_configured: bool, wheel_channels: Iterable[str] = (),
                      battery_monitor: bool = False, gnss: bool = False, imu: bool = True,
                      temp_channels: Iterable[str] = ()) -> set[str]:
    """The signals a configuration can provide: the controller signals the adapter maps, wheel speed and
    distance only when circumference and pulses per revolution are known, the optional sensors when fitted."""
    out = set(adapter_map)
    if wheel_configured:
        for ch in wheel_channels:
            out |= {f"wheel.{ch}.speed", f"wheel.{ch}.distance"}
    if gnss:
        out |= {"gnss.speed", "gnss.speed_acc", "gnss.num_sv"}
    if imu:
        out |= {"imu.ax", "imu.gz"}
    if battery_monitor:
        out |= {"batt.voltage", "batt.current"}
    out |= {f"temp.{ch}" for ch in temp_channels}
    return out


def adapter_signals(adapter) -> set[str]:
    """Registry signals an adapter can produce (SimFixtureAdapter, DbcAdapter, NullAdapter)."""
    from host.telematics import controller_adapter as CA
    if isinstance(adapter, CA.SimFixtureAdapter):
        return {sig for fields in CA.SIM_MAP.values() for _f, sig, _v, _c in fields}
    if isinstance(adapter, CA.DbcAdapter):
        return {s["to"] for lst in adapter.map.values() for s in lst}
    return set()


assert set(VALIDITY) <= set(schema()["validity_to_state"]), "every measurement validity needs an evidence state"
