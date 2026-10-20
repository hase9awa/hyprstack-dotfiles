#!/usr/bin/env python3
"""Load the personal BenQ GW2406Z EDID before the graphical session starts."""

from pathlib import Path
import hashlib
import sys

DRM = Path("/sys/class/drm")
DEBUG_DRI = Path("/sys/kernel/debug/dri")
EDID = Path(__file__).with_name("benq-gw2406z-1080p75.bin")
IDENTITY = bytes.fromhex("09d1e17845540000")
EDID_SHA256 = "f9c05286581d5374316ac49345f79500f876dc2e5997bcb60db16a3466696013"


def apply():
    data = EDID.read_bytes()
    if hashlib.sha256(data).hexdigest() != EDID_SHA256:
        raise ValueError("Unexpected BenQ EDID checksum")

    for connector in sorted(DRM.glob("card*-HDMI-A-*")):
        try:
            current = (connector / "edid").read_bytes()
        except OSError:
            continue
        if current[8:16] != IDENTITY:
            continue
        if current == data:
            return

        card, name = connector.name.split("-", 1)
        minor = (DRM / card / "dev").read_text().strip().split(":")[1]
        override = DEBUG_DRI / minor / name / "edid_override"
        override.write_bytes(data)
        (connector / "status").write_text("detect\n")
        return


if __name__ == "__main__":
    if sys.argv[1:] != ["apply"]:
        sys.exit("Usage: benq-75hz.py apply")
    apply()
