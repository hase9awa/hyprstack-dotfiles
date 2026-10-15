#!/usr/bin/env python3
"""Verify live browser feedback and HDR brightness lock in a disposable session."""
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
PERSONAL = Path(os.environ.get("TEST_PERSONAL_DIR", str(ROOT.parents[1])))
SHELL = PERSONAL / "shell"
PROBE = PERSONAL / "retired/hdr-brightness/probe"
PLUGIN = Path(os.environ.get("TEST_HDR_PLUGIN", str(ROOT / "hdr-reference.so")))
base = Path(tempfile.mkdtemp(prefix="hs-hdr-"))
print("Artifacts:", base, flush=True)
runtime, config, test_shell = base / "r", base / "config", base / "shell"
runtime.mkdir(mode=0o700)
(config / "hyprstack").mkdir(parents=True)
(config / "hyprstack/brightness-backends.json").write_text(json.dumps({"disabled_in_hdr": ["WAYLAND-1"]}))
test_shell.mkdir()
for name in ("services", "components", "utils", "assets"):
    (test_shell / name).symlink_to(SHELL / name, target_is_directory=True)
(test_shell / "shell.qml").write_text('''import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.services
ShellRoot {
    PanelWindow {
        screen: Quickshell.screens[0]
        color: "white"
        anchors { top: true; bottom: true; left: true; right: true }
        WlrLayershell.layer: WlrLayer.Background
        WlrLayershell.exclusionMode: ExclusionMode.Ignore
    }
    IpcHandler {
        target: "test"
        function state(): string {
            return JSON.stringify(Brightness.monitors.map(m => ({name:m.modelData.name,
                backend:m.backend, available:m.brightnessAvailable, brightness:m.brightness,
                effective:m.effectiveBrightness, overlay:m.dimLayer.visible})));
        }
    }
}''')
hypr = base / "hyprland.lua"
hypr.write_text('package.path=' + json.dumps(str(SHELL / "assets/hyprland/config/?.lua")) + "..';'..package.path\n" +
                'dofile(' + json.dumps(str(SHELL / "assets/hyprland/dimming.lua")) + ')\n' +
                'hl.plugin.load(' + json.dumps(str(PLUGIN)) + ')\n' +
                'hl.plugin.hdr_reference.sync("WAYLAND-1")\n' +
                '''hl.monitor({output="WAYLAND-1",mode="640x480@60",position="auto",scale=1,
    cm="hdr",bitdepth=10,supports_hdr=1,supports_wide_color=1,
    max_luminance=1107,min_luminance=0.0109,max_avg_luminance=972,sdr_max_luminance=300})
hl.config({animations={enabled=false},misc={disable_hyprland_logo=true,disable_splash_rendering=true},
    render={cm_auto_hdr=1,cm_sdr_eotf="gamma22force"},
    decoration={blur={enabled=false},shadow={enabled=false}}})
''')
parent_display = os.environ["WAYLAND_DISPLAY"]
if not parent_display.startswith("/"):
    parent_display = str(Path(os.environ["XDG_RUNTIME_DIR"]) / parent_display)
data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "hyprstack"
env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(config),
           XDG_DATA_HOME=str(base / "data"), XDG_STATE_HOME=str(base / "state"),
           XDG_CACHE_HOME=str(base / "cache"), WAYLAND_DISPLAY=parent_display,
           AQ_DRM_DEVICES="/dev/null", QT_QPA_PLATFORM="wayland", HYPRSTACK_NESTED="1",
           QML_IMPORT_PATH=str(data / "qml"), QML2_IMPORT_PATH=str(data / "qml"),
           HYPRSTACK_LIB_DIR=str(data / "lib"), PYTHONDONTWRITEBYTECODE="1")
env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
children = []


def launch(args, name, extra=None):
    log = (base / name).open("w")
    process = subprocess.Popen(args, env=dict(env, **(extra or {})), stdout=log, stderr=log, start_new_session=True)
    children.append(process)
    return process


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def wait(check, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out: " + label)


def command(*args):
    return subprocess.check_output(list(args), env=env, text=True, stderr=subprocess.DEVNULL, timeout=6).strip()


def ipc(target, method, *args):
    return command("qs", "-p", str(test_shell), "ipc", "call", target, method, *map(str, args))


def state():
    return json.loads(ipc("test", "state"))[0]


def description():
    process = subprocess.Popen([str(PROBE), "WAYLAND-1"], env=env, stdout=subprocess.PIPE, text=True)
    try:
        assert select.select([process.stdout], [], [], 3)[0], "No color description"
        return json.loads(process.stdout.readline())
    finally:
        process.terminate()
        process.wait(timeout=3)


def monitor():
    return json.loads(command("hyprctl", "monitors", "-j"))[0]


def modes():
    return json.loads(command("python3", str(SHELL / "assets/brightness.py"), "modes"))


def set_monitor(**fields):
    fields["output"] = "WAYLAND-1"
    lua = ",".join(key + "=" + json.dumps(value) for key, value in fields.items())
    command("hyprctl", "eval", "hl.monitor({" + lua + "})")


try:
    compositor = launch(["Hyprland", "-c", str(hypr)], "hyprland.log")
    socket = wait(lambda: next((runtime / "hypr").glob("*/.socket.sock"), None), "compositor")
    env["HYPRLAND_INSTANCE_SIGNATURE"] = socket.parent.name
    env["WAYLAND_DISPLAY"] = str(wait(lambda: next((p for p in runtime.glob("wayland-*")
                                                    if not p.name.endswith(".lock")), None), "Wayland socket"))
    wait(lambda: description()["reference"] == 300, "configured reference")
    bounds = description()
    assert bounds["tf"] == 11 and bounds["max"] == 1107 and bounds["maxFALL"] == 972, bounds
    shell = launch(["qs", "-p", str(test_shell)], "shell.log",
                   {"LIBGL_ALWAYS_SOFTWARE": "1", "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json"})
    wait(lambda: state()["backend"] == "disabled", "disabled HDR slider")
    assert not state()["available"] and not state()["overlay"], state()
    assert "disabled" in ipc("brightness", "setFor", "WAYLAND-1", "20%")
    command("hyprctl", "eval", "hyprstack_brightness.dim()")
    time.sleep(0.4)
    assert state()["effective"] == 1 and not state()["overlay"], state()
    command("hyprctl", "eval", "hyprstack_brightness.restore()")
    assert not (config / "hyprstack/brightness.json").exists()
    print("PASS: HDR slider and idle dimming leave the output at full brightness.", flush=True)

    browser = launch(["thorium-browser", "--user-data-dir=" + str(base / "browser-profile"),
        "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
        "--disable-component-update", "--disable-sync", "--disable-extensions", "--password-store=basic",
        "--ozone-platform=wayland", "--enable-features=WaylandWpColorManagerV1",
        '--app=data:text/html,<body style="background:white"><script>let q=matchMedia("(dynamic-range: high)");function report(){document.title="HDR-reference-test:"+q.matches}q.addEventListener("change",report);report()</script>'],
        "browser.log", {"WAYLAND_DEBUG": "1"})
    wait(lambda: any(client.get("title") == "HDR-reference-test:true"
                     for client in json.loads(command("hyprctl", "clients", "-j"))), "browser HDR")
    original_mode = [monitor()[key] for key in ("width", "height", "refreshRate", "currentFormat")]
    for white in (140, 350, 300):
        set_monitor(sdr_max_luminance=white)
        wait(lambda: description()["reference"] == white, "reference " + str(white))
        wait(lambda: re.search(r"luminances\([^)]*, 1107, " + str(white) + r"\)", (base / "browser.log").read_text()),
             "browser feedback " + str(white))
        current = description()
        assert all(current[key] == bounds[key] for key in ("min", "max", "tf", "primaries", "maxFALL")), current
        current_mode = [monitor()[key] for key in ("width", "height", "refreshRate", "currentFormat")]
        # A nested output also follows the host window's asynchronous resize.
        assert current_mode[2:] == original_mode[2:], (original_mode, current_mode)
    print("PASS: an existing HDR browser receives 140/350/300 SDR-white updates; HDR bounds, refresh and bit depth stay unchanged.", flush=True)
    command("hyprctl", "reload")
    wait(lambda: description()["reference"] == 300, "reference after reload")
    stop(browser)

    set_monitor(cm="srgb")
    wait(lambda: description()["tf"] != 11, "SDR mode")
    wait(lambda: state()["backend"] == "software" and state()["available"], "SDR slider restored")
    ipc("brightness", "setFor", "WAYLAND-1", "45%")
    wait(lambda: state()["overlay"] and abs(state()["brightness"] - 0.45) < 0.001, "SDR dimming")
    wait(lambda: json.loads((config / "hyprstack/brightness.json").read_text()).get("WAYLAND-1") == 0.45,
         "committed SDR selection")
    set_monitor(cm="hdr")
    wait(lambda: state()["backend"] == "disabled" and not state()["overlay"] and state()["effective"] == 1,
         "remove SDR overlay in HDR")
    assert description()["reference"] == 300
    set_monitor(cm="srgb")
    wait(lambda: state()["backend"] == "software" and abs(state()["brightness"] - 0.45) < 0.001,
         "restore saved SDR brightness")
    ipc("brightness", "setFor", "WAYLAND-1", "100%")
    print("PASS: mode transitions disable HDR dimming and restore the saved SDR slider level.", flush=True)

    video = base / "hdr.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
        "-t", "1", "-vf", "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
        "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
        "-x265-params", "log-level=error:pools=1:frame-threads=1:colorprim=9:transfer=16:colormatrix=9",
        "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", str(video)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    player = launch(["mpv", "--no-config", "--vo=gpu-next", "--gpu-api=vulkan", "--gpu-context=waylandvk", "--gpu-sw=yes",
        "--target-colorspace-hint=yes", "--target-colorspace-hint-mode=source", "--fullscreen", "--loop-file=inf", str(video)], "mpv.log")
    wait(lambda: modes().get("WAYLAND-1") == "hdr", "actual automatic HDR detection")
    wait(lambda: state()["backend"] == "disabled", "automatic HDR brightness lock")
    assert description()["reference"] == 300 and not state()["overlay"]
    stop(player)
    wait(lambda: modes().get("WAYLAND-1") == "srgb" and state()["available"], "return from automatic HDR")
    print("PASS: automatic fullscreen HDR also disables the slider and returns to SDR correctly.", flush=True)

    set_monitor(cm="hdr")
    wait(lambda: description()["reference"] == 300, "HDR before unload")
    command("hyprctl", "plugin", "unload", str(PLUGIN))
    wait(lambda: description()["reference"] == 203, "restore compositor reference on unload")
    for name in ("hyprland.log", "shell.log"):
        log = (base / name).read_text()
        assert not any(error in log for error in ("ReferenceError", "TypeError", "Unable to set", "Unable to probe", "Failed to load")), log[-3000:]
    print("PASS: reload, unload, and clean QML runtime.", flush=True)
except BaseException:
    for name in ("hyprland.log", "shell.log", "mpv.log"):
        path = base / name
        if path.exists():
            print(name + ":\n" + "\n".join(path.read_text().splitlines()[-12:]), flush=True)
    raise
finally:
    for child in reversed(children):
        stop(child)
