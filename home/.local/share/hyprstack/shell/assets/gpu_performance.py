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
import time


PERFORMANCE_MODE = 1
CHECK_INTERVAL = 1.0


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
            ("nvmlDeviceGetPerformanceState",[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint)]),
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

    def performance_state(self):
        state = ctypes.c_uint()
        self.check(self.lib.nvmlDeviceGetPerformanceState(self.device,ctypes.byref(state)))
        return state.value


def enforce(power):
    mode = power.mode().current
    state = power.performance_state()
    # A client's cached preference can remain 1 after the GPU has fallen back
    # to P5/P8. Renew that vote using the physical state as well as the API mode.
    changed = mode != PERFORMANCE_MODE or state >= 5
    if changed:
        power.set(PERFORMANCE_MODE)
        if power.mode().current != PERFORMANCE_MODE:
            raise RuntimeError("NVIDIA did not accept the performance preference")
    return changed, mode, state


def main():
    stop = threading.Event()
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *args:stop.set())
    state = Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state"))) / "hyprstack/gpu-performance.json"
    power = PowerMizer()
    previous = power.mode().current
    if not power.mode().supported & (1 << PERFORMANCE_MODE):
        raise RuntimeError("GPU does not support the stock performance preference")
    state.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    recoveries = 0

    def record():
        temporary = state.with_name(state.name + ".tmp")
        temporary.write_text(json.dumps({"mode":PERFORMANCE_MODE,"previous":previous,"pid":os.getpid(),
            "session":os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"),"recoveries":recoveries,
            "updated":time.time()})+"\n")
        temporary.replace(state)

    try:
        # A live NVML client alone does not guarantee that the global preference
        # survives other clients or driver state changes. Check once a second;
        # only write to the driver and state file when the preference drifts.
        enforce(power)
        record()
        print("NVIDIA desktop performance enabled; previous preference:",previous,flush=True)
        while not stop.wait(CHECK_INTERVAL):
            changed, mode, performance_state = enforce(power)
            if changed:
                recoveries += 1
                record()
                print("NVIDIA performance preference renewed; client mode",mode,
                    "GPU P"+str(performance_state),"recovery",recoveries,flush=True)
    finally:
        # Return to the preference observed before this desktop session.
        power.set(previous)
        power.check(power.lib.nvmlShutdown())
        state.unlink(missing_ok=True)
        print("NVIDIA performance preference restored:",previous,flush=True)


if __name__ == "__main__":
    main()
