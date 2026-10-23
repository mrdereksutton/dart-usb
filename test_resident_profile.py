"""Run the RAM trial through native CU setup, queue and completion routines."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

from arm_object_loader import load_arm_objects
from build_resident_profile import build
from native_control_offline import NativeControlEmulator
import native_usb_offline as native


def setup(kind, value, index=0, length=18):
    return struct.pack('<BBHHH', kind, 6, value, index, length)


class ResidentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('unicorn') is None or not all(p.is_file() for p in native.default_images()):
            raise unittest.SkipTest('Unicorn and pinned local captures are required')
        cls.folder = tempfile.TemporaryDirectory(prefix='dart-resident-profile-')
        cls.addClassCleanup(cls.folder.cleanup)
        cls.manifest, cls.objects = build(Path(cls.folder.name))

    def model(self):
        machine = NativeControlEmulator()
        # The stock descriptor path uses the captured ROM memcpy thunk.
        rom = (Path(__file__).parent / 'results/flash-backup/rom_dump_0x00001000-0x0009f000.bin').read_bytes()
        machine.machine.mem_map(0x7000, 0x1000)
        machine.machine.mem_write(0x7000, rom[0x6000:0x7000])
        symbols, _ = load_arm_objects(machine.machine, self.objects)
        machine.put_word(0x30d164, symbols['dart_resident_setup'])
        return machine, symbols

    def reply(self, machine, symbols):
        request = symbols['dart_resident_request']
        return bytes(machine.machine.mem_read(machine.word(request), machine.word(request + 4)))

    def test_descriptors_use_actual_native_queue_and_completion(self):
        m, s = self.model()
        for kind, value, interface, length, name in (
            (0x80, 0x017e, 0, 18, 'resident_device'),
            (0x80, 0x027e, 0, 128, 'resident_configuration'),
            (0x81, 0x227e, 2, 96, 'resident_report')):
            self.assertEqual(m.setup(setup(kind, value, interface, length)), 0)
            self.assertEqual(self.reply(m, s), bytes.fromhex(self.manifest['descriptors'][name]))
            self.assertEqual(m.word(s['dart_resident_busy']), 1)
            m.finish_control()
            self.assertEqual(m.word(s['dart_resident_busy']), 0)
            self.assertEqual(m.word(0x30cbc8), 0)
        self.assertEqual(m.word(s['dart_resident_completed']), 3)
        self.assertEqual(m.word(s['dart_resident_errors']), 0)
        self.assertEqual(m.byte(0x2c10d9), 6)
        self.assertTrue(all(call['arguments'][0] == 5 for call in m.calls if call['entry'] == 0x18c9a))

    def test_live_descriptor_dma_mode_uses_existing_native_ring(self):
        m, s = self.model()
        m.machine.mem_write(m.core + 0x43, b'\x01')
        self.assertEqual(m.setup(setup(0x80, 0x027e, length=128)), 0)
        self.assertEqual(len(self.reply(m, s)), 128)
        m.finish_control()
        self.assertEqual(m.word(s['dart_resident_busy']), 0)

    def test_partial_descriptor_bounds_and_zero_packet_flag(self):
        m, s = self.model()
        self.assertEqual(m.setup(setup(0x80, 0x027e, length=9)), 0)
        self.assertEqual(len(self.reply(m, s)), 9)
        m.finish_control()
        self.assertEqual(m.setup(setup(0x80, 0x027e, length=255)), 0)
        self.assertEqual(len(self.reply(m, s)), 128)
        self.assertEqual(m.byte(s['dart_resident_request'] + 40) & 2, 2)
        m.finish_control()

    def test_normal_device_request_retains_the_stock_handler(self):
        m, s = self.model()
        self.assertEqual(m.setup(setup(0x80, 0x0101)), 0)
        self.assertEqual(m.word(s['dart_resident_completed']), 0)
        self.assertEqual(m.word(0x30d164), s['dart_resident_setup'])
        m.finish_control()

    def test_cleanup_restores_callback_and_returns_stock_descriptor(self):
        m, s = self.model()
        self.assertEqual(m.setup(setup(0x80, 0x017f)), 0)
        self.assertEqual(m.word(0x30d164), 0x20be8a1)
        self.assertEqual(m.word(s['dart_resident_busy']), 0)
        m.finish_control()

    def test_new_setup_drains_an_owned_request_before_stock_dispatch(self):
        m, s = self.model()
        self.assertEqual(m.setup(setup(0x80, 0x027e, length=128)), 0)
        self.assertEqual(m.setup(setup(0x80, 0x0101)), 0)
        self.assertEqual(m.word(s['dart_resident_busy']), 0)
        self.assertEqual(m.word(0x30cbc8), 0)
        m.finish_control()


if __name__ == '__main__':
    unittest.main()
