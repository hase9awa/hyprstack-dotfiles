#!/usr/bin/env python3
"""Probe each output's physical brightness; fall back to a shell dimming layer."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile


def run(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=12)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def vcp(text):
    match = re.search(r"^VCP 10 C (\d+) (\d+)$", text or "", re.MULTILINE)
    if not match:
        return None
    current, maximum = map(int, match.groups())
    return (current, maximum) if maximum > 0 and 0 <= current <= maximum else None


def ddc_displays(text):
    displays = {}
    for block in re.split(r"\n\s*\n", text or ""):
        if not re.match(r"\s*Display \d+", block):
            continue
        bus = re.search(r"I2C bus:\s*/dev/i2c-(\d+)", block)
        connector = re.search(r"DRM connector:\s*card\d+-(\S+)", block)
        if bus and connector:
            displays[connector[1]] = bus[1]
    return displays


def preferences_path():
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "hyprstack/brightness.json"


def disabled_in_hdr_outputs():
    path = preferences_path().with_name("brightness-backends.json")
    try:
        outputs = json.loads(path.read_text()).get("disabled_in_hdr", [])
        return {output for output in outputs if isinstance(output, str)} if isinstance(outputs, list) else set()
    except (OSError, ValueError, AttributeError):
        return set()


def output_modes():
    # Automatic HDR does not necessarily change the configured monitor preset.
    native = run(["hyprctl", "repl", 'return require("utils.json").encode(hl.plugin.hdr_reference.modes())'])
    try:
        modes = json.loads(native or "null")
        if isinstance(modes, dict) and all(isinstance(value, str) for value in modes.values()):
            return modes
    except ValueError:
        pass
    try:
        return {monitor["name"]: monitor.get("colorManagementPreset", "srgb")
                for monitor in json.loads(run(["hyprctl", "monitors", "-j"]) or "[]")}
    except (ValueError, TypeError, KeyError):
        return {}


def hdr_disabled(name, key, policies, modes):
    return (key in policies or name in policies) and modes.get(name) in ("hdr", "hdredid")


def preferences():
    try:
        data = json.loads(preferences_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(key, level):
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = preferences()
        data[key] = level
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file)
            file.write("\n")
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def clamp(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Brightness must be finite")
    return max(0, min(1, value))


def connector_path(name):
    return next(iter(Path("/sys/class/drm").glob("card*-" + name)), None)


def output_key(screen):
    path = connector_path(screen["name"])
    if path:
        try:
            edid = (path / "edid").read_bytes()
            if edid:
                return "edid:" + hashlib.sha256(edid).hexdigest()
        except OSError:
            pass
    return screen.get("serial") or screen.get("model") or screen["name"]


def backlight(name):
    # An unrelated laptop backlight must never control an external HDMI/DP output.
    if not name.startswith(("eDP-", "LVDS-", "DSI-")):
        return None
    connector = connector_path(name)
    devices = list(Path("/sys/class/backlight").glob("*"))
    if connector:
        gpu = connector.resolve().parent.parent
        related = [device for device in devices if gpu in (device / "device").resolve().parents
                   or (device / "device").resolve() == gpu]
        if related:
            devices = related
    if not devices:
        return None
    # Prefer the native/raw controller over duplicate firmware interfaces.
    devices.sort(key=lambda device: ((device / "type").read_text().strip() != "raw", device.name))
    for device in devices:
        try:
            current = int((device / "brightness").read_text())
            maximum = int((device / "max_brightness").read_text())
            if maximum > 0:
                return {"backend": "backlight", "device": device.name, "current": current / maximum,
                        "maximum": maximum}
        except (OSError, ValueError):
            continue
    return None


def probe(screens, dimmed=False):
    policies = disabled_in_hdr_outputs()
    modes = output_modes() if policies else {}
    buses = ddc_displays(run(["ddcutil", "detect", "--brief"]))
    saved = preferences()
    result = {}
    for screen in screens:
        name, key = screen["name"], output_key(screen)
        if hdr_disabled(name, key, policies, modes):
            # The owner wants full HDR brightness and manual SDR white calibration.
            result[name] = {"backend": "disabled", "current": 1, "maximum": 1,
                            "name": name, "key": key, "level": 1, "hdr_disabled": True}
            continue
        info = backlight(name)
        if info is None and name in buses:
            values = vcp(run(["ddcutil", "--bus", buses[name], "getvcp", "10", "--brief"]))
            if values:
                current, maximum = values
                info = {"backend": "ddc", "bus": buses[name], "current": current / maximum,
                        "maximum": maximum}
        if info is None and screen.get("model", "").startswith("StudioDisplay"):
            value = run(["asdbctl", "get"])
            if value and value.isdigit():
                info = {"backend": "apple", "current": int(value) / 101, "maximum": 101}
        info = info or {"backend": "software", "current": saved.get(key, 1), "maximum": 1}
        try:
            level = clamp(saved.get(key, info["current"]) if dimmed or info["backend"] == "software"
                          else info["current"])
        except (TypeError, ValueError):
            level = 1
        result[name] = dict(info, name=name, key=key, level=level)
    return result


def set_brightness(info, level, dimmed=False):
    level = clamp(level)
    effective = level * (0.65 if dimmed else 1)
    policies = disabled_in_hdr_outputs()
    if info["key"] in policies or info.get("name") in policies:
        modes = output_modes()
        name = info.get("name")
        if hdr_disabled(name, info["key"], policies, modes):
            info = dict(info, backend="disabled", maximum=1, hdr_disabled=True)
        elif info.get("hdr_disabled") and name in modes:
            info = probe([{"name": name}])[name]
    backend = info["backend"]
    if backend == "disabled":
        return dict(info, level=1, effective=1)
    maximum = int(info["maximum"])
    target = round(effective * maximum)
    current = None
    if backend == "ddc":
        bus = str(info["bus"])
        if run(["ddcutil", "--bus", bus, "setvcp", "10", str(target)]) is not None:
            values = vcp(run(["ddcutil", "--bus", bus, "getvcp", "10", "--brief"]))
            if values:
                current, maximum = values
    elif backend == "backlight":
        device = str(info["device"])
        if run(["brightnessctl", "--device", device, "set", str(target)]) is not None:
            value = run(["brightnessctl", "--device", device, "get"])
            if value and value.isdigit():
                current = int(value)
    elif backend == "apple":
        if run(["asdbctl", "set", str(target)]) is not None:
            value = run(["asdbctl", "get"])
            if value and value.isdigit():
                current = int(value)
    # Some panels advertise VCP 10 but ignore writes (especially in HDR).
    # Verify the response before continuing to treat the slider as physical.
    if backend != "software" and (current is None or abs(current - target) > max(1, maximum * 0.01)):
        info = dict(info, backend="software", maximum=1)
    save(info["key"], level)
    return dict(info, level=level, effective=effective)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("probe", "set", "modes"))
    parser.add_argument("info", type=json.loads, nargs="?")
    parser.add_argument("--level", type=clamp)
    parser.add_argument("--dimmed", action="store_true")
    args = parser.parse_args()
    if args.operation == "modes":
        print(json.dumps(output_modes(), sort_keys=True))
        return
    if args.info is None:
        parser.error("probe and set require output information")
    if args.operation == "set" and args.level is None:
        parser.error("set requires --level")
    result = probe(args.info, args.dimmed) if args.operation == "probe" else set_brightness(args.info, args.level, args.dimmed)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
