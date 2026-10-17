import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


class AudioSource(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in
                ("sample_rate", "remainder", "missing_frames", "tone_phase")]


class AudioSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clang = shutil.which("clang")
        if not clang:
            raise unittest.SkipTest("clang is required for the C packetizer tests")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        library = Path(cls.temporary.name) / "audio.dylib"
        source = Path(__file__).parent / "firmware/usb_audio_source.c"
        subprocess.run([clang, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                        str(source), "-o", str(library)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.dart_audio_init.argtypes = [C.POINTER(AudioSource), C.c_uint32]
        cls.lib.dart_audio_init.restype = C.c_int
        cls.lib.dart_audio_packet.argtypes = [C.POINTER(AudioSource), C.POINTER(C.c_int16),
            C.c_size_t, C.POINTER(C.c_uint8), C.c_size_t, C.POINTER(C.c_size_t)]
        cls.lib.dart_audio_packet.restype = C.c_size_t
        cls.lib.dart_audio_test_tone.argtypes = [C.POINTER(AudioSource), C.POINTER(C.c_uint8), C.c_size_t]
        cls.lib.dart_audio_test_tone.restype = C.c_size_t

    def state(self, rate):
        state = AudioSource()
        self.assertEqual(self.lib.dart_audio_init(C.byref(state), rate), 1)
        return state

    def test_exact_second_at_both_sample_rates(self):
        for rate, packet_sizes in ((48000, {192: 1000}), (44100, {176: 900, 180: 100})):
            state, output, counts = self.state(rate), (C.c_uint8 * 192)(), {}
            for _ in range(1000):
                length = self.lib.dart_audio_test_tone(C.byref(state), output, 192)
                counts[length] = counts.get(length, 0) + 1
            self.assertEqual(counts, packet_sizes)
            self.assertEqual(sum(size * count for size, count in counts.items()), rate * 4)
            self.assertEqual(state.remainder, 0)
            self.assertEqual(state.tone_phase, 0)

    def test_stereo_order_endianness_and_silence_on_underrun(self):
        state, output = self.state(48000), (C.c_uint8 * 192)()
        pcm = (C.c_int16 * 4)(0x1234, -2, -32768, 32767)
        consumed = C.c_size_t()
        length = self.lib.dart_audio_packet(C.byref(state), pcm, 2, output, 192, C.byref(consumed))
        self.assertEqual(length, 192)
        self.assertEqual(bytes(output[:8]), struct.pack("<hhhh", 0x1234, -2, -32768, 32767))
        self.assertEqual(bytes(output[8:]), bytes(184))
        self.assertEqual(consumed.value, 2)
        self.assertEqual(state.missing_frames, 46)

    def test_short_buffer_does_not_advance_clock_or_consume_audio(self):
        state, output = self.state(44100), (C.c_uint8 * 192)()
        state.remainder = 900
        before, consumed = bytes(state), C.c_size_t(99)
        self.assertEqual(self.lib.dart_audio_packet(C.byref(state), None, 0, output, 179,
                                                  C.byref(consumed)), 0)
        self.assertEqual(bytes(state), before)
        self.assertEqual(consumed.value, 0)

    def test_test_tone_has_both_channels_and_continuous_phase(self):
        state, output = self.state(48000), (C.c_uint8 * 192)()
        self.assertEqual(self.lib.dart_audio_test_tone(C.byref(state), output, 192), 192)
        samples = struct.unpack("<96h", bytes(output))
        self.assertEqual(samples[:48], (4096,) * 48)
        self.assertEqual(samples[48:], (-4096,) * 48)
        self.assertEqual(state.tone_phase, 0)

    def test_invalid_format_is_rejected(self):
        state = AudioSource()
        self.assertEqual(self.lib.dart_audio_init(C.byref(state), 96000), 0)


if __name__ == "__main__":
    unittest.main()
