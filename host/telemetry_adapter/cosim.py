"""Lockstep co-simulation: Python supervisor <-> CAN codec <-> C controller core.

Drives `semmc_host --interactive`: Python writes events (driver IO, faults,
supervisor CAN frames encoded with the Python codec), then STEP <t>. The C side
decodes the frames with the generated C codec, runs freshness checks, the state
machine, arbitration, the FOC loop and the simulated plant, and returns its TX
frames, which Python decodes again. Both codecs are exercised every step.

HOST SIMULATION ONLY. Nothing here is hardware validation.
"""
from __future__ import annotations

import dataclasses
import pathlib
import subprocess
from typing import Iterable

from host.logger.semmc_log import Event


@dataclasses.dataclass
class StepResult:
    t_us: int
    frames: list[tuple[int, int, bytes]]  # (t_us, id, data)
    state: str
    accepted_Nm: float
    requested_Nm: float
    reason: int
    v_mps: float
    s_m: float
    energy_plant_J: float
    faults: int
    tag: int


class HostController:
    def __init__(self, exe: pathlib.Path, cal: pathlib.Path, out_csv: pathlib.Path,
                 frames_log: pathlib.Path | None = None, decimate: int = 10, extra: Iterable[str] = ()):
        args = [str(exe), "--cal", str(cal), "--interactive", "--out", str(out_csv), "--decimate", str(decimate)]
        if frames_log:
            args += ["--frames", str(frames_log)]
        args += list(extra)
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1)
        self.summary = ""

    def send(self, events: Iterable[Event]) -> None:
        for e in events:
            self.proc.stdin.write(e.line() + "\n")

    def step(self, t_us: int) -> StepResult:
        self.proc.stdin.write(f"{t_us} STEP\n")
        self.proc.stdin.flush()
        frames = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("controller process ended: " + self.proc.stderr.read())
            parts = line.split()
            if parts[1] == "CAN":
                frames.append((int(parts[0]), int(parts[2], 16), bytes.fromhex(parts[3])))
            elif parts[1] == "STATE":
                st = parts
            elif parts[1] == "END_STEP":
                break
        return StepResult(int(st[0]), frames, st[2], float(st[3]), float(st[4]), int(st[5]), float(st[6]),
                          float(st[7]), float(st[8]), int(st[9]), int(st[10]))

    def close(self) -> str:
        if self.proc.poll() is None:
            self.proc.stdin.write("0 END\n")
            self.proc.stdin.flush()
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        self.summary = self.proc.stderr.read()
        return self.summary
