"""Host-only protocol tests. Compile our C code; never import the USB probes."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SOURCES = ("usb_audio_source.c", "iap_hid.c", "iap_metadata.c", "usb_bridge.c")


class UsbBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang")
        if not compiler:
            raise unittest.SkipTest("clang is required for the host-only C tests")
        cls.folder = tempfile.TemporaryDirectory(prefix="dart-usb-host-tests-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.binary = Path(cls.folder.name) / "usb-bridge-tests"
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-g",
                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                   "-I", str(ROOT / "firmware"), str(ROOT / "tests/usb_bridge_host_test.c"),
                   *(str(ROOT / "firmware" / name) for name in SOURCES), "-o", str(cls.binary)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(completed.stderr)

    def run_case(self, name):
        completed = subprocess.run([str(self.binary), name], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout.strip(), name)

    def test_descriptors(self): self.run_case("descriptors")
    def test_configuration_and_streaming_lifecycle(self): self.run_case("lifecycle")
    def test_invalid_requests_preserve_state_and_buffer_bounds(self): self.run_case("invalid_requests")
    def test_sample_rate_controls_discard_old_format_audio(self): self.run_case("sample_rates")
    def test_one_second_at_both_rates_preserves_every_stereo_sample(self): self.run_case("audio_seconds")
    def test_buffer_wrap_backpressure_idle_and_underrun(self): self.run_case("audio_buffering")
    def test_iap_known_wire_vector_and_nonconsuming_tx_peek(self): self.run_case("iap_known_vector")
    def test_iap_every_payload_length_through_1024_bytes(self): self.run_case("iap_roundtrip")
    def test_iap_malformed_frames_and_unread_payload(self): self.run_case("iap_malformed")
    def test_iap_fragment_restart_and_disconnect(self): self.run_case("iap_fragment_restart")
    def test_hid_idle_reports(self): self.run_case("hid_idle")
    def test_metadata_status_index_title_artist_and_album(self): self.run_case("metadata_replies")
    def test_metadata_transaction_ids_and_utf8(self): self.run_case("metadata_transaction_ids")


if __name__ == "__main__":
    unittest.main()
