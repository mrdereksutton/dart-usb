import base64
import struct
import unittest

import bt600_probe as probe


class StockPatchTests(unittest.TestCase):
    def test_actual_rom_one_selects_chip_two(self):
        version, chip_id, payload = probe.stock_payload(1)
        self.assertEqual((version, chip_id, len(payload)), (0x4618D3F3, 2, 263))
        firmware = base64.b64decode(probe.STOCK_FIRMWARE_B64)
        config = base64.b64decode(probe.STOCK_CONFIG_B64)
        self.assertEqual(payload[:248], firmware[48:296])
        self.assertEqual(payload[248:252], struct.pack('<I', version))
        self.assertEqual(payload[252:], config)

    def test_failed_or_absent_rom_cannot_select_entry_zero(self):
        for rom in (-1, 4, 255):
            with self.subTest(rom=rom), self.assertRaises(RuntimeError):
                probe.stock_payload(rom)

    def test_actual_payload_has_two_fragments(self):
        _, _, payload = probe.stock_payload(1)
        parts = list(probe.download_fragments(payload))
        self.assertEqual([(p[0], len(p) - 1) for p in parts], [(0, 252), (0x81, 11)])
        self.assertEqual(b''.join(p[1:] for p in parts), payload)

    def test_fragment_boundaries_and_linux_index_wrap(self):
        for length in (0, 1, 251, 252, 253, 504, 32004):
            with self.subTest(length=length):
                payload = bytes(i % 251 for i in range(length))
                parts = list(probe.download_fragments(payload))
                self.assertEqual(b''.join(p[1:] for p in parts), payload)
                self.assertEqual(len(parts), length // 252 + 1)
                self.assertTrue(parts[-1][0] & 0x80)
                self.assertFalse(any(p[0] & 0x80 for p in parts[:-1]))
                self.assertTrue(all(len(p) <= 253 for p in parts))
        parts = list(probe.download_fragments(bytes(32256)))
        self.assertEqual([p[0] for p in parts[126:129]], [126, 127, 0x81])


class MemoryProbeTests(unittest.TestCase):
    def test_vector_table_interpretation(self):
        data = struct.pack('<II', 0x0021ab00, 0x00001291)
        sp, reset = probe.parse_vector_table(data)
        self.assertEqual(sp, 0x0021ab00)
        self.assertEqual(reset, 0x00001291)
        self.assertEqual(reset & ~1, 0x00001290)  # Thumb bit cleared for the entry

    def test_vector_table_partial_and_empty(self):
        self.assertEqual(probe.parse_vector_table(b''), (None, None))
        self.assertEqual(
            probe.parse_vector_table(struct.pack('<I', 0x0021ab00)),
            (0x0021ab00, None),
        )

    def test_vector_table_read_is_first_and_literals_present(self):
        addresses = [a for a, _ in probe.MEMORY_PROBE_ADDRESSES]
        self.assertEqual(addresses[0], 0x00000000)
        self.assertIn(0x00217E88, addresses)
        self.assertIn(0x0880A0A8, addresses)


if __name__ == '__main__':
    unittest.main()
