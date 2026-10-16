import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import bt600_probe
import capture_ipod
import descriptor_capture as capture
import usb_inspect


DEVICE = bytes.fromhex("12 01 00 02 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01")
CONFIG = bytes.fromhex("09 02 19 00 01 01 00 80 32 09 04 00 00 01 e0 01 01 00 07 05 81 03 40 00 01")


def get_descriptor(kind, index, length):
    return {1: DEVICE, 2: CONFIG}[kind][:length]


class CaptureTests(unittest.TestCase):
    def test_interface_and_endpoint_search_works_without_any_vid_pid_in_ram(self):
        blob = b"\xff" * 3 + CONFIG[9:] + b"\xff" * 13
        self.assertNotIn(DEVICE[8:12], blob)
        for layout, order in capture.WORD_LAYOUTS.items():
            encoded = bytes(blob[base + index] for base in range(0, len(blob), 4) for index in order)
            hits = capture.find_descriptors(encoded, capture.RAM_START, {"device": DEVICE, "configuration_0": CONFIG})
            with self.subTest(layout=layout):
                match = next(hit for hit in hits if hit["pattern"] == "configuration_0/interface@0009" and hit["layout"] == layout)
                self.assertEqual((match["word_address"], match["offset_in_word"]), ("0x00210000", 3))
                self.assertTrue(any(hit["pattern"] == "configuration_0/endpoint@0012" for hit in hits))

    def test_full_descriptor_crosses_word_boundary_and_all_matches_are_kept(self):
        blob = b"\xff" * 3 + DEVICE + b"\xff" * 2 + DEVICE + b"\xff" * 3
        hits = capture.find_descriptors(blob, capture.RAM_START, {"device": DEVICE})
        full = [hit for hit in hits if hit["pattern"] == "device" and hit["layout"] == "native"]
        self.assertEqual([(hit["word_address"], hit["offset_in_word"]) for hit in full],
                         [("0x00210000", 3), ("0x00210014", 3)])

    def test_timeout_or_interrupt_preserves_completed_words_and_stops_immediately(self):
        for failure, status in ((RuntimeError("USB timeout"), "partial"), (KeyboardInterrupt(), "interrupted")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                reader = Mock(side_effect=[b"\x11\x22\x33\x44", failure])
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(type(failure)):
                    capture.capture(reader, get_descriptor, directory, words=3)
                self.assertEqual(reader.call_count, 2)
                root = Path(directory)
                report = json.loads((root / "capture.json").read_text())
                self.assertEqual((report["status"], report["bytes_read"]), (status, 4))
                self.assertEqual((root / "ram.bin").read_bytes(), b"\x11\x22\x33\x44")
                self.assertEqual((root / "device.bin").read_bytes(), DEVICE)

    def test_invalid_window_or_malformed_descriptor_never_starts_ram_reads(self):
        reader, descriptor = Mock(), Mock()
        with tempfile.TemporaryDirectory() as directory:
            for start, words in ((0xA0000, 1), (0x0880A0A8, 1), (capture.RAM_START + 1, 1), (capture.RAM_END - 4, 2)):
                with self.subTest(start=start), self.assertRaises(ValueError):
                    capture.capture(reader, descriptor, directory, start=start, words=words)
            reader.assert_not_called()
            descriptor.assert_not_called()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "Incomplete"):
                capture.capture(reader, lambda kind, index, length: get_descriptor(kind, index, length)[:-1]
                                if kind == 2 and length > 9 else get_descriptor(kind, index, length), directory, words=1)
            reader.assert_not_called()
            report = json.loads((Path(directory) / "capture.json").read_text())
            self.assertEqual((report["status"], report["bytes_read"]), ("failed", 0))

    def test_complete_capture_is_searchable_offline_without_hardware(self):
        blob = DEVICE + b"\xff\xff"
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            reader = Mock(side_effect=[blob[i:i + 4] for i in range(0, len(blob), 4)])
            report = capture.capture(reader, get_descriptor, directory, words=5)
            self.assertEqual(report["status"], "complete")
            with patch("sys.argv", ["descriptor_capture.py", directory]), patch.object(bt600_probe.C, "CDLL") as usb:
                self.assertEqual(capture.main(), 0)
                usb.assert_not_called()
            self.assertEqual((Path(directory) / "ram.bin").read_bytes(), blob)

    def test_capture_mode_cannot_accidentally_upload_or_write(self):
        for extra in (["--load-stock"], ["--write-test"], ["--find-descriptor"]):
            with self.subTest(extra=extra), patch.object(bt600_probe.C, "CDLL") as usb, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                bt600_probe.main(["--capture-usb-ram", "unused", *extra])
            self.assertEqual(error.exception.code, 2)
            usb.assert_not_called()


class IPodReferenceTests(unittest.TestCase):
    def test_every_configuration_and_alternate_setting_is_retained(self):
        device = bytearray(DEVICE)
        device[8:12] = bytes.fromhex("ac 05 61 12")
        device[17] = 2
        second = bytes.fromhex("09 02 1b 00 01 02 00 80 32 09 04 01 00 00 01 02 00 00 09 04 01 01 00 01 02 00 00")
        descriptors = capture.read_descriptors(
            lambda kind, index, length: (bytes(device) if kind == 1 else [CONFIG, second][index])[:length],
            expected_identity=(0x05AC, 0x1261),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "reference"
            report = capture_ipod.save_reference(descriptors, root, "iPod", "Apple Inc.")
            self.assertEqual(len(report["configurations"]), 2)
            interfaces = report["configurations"][1]["interfaces"]
            self.assertEqual([(item["number"], item["alternate"]) for item in interfaces], [(1, 0), (1, 1)])
            self.assertEqual((root / "configuration_1.bin").read_bytes(), second)

    def test_product_name_uses_a_supported_usb_language(self):
        raw_name = "iPod".encode("utf-16-le")
        raw_name = bytes((len(raw_name) + 2, 3)) + raw_name
        with patch.object(usb_inspect, "get_descriptor", side_effect=[bytes.fromhex("04 03 09 04"), raw_name]) as read:
            self.assertEqual(usb_inspect.read_string(None, None, 2), "iPod")
            self.assertEqual(read.call_args.kwargs["language"], 0x0409)


if __name__ == "__main__":
    unittest.main()
