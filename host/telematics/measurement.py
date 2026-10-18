"""The common measurement model of the telematics unit.

Every value the unit reports, whether decoded from the external controller's CAN broadcast by an adapter
(controller_adapter.py) or read from one of the unit's own sensors, becomes a `Measurement`. A measurement
carries its evidence with it:

  record_id      assigned locally (node or importer), increasing; it identifies the record, never the
                 source's sample, and is kept apart from `source_seq`
  source         where the value came from: "controller", "wheel", "gnss", "imu", "temp", "batt"
  signal, unit   a registry identity (signals.py) and its unit
  value          the value in that unit, or None when there is none (invalid, missing, decode error);
                 a missing value is never written as 0
  t_rx_us        local receive or capture time in the telematics clock (microseconds)
  t_sample_us    when the quantity was sampled, in the telematics clock, or None when the source does not
                 say; a source timestamp is never invented: a protocol without one gives None
  t_unc_us       bound on how far the true sample time can be from the reference time (t_sample_us when
                 known, else t_rx_us), or None when nothing bounds it
  source_seq     the source protocol's own sequence counter when it has one, else None
  validity       one of VALIDITY (below)
  provenance     adapter or driver identity, message and field, so the value can be traced to the bytes
  upper          an upper bound when `value` is None but the evidence bounds it (wheel speed with no recent
                 edge: the wheel turned less than one pulse pitch since the last edge)

`age_us(now)` is computed when the value is used, from the reference time. Nothing here runs on hardware.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

from host.telematics import signals

VALIDITY = (
    "valid",          # decoded, in range, and confirmed by the source's validity flag when it has one
    "unverified",     # in range but not confirmed: the source's validity flag is missing or stale, or the value
                      # is known to be a bound (distance after lost wheel edges is a lower bound)
    "invalid",        # the source marked it invalid (flag or sentinel value)
    "out_of_range",   # outside the registry's plausible range: kept as evidence, value withheld
    "decode_error",   # the frame or record failed its check (CRC, length): no value
    "no_evidence",    # nothing observed in the interval (wheel without edges, not shown to be standstill)
)
USABLE = ("valid",)   # what energy and speed computations accept


@dataclasses.dataclass(frozen=True)
class Measurement:
    record_id: int
    source: str
    signal: str
    value: Optional[float]
    unit: str
    t_rx_us: int
    t_sample_us: Optional[int]
    t_unc_us: Optional[int]
    source_seq: Optional[int]
    validity: str
    provenance: str
    upper: Optional[float] = None

    def __post_init__(self):
        if self.validity not in VALIDITY:
            raise ValueError(f"unknown validity {self.validity!r}")
        if self.value is not None and (not isinstance(self.value, (int, float)) or not math.isfinite(self.value)):
            raise ValueError(f"{self.signal}: value must be a finite number or None")
        if self.validity in ("invalid", "out_of_range", "decode_error", "no_evidence") and self.value is not None:
            raise ValueError(f"{self.signal}: a {self.validity} measurement carries no value")
        if self.validity in ("valid", "unverified") and self.value is None:
            raise ValueError(f"{self.signal}: a {self.validity} measurement needs a value")
        s = signals.lookup(self.signal)
        if s is None:
            raise ValueError(f"unknown signal {self.signal!r}")
        if s.unit != self.unit:
            raise ValueError(f"{self.signal}: unit {self.unit!r}, the registry says {s.unit!r}")

    @property
    def t_ref_us(self) -> int:
        return self.t_sample_us if self.t_sample_us is not None else self.t_rx_us

    def age_us(self, now_us: int) -> int:
        return now_us - self.t_ref_us

    @property
    def usable(self) -> bool:
        return self.validity in USABLE

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def checked(record_id: int, source: str, signal: str, value, unit: str, t_rx_us: int, *, t_sample_us=None,
            t_unc_us=None, source_seq=None, provenance: str, invalid: bool = False,
            confirmed: Optional[bool] = True) -> Measurement:
    """Build a measurement and classify it: a NaN or sentinel (`invalid`) gives "invalid", a value outside
    the registry range "out_of_range", an unconfirmed one (`confirmed` None: no fresh validity flag)
    "unverified", a flag that says invalid (`confirmed` False) "invalid"."""
    v = None if value is None else float(value)
    if invalid or v is None or not math.isfinite(v) or confirmed is False:
        return Measurement(record_id, source, signal, None, unit, t_rx_us, t_sample_us, t_unc_us, source_seq,
                           "invalid", provenance)
    if not signals.in_range(signal, v):
        return Measurement(record_id, source, signal, None, unit, t_rx_us, t_sample_us, t_unc_us, source_seq,
                           "out_of_range", provenance)
    return Measurement(record_id, source, signal, v, unit, t_rx_us, t_sample_us, t_unc_us, source_seq,
                       "valid" if confirmed else "unverified", provenance)


class LatestTable:
    """Latest measurement per signal, as the live summary reads it.

    A newer measurement always replaces the older one, also when it is invalid, so an invalid value is
    reported as invalid and never hidden behind an older valid one."""

    def __init__(self):
        self.m: dict[str, Measurement] = {}

    def put(self, meas: Measurement) -> None:
        self.m[meas.signal] = meas

    def summary(self, now_us: int, wanted: list[str]) -> dict:
        """{signal: {v, u, q, age_ms, seq, ts}} for every wanted signal. q is the validity, or "stale" when
        the value is older than the registry's stale_s, or "missing" when nothing was ever received. v is
        null unless q is "valid" or "unverified"."""
        out = {}
        for sid in wanted:
            s = signals.lookup(sid)
            meas = self.m.get(sid)
            if meas is None:
                out[sid] = {"v": None, "u": s.unit, "q": "missing", "age_ms": None, "seq": None, "ts": None}
                continue
            age = meas.age_us(now_us)
            q = meas.validity
            v = meas.value
            if q in ("valid", "unverified") and age > s.stale_s * 1e6:
                q, v = "stale", None
            out[sid] = {"v": v, "u": s.unit, "q": q, "age_ms": max(0, int(round(age / 1000))),
                        "seq": meas.source_seq, "ts": "sample" if meas.t_sample_us is not None else "rx"}
            if meas.upper is not None:
                out[sid]["upper"] = meas.upper
        return out
