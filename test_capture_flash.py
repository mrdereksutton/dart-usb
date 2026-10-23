import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from capture_flash import capture_flash, FLASH_BASE


class FlashCaptureTests(unittest.TestCase):
    def test_exact_prefix_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path, report = Path(directory) / "capture.bin", {}
            reader = Mock(side_effect=lambda a: (a - FLASH_BASE).to_bytes(4, "little"))
            capture_flash(reader, path, 256, report, Mock())
            self.assertEqual(reader.call_count, 64)
            self.assertEqual(reader.call_args.args[0], FLASH_BASE + 252)
            self.assertEqual(report["capture_status"], "complete")
            self.assertEqual(report["binary_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_failure_keeps_only_real_bytes_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            path, report = Path(directory) / "capture.bin", {}
            reader = Mock(side_effect=[b"abcd", RuntimeError("transfer failed"), b"never"])
            with self.assertRaisesRegex(RuntimeError, "transfer failed"):
                capture_flash(reader, path, 256, report, Mock())
            self.assertEqual(path.read_bytes(), b"abcd")
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(report["bytes_read"], 4)
            self.assertEqual(report["capture_status"], "partial")

    def test_interruption_keeps_partial_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path, report = Path(directory) / "capture.bin", {}
            reader = Mock(side_effect=[b"abcd", KeyboardInterrupt()])
            with self.assertRaises(KeyboardInterrupt):
                capture_flash(reader, path, 256, report, Mock())
            self.assertEqual(path.read_bytes(), b"abcd")
            self.assertEqual(report["capture_status"], "partial")

    def test_does_not_overwrite_or_read_on_invalid_length(self):
        with tempfile.TemporaryDirectory() as directory:
            path, reader = Path(directory) / "capture.bin", Mock()
            path.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                capture_flash(reader, path, 256, {}, Mock())
            with self.assertRaises(ValueError):
                capture_flash(reader, path, 257, {}, Mock())
            reader.assert_not_called()
            self.assertEqual(path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
