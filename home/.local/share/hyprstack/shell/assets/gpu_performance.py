#!/usr/bin/env python3
"""Keep stock NVIDIA performance available for a high-refresh desktop session.

The previous PowerMizer preference is restored when the shell session ends.
No clocks, voltage, power limit or fan settings are changed.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import threading


class Modes(ctypes.Structure):
    # nvmlDevicePowerMizerModes_v1_t from the installed NVIDIA NVML SDK.
    _fields_ = [("current",ctypes.c_uint),("requested",ctypes.c_uint),("supported",ctypes.c_uint)]


class PowerMizer:
    def __init__(self):
        self.lib = ctypes.CDLL("libnvidia-ml.so.1")
        for name, arguments in (
            ("nvmlInit_v2",[]),("nvmlShutdown",[]),
            ("nvmlDeviceGetHandleByIndex_v2",[ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p)]),
            ("nvmlDeviceGetPowerMizerMode_v1",[ctypes.c_void_p,ctypes.POINTER(Modes)]),
            ("nvmlDeviceSetPowerMizerMode_v1",[ctypes.c_void_p,ctypes.POINTER(Modes)]),
        ):
            function = getattr(self.lib,name)
            function.argtypes = arguments
            function.restype = ctypes.c_uint
        self.lib.nvmlErrorString.argtypes = [ctypes.c_uint]
        self.lib.nvmlErrorString.restype = ctypes.c_char_p
        self.check(self.lib.nvmlInit_v2())
        self.device = ctypes.c_void_p()
        self.check(self.lib.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(self.device)))

    def check(self, result):
        if result:
            raise RuntimeError(self.lib.nvmlErrorString(result).decode())

    def mode(self):
        modes = Modes()
        self.check(self.lib.nvmlDeviceGetPowerMizerMode_v1(self.device,ctypes.byref(modes)))
        return modes

    def set(self, value):
        modes = Modes(requested=value)
        self.check(self.lib.nvmlDeviceSetPowerMizerMode_v1(self.device,ctypes.byref(modes)))


def main():
    stop = threading.Event()
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *args:stop.set())
    state = Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state"))) / "hyprstack/gpu-performance.json"
    power = PowerMizer()
    previous = power.mode().current
    if not power.mode().supported & (1 << 1):
        raise RuntimeError("GPU does not support the stock performance preference")
    state.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        # On Wayland, this preference belongs to the NVML client. A short
        # nvidia-settings invocation releases it as soon as nvmlShutdown runs.
        # Keep this client alive for the session, without polling or rendering.
        power.set(1)
        if power.mode().current != 1:
            raise RuntimeError("NVIDIA did not accept the performance preference")
        state.write_text(json.dumps({"mode":1,"previous":previous,"pid":os.getpid(),
            "session":os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")})+"\n")
        print("NVIDIA desktop performance enabled; previous preference:",previous,flush=True)
        stop.wait()
    finally:
        # Release only this client's preference; other applications keep theirs.
        power.set(previous)
        power.check(power.lib.nvmlShutdown())
        state.unlink(missing_ok=True)
        print("NVIDIA performance preference restored:",previous,flush=True)


if __name__ == "__main__":
    main()
