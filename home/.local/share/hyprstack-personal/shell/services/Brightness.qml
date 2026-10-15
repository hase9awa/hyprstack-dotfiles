pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.utils
import Hyprstack.Config
import qs.components.misc

Singleton {
    id: root

    readonly property list<Monitor> monitors: variants.instances // qmllint disable incompatible-type
    readonly property string helper: Paths.toLocalFile(Qt.resolvedUrl("../assets/brightness.py"))
    property var backends: ({})
    property bool dimmed: false
    property string outputModes: ""

    FileView {
        path: `${Quickshell.env("XDG_RUNTIME_DIR")}/hyprstack-brightness-${Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE")}.json`
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                root.dimmed = JSON.parse(text()).dimmed === true;
            } catch (error) {
                console.warn(`Unable to load brightness dim state: ${error}`);
            }
        }
    }

    onDimmedChanged: {
        for (const monitor of monitors)
            if (monitor.info)
                monitor.queueWrite();
    }

    function getMonitorForScreen(screen: ShellScreen): var {
        return monitors.find(m => m.modelData === screen); // qmllint disable missing-property
    }

    function getMonitor(query: string): var {
        if (query === "active") {
            return monitors.find(m => m.modelData.name === Hypr.focusedMonitor?.name); // qmllint disable missing-property
        }

        if (query.startsWith("model:")) {
            const model = query.slice(6);
            return monitors.find(m => m.modelData.model === model); // qmllint disable missing-property
        }

        if (query.startsWith("serial:")) {
            const serial = query.slice(7);
            return monitors.find(m => m.modelData.serialNumber === serial); // qmllint disable missing-property
        }

        if (query.startsWith("id:")) {
            const id = parseInt(query.slice(3), 10);
            return monitors.find(m => Hypr.monitorFor(m.modelData)?.id === id); // qmllint disable missing-property
        }

        return monitors.find(m => m.modelData.name === query); // qmllint disable missing-property
    }

    function increaseBrightness(): void {
        const monitor = getMonitor("active");
        if (monitor)
            monitor.setBrightness(monitor.brightness + GlobalConfig.services.brightnessIncrement);
    }

    function decreaseBrightness(): void {
        const monitor = getMonitor("active");
        if (monitor)
            monitor.setBrightness(monitor.brightness - GlobalConfig.services.brightnessIncrement);
    }

    onMonitorsChanged: probeTimer.restart()

    Variants {
        id: variants
        model: Quickshell.screens
        Monitor {}
    }

    Timer {
        id: probeTimer
        interval: 200
        onTriggered: {
            if (probeProc.running) {
                restart();
                return;
            }
            const screens = root.monitors.map(m => ({name: m.modelData.name,
                model: m.modelData.model, serial: m.modelData.serialNumber}));
            probeProc.command = ["python3", root.helper, "probe", JSON.stringify(screens)];
            if (root.dimmed)
                probeProc.command = [...probeProc.command, "--dimmed"];
            probeProc.running = true;
        }
    }

    Process {
        id: probeProc
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.backends = JSON.parse(text);
                } catch (error) {
                    console.warn(`Unable to probe brightness: ${error}`);
                }
            }
        }
    }

    // QScreen geometry does not change when an output switches between SDR/HDR.
    Timer {
        interval: 2000
        repeat: true
        running: true
        onTriggered: {
            if (!modeProc.running)
                modeProc.running = true;
        }
    }

    Process {
        id: modeProc
        command: ["python3", root.helper, "modes"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const outputs = JSON.parse(text);
                    const modes = Object.keys(outputs).sort().map(name => `${name}:${outputs[name]}`).join(",");
                    if (modes && root.outputModes !== modes) {
                        root.outputModes = modes;
                        probeTimer.restart();
                    }
                } catch (error) {
                    console.warn(`Unable to read output modes: ${error}`);
                }
            }
        }
    }

    // qmllint disable unresolved-type
    CustomShortcut {
        // qmllint enable unresolved-type
        name: "brightnessUp"
        description: "Increase brightness"
        onPressed: root.increaseBrightness()
    }

    // qmllint disable unresolved-type
    CustomShortcut {
        // qmllint enable unresolved-type
        name: "brightnessDown"
        description: "Decrease brightness"
        onPressed: root.decreaseBrightness()
    }

    IpcHandler {
        function get(): real {
            return getFor("active");
        }

        // Allows searching by active/model/serial/id/name
        function getFor(query: string): real {
            return root.getMonitor(query)?.brightness ?? -1;
        }

        function set(value: string): string {
            return setFor("active", value);
        }

        // Handles brightness value like brightnessctl: 0.1, +0.1, 0.1-, 10%, +10%, 10%-
        function setFor(query: string, value: string): string {
            const monitor = root.getMonitor(query);
            if (!monitor)
                return "Invalid monitor: " + query;
            if (monitor.backend === "disabled")
                return `Brightness slider is disabled in HDR for ${monitor.modelData.name}; set SDR brightness in the monitor config`;

            let targetBrightness;
            if (value.endsWith("%-")) {
                const percent = parseFloat(value.slice(0, -2));
                targetBrightness = monitor.brightness - (percent / 100);
            } else if (value.startsWith("+") && value.endsWith("%")) {
                const percent = parseFloat(value.slice(1, -1));
                targetBrightness = monitor.brightness + (percent / 100);
            } else if (value.endsWith("%")) {
                const percent = parseFloat(value.slice(0, -1));
                targetBrightness = percent / 100;
            } else if (value.startsWith("+")) {
                const increment = parseFloat(value.slice(1));
                targetBrightness = monitor.brightness + increment;
            } else if (value.endsWith("-")) {
                const decrement = parseFloat(value.slice(0, -1));
                targetBrightness = monitor.brightness - decrement;
            } else if (value.includes("%") || value.includes("-") || value.includes("+")) {
                return `Invalid brightness format: ${value}\nExpected: 0.1, +0.1, 0.1-, 10%, +10%, 10%-`;
            } else {
                targetBrightness = parseFloat(value);
            }

            if (isNaN(targetBrightness))
                return `Failed to parse value: ${value}\nExpected: 0.1, +0.1, 0.1-, 10%, +10%, 10%-`;

            monitor.setBrightness(targetBrightness);

            return `Set monitor ${monitor.modelData.name} brightness to ${+monitor.brightness.toFixed(2)}`;
        }

        function status(): string {
            return JSON.stringify(root.monitors.map(m => ({output: m.modelData.name,
                backend: m.backend, brightness: m.brightness,
                effective: m.effectiveBrightness, dimmed: root.dimmed})));
        }

        function refresh(): void { probeTimer.restart(); }

        target: "brightness"
    }

    component Monitor: QtObject {
        id: monitor
        required property ShellScreen modelData
        readonly property var detectedInfo: root.backends[modelData.name] ?? null
        property var info: null
        readonly property string backend: info?.backend ?? "pending"
        readonly property bool brightnessAvailable: backend !== "disabled" && backend !== "pending"
        property real brightness: 1
        readonly property real effectiveBrightness: backend === "disabled" ? 1 : brightness * (root.dimmed ? 0.65 : 1)
        property bool pendingWrite: false
        property int probeGeneration: 0

        onInfoChanged: {
            if (backend === "disabled") {
                brightness = 1;
                pendingWrite = false;
            }
        }

        onDetectedInfoChanged: {
            if (!detectedInfo)
                return;
            probeGeneration++;
            info = detectedInfo;
            if (!pendingWrite)
                brightness = detectedInfo.level;
            if (pendingWrite || root.dimmed)
                queueWrite();
        }

        function queueWrite(): void {
            if (backend === "disabled")
                return;
            pendingWrite = true;
            if (info && !writeTimer.running)
                writeTimer.start();
        }

        function setBrightness(value: real): void {
            if (backend === "disabled")
                return;
            if (!isFinite(value))
                return;
            value = Math.max(0, Math.min(1, value));
            if (Math.round(brightness * 100) === Math.round(value * 100) && !root.dimmed)
                return;
            // User activity cancels temporary idle dimming on every output.
            if (root.dimmed) {
                root.dimmed = false;
                Hypr.extras.message("eval hyprstack_brightness.restore()");
            }
            brightness = value;
            queueWrite();
        }

        readonly property Timer writeTimer: Timer {
            interval: monitor.backend === "software" ? 50 : 250
            onTriggered: {
                if (!monitor.info || !monitor.pendingWrite)
                    return;
                if (monitor.writeProc.running) {
                    restart();
                    return;
                }
                monitor.pendingWrite = false;
                monitor.writeProc.probeGeneration = monitor.probeGeneration;
                monitor.writeProc.command = ["python3", root.helper, "set", JSON.stringify(monitor.info),
                    "--level", String(monitor.brightness)];
                if (root.dimmed)
                    monitor.writeProc.command = [...monitor.writeProc.command, "--dimmed"];
                monitor.writeProc.running = true;
            }
        }

        readonly property Process writeProc: Process {
            property int probeGeneration: -1
            stdout: StdioCollector {
                onStreamFinished: {
                    try {
                        // A write started before a mode change cannot restore an old backend.
                        if (monitor.writeProc.probeGeneration !== monitor.probeGeneration)
                            return;
                        // A completed older write must not move the user's slider.
                        monitor.info = JSON.parse(text);
                    } catch (error) {
                        console.warn(`Unable to set ${monitor.modelData.name} brightness: ${error}`);
                    }
                }
            }
            onExited: (code, status) => {
                if (code !== 0 && monitor.writeProc.probeGeneration === monitor.probeGeneration && monitor.backend !== "disabled")
                    monitor.info = Object.assign({}, monitor.info, {backend: "software"});
                if (monitor.pendingWrite)
                    monitor.writeTimer.restart();
            }
        }

        // A black, input-transparent layer dims the entire output, including HDR
        // applications, without changing its mode, gamut or SDR reference white.
        readonly property PanelWindow dimLayer: PanelWindow {
            screen: monitor.modelData
            visible: monitor.backend === "software" && monitor.effectiveBrightness < 1
            color: Qt.rgba(0, 0, 0, 1 - monitor.effectiveBrightness)
            anchors { top: true; bottom: true; left: true; right: true }
            mask: Region {}
            WlrLayershell.namespace: "hyprstack-brightness"
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.exclusionMode: ExclusionMode.Ignore
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        }
    }
}
