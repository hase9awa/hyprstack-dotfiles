#!/usr/bin/env python3
"""Bounded, read-only startup trace for freezes on the physical desktop.

Use from the affected user's session; no input injection, window changes or
browser profile reads. A boot/session-specific JSONL file survives a reboot.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import time


def probe(path, timeout=.3):
    started = time.monotonic()
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(b"j/cursorpos")
        connection.shutdown(socket.SHUT_WR)
        data = connection.recv(8192)
        json.loads(data)
    return (time.monotonic()-started)*1000


def processes():
    result = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            name = (proc / "comm").read_text().strip()
            if name not in ("Hyprland", "qs", "thorium", "kwalletd6", "ksecretd"):
                continue
            if proc.stat().st_uid != os.getuid():
                continue
            # Report process type only; URLs, arguments and profile content
            # never enter the trace.
            command = (proc / "cmdline").read_bytes().split(b"\0")
            kind = next((a.decode() for a in command if a.startswith(b"--type=")), "main")
            status = (proc / "status").read_text().splitlines()
            fields = {s.split(":",1)[0]:s.split(":",1)[1].strip() for s in status if ":" in s}
            result.append({"pid":int(proc.name),"name":name,"kind":kind,
                           "state":fields.get("State"),"memory":fields.get("VmRSS"),
                           "wait":(proc / "wchan").read_text().strip()})
        except (OSError, UnicodeError):
            continue
    return result


def main(args):
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if not signature or "/" in signature:
        raise SystemExit("Run from a Hyprland session")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    sock = runtime / "hypr" / signature / ".socket.sock"
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home()/".local/state")))
    directory = state / "hyprstack/startup-traces"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    path = directory / f"{boot}-{signature}.jsonl"
    # One trace per compositor instance, including shell-only restarts.
    try:
        descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    except FileExistsError:
        return
    start = time.monotonic()
    deadline = start + args.seconds
    failed_since = None
    count = failures = 0
    maximum = 0
    with os.fdopen(descriptor,"w", buffering=1) as output:
        def write(kind, **values):
            output.write(json.dumps({"event":kind,"ms":round((time.monotonic()-start)*1000,3),**values})+"\n")
        write("start", boot=boot, signature=signature, duration=args.seconds, wallTime=time.time(), processes=processes())
        while time.monotonic() < deadline:
            sampled = time.monotonic()
            try:
                latency = probe(sock)
                maximum = max(maximum, latency)
                count += 1
                if failed_since is not None:
                    write("recovered", stallMs=round((time.monotonic()-failed_since)*1000,3), latencyMs=round(latency,3))
                    failed_since = None
                if latency > 30:
                    write("slow-reply", latencyMs=round(latency,3), processes=processes())
                elif count % 20 == 0:
                    write("responsive", latencyMs=round(latency,3), processes=processes())
            except (OSError, ValueError) as error:
                failures += 1
                if failed_since is None:
                    failed_since = sampled
                write("unresponsive", error=type(error).__name__, processes=processes())
                if not sock.exists():
                    break
            # Queries wake only the event loop, never request a render. The
            # collector exits after three minutes and has no restart loop.
            delay = .25 - (time.monotonic()-sampled)
            if delay > 0:
                time.sleep(delay)
        write("end", probes=count, failures=failures, maximumReplyMs=round(maximum,3))
    print(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds",type=float,default=180)
    args = parser.parse_args()
    if not 0 < args.seconds <= 300:
        parser.error("--seconds must be in (0, 300]")
    main(args)
