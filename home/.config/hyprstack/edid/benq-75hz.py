#!/usr/bin/env python3
"""Personal BenQ GW2406Z EDID setup. Never edits the hyprstack repository."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time

USER = "hasegawa"
UID = pwd.getpwnam(USER).pw_uid
HOME_DIR = Path(pwd.getpwnam(USER).pw_dir)
RUNTIME = Path(f"/run/user/{UID}")
CONFIG = HOME_DIR / ".config/hyprstack/monitors.lua"
SYSTEM_DIR = Path("/etc/hyprstack/benq-75hz")
UNIT = "hyprstack-benq-75hz.service"
ROLLBACK = "hyprstack-benq-75hz-rollback"
CONFIRM = RUNTIME / "hyprstack-benq-75hz-confirm"
IDENTITY = bytes.fromhex("09d1e17845540000")
EDID_NAME = "benq-gw2406z-1080p75.bin"
EDID_HASH = "f9c05286581d5374316ac49345f79500f876dc2e5997bcb60db16a3466696013"
MODE_75 = "modeline 165.000 1920 1928 1960 2000 1080 1083 1088 1100 +hsync +vsync"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, timeout=30, **kwargs)


def hyprctl(*args):
    result = run("/usr/bin/runuser", "-u", USER, "--", "/usr/bin/env",
                 f"XDG_RUNTIME_DIR={RUNTIME}", "/usr/bin/hyprctl", "-i", "0",
                 *args, capture_output=True, text=True)
    return result.stdout


def output():
    for connector in sorted(Path("/sys/class/drm").glob("card*-HDMI-A-*")):
        try:
            if (connector / "edid").read_bytes()[8:16] != IDENTITY:
                continue
        except OSError:
            continue
        card, name = connector.name.split("-", 1)
        minor = (connector.parent / card / "dev").read_text().strip().split(":")[1]
        override = Path("/sys/kernel/debug/dri") / minor / name / "edid_override"
        if not override.exists():
            raise RuntimeError(f"EDID override unavailable: {override}")
        return connector, override
    raise RuntimeError("The expected BenQ GW2406Z is not connected")


def apply():
    folder = SYSTEM_DIR if (SYSTEM_DIR / EDID_NAME).exists() else Path(__file__).parent
    data = (folder / EDID_NAME).read_bytes()
    if hashlib.sha256(data).hexdigest() != EDID_HASH:
        raise RuntimeError("The prepared EDID checksum has changed")
    connector, override = output()
    if (connector / "edid").read_bytes() == data:
        return
    override.write_bytes(data)
    (connector / "status").write_text("detect\n")


def mode(rate):
    text = CONFIG.read_text()
    pattern = r'(output\s*=\s*"desc:BNQ BenQ GW2406Z P4H0067101Q",\s*mode\s*=\s*)"[^"\n]+"'
    selected = MODE_75 if rate == 75 else "1920x1080@60"
    text, count = re.subn(pattern, lambda match: match[1] + json.dumps(selected), text)
    if count != 1:
        raise RuntimeError("The personal BenQ monitor rule was not found exactly once")
    CONFIG.write_text(text)


def reset():
    try:
        connector, override = output()
        override.write_bytes(b"reset")
        (connector / "status").write_text("detect\n")
    finally:
        mode(60)
        try:
            hyprctl("reload")
        except subprocess.SubprocessError:
            pass


def install():
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    SYSTEM_DIR.chmod(0o755)
    for source, name in ((Path(__file__), "benq-75hz.py"),
                         (Path(__file__).parent / EDID_NAME, EDID_NAME)):
        target = SYSTEM_DIR / name
        shutil.copyfile(source, target)
        target.chmod(0o644)
    unit = Path("/etc/systemd/system") / UNIT
    unit.write_text("""[Unit]
Description=Personal BenQ GW2406Z 1080p 75 Hz EDID
Requires=sys-kernel-debug.mount
After=sys-kernel-debug.mount systemd-udev-settle.service
Wants=systemd-udev-settle.service
Before=display-manager.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /etc/hyprstack/benq-75hz/benq-75hz.py apply
RemainAfterExit=yes
TimeoutStartSec=30

[Install]
WantedBy=graphical.target
""")
    unit.chmod(0o644)
    run("/usr/bin/systemctl", "daemon-reload")
    run("/usr/bin/systemctl", "enable", "--now", UNIT)


def setup():
    output()  # Check that this kernel exposes the needed interface before changing anything.
    if (Path("/etc/systemd/system") / UNIT).exists():
        raise RuntimeError("A personal 75 Hz service already exists; inspect it before replacing it")
    CONFIRM.unlink(missing_ok=True)
    run("/usr/bin/systemd-run", f"--unit={ROLLBACK}", "--on-active=180s",
        "--timer-property=AccuracySec=1s", "/usr/bin/python3", str(Path(__file__).resolve()), "reset")
    committed = False
    try:
        apply()
        mode(75)
        hyprctl("reload")
        time.sleep(1)
        monitors = json.loads(hyprctl("-j", "monitors", "all"))
        display = next(m for m in monitors if m["description"] == "BNQ BenQ GW2406Z P4H0067101Q")
        if (display["width"], display["height"]) != (1920, 1080) or abs(display["refreshRate"] - 75) > .1:
            raise RuntimeError(f"The driver did not activate 1080p/75 Hz: {display['refreshRate']} Hz")
        print("MODE_ACTIVE 1920x1080@75Hz; waiting up to 120 seconds for a visual check.", flush=True)
        print(f"To keep the mode: touch {CONFIRM}", flush=True)
        for _ in range(120):
            if CONFIRM.exists():
                install()
                committed = True
                print("SAVED: 75 Hz enabled for this session and future boots.", flush=True)
                return
            time.sleep(1)
        raise RuntimeError("No visual confirmation received; restoring 60 Hz")
    finally:
        if not committed:
            reset()
        run("/usr/bin/systemctl", "stop", ROLLBACK + ".timer")
        CONFIRM.unlink(missing_ok=True)


def commit():
    connector, _ = output()
    if hashlib.sha256((connector / "edid").read_bytes()).hexdigest() != EDID_HASH:
        raise RuntimeError("The tested EDID is no longer active")
    display = next(m for m in json.loads(hyprctl("-j", "monitors", "all"))
                   if m["description"] == "BNQ BenQ GW2406Z P4H0067101Q")
    if (display["width"], display["height"]) != (1920, 1080) or abs(display["refreshRate"] - 75) > .1:
        raise RuntimeError("The visually confirmed 1080p/75 Hz mode is no longer active")
    # The owner has confirmed this exact mode. Keep the tested modeline as well
    # as the EDID so this running compositor does not depend on a mode rescan.
    mode(75)
    hyprctl("reload")
    install()
    run("/usr/bin/systemctl", "stop", ROLLBACK + ".timer")
    print("SAVED: 1920x1080 at 75 Hz, including future boots.", flush=True)


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("Administrator rights are required; run this file through sudo or pkexec.")
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action == "apply":
        apply()
    elif action == "reset":
        reset()
    elif action == "setup":
        setup()
    elif action == "commit":
        commit()
    else:
        sys.exit("Usage: benq-75hz.py {setup|apply|reset|commit}")
