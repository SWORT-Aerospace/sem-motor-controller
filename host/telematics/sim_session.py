"""SIMULATION FIXTURE: one telematics unit recording one simulated drive, with chosen faults (host only).

The end-to-end demonstration (tools/run_telematics_demo.py) runs a fixed 165 s scenario with every fault at once.
The vehicle-validation protocols (research/vehicle_validation/) need one disturbance at a time, so this runs the
same pieces (sim_vehicle.VehicleSim, the receive-only node, its STLG log) with the faults, duration and speed
profile the caller gives, plus three receive-side conditions the vehicle model cannot express:

  power_cuts      ((t0, t1), ...): the unit loses power at t0 (no shutdown: queued records and the open block
                  are lost) and boots again at t1 with a brown-out reset cause; each boot is its own log
  can_delay       ((t0, t1, delay_s), ...): controller frames sent in the window reach the unit `delay_s` later
                  (a slow transmit queue on the controller or a busy bus); they keep their order
  can_stall       ((t0, t1), ...): controller frames sent in the window are held and all reach the unit at t1 (a
                  stalled transmit queue released at once)
  storage_stalls  ((t0, t1), ...): the log writer cannot write (flash busy)

Everything here is SIMULATED. Nothing here is the firmware; the node is its host model.
"""
from __future__ import annotations

import collections
import pathlib
from typing import Callable, Optional

import numpy as np

from host.telematics import stlg
from host.telematics.clocks import LocalClock, PpsModel
from host.telematics.controller_adapter import SimFixtureAdapter
from host.telematics.node import NodeConfig, SimLink, TelematicsNode, meta_fields
from host.telematics.sim_vehicle import Faults, VehicleSim, VehicleSimConfig, default_profile
from host.telematics.wheel import WheelConfig

CHANNELS = ("wheel_l", "wheel_r", "wheel_drive")
KIND = "HOST SIMULATION - not a vehicle run"


def simulate(out: pathlib.Path, faults: Faults = Faults(), duration: float = 60.0, *,
             profile: Callable[[float], float] = default_profile, unit: str = "TLMSIM-EXP",
             power_cuts: tuple = (), can_delay: tuple = (), can_stall: tuple = (), storage_stalls: tuple = (), link_outages: tuple = (),
             vcfg: Optional[VehicleSimConfig] = None, ncfg: Optional[NodeConfig] = None, dt: float = 0.01,
             note: str = "") -> dict:
    """Run one simulated drive; returns {"runs": [(run_id, log path)], "truth": [(t, v, distance)], "sim",
    "links", "clock"}; times in `truth` and in the arguments are simulation (controller) time, times in the logs are the
    unit's clock (`clock.local`). Every log's metadata says it is a host simulation."""
    out.mkdir(parents=True, exist_ok=True)
    vcfg = vcfg or VehicleSimConfig()
    sim = VehicleSim(vcfg, faults, profile)
    clock = LocalClock()
    pps = PpsModel(outages=tuple(faults.gnss_outage))
    pps_rng = np.random.default_rng(5)
    ncfg = ncfg or NodeConfig(wheel=WheelConfig(vcfg.wheel_circumference_m, vcfg.wheel_ppr), wheel_channels=CHANNELS,
                              battery_monitor=True)
    runs, links, truth = [], {}, []
    state = {"boot": 0, "node": None}

    def start(t: float, cause: str) -> TelematicsNode:
        state["boot"] += 1
        rid = f"{unit}-B{state['boot']:04d}"
        adapter = SimFixtureAdapter()
        meta = meta_fields(ncfg, adapter, rid, unit, state["boot"])
        meta.update(kind=KIND, simulation={"controller": "host/telematics/sim_vehicle.py (stand-in for the external "
                                                         "controller; semmc fixture protocol)",
                                           "faults": repr(faults), "power_cuts": list(power_cuts),
                                           "can_delay": list(can_delay), "can_stall": list(can_stall), "note": note or "SYNTHETIC; no hardware"})
        path = out / f"{rid}.stlg"
        w = stlg.Writer(path, meta, ncfg.storage_bytes)
        links[rid] = SimLink(outages=link_outages)
        runs.append((rid, path))
        return TelematicsNode(ncfg, clock, w, links[rid], adapter, rid, boot=state["boot"],
                              flash_stalls=tuple(storage_stalls), reset_cause=cause, t_start=t)

    def rx_of(tx: float) -> float:
        held = next((b for a, b in can_stall if a <= tx < b), None)
        return held if held is not None else tx + next((d for a, b, d in can_delay if a <= tx < b), 0.0)

    node = start(0.0, "power-on (simulated)")
    pending: collections.deque = collections.deque()      # (receive time, id, data), receive times increasing
    t_prev = 0.0
    for k in range(1, int(round(duration / dt)) + 1):
        t = round(k * dt, 6)
        res = sim.step(t, dt)
        frames = sim.frames(t)
        truth.append((t, sim.v, sim.dist))
        cut = next(((a, b) for a, b in power_cuts if a <= t < b), None)
        if cut and node is not None:
            node.crash()
            node = None
        if node is None and cut is None:
            node = start(t, "power loss (simulated: brown-out reset)")
            pending.clear()
        if node is None:
            pending.clear()
            t_prev = t
            continue
        for te, ch in res["edges"]:
            node.on_wheel_edge(te, ch)
        for ch in range(vcfg.wheel_channels):
            node.on_wheel_line(ch, sim.line_high(ch, t))
        for tx, cid, data in frames:
            # frames keep their order: a delayed frame holds back the ones behind it
            pending.append((max(rx_of(tx), pending[-1][0] if pending else 0.0), cid, data))
        while pending and pending[0][0] <= t + 1e-9:
            rx, cid, data = pending.popleft()
            node.on_can(rx, cid, data)
        for te, u in pps.edges(t_prev, t, pps_rng):
            node.on_pps(te, u)
        for kind, args in sim.sensors(t):
            node.on_sensor(t, kind, args)
        node.service(t, dt)
        t_prev = t
    if node is not None:
        node.close(duration)
    return {"runs": runs, "truth": truth, "sim": sim, "links": links, "clock": clock}
