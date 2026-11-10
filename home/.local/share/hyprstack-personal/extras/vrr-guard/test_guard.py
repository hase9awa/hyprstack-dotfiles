"""Monitor/fullscreen policy tests, using the real Hyprland JSON field values."""
import copy
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

spec = importlib.util.spec_from_file_location("vrr_guard", Path(__file__).with_name("guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.monitors = [
            {"id": 0, "name": "HDMI-A-1", "description": "BenQ", "vrr": False,
             "activeWorkspace": {"id": 21}, "specialWorkspace": {"id": 0}},
            {"id": 1, "name": "DP-1", "description": "P275MR+", "vrr": True,
             "activeWorkspace": {"id": 3}, "specialWorkspace": {"id": 0}},
        ]
        self.client = {"monitor": 1, "workspace": {"id": 3}, "mapped": True,
                       "hidden": False, "fullscreen": 0, "fullscreenClient": 0}

    def test_uses_vrr_monitor_instead_of_first_output(self):
        before = copy.deepcopy(self.monitors)
        self.assertEqual(guard.desktop_outputs(self.monitors, []), {"DP-1"})
        self.assertEqual(self.monitors, before)

    def test_fullscreen_pauses_only_its_monitor(self):
        for mode in (2, 3):
            self.client["fullscreen"] = mode
            self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), set())
        self.client["monitor"] = 0
        self.client["workspace"]["id"] = 21
        self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), {"DP-1"})

    def test_maximize_and_fake_client_fullscreen_remain_protected(self):
        self.client["fullscreenClient"] = 2
        for mode in (0, 1):
            self.client["fullscreen"] = mode
            self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), {"DP-1"})

    def test_static_fullscreen_browsers_remain_protected(self):
        self.client["fullscreen"] = 2
        for app in ("thorium-browser", "org.chromium.Thorium", "firefox", "Google-chrome", "zen-browser"):
            self.client["class"] = app
            self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), {"DP-1"})
        for app in ("steam_app_123", "mpv", "my-thorium-game"):
            self.client["class"] = app
            self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), set())

    def test_hidden_or_inactive_fullscreen_does_not_pause(self):
        self.client["fullscreen"] = 2
        for key, value in (("hidden", True), ("mapped", False)):
            client = dict(self.client, **{key: value})
            self.assertEqual(guard.desktop_outputs(self.monitors, [client]), {"DP-1"})
        self.client["workspace"] = {"id": 2}
        self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), {"DP-1"})

    def test_fullscreen_on_visible_special_workspace_pauses(self):
        self.monitors[1]["specialWorkspace"]["id"] = -98
        self.client.update(fullscreen=2, workspace={"id": -98})
        self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), set())

    def test_dpms_disabled_mirror_and_hotplug(self):
        for setting in ({"dpmsStatus": False}, {"disabled": True}, {"vrr": False}, {"mirrorOf": "HDMI-A-1"}):
            monitors = copy.deepcopy(self.monitors)
            monitors[1].update(setting)
            self.assertEqual(guard.desktop_outputs(monitors, []), set())
        self.assertEqual(guard.desktop_outputs(self.monitors[:1], []), set())
        self.assertEqual(guard.desktop_outputs(self.monitors, []), {"DP-1"})

    def test_filter_and_connector_rename(self):
        self.assertEqual(guard.desktop_outputs(self.monitors, [], "HDMI-A-1"), set())
        self.monitors[1]["name"] = "DP-2"
        self.assertEqual(guard.desktop_outputs(self.monitors, [], "DP-1"), set())
        self.assertEqual(guard.desktop_outputs(self.monitors, [], "desc:P275"), {"DP-2"})

    def test_057_monitor_addresses_match_client_names(self):
        self.monitors[1].update(activeWorkspace={"address": "3", "name": "3", "type": "normal"},
                                specialWorkspace={"address": "", "name": "", "type": ""})
        self.client.update(fullscreen=2, workspace={"id": 3, "address": "3", "name": "3"})
        self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), set())
        self.client["workspace"] = {"id": 4, "address": "4", "name": "4"}
        self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), {"DP-1"})
        self.monitors[1]["specialWorkspace"] = {"address": "special:game", "name": "special:game"}
        self.client["workspace"] = {"id": -98, "name": "special:game"}
        self.assertEqual(guard.desktop_outputs(self.monitors, [self.client]), set())


class LifecycleTest(unittest.TestCase):
    def test_socket_events_stop_resume_and_clean_up_real_worker(self):
        with tempfile.TemporaryDirectory(prefix="vrr-guard-test-") as directory:
            root = Path(directory)
            pixel = root / "pixel"
            pixel.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n")
            pixel.chmod(0o755)
            monitors = [{"id": 1, "name": "DP-1", "vrr": True,
                         "activeWorkspace": {"id": 3}, "specialWorkspace": {"id": 0}}]
            clients = [{"monitor": 1, "workspace": {"id": 3}, "fullscreen": 2}]
            requests, errors = [], []
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as commands, \
                    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as events:
                commands.bind(str(root / ".socket.sock")); commands.listen()
                events.bind(str(root / ".socket2.sock")); events.listen()
                commands.settimeout(0.1)
                serving = threading.Event(); serving.set()

                def serve():
                    while serving.is_set():
                        try:
                            connection, _ = commands.accept()
                        except socket.timeout:
                            continue
                        with connection:
                            chunks = []
                            while chunk := connection.recv(4096): chunks.append(chunk)
                            command = b"".join(chunks).decode()
                            requests.append(command)
                            connection.sendall(json.dumps(monitors if command == "j/monitors" else clients).encode())

                def wait_for(predicate):
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        if predicate(): return
                        if errors: raise errors[0]
                        time.sleep(0.01)
                    self.fail("Supervisor did not react to an IPC transition")

                worker_guard = guard.Guard(root, pixel)
                def supervise():
                    try: worker_guard.run()
                    except Exception as error: errors.append(error)

                server = threading.Thread(target=serve)
                runner = threading.Thread(target=supervise)
                server.start(); runner.start()
                stream, _ = events.accept()
                try:
                    wait_for(lambda: len(requests) >= 2)
                    self.assertFalse(worker_guard.workers, "Must not start over an existing fullscreen app")
                    clients[0]["fullscreen"] = 0
                    stream.sendall(b"fullscreen>>0\n")
                    wait_for(lambda: "DP-1" in worker_guard.workers)
                    first = worker_guard.workers["DP-1"]
                    stream.sendall(b"fullscreen>>0\nfullscreen>>0\n")
                    time.sleep(0.1)
                    self.assertIs(worker_guard.workers["DP-1"], first, "Duplicate events created another worker")
                    count = len(requests)
                    time.sleep(1.1)
                    self.assertEqual(len(requests), count, "IPC was polled on a static desktop")
                    clients[0]["fullscreen"] = 2
                    stream.sendall(b"fullscreen>>1\n")
                    wait_for(lambda: not worker_guard.workers and first.poll() is not None)
                    clients[0]["workspace"] = {"id": 2}
                    stream.sendall(b"workspacev2>>3,3\n")
                    wait_for(lambda: "DP-1" in worker_guard.workers)
                    second = worker_guard.workers["DP-1"]
                    self.assertNotEqual(second.pid, first.pid)
                    stream.close()  # Compositor exit terminates the remaining worker.
                    runner.join(timeout=3)
                    self.assertFalse(runner.is_alive())
                    self.assertIsNotNone(second.poll())
                    self.assertFalse(worker_guard.workers)
                    self.assertFalse(errors, errors)
                finally:
                    worker_guard.stop()
                    stream.close()
                    runner.join(timeout=3)
                    serving.clear(); server.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
