"""Offline checks: no real USB calls or controller state changes."""
import ctypes as C
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

import bt600_vendor_read as probe

DEVICE = bytes.fromhex('12 01 00 02 e0 01 01 40 05 0b 70 1d 00 02 01 02 03 01')
TARGET = 0x002C2000


class DescriptorTargetsTests(unittest.TestCase):
    def reader(self, pointer=TARGET, descriptor=DEVICE):
        memory = {probe.DESCRIPTOR_POINTER_ADDRESS: struct.pack('<I', pointer),
                  probe.USB_ID_CONFIG_ADDRESS: bytes.fromhex('05 0b 70 1d')}
        padded = descriptor + b'\x00\x00'
        memory.update({TARGET + i: padded[i:i+4] for i in range(0, 20, 4)})
        return Mock(side_effect=memory.__getitem__)

    def test_complete_descriptor_and_exact_read_budget(self):
        reader, report = self.reader(), {}
        probe.inspect_descriptor_targets(reader, report)
        self.assertEqual(reader.call_count, 7)
        self.assertEqual(report['descriptor']['raw'], DEVICE.hex(' '))
        self.assertEqual(report['descriptor']['usb_id'], '0b05:1d70')
        self.assertTrue(report['config_matches_adapter'])
        probe.compare_descriptor(report, DEVICE)
        self.assertTrue(report['matches_standard_descriptor'])

    def test_invalid_pointers_never_followed(self):
        for pointer in (0, TARGET+1, 0x001ffffc, 0x00300000, 0x002ffff0, 0x0880a0a8):
            with self.subTest(pointer=pointer):
                reader = self.reader(pointer)
                probe.inspect_descriptor_targets(reader, {})
                self.assertEqual([c.args[0] for c in reader.call_args_list],
                                 [probe.DESCRIPTOR_POINTER_ADDRESS, probe.USB_ID_CONFIG_ADDRESS])

    def test_non_descriptor_does_not_trigger_remaining_words(self):
        reader, report = self.reader(descriptor=b'\x00'*18), {}
        probe.inspect_descriptor_targets(reader, report)
        self.assertEqual(reader.call_count, 3)
        self.assertNotIn('descriptor', report)

    def test_failure_at_each_read_stops_immediately(self):
        for failed_read in range(1, 8):
            reader = self.reader()
            original = reader.side_effect
            calls = []
            def read(address):
                calls.append(address)
                if len(calls) == failed_read:
                    raise RuntimeError('transport failure')
                return original(address)
            with self.assertRaisesRegex(RuntimeError, 'transport failure'):
                probe.inspect_descriptor_targets(read, {})
            self.assertEqual(len(calls), failed_read)

    def test_rejected_and_malformed_memory_replies(self):
        for reply in (b'', b'\x00', b'\x00'*4, b'\x00'*6, b'\x01'+b'\x00'*4):
            with self.assertRaises(RuntimeError):
                probe.memory_data(reply, TARGET)
        self.assertEqual(probe.memory_data(b'\x00abcd', TARGET), b'abcd')

    def test_malformed_identity_queries(self):
        for name, size in (('local_version', 9), ('rom_version', 2), ('asus_security_register', 3)):
            probe.validate_query(name, b'\x00'*size)
            for reply in (b'', b'\x00'*(size-1), b'\x00'*(size+1), b'\x01'+b'\x00'*(size-1)):
                with self.assertRaises(RuntimeError):
                    probe.validate_query(name, reply)

    def test_standard_descriptor_mismatch_is_evidence(self):
        report = {'descriptor': {'raw': DEVICE.hex()}}
        standard = bytearray(DEVICE)
        standard[8] ^= 1
        probe.compare_descriptor(report, bytes(standard))
        self.assertFalse(report['matches_standard_descriptor'])
        self.assertEqual(report['differing_byte_offsets'], [8])
        for invalid in (b'', DEVICE[:-1], b'\x00'+DEVICE[1:]):
            with self.assertRaises(RuntimeError):
                probe.compare_descriptor({}, invalid)


class ProbeLifecycleTests(unittest.TestCase):
    def run_probe(self, failure=None, rom=1, restore_code=0):
        usb = Mock()
        commands = []
        devices = (C.c_void_p * 2)(1, None)
        def init(context):
            context._obj.value = 1
            return 0
        def get_list(context, output):
            C.cast(output, C.POINTER(C.POINTER(C.c_void_p)))[0] = devices
            return 1
        def descriptor(device, output):
            d = output._obj
            d.vid, d.pid = probe.VID, probe.PID
            d.device_class, d.subclass, d.protocol = 0xe0, 1, 1
            return 0
        def opened(device, handle):
            handle._obj.value = 2
            return 0
        def control(handle, kind, request, value, index, buf, length, timeout):
            if kind == 0x80:
                C.memmove(buf, DEVICE, 18)
                return 18
            packet = C.string_at(buf, length)
            commands.append((struct.unpack_from('<H', packet)[0], packet[3:]))
            return length
        def interrupt(handle, endpoint, buf, length, transferred, timeout):
            opcode, params = commands[-1]
            if opcode == 0x1001:
                reply = bytes.fromhex('00 0e 0e 00 0e 5d 00 61 87')
            elif opcode == 0xfc6d:
                reply = bytes((0, rom))
            elif params[0] == 0x10:
                reply = b'\x00'*3
            elif failure == 'interrupt':
                raise KeyboardInterrupt()
            elif failure == 'timeout':
                return -7
            else:
                reply = b'\x00'*5  # Null candidate pointer/config.
            event = bytes((0x0e, len(reply)+3, 1)) + struct.pack('<H', opcode) + reply
            C.memmove(buf, event, len(event))
            transferred._obj.value = len(event)
            return 0
        usb.libusb_init.side_effect = init
        usb.libusb_get_device_list.side_effect = get_list
        usb.libusb_get_device_descriptor.side_effect = descriptor
        usb.libusb_open.side_effect = opened
        usb.libusb_get_configuration.return_value = 0
        usb.libusb_set_configuration.side_effect = lambda h, c: restore_code if c == -1 else 0
        usb.libusb_claim_interface.return_value = 0
        usb.libusb_release_interface.return_value = 0
        usb.libusb_control_transfer.side_effect = control
        usb.libusb_interrupt_transfer.side_effect = interrupt
        usb.libusb_error_name.return_value = b'FAKE_USB_ERROR'
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'probe.py'
            script.write_text('test provenance')
            with patch.object(probe, '__file__', str(script)), patch.object(probe.C, 'CDLL', return_value=usb), patch.object(probe.Path, 'is_file', return_value=True), patch('usb_access_guard.BLOCK_FILE', Path(temp) / 'USB_ACCESS_DISABLED'), patch('sys.argv', ['probe', '--descriptor-targets']), patch('builtins.print'):
                code = probe.main()
            paths = list((Path(temp)/'results').glob('*.json'))
            self.assertEqual(len(paths), 1)
            result = json.loads(paths[0].read_text())
        usb.libusb_close.assert_called_once()
        usb.libusb_release_interface.assert_called_once()
        usb.libusb_exit.assert_called_once()
        self.assertEqual(usb.libusb_set_configuration.call_args.args[1], -1)
        self.assertTrue(all(op in (0x1001, 0xfc6d, 0xfc61) for op, _ in commands))
        return code, result, commands

    def test_success_saves_standard_descriptor_and_restores(self):
        code, result, commands = self.run_probe()
        self.assertEqual(code, 0)
        self.assertTrue(result['unconfigured_state_restored'])
        self.assertEqual(result['descriptor_targets']['standard_device_descriptor'], DEVICE.hex(' '))
        self.assertEqual(len(commands), 5)

    def test_timeout_or_interrupt_preserves_failed_address_and_stops(self):
        for failure in ('timeout', 'interrupt'):
            with self.subTest(failure=failure):
                code, result, commands = self.run_probe(failure)
                self.assertEqual(code, 1)
                self.assertEqual(len(commands), 4)
                reads = result['descriptor_targets']['reads']
                self.assertEqual(len(reads), 1)
                self.assertEqual(reads[0]['address'], '0x002c10b4')
                self.assertIn('error', reads[0])
                self.assertTrue(result['unconfigured_state_restored'])

    def test_different_rom_does_not_read_candidate_addresses(self):
        code, result, commands = self.run_probe(rom=2)
        self.assertEqual(code, 1)
        self.assertEqual(len(commands), 3)
        self.assertNotIn('descriptor_targets', result)

    def test_restore_failure_has_nonzero_exit(self):
        code, result, _ = self.run_probe(restore_code=-3)
        self.assertEqual(code, 1)
        self.assertFalse(result['unconfigured_state_restored'])


if __name__ == '__main__':
    unittest.main()
