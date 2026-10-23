from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import bt600_probe
import bt600_vendor_read
import usb_access_guard as guard
import usb_inspect


class UsbAccessGuardTests(unittest.TestCase):
    def test_pause_blocks_each_library_entry_before_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "USB_ACCESS_DISABLED"
            marker.write_text("paused")
            entries = ((bt600_probe, bt600_probe.main),
                       (bt600_vendor_read, bt600_vendor_read.main),
                       (usb_inspect, usb_inspect.load_libusb))
            for module, entry in entries:
                with self.subTest(module=module.__name__), \
                     patch.object(guard, "BLOCK_FILE", marker), \
                     patch.object(module.C, "CDLL") as load, \
                     patch.object(module.Path, "is_file", return_value=True), \
                     patch("sys.argv", [module.__name__]), patch("builtins.print"):
                    with self.assertRaisesRegex(SystemExit, "USB entry point remains blocked"):
                        entry()
                    load.assert_not_called()

    def test_offline_modes_remain_available_while_paused(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "USB_ACCESS_DISABLED"
            marker.write_text("paused")
            for module, option in ((bt600_probe, "--inspect-stock"),
                                   (bt600_vendor_read, "--describe")):
                with self.subTest(option=option), patch.object(guard, "BLOCK_FILE", marker), \
                     patch.object(module.C, "CDLL") as load, \
                     patch("sys.argv", [module.__name__, option]), patch("builtins.print"):
                    self.assertEqual(module.main(), 0)
                    load.assert_not_called()

    def test_absent_marker_only_releases_the_guard(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(guard, "BLOCK_FILE", Path(folder) / "USB_ACCESS_DISABLED"):
            self.assertIsNone(guard.require_usb_access())

    def test_recorded_descriptor_scope_leaves_legacy_paths_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            marker, resume = Path(folder) / "USB_ACCESS_DISABLED", Path(folder) / "resume.json"
            marker.write_text("paused")
            resume.write_text(json.dumps({"user_authorized_hardware": True,
                "operations": ["device_descriptor_read", "claim_interface"]}))
            with patch.object(guard, "BLOCK_FILE", marker), patch.object(guard, "RESUME_FILE", resume):
                self.assertIsNone(guard.require_usb_access("device_descriptor_read"))
                for operation in (None, "claim_interface", "native_hci_read"):
                    with self.subTest(operation=operation), self.assertRaises(SystemExit):
                        guard.require_usb_access(operation)

    def test_missing_invalid_or_unapproved_resume_record_stays_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            marker, resume = Path(folder) / "USB_ACCESS_DISABLED", Path(folder) / "resume.json"
            marker.write_text("paused")
            with patch.object(guard, "BLOCK_FILE", marker), patch.object(guard, "RESUME_FILE", resume):
                for content in (None, "not json", "[]", '{}',
                        '{"user_authorized_hardware": true, "operations": null}',
                        '{"user_authorized_hardware": true, "operations": "device_descriptor_read"}',
                        '{"user_authorized_hardware": false, "operations": ["device_descriptor_read"]}',
                        '{"user_authorized_hardware": true, "operations": []}'):
                    if content is not None: resume.write_text(content)
                    with self.subTest(content=content), self.assertRaises(SystemExit):
                        guard.require_usb_access("device_descriptor_read")


if __name__ == "__main__":
    unittest.main()
