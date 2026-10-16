import struct
import unittest

from analyze_asus_firmware import analyze, parse_images, select_snippet


def container(body):
    return b'RTBTCore' + b'\x00'*8 + struct.pack('<III', 1, 1, len(body)) + body


class AsusFirmwareTests(unittest.TestCase):
    def test_selects_eco_two_instead_of_first_snippet(self):
        body = struct.pack('<HH', 2, 0)
        body += struct.pack('<BBHI', 1, 15, 0, 3) + b'old'
        body += struct.pack('<BBHI', 2, 15, 0, 3) + b'new'
        self.assertEqual(select_snippet(container(body)), (51, 15, b'new'))

    def test_truncated_section_and_snippet_fail(self):
        body = struct.pack('<HHBBHI', 1, 0, 2, 15, 0, 100) + b'x'
        with self.assertRaises(ValueError):
            select_snippet(container(body))
        valid = container(struct.pack('<HHBBHI', 1, 0, 2, 15, 0, 1)+b'x')
        for size in (0, 8, 19, 27, len(valid)-1):
            with self.subTest(size=size), self.assertRaises(ValueError):
                select_snippet(valid[:size])

    def test_ambiguous_snippets_are_not_silently_concatenated(self):
        record = struct.pack('<BBHI', 2, 15, 0, 1)+b'x'
        with self.assertRaisesRegex(ValueError, 'found 2'):
            select_snippet(container(struct.pack('<HH', 2, 0)+record*2))

    def test_rejects_unknown_firmware_before_using_addresses(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            analyze(b'RTBTCore'+b'\x00'*100)

    def test_image_bounds_and_header_fields(self):
        table = b'\x01\x07' + b''.join(struct.pack('<HHII', 0x2790+i, 0, 1024, i) for i in range(7))
        payload = bytearray(1024*7)
        struct.pack_into('<III', payload, 0x14c, 0x200000, 0x2100000, 0x40)
        snippet = table+payload
        images = parse_images(snippet, 100)
        self.assertEqual(images[0]['file_offset'], 186)
        self.assertEqual(images[0]['header_0x14c'], 0x200000)
        for bad in (snippet[:-1], snippet+b'x'):
            with self.assertRaises(ValueError):
                parse_images(bad, 100)
        oversized = bytearray(snippet)
        struct.pack_into('<I', oversized, 6, 0xffffffff)
        with self.assertRaises(ValueError):
            parse_images(oversized, 100)


if __name__ == '__main__':
    unittest.main()
