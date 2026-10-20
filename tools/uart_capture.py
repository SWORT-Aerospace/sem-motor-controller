#!/usr/bin/env python3
"""Console capture for the telematics bench: a serial terminal that writes everything it receives to a file.

    python3 tools/uart_capture.py /dev/ttyACM0 capture_B3.txt                        # type commands, Ctrl-D ends
    python3 tools/uart_capture.py /dev/ttyACM0 capture_B7d.txt --send "DUMP 2090 2120" --until "DUMP END"
    python3 tools/uart_capture.py /dev/ttyACM0 capture_B7.txt --duration 4560           # 76 min, no typing

The board's console (USART1 through the ST-LINK virtual COM port) runs at 115200 8N1. The file holds the bytes
exactly as received (no timestamps added), which is what tools/telematics_import.py reads: the status lines
(--status-capture) and the DUMP output (--uart-capture). Lines typed on stdin are sent with CR LF.

Standard library only (termios), so it runs on Linux and macOS without pyserial. On Windows, use a terminal
with logging instead (PuTTY: Session > Logging > All session output).
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import time

BAUD = {9600: "B9600", 19200: "B19200", 38400: "B38400", 57600: "B57600", 115200: "B115200", 230400: "B230400"}


def open_port(path: str, baud: int) -> int:
    """Open the port raw, 8N1, no flow control."""
    import termios
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[0] = 0                                                        # iflag: no translation, no XON/XOFF
    a[1] = 0                                                        # oflag: raw
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL             # cflag: 8 bits, no parity, 1 stop
    a[3] = 0                                                        # lflag: no echo, not canonical
    speed = getattr(termios, BAUD[baud])
    a[4] = a[5] = speed
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    termios.tcflush(fd, termios.TCIOFLUSH)
    return fd


def capture(fd: int, out, send: list[str], until: str | None, duration: float | None, stdin=None,
            echo=None) -> dict:
    """Copy the port to `out` until `until` is seen, `duration` s pass, or stdin ends (when given)."""
    for cmd in send:
        os.write(fd, cmd.encode() + b"\r\n")
    t_end = time.monotonic() + duration if duration else None
    tail, n = b"", 0
    srcs = [fd] + ([stdin] if stdin is not None else [])
    reason = "duration"
    while t_end is None or time.monotonic() < t_end:
        r, _w, _x = select.select(srcs, [], [], 0.2)
        if fd in r:
            try:
                data = os.read(fd, 4096)
            except BlockingIOError:
                data = b""
            if data:
                out.write(data)
                out.flush()
                n += len(data)
                if echo is not None:
                    echo.write(data.decode(errors="replace"))
                    echo.flush()
                if until:
                    tail = (tail + data)[-(len(until) + 4096):]
                    if until.encode() in tail:
                        reason = "until"
                        break
        if stdin is not None and stdin in r:
            line = os.read(stdin, 1024)
            if not line:
                reason = "stdin closed"
                break
            os.write(fd, line.rstrip(b"\r\n") + b"\r\n")
    return {"bytes": n, "stopped_by": reason}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("port")
    ap.add_argument("outfile")
    ap.add_argument("--baud", type=int, default=115200, choices=sorted(BAUD))
    ap.add_argument("--send", action="append", default=[], help="command sent after opening (repeatable)")
    ap.add_argument("--until", help="stop once this text has been received (e.g. 'DUMP END')")
    ap.add_argument("--duration", type=float, help="stop after this many seconds")
    ap.add_argument("--append", action="store_true", help="append to the file instead of replacing it")
    ap.add_argument("--quiet", action="store_true", help="do not echo to the terminal")
    a = ap.parse_args()
    fd = open_port(a.port, a.baud)
    interactive = not a.until and not a.duration                   # typed commands; Ctrl-D ends
    try:
        with open(a.outfile, "ab" if a.append else "wb") as out:
            res = capture(fd, out, a.send, a.until, a.duration, stdin=sys.stdin.fileno() if interactive else None,
                          echo=None if a.quiet else sys.stdout)
    except KeyboardInterrupt:
        res = {"stopped_by": "interrupt"}
    finally:
        os.close(fd)
    print(f"\n[uart_capture] {a.outfile}: {res.get('bytes', '?')} bytes, stopped by {res['stopped_by']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
