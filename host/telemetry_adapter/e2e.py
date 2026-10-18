"""End-to-end SYNTHETIC demonstration:

  synthetic plant telemetry -> controller TX frames (C codec) -> Python decode
  -> supervisor policy -> Python encode -> C decode -> freshness/validity
  -> state machine -> arbitration -> FOC -> simulated plant -> logged results

Every quantity is from the synthetic configuration and synthetic plant. This
demonstrates software integration on a host; it validates no hardware.
"""
from __future__ import annotations

import csv
import dataclasses
import pathlib
from typing import Callable, Optional

from host.logger.semmc_log import Event, can_event, io_event
from host.telemetry_adapter.cosim import HostController, StepResult
from host.telemetry_adapter.supervisor import Supervisor, SupervisorConfig, speed_hold_policy
from protocol.generated import semmc_protocol as proto
from tools import config_tool as ct

ROOT = pathlib.Path(__file__).resolve().parents[2]


@dataclasses.dataclass
class Scenario:
    duration_s: float = 25.0
    arm_at_s: float = 0.1
    eco_at_s: float = 0.3
    supervisor_off_at_s: Optional[float] = 20.0
    target_mps: float = 6.0
    step_s: float = 0.02
    io_events: list[Event] = dataclasses.field(default_factory=list)
    on_step: Optional[Callable[[float, Supervisor, "HostController"], None]] = None
    advisory: Optional[Callable[[float, Supervisor], Optional[bytes]]] = None
    policy: Optional[Callable] = None          # default: speed hold at target_mps


@dataclasses.dataclass
class RunResult:
    steps: list[StepResult]
    supervisor: Supervisor
    tx_frames: list[tuple[int, str, dict, dict]]
    csv_rows: list[dict]
    summary: str
    outdir: pathlib.Path


def run(scn: Scenario, build_dir: pathlib.Path, outdir: pathlib.Path) -> RunResult:
    outdir.mkdir(parents=True, exist_ok=True)
    cfg = ct.load_yaml(ROOT / "config" / "vehicle.synthetic.yaml")
    cal = build_dir / "cal" / "synthetic.bin"
    hc = HostController(build_dir / "semmc_host", cal, outdir / "e2e.csv", outdir / "e2e_tx.log", decimate=10)
    sup = Supervisor(SupervisorConfig(max_torque_Nm=cfg["limits"]["max_motor_torque_Nm"]),
                     scn.policy or speed_hold_policy(scn.target_mps, 1.5, cfg["vehicle"]["wheel_circumference_m"],
                                                     cfg["vehicle"]["gear_ratio"], cfg["limits"]["max_motor_torque_Nm"]))
    pending = sorted([io_event(0, arm=False, throttle=0.0, eco=False),
                      io_event(int(scn.arm_at_s * 1e6), arm=True),
                      io_event(int(scn.eco_at_s * 1e6), eco=True)] + scn.io_events, key=lambda e: e.t_us)
    steps: list[StepResult] = []
    tx_decoded = []
    n = int(round(scn.duration_s / scn.step_s))
    try:
        for k in range(n + 1):
            t_s = k * scn.step_s
            t_us = int(round(t_s * 1e6))
            if scn.supervisor_off_at_s is not None and t_s >= scn.supervisor_off_at_s:
                sup.enabled = False
            if scn.on_step:
                scn.on_step(t_s, sup, hc)
            due = [e for e in pending if e.t_us <= t_us]
            pending = [e for e in pending if e.t_us > t_us]
            frames = [can_event(t_us, cid, data) for cid, data in sup.tick(t_s)]
            if scn.advisory:
                adv = scn.advisory(t_s, sup)
                if adv is not None:
                    frames.append(can_event(t_us, proto.MESSAGES["csia_advisory"]["id"], adv))
            hc.send(due + frames)
            res = hc.step(t_us)
            steps.append(res)
            for (ft, cid, data) in res.frames:
                sup.on_frame(ft / 1e6, cid, data)
                values, info = proto.decode(cid, data)
                tx_decoded.append((ft, proto.BY_ID[cid]["name"] if cid in proto.BY_ID else hex(cid), values, info))
    finally:
        summary = hc.close()
    with (outdir / "e2e.csv").open() as f:
        rows = list(csv.DictReader(f))
    return RunResult(steps, sup, tx_decoded, rows, summary, outdir)
