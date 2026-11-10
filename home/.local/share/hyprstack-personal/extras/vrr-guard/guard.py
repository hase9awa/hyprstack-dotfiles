#!/usr/bin/env python3
"""Keep static VRR desktops/browsers refreshing; leave fullscreen games in control.

Read-only Hyprland IPC. Snapshot on startup and socket2 events, never poll hyprctl
or change monitor modes. The pixel worker is removed, not merely occluded, when
a fullscreen application other than a browser is visible on its output.
"""
import argparse
import json
import os
import re
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import time


EVENTS = {
    "fullscreen", "workspace", "workspacev2", "focusedmon", "focusedmonv2",
    "activespecial", "activespecialv2", "monitoradded", "monitoraddedv2",
    "monitorremoved", "configreloaded", "movewindow", "movewindowv2",
    "closewindow", "openwindow", "moveworkspace", "moveworkspacev2", "dpms",
}

STATIC_FULLSCREEN_BROWSERS = re.compile(
    r"^(?:org\.chromium\.)?(?:thorium(?:-browser)?|chromium(?:-browser)?|google-chrome.*|"
    r"firefox|librewolf|zen(?:-browser)?)$", re.IGNORECASE)


def workspace_key(workspace):
    # 0.57 monitor IPC uses workspace addresses; clients still include numeric
    # IDs. Names cover named/special workspaces and remain stable across both.
    value = workspace.get("name") or workspace.get("address") or workspace.get("id")
    return str(value) if value not in (None, "", 0, "0") else None


def desktop_outputs(monitors, clients, output_filter=None):
    """Exclusive fullscreen is bit 2; maximized windows (bit 1) need protection."""
    outputs = set()
    for monitor in monitors:
        name = monitor["name"]
        if output_filter:
            if output_filter.startswith("desc:"):
                if not monitor.get("description", "").startswith(output_filter[5:]):
                    continue
            elif name != output_filter:
                continue
        if (monitor.get("disabled", False) or not monitor.get("vrr", False)
                or not monitor.get("dpmsStatus", True)
                or monitor.get("mirrorOf", "none") != "none"):
            continue
        visible = {workspace_key(monitor.get("activeWorkspace", {})),
                   workspace_key(monitor.get("specialWorkspace", {}))}
        visible.discard(None)
        fullscreen = any(
            client.get("monitor") == monitor["id"]
            and workspace_key(client.get("workspace", {})) in visible
            and client.get("mapped", True) and not client.get("hidden", False)
            and int(client.get("fullscreen", 0)) & 2
            # A fullscreen test page can be completely static. Suspending the
            # guard there reintroduces idle VRR flicker despite the desktop fix.
            and not STATIC_FULLSCREEN_BROWSERS.fullmatch(client.get("class", ""))
            for client in clients
        )
        if not fullscreen:
            outputs.add(name)
    return outputs


def query(root, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(str(root / ".socket.sock"))
        connection.sendall(("j/" + command).encode())
        connection.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := connection.recv(65536):
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


class Guard:
    def __init__(self, root, pixel, output_filter=None):
        self.root, self.pixel, self.output_filter = root, pixel, output_filter
        self.workers = {}
        self.running = True

    def stop(self, *_):
        self.running = False

    def remove(self, name):
        worker = self.workers.pop(name)
        worker.terminate()
        try:
            worker.wait(timeout=3)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()
        print(f"vrr-guard[{name}]: paused", flush=True)

    def reconcile(self):
        wanted = desktop_outputs(query(self.root, "monitors"), query(self.root, "clients"),
                                 self.output_filter)
        for name in set(self.workers) - wanted:
            self.remove(name)
        for name in wanted - set(self.workers):
            self.workers[name] = subprocess.Popen([str(self.pixel), "--output", name])
            print(f"vrr-guard[{name}]: desktop keep-alive enabled", flush=True)

    def run(self):
        # Subscribe before the initial snapshot so a concurrent fullscreen
        # transition cannot leave a stale worker running.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as events, selectors.DefaultSelector() as selector:
            events.connect(str(self.root / ".socket2.sock"))
            events.setblocking(False)
            selector.register(events, selectors.EVENT_READ)
            try:
                self.reconcile()
                pending, deadline = b"", None
                while self.running:
                    timeout = 1 if deadline is None else min(1, max(0, deadline - time.monotonic()))
                    if selector.select(timeout):
                        chunk = events.recv(65536)
                        if not chunk:
                            return 0  # Compositor exited. Do not restart in a stale session.
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            event = line.split(b">>", 1)[0].decode(errors="replace")
                            if event in EVENTS and deadline is None:
                                deadline = time.monotonic() + 0.03
                    if deadline is not None and time.monotonic() >= deadline:
                        self.reconcile()
                        deadline = None
                    if any(worker.poll() is not None for worker in self.workers.values()):
                        # Hotplug may close a layer before its socket2 event is
                        # handled. Re-read the output list before treating it as failure.
                        self.reconcile()
                        if any(worker.poll() is not None for worker in self.workers.values()):
                            raise RuntimeError("VRR pixel worker exited unexpectedly")
            finally:
                for name in list(self.workers):
                    self.remove(name)
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Connector name or desc: prefix; default: all enabled VRR outputs")
    parser.add_argument("--pixel", type=Path, default=Path.home() / ".local/lib/hyprstack/hyprstack-vrr-pixel")
    args = parser.parse_args()
    runtime, signature = os.environ.get("XDG_RUNTIME_DIR"), os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not runtime or not signature:
        print("vrr-guard: requires the current Hyprland session environment", file=sys.stderr)
        return 1
    root = Path(runtime) / "hypr" / signature
    if not (root / ".socket2.sock").exists():
        return 0
    guard = Guard(root, args.pixel, args.output)
    signal.signal(signal.SIGINT, guard.stop)
    signal.signal(signal.SIGTERM, guard.stop)
    try:
        return guard.run()
    except (OSError, ValueError, RuntimeError) as error:
        print(f"vrr-guard: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
