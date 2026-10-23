import struct
import unittest
from unittest.mock import Mock
from bt600_vendor_read import USB_CONTEXT_POINTER_ADDRESS, inspect_active_descriptor, inspect_usb_context, compare_descriptor

R, C = 0x002C3000, 0x002C4000
DEVICE = bytes.fromhex('12 01 10 01 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01')


class ActiveDescriptorTests(unittest.TestCase):
    def reader(self, context=R, composite=C, descriptor=DEVICE):
        memory = {USB_CONTEXT_POINTER_ADDRESS: struct.pack('<I', context),
                  R+0x40: struct.pack('<I', composite)}
        padded = descriptor + b'\x00\x00'
        memory.update({C+0x0c+i: padded[i:i+4] for i in range(0, 20, 4)})
        return Mock(side_effect=memory.__getitem__)

    def test_full_chain_and_standard_match(self):
        reader, report = self.reader(), {}
        inspect_active_descriptor(reader, report)
        self.assertEqual(reader.call_count, 7)
        self.assertEqual(report['descriptor_address'], '0x002c400c')
        compare_descriptor(report, DEVICE)
        self.assertTrue(report['matches_standard_descriptor'])

    def test_firmware_pool_context_and_composite(self):
        context, composite = 0x0030fe28, 0x00310000
        words = {USB_CONTEXT_POINTER_ADDRESS: struct.pack('<I', context),
                 context+0x40: struct.pack('<I', composite)}
        padded = DEVICE + b'\x00\x00'
        words.update({composite+12+i: padded[i:i+4] for i in range(0, 20, 4)})
        reader, report = Mock(side_effect=words.__getitem__), {}
        inspect_active_descriptor(reader, report)
        self.assertEqual(reader.call_count, 7)
        self.assertEqual(report['descriptor_address'], '0x0031000c')

    def test_pool_end_cannot_be_crossed(self):
        reader = self.reader(context=0x00313fc0)
        inspect_active_descriptor(reader, {})
        self.assertEqual(reader.call_count, 1)
        reader = self.reader(composite=0x00313fe4)
        inspect_active_descriptor(reader, {})
        self.assertEqual(reader.call_count, 2)

    def test_bad_context_never_followed(self):
        for value in (0, 7, 0x1ffffc, R+1, 0x2fffc0, 0x314000):
            reader = self.reader(context=value)
            inspect_active_descriptor(reader, {})
            self.assertEqual(reader.call_count, 1)

    def test_bad_composite_never_followed(self):
        for value in (0, 7, 0x1ffffc, C+1, 0x2fffe4, 0x314000):
            reader = self.reader(composite=value)
            inspect_active_descriptor(reader, {})
            self.assertEqual(reader.call_count, 2)

    def test_header_mismatch_stops_after_three_reads(self):
        reader, report = self.reader(descriptor=b'\x00'*18), {}
        inspect_active_descriptor(reader, report)
        self.assertEqual(reader.call_count, 3)
        self.assertNotIn('descriptor', report)

    def test_each_transport_failure_stops_the_chain(self):
        for fail_at in range(1, 8):
            reader = self.reader()
            original = reader.side_effect
            calls = []
            def read(address):
                calls.append(address)
                if len(calls) == fail_at:
                    raise RuntimeError('failed transfer')
                return original(address)
            with self.assertRaises(RuntimeError):
                inspect_active_descriptor(read, {})
            self.assertEqual(len(calls), fail_at)

class ContextHeaderTests(unittest.TestCase):
    def test_fixed_span_without_following_fields(self):
        def read(address):
            return struct.pack('<I', 0x0030fe28 if address == USB_CONTEXT_POINTER_ADDRESS else 0x0880a0a8)
        reader, report = Mock(side_effect=read), {}
        inspect_usb_context(reader, report)
        self.assertEqual(reader.call_count, 21)
        self.assertEqual(reader.call_args.args[0], 0x0030fe74)
        self.assertEqual(len(report['context_words']), 20)

    def test_context_header_rejects_out_of_bounds_span(self):
        reader = Mock(return_value=struct.pack('<I', 0x00313fc0))
        inspect_usb_context(reader, {})
        self.assertEqual(reader.call_count, 1)

    def test_context_header_keeps_partial_words_on_error(self):
        reader = Mock(side_effect=[struct.pack('<I', 0x0030fe28), b'abcd', RuntimeError('stop')])
        report = {}
        with self.assertRaises(RuntimeError):
            inspect_usb_context(reader, report)
        self.assertEqual(len(report['context_words']), 1)
        self.assertEqual(reader.call_count, 3)


if __name__ == '__main__':
    unittest.main()
