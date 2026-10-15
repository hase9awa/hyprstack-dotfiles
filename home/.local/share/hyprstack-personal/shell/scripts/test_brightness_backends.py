#!/usr/bin/env python3
"""Verify output routing and fallback without writing to physical displays."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("brightness_backend", ROOT / "assets/brightness.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class BrightnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, XDG_CONFIG_HOME=self.directory.name)
        environment.start()
        self.addCleanup(environment.stop)

    def hdr_policy(self, *outputs):
        path = backend.preferences_path().with_name("brightness-backends.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"disabled_in_hdr": outputs}))

    def test_hdr_policy_disables_only_the_selected_panel_without_ddc_writes(self):
        self.hdr_policy("main")
        backend.save("main", 0.7)
        commands = []

        def run(args):
            commands.append(args)
            if args[0] == "hyprctl":
                return '{"DP-1":"hdr","DP-2":"hdr"}'
            if "detect" in args:
                return "Display 1\n I2C bus: /dev/i2c-2\n DRM connector: card1-DP-2"
            return "VCP 10 C 45 100"

        with patch.object(backend, "run", side_effect=run), \
             patch.object(backend, "output_key", side_effect=lambda s: "main" if s["name"] == "DP-1" else "other"):
            result = backend.probe([{"name": "DP-1"}, {"name": "DP-2"}], dimmed=True)
            changed = backend.set_brightness(result["DP-1"], 0.2, dimmed=True)
        self.assertEqual(result["DP-1"]["backend"], "disabled")
        self.assertEqual(result["DP-2"]["backend"], "ddc")
        self.assertEqual(changed["level"], 1)
        self.assertEqual(changed["effective"], 1)
        self.assertEqual(backend.preferences()["main"], 0.7)
        self.assertFalse(any("setvcp" in command for command in commands))

    def test_stale_ddc_backend_cannot_write_after_hdr_switch(self):
        self.hdr_policy("panel")
        info = {"backend": "ddc", "bus": "2", "maximum": 100, "key": "panel", "name": "DP-1"}
        with patch.object(backend, "run", return_value='{"DP-1":"hdr"}') as run:
            result = backend.set_brightness(info, 0.4)
        self.assertEqual(result["backend"], "disabled")
        self.assertFalse(any("setvcp" in call.args[0] for call in run.call_args_list))
        self.assertEqual(backend.preferences(), {})

    def test_hdr_policy_restores_physical_control_when_output_returns_to_sdr(self):
        self.hdr_policy("panel")
        info = {"backend": "disabled", "maximum": 1, "key": "panel", "name": "DP-1", "hdr_disabled": True}
        commands = []

        def run(args):
            commands.append(args)
            if args[0] == "hyprctl": return '{"DP-1":"srgb"}'
            if "detect" in args: return "Display 1\n I2C bus: /dev/i2c-2\n DRM connector: card1-DP-1"
            return "VCP 10 C 40 100" if "getvcp" in args else ""

        with patch.object(backend, "run", side_effect=run), patch.object(backend, "output_key", return_value="panel"):
            result = backend.set_brightness(info, 0.4)
        self.assertEqual(result["backend"], "ddc")
        self.assertIn(["ddcutil", "--bus", "2", "setvcp", "10", "40"], commands)

    def test_actual_hdr_description_takes_priority_over_configured_sdr_preset(self):
        with patch.object(backend, "run", return_value='{"DP-1":"hdr"}') as run:
            self.assertEqual(backend.output_modes(), {"DP-1": "hdr"})
        self.assertEqual(run.call_count, 1)

    def test_detection_rejects_invalid_or_incomplete_ddc_blocks(self):
        text = """Display 1
  I2C bus: /dev/i2c-2
  DRM connector: card12-DP-1

Invalid display
  I2C bus: /dev/i2c-3
  DRM connector: card12-HDMI-A-2

Display 3
  I2C bus: /dev/i2c-4
"""
        self.assertEqual(backend.ddc_displays(text), {"DP-1": "2"})
        self.assertEqual(backend.vcp("VCP 10 C 40 200"), (40, 200))
        for text in ("VCP 10 ERR", "VCP 10 C 10 0", "VCP 10 C 101 100"):
            self.assertIsNone(backend.vcp(text))

    def test_external_output_does_not_use_laptop_backlight(self):
        with patch.object(backend, "connector_path", side_effect=AssertionError("external backlight query")):
            self.assertIsNone(backend.backlight("HDMI-A-1"))
            self.assertIsNone(backend.backlight("DP-1"))

    def test_physical_control_has_priority_and_scales_to_vcp_maximum(self):
        commands = []

        def run(args):
            commands.append(args)
            return "VCP 10 C 80 200" if "getvcp" in args else ""

        info = {"backend": "ddc", "bus": "2", "maximum": 200, "key": "panel", "name": "DP-1"}
        with patch.object(backend, "run", side_effect=run):
            result = backend.set_brightness(info, 0.4)
        self.assertEqual(result["backend"], "ddc")
        self.assertEqual(commands[0], ["ddcutil", "--bus", "2", "setvcp", "10", "80"])
        self.assertEqual(backend.preferences(), {"panel": 0.4})

    def test_failed_or_ignored_hardware_writes_use_software(self):
        info = {"backend": "ddc", "bus": "2", "maximum": 100, "key": "panel"}
        for reply in (None, "VCP 10 C 100 100"):
            with patch.object(backend, "run", return_value=reply):
                result = backend.set_brightness(info, 0.5)
            self.assertEqual(result["backend"], "software")
            self.assertEqual(result["effective"], 0.5)
        self.assertEqual(backend.preferences()["panel"], 0.5)

    def test_missing_ddc_brightness_falls_back_per_output(self):
        detect = "Display 1\n I2C bus: /dev/i2c-2\n DRM connector: card1-DP-1"
        backend.save("second", 0.7)
        with patch.object(backend, "run", side_effect=[detect, "VCP 10 C 45 100"]), \
             patch.object(backend, "output_key", side_effect=lambda s: s["name"]):
            result = backend.probe([{"name": "DP-1"}, {"name": "second"}])
        self.assertEqual(result["DP-1"]["backend"], "ddc")
        self.assertEqual(result["DP-1"]["level"], 0.45)
        self.assertEqual(result["second"]["backend"], "software")
        self.assertEqual(result["second"]["level"], 0.7)

    def test_dimming_does_not_overwrite_selected_level(self):
        info = {"backend": "ddc", "bus": "2", "maximum": 100, "key": "panel"}
        with patch.object(backend, "run", side_effect=["", "VCP 10 C 52 100"]):
            result = backend.set_brightness(info, 0.8, dimmed=True)
        self.assertEqual(result["backend"], "ddc")
        self.assertEqual(result["effective"], 0.52)
        self.assertEqual(backend.preferences()["panel"], 0.8)
        detect = "Display 1\n I2C bus: /dev/i2c-2\n DRM connector: card1-DP-1"
        with patch.object(backend, "run", side_effect=[detect, "VCP 10 C 52 100"]), \
             patch.object(backend, "output_key", return_value="panel"):
            result = backend.probe([{"name": "DP-1"}], dimmed=True)
        self.assertEqual(result["DP-1"]["level"], 0.8)

    def test_software_levels_persist_and_invalid_values_do_not_write(self):
        info = {"backend": "software", "maximum": 1, "key": "one"}
        backend.set_brightness(info, 0.6)
        backend.set_brightness(dict(info, key="two"), 0.3)
        self.assertEqual(backend.preferences(), {"one": 0.6, "two": 0.3})
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                backend.set_brightness(info, value)
        self.assertEqual(backend.preferences()["one"], 0.6)


if __name__ == "__main__":
    unittest.main()
