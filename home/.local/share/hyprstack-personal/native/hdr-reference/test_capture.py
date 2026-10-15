#!/usr/bin/env python3
"""Measure real Thorium, SDR reference and live window previews in isolated HDR."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import re

from PIL import Image

HERE = Path(__file__).resolve().parent
PLUGIN = Path(os.environ.get("TEST_HDR_PLUGIN", str(HERE / "hdr-reference.so")))
CHECK = os.environ.get("ASSERT_CAPTURE", "1") != "0"
CLIENT_SDR = os.environ.get("TEST_CLIENT_SDR", "0") == "1"
CLIENT_CM_OFF = os.environ.get("TEST_CLIENT_CM_OFF", "0") == "1"
base = Path(tempfile.mkdtemp(prefix="c-"))
print("Artifacts:", base, flush=True)
runtime = base / "r"
runtime.mkdir(mode=0o700)
host = dict(os.environ)
display = host["WAYLAND_DISPLAY"]
if not display.startswith("/"):
    display = str(Path(host["XDG_RUNTIME_DIR"]) / display)
env = dict(host, XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=display,
           XDG_CONFIG_HOME=str(base / "config"), XDG_DATA_HOME=str(base / "data"),
           XDG_CACHE_HOME=str(base / "cache"), XDG_STATE_HOME=str(base / "state"),
           AQ_DRM_DEVICES="/dev/null", QT_QPA_PLATFORM="wayland", HYPRSTACK_NESTED="1")
env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
children = []
inspector=base/"color-inspector.so"
flags=subprocess.check_output(["pkg-config","--cflags","hyprland","pixman-1","libdrm","libinput","libudev","wayland-server","xkbcommon","lua"],text=True).split()
subprocess.run(["c++","-std=c++23","-shared","-fPIC","-fno-gnu-unique",*flags,str(HERE/"test-colors.cpp"),"-o",str(inspector)],check=True)
values = [(v, v, v) for v in (32, 64, 128, 192, 224, 255)] + [
    (160,32,24), (16,144,64), (48,80,224), (192,144,16), (144,48,176), (16,160,176)]
config = base / "hyprland.lua"
config.write_text('package.path=' + json.dumps(str(Path.home() / ".local/share/hyprstack/shell/assets/hyprland/config/?.lua")) + "..';'..package.path\n" +
    'hl.plugin.load(' + json.dumps(str(PLUGIN)) + ')\n' +
    'hl.plugin.load(' + json.dumps(str(inspector)) + ')\n' +
    '''hl.monitor({output="WAYLAND-1",mode="1280x900@60",position="0x0",scale=1,
      cm="hdr",bitdepth=10,supports_hdr=1,supports_wide_color=1,
      max_luminance=1107,min_luminance=0.0109,max_avg_luminance=972,sdr_max_luminance=300})
    hl.plugin.hdr_reference.sync("WAYLAND-1")
    hl.config({animations={enabled=false},general={border_size=0,gaps_in=0,gaps_out=0},
      misc={disable_hyprland_logo=true,disable_splash_rendering=true},
      decoration={rounding=0,shadow={enabled=false},blur={enabled=false}},render={cm_auto_hdr=0}})
    hl.window_rule({match={class=".*"},float=true})
''' + ('hl.plugin.hdr_reference.sdr_client("thorium-browser")\n' if CLIENT_SDR else ""))

def run(args, e=None):
    r = subprocess.run(args, env=e or env, capture_output=True, text=True, timeout=10)
    if r.returncode:
        raise RuntimeError(str(args)+": "+r.stdout+r.stderr)
    return r.stdout.strip()

def ctl(*args):
    return run(["hyprctl", *args])

def launch(args, name, extra=None):
    log = (base / name).open("w")
    p = subprocess.Popen(args, env=dict(env, **(extra or {})), stdout=log, stderr=log, start_new_session=True)
    children.append(p)
    return p

def wait(check, label):
    until = time.monotonic()+25
    while time.monotonic()<until:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(.1)
    raise AssertionError("Timed out: "+label)

def client(title):
    return next((c for c in json.loads(ctl("-j","clients")) if c["title"]==title), None)

def place(w, x, y, width=600, height=300):
    ctl("eval", 'local w=hl.get_window('+json.dumps("address:"+w["address"])+'); '
        'hl.dispatch(hl.dsp.window.resize({window=w,x='+str(width)+',y='+str(height)+',relative=false})); '
        'hl.dispatch(hl.dsp.window.move({window=w,x='+str(x)+',y='+str(y)+',relative=false}))')

def sample(name):
    time.sleep(.8)
    path=base/(name+".png")
    run(["grim","-o","WAYLAND-1",str(path)])
    im=Image.open(path).convert("RGB")
    rows={label:[im.getpixel((x+25+50*i,y)) for i in range(12)] for label,x,y in (
        ("sdr",20,180),("browser",660,180),("sdr-preview",20,590),("browser-preview",620,590))}
    print(json.dumps({"case":name,"samples":rows}),flush=True)
    if CHECK:
        for label,row in rows.items():
            assert max(abs(c-e) for p,v in zip(row[:6],values[:6]) for c,e in zip(p,v))<=3,(name,label,row)
            def linear(c):
                c=c/255
                return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
            assert max(abs(linear(c)-linear(e)) for p,v in zip(row[6:],values[6:]) for c,e in zip(p,v))<=.025,(name,label,row)
        for original,preview in (("sdr","sdr-preview"),("browser","browser-preview")):
            assert max(abs(c-e) for p,v in zip(rows[original],rows[preview]) for c,e in zip(p,v))<=3,(name,original,rows)
    if CLIENT_SDR:
        gradients={label:[im.getpixel((x+i,330)) for i in range(600)] for label,x in (("sdr",20),("browser",660))}
        for label,line in gradients.items():
            levels=len(set(line))
            chroma=max(max(v)-min(v) for v in line)
            step=max(max(abs(a-b) for a,b in zip(line[i],line[i-1])) for i in range(1,600))
            print(json.dumps({"case":name,"gradient":label,"levels":levels,"max_chroma":chroma,"max_step":step}),flush=True)
            if CHECK:
                assert levels>=250 and chroma<=1 and step<=2,(name,label,levels,chroma,step)
    return rows

try:
    compositor=launch(["Hyprland","-c",str(config)],"hyprland.log")
    sock=wait(lambda:next((runtime/"hypr").glob("*/.socket.sock"),None),"compositor")
    env["HYPRLAND_INSTANCE_SIGNATURE"]=sock.parent.name
    env["WAYLAND_DISPLAY"]=str(wait(lambda:next((p for p in runtime.glob("wayland-*") if not p.name.endswith(".lock")),None),"display"))
    outer=wait(lambda:next((c for c in json.loads(run(["hyprctl","-j","clients"],host)) if c["pid"]==compositor.pid),None),"nested host window")
    run(["hyprctl","eval",'local w=hl.get_window('+json.dumps("address:"+outer["address"])+'); '
        'hl.dispatch(hl.dsp.window.float({window=w,action="enable"})); '
        'hl.dispatch(hl.dsp.window.resize({window=w,x=1280,y=900,relative=false}))'],host)
    wait(lambda:any(m["width"]==1280 and m["height"]==900 for m in json.loads(ctl("-j","monitors"))),"fixed test dimensions")
    time.sleep(.5)
    qml=base/"reference.qml"
    qml.write_text('''import QtQuick
import Quickshell
FloatingWindow {
 visible:true; implicitWidth:600; implicitHeight:300; title:"SDR-reference"
 Row { width:600; height:200
  Repeater { model:''' + json.dumps(values) + '''
   Rectangle { required property var modelData; width:50; height:200
    color:Qt.rgba(modelData[0]/255,modelData[1]/255,modelData[2]/255,1)
   }
  }
 }
 Rectangle { y:200; width:600; height:100
  gradient:Gradient { orientation:Gradient.Horizontal; GradientStop {position:0;color:"black"} GradientStop {position:1;color:"white"} }
 }
}''')
    launch(["qs","-p",str(qml)],"reference.log",{
        "LIBGL_ALWAYS_SOFTWARE":"1","__EGL_VENDOR_LIBRARY_FILENAMES":"/usr/share/glvnd/egl_vendor.d/50_mesa.json"})
    page=base/"patches.html"
    page.write_text('<title>Thorium-reference</title><style>html,body{margin:0;overflow:hidden}#colors{display:flex;height:200px}#colors div{width:8.3333333333%;height:100%}#gradient{height:100px;background:linear-gradient(90deg,#000,#fff)}</style><div id="colors">'+
        ''.join('<div style="background:rgb(%d,%d,%d)"></div>'%v for v in values)+'</div><div id="gradient"></div>')
    launch(["thorium-browser","--user-data-dir="+str(base/"browser-profile"),"--no-first-run",
        "--no-default-browser-check","--disable-background-networking","--disable-component-update",
        "--disable-sync","--disable-extensions","--password-store=basic","--ozone-platform=wayland",
        "--enable-features=HdrAgtm,WaylandWpColorManagerV1",*( ["--disable-features=WaylandWpColorManagerV1"] if CLIENT_CM_OFF else []),"--app="+page.as_uri()],"browser.log",{"WAYLAND_DEBUG":"1"})
    q=wait(lambda:client("SDR-reference"),"SDR reference")
    b=wait(lambda:client("Thorium-reference"),"browser reference")
    place(q,20,80); place(b,660,80)
    if CLIENT_SDR:
        ctl("eval",'hl.plugin.hdr_reference.sdr_client('+json.dumps(b["class"])+')')
        ctl("eval",'hl.monitor({output="WAYLAND-1",sdr_max_luminance=350,sdr_min_luminance=0})')
    previews=base/"previews.qml"
    previews.write_text('''import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import Quickshell.Io
FloatingWindow {
 visible:true; implicitWidth:1200; implicitHeight:300; title:"Colour-previews"
 Row { Repeater { id:views; model:["SDR-reference","Thorium-reference"]
  ScreencopyView {required property string modelData; width:600; height:300; live:true
   constraintSize:Qt.size(600,300)
   captureSource:ToplevelManager.toplevels.values.find(t=>t.title===modelData)??null
  }
 }}
 IpcHandler {target:"test"
  function state():string {return JSON.stringify([0,1].map(i=>({source:views.itemAt(i)?.captureSource?.title,content:views.itemAt(i)?.hasContent})));}
 }
}''')
    launch(["qs","-p",str(previews)],"previews.log",{
        "LIBGL_ALWAYS_SOFTWARE":"1","__EGL_VENDOR_LIBRARY_FILENAMES":"/usr/share/glvnd/egl_vendor.d/50_mesa.json"})
    p=wait(lambda:client("Colour-previews"),"preview window")
    place(p,20,490,1200,300)
    wait(lambda:all(x["content"] for x in json.loads(run(["qs","-p",str(previews),"ipc","call","test","state"]))),"real captures")
    print(ctl("repl",'return require("utils.json").encode(hl.plugin.color_inspector.status())'),flush=True)
    for white, brightness in ((300,1.0),(140,1.0),(350,1.0),(300,0.5),(300,1.25),(300,1.0)):
        ctl("eval",'hl.monitor({output="WAYLAND-1",sdr_max_luminance='+str(white)+',sdrbrightness='+str(brightness)+'})')
        sample("white-"+str(white)+"-brightness-"+str(brightness))
        if CHECK:
            effective=round(white*brightness)
            log=(base/"browser.log").read_text()
            if CLIENT_CM_OFF:
                assert "wp_color_manager_v1#" not in log,"client used disabled protocol"
            elif CLIENT_SDR:
                assert re.search(r"luminances\([^)]*, "+str(effective)+", "+str(effective)+r"\)",log),(white,brightness,"missing SDR feedback")
            else:
                assert re.search(r"luminances\([^)]*, 1107, "+str(effective)+r"\)",log),(white,brightness,"missing feedback")
            if CLIENT_SDR:
                state=json.loads(ctl("repl",'return require("utils.json").encode(hl.plugin.color_inspector.status())'))
                browser=next(w for w in state if w["title"]=="Thorium-reference")
                assert all(s.get("tf",9)==9 and s.get("primaries",1)==1 for s in browser["surfaces"]),(white,brightness,browser)
            else:
                assert re.search(r"set_luminances\(0, 1000, "+str(effective)+r"\)",log),(white,brightness,"browser did not update encoding")
    ctl("reload")
    sample("reloaded")
    ctl("eval",'hl.monitor({output="WAYLAND-1",cm="srgb"})')
    sample("sdr-mode")
    ctl("eval",'hl.monitor({output="WAYLAND-1",cm="hdr"})')
    sample("back-to-hdr")
    ctl("plugin","unload",str(PLUGIN))
    if CHECK:
        print("PASS: SDR/browser grayscale and colors, live previews, both global controls, reload, mode changes and unload.",flush=True)
    print("DONE",flush=True)
finally:
    for p in reversed(children):
        if p.poll() is None:
            os.killpg(p.pid,signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGKILL); p.wait()
