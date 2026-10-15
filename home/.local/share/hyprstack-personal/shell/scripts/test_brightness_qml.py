#!/usr/bin/env python3
"""Check software dimming pixels and persistence in an isolated Wayland session."""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_CM = os.environ.get("HYPRSTACK_TEST_DESKTOP_CM", "srgb")
assert DESKTOP_CM in ("srgb", "dcip3")
base = Path(tempfile.mkdtemp(prefix="hs-bri-"))
print("Artifacts:", base, flush=True)
runtime, config, shell = base / "r", base / "config", base / "shell"
runtime.mkdir(mode=0o700)
(config / "hyprstack").mkdir(parents=True)
shell.mkdir()
for directory in ("services", "components", "utils", "assets"):
    (shell / directory).symlink_to(ROOT / directory, target_is_directory=True)
(shell / "shell.qml").write_text('''import QtQuick
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
                backend:m.backend, brightness:m.brightness, effective:m.effectiveBrightness,
                overlay:m.dimLayer.visible, width:m.dimLayer.width, height:m.dimLayer.height,
                screenWidth:m.modelData.width, screenHeight:m.modelData.height})));
        }
        function dim(value: bool): void { Brightness.dimmed = value; }
    }
}''')
hypr = base / "hyprland.lua"
hypr.write_text('package.path=' + json.dumps(str(ROOT / "assets/hyprland/config/?.lua")) + "..';'..package.path\n" +
               'dofile(' + json.dumps(str(ROOT / "assets/hyprland/dimming.lua")) + ')\n' +
               '''hl.monitor({output="",mode="640x480@60",position="auto",scale=1})
hl.config({animations={enabled=false},misc={disable_hyprland_logo=true,disable_splash_rendering=true},
    decoration={blur={enabled=false},shadow={enabled=false}}})
hl.layer_rule({match={namespace="^hyprstack-brightness$"},no_anim=true})
''')
parent_display = os.environ["WAYLAND_DISPLAY"]
if not parent_display.startswith("/"):
    parent_display = str(Path(os.environ["XDG_RUNTIME_DIR"]) / parent_display)
data = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "hyprstack"
env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), XDG_CONFIG_HOME=str(config),
           XDG_DATA_HOME=str(base / "data"), XDG_STATE_HOME=str(base / "state"),
           XDG_CACHE_HOME=str(base / "cache"), WAYLAND_DISPLAY=parent_display,
           AQ_DRM_DEVICES="/dev/null", QT_QPA_PLATFORM="wayland", HYPRSTACK_NESTED="1",
           QML_IMPORT_PATH=str(data / "qml"), QML2_IMPORT_PATH=str(data / "qml"),
           HYPRSTACK_LIB_DIR=str(data / "lib"), PYTHONDONTWRITEBYTECODE="1")
env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
children = []


def launch(args, logname):
    log = (base / logname).open("w")
    process = subprocess.Popen(args, env=env, stdout=log, stderr=log, start_new_session=True)
    children.append(process)
    return process


def wait(check, label):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(0.1)
    raise AssertionError("Timed out: " + label)


def command(args):
    return subprocess.check_output(args, env=env, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()


def ipc(target, method, *args):
    return command(["qs", "-p", str(shell), "ipc", "call", target, method, *map(str, args)])


def state():
    return json.loads(ipc("test", "state"))[0]


def pixel(name):
    output = base / (name + ".png")
    command(["grim", "-o", "WAYLAND-1", str(output)])
    image = Image.open(output).convert("RGB")
    return image.getpixel((image.width // 2, image.height // 2))


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


try:
    compositor = launch(["Hyprland", "-c", str(hypr)], "hyprland.log")
    socket = wait(lambda: next((runtime / "hypr").glob("*/.socket.sock"), None), "compositor")
    env["HYPRLAND_INSTANCE_SIGNATURE"] = socket.parent.name
    env["WAYLAND_DISPLAY"] = str(wait(lambda: next((p for p in runtime.glob("wayland-*")
                                                    if not p.name.endswith(".lock")), None), "display"))
    env.update(LIBGL_ALWAYS_SOFTWARE="1", __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json")
    window = launch(["qs", "-p", str(shell)], "shell.log")
    wait(lambda: state()["backend"] == "software", "software backend")
    assert not state()["overlay"]
    assert min(pixel("full")) >= 253
    ipc("brightness", "setFor", "WAYLAND-1", "45%")
    wait(lambda: state()["overlay"] and abs(state()["brightness"] - 0.45) < 0.001, "dim layer")
    time.sleep(0.7)
    measured = pixel("45-percent")
    assert all(abs(value - 115) <= 3 for value in measured), measured
    dimensions = state()
    assert dimensions["width"] == dimensions["screenWidth"] and dimensions["height"] == dimensions["screenHeight"], dimensions
    command(["hyprctl", "eval", "hyprstack_brightness.dim()"])
    time.sleep(0.7)
    measured = pixel("idle-dim")
    assert all(abs(value - 75) <= 3 for value in measured), measured
    stop(window)
    window = launch(["qs", "-p", str(shell)], "shell-dim-restarted.log")
    wait(lambda: state()["backend"] == "software" and abs(state()["brightness"] - 0.45) < 0.001
         and abs(state()["effective"] - 0.45 * 0.65) < 0.001, "selection after dimmed restart")
    command(["hyprctl", "eval", "hyprstack_brightness.restore()"])
    time.sleep(0.7)
    assert all(abs(value - 115) <= 3 for value in pixel("restored"))
    wait(lambda: json.loads((config / "hyprstack/brightness.json").read_text()).get("WAYLAND-1") == 0.45,
         "saved brightness")
    stop(window)
    window = launch(["qs", "-p", str(shell)], "shell-restarted.log")
    wait(lambda: state()["backend"] == "software" and abs(state()["brightness"] - 0.45) < 0.001, "restored selection")
    ipc("brightness", "setFor", "WAYLAND-1", "100%")
    wait(lambda: not state()["overlay"], "remove dim layer")
    time.sleep(0.5)
    assert min(pixel("full-again")) >= 253
    # Prove that an SDR desktop can still enter HDR for an actual PQ video.
    with hypr.open("a") as file:
        file.write('\nhl.monitor({output="",mode="640x480@60",position="auto",scale=1,cm="' + DESKTOP_CM + '",bitdepth=10,supports_hdr=1,supports_wide_color=1})\n'
                   'hl.config({render={cm_auto_hdr=1}})\n')
    command(["hyprctl", "reload"])

    def monitor_state():
        return json.loads(command(["hyprctl", "-j", "monitors"]))[0]

    subprocess.run(["make", "-C", str(ROOT.parent / "retired/hdr-brightness"), "probe"], check=True, stdout=subprocess.DEVNULL)

    def color_description():
        probe = subprocess.Popen([str(ROOT.parent / "retired/hdr-brightness/probe"), "WAYLAND-1"],
                                 env=env, stdout=subprocess.PIPE, text=True)
        try:
            if not select.select([probe.stdout], [], [], 3)[0]:
                raise AssertionError("No Wayland color description")
            return json.loads(probe.stdout.readline())
        finally:
            probe.terminate()
            probe.wait(timeout=3)

    wait(lambda: monitor_state()["colorManagementPreset"] == DESKTOP_CM, "SDR desktop")
    mode = [(monitor_state()[key]) for key in ("width", "height", "refreshRate")]
    video = base / "hdr.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
                    "-t", "1", "-vf", "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
                    "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
                    "-x265-params", "log-level=error:pools=1:frame-threads=1:colorprim=9:transfer=16:colormatrix=9",
                    "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", str(video)], check=True, timeout=15)
    player = launch(["mpv", "--no-config", "--vo=gpu-next", "--gpu-api=vulkan", "--gpu-context=waylandvk", "--gpu-sw=yes",
                     "--target-colorspace-hint=yes", "--target-colorspace-hint-mode=source", "--fullscreen",
                     "--loop-file=inf", str(video)], "mpv.log")
    # monitors reports the configured preset, even while auto-HDR is active.
    # Inspect the actual output description advertised through Wayland instead.
    wait(lambda: color_description()["tf"] == 11, "fullscreen HDR switch")
    assert monitor_state()["currentFormat"] in ("XBGR2101010", "XRGB2101010"), monitor_state()
    stop(player)
    wait(lambda: monitor_state()["colorManagementPreset"] == DESKTOP_CM, "return to SDR")
    wait(lambda: color_description()["tf"] != 11, "SDR transfer restored")
    assert [(monitor_state()[key]) for key in ("width", "height", "refreshRate")] == mode
    for name in ("shell.log", "shell-dim-restarted.log", "shell-restarted.log"):
        log = (base / name).read_text()
        assert not any(error in log for error in ("ReferenceError", "TypeError", "Unable to set", "Unable to probe", "Failed to load")), log
    print("PASS: real dimming pixels, full output coverage, idle restore, saved levels, restart, " + DESKTOP_CM + " desktop and automatic fullscreen HDR", flush=True)
finally:
    for process in reversed(children):
        stop(process)
