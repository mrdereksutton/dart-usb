import base64
import contextlib
import io
import struct
import unittest
from unittest.mock import Mock, patch

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
    def test_default_probe_excludes_the_address_that_disconnected_usb(self):
        addresses = [address for address, _ in probe.MEMORY_PROBE_ADDRESSES]
        self.assertEqual(addresses, [0x00217E88])
        words = {0: struct.pack("<I", 0x0021A400), 4: struct.pack("<I", 0x00001291)}
        sp, reset = probe.parse_vector_table(words[0] + words[4])
        self.assertEqual((sp, reset & ~1, reset & 1), (0x0021A400, 0x1290, 1))

    def test_partial_vector_read_does_not_invent_a_reset_handler(self):
        self.assertEqual(probe.parse_vector_table(b""), (None, None))
        self.assertEqual(probe.parse_vector_table(struct.pack("<I", 0x0021A400)), (0x0021A400, None))


class HCIResponseTests(unittest.TestCase):
    def test_usb_packets_reassemble_one_event_and_preserve_the_next(self):
        first = bytes.fromhex("0e 0c 01 01 10 00 0e 0e 00 0e 5d 00 61 87")
        second = bytes.fromhex("0e 05 01 6d fc 00 01")
        events = probe.HCIEvents()
        self.assertEqual(events.feed(first[:4]), [])
        self.assertEqual(events.feed(first[4:] + second[:3]), [first])
        self.assertEqual(events.feed(second[3:]), [second])
        self.assertEqual(probe.command_result(first, 0x1001), first[5:])
        self.assertEqual(probe.command_result(second, 0xFC6D), b"\x00\x01")

    def test_rejected_command_status_is_reported_immediately(self):
        with self.assertRaisesRegex(RuntimeError, "status 0x01"):
            probe.command_result(bytes.fromhex("0f 04 01 01 61 fc"), 0xFC61)
        self.assertIsNone(probe.command_result(bytes.fromhex("0f 04 00 01 61 fc"), 0xFC61))
        self.assertIsNone(probe.command_result(bytes.fromhex("0e 05 01 6d fc 00 01"), 0x1001))

    def test_truncated_events_cannot_be_treated_as_success(self):
        for event in (b"", b"\x0e", bytes.fromhex("0e 05 01 6d fc 00"), bytes.fromhex("0e 01 01")):
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                probe.command_result(event, 0xFC6D)

    def test_stock_upload_requires_the_running_version_to_change(self):
        # btrtl only logs the post-download version, so success is a change
        # from the pre-download value, not a match to the container version.
        before = 0x000E8761
        unchanged = bytes.fromhex("00 0e 0e 00 0e 5d 00 61 87")  # still 0x000e8761
        changed = struct.pack("<BBHBHH", 0, 0x0E, 0x7BF1, 0x0E, 0x005D, 0x5762)  # 0x7bf15762
        with patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "did not change"):
                probe.require_stock_version(unchanged, before)
            probe.require_stock_version(changed, before)  # observed on hardware; no raise

    def test_acknowledgement_must_match_the_fragment(self):
        probe.require_download_ack(b"\x00\x00", 0)
        probe.require_download_ack(b"\x00\x81", 0x81)
        probe.require_download_ack(b"\x00\x01", 0x81)
        for response in (b"\x00", b"\x01\x01", b"\x00\x00", b"\x00\x81\x00"):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                probe.require_download_ack(response, 0x81)


class ReadRangeTests(unittest.TestCase):
    def test_find_patch_base_locates_the_resident_prologue(self):
        needle = probe.stock_payload(1)[2][:16]
        blob = b"\x00" * 8 + needle + b"\xff" * 4
        self.assertEqual(probe.find_patch_base(blob, 0x00217000, needle), 0x00217008)

    def test_find_patch_base_absent_returns_none(self):
        needle = probe.stock_payload(1)[2][:16]
        self.assertIsNone(probe.find_patch_base(b"\x00" * 64, 0x00217000, needle))

    def test_range_rejects_failed_window_and_page_crossings_before_sending(self):
        for start, words in ((0x0880A0A8, 1), (0x217E88, 0), (0x217E88, -1),
                             (0x217E88, 257), (0x217E89, 1), (0x217FFC, 2), (0xFFFFFFFF, 2)):
            command = Mock()
            with self.subTest(start=start, words=words), self.assertRaises(ValueError):
                probe.read_memory_range(command, start, words)
            command.assert_not_called()

    def test_failed_word_stops_reads_and_keeps_completed_output(self):
        for failure in (RuntimeError("USB timeout"), b"\x01", b"\x00\x11"):
            command = Mock(side_effect=[b"\x00\xb4\x88\x3b\xc2", failure])
            output = io.StringIO()
            with self.subTest(failure=failure), contextlib.redirect_stdout(output), self.assertRaises(RuntimeError):
                probe.read_memory_range(command, 0x217E88, 3)
            self.assertEqual(command.call_count, 2)
            self.assertIn("Memory 0x00217e88: b4 88 3b c2", output.getvalue())


class DescriptorScanTests(unittest.TestCase):
    def test_signature_is_the_little_endian_vid_pid(self):
        self.assertEqual(probe.USB_VID_PID_SIGNATURE, bytes.fromhex("050b701d"))

    def test_find_locates_the_descriptor_signature_in_a_blob(self):
        blob = b"\x00" * 20 + bytes.fromhex("12 01 00 02 e0 01 01 40") + probe.USB_VID_PID_SIGNATURE
        hit = probe.find_patch_base(blob, 0x00210000, probe.USB_VID_PID_SIGNATURE)
        self.assertEqual(hit, 0x00210000 + 28)

    def test_absent_signature_returns_none(self):
        self.assertIsNone(probe.find_patch_base(b"\x11" * 64, 0x00210000, probe.USB_VID_PID_SIGNATURE))

    def test_byte_order_variants_cover_both_endiannesses(self):
        variants = set(probe.USB_SIGNATURE_VARIANTS)
        self.assertIn(bytes.fromhex("050b701d"), variants)
        self.assertIn(bytes.fromhex("1d700b05"), variants)
        # A reversed-word layout is located by one of the variants.
        blob = b"\x00" * 12 + bytes.fromhex("1d700b05")
        self.assertTrue(any(probe.find_patch_base(blob, 0x1000, v) is not None
                            for v in probe.USB_SIGNATURE_VARIANTS))


class MapMemoryTests(unittest.TestCase):
    def test_coalesce_runs_merges_consecutive_kinds(self):
        samples = [(0x0, "zero"), (0x1000, "zero"), (0x2000, "data"),
                   (0x3000, "data"), (0x4000, "zero")]
        self.assertEqual(
            probe.coalesce_runs(samples),
            [(0x0, 0x1000, "zero"), (0x2000, 0x3000, "data"), (0x4000, 0x4000, "zero")],
        )

    def test_coalesce_runs_empty(self):
        self.assertEqual(probe.coalesce_runs([]), [])


class MemoryWriteTests(unittest.TestCase):
    def test_write_frames_opcode_access_address_and_data(self):
        sent = []
        probe.write_memory_word(lambda op, params=b"", quiet=False: sent.append((op, params)) or b"\x00",
                                0x00210000, b"\xde\xad\xbe\xef")
        self.assertEqual(sent[0][0], probe.MEMORY_WRITE_OPCODE)
        self.assertEqual(sent[0][1],
                         struct.pack("<BI", probe.MEMORY_READ_ACCESS, 0x00210000) + b"\xde\xad\xbe\xef")

    def test_write_rejects_bad_length_and_error_status(self):
        with self.assertRaises(RuntimeError):
            probe.write_memory_word(lambda *a, **k: b"\x00", 0, b"\x01\x02")
        with self.assertRaisesRegex(RuntimeError, "0x01"):
            probe.write_memory_word(lambda *a, **k: b"\x01", 0, b"\x01\x02\x03\x04")


if __name__ == '__main__':
    unittest.main()


class MemoryRangeValidationTests(unittest.TestCase):
    def test_original_candidate_page_still_allowed(self):
        self.assertEqual(
            probe.validate_memory_range(0x00217e88, 1), (0x00217e88, 1))

    def test_flash_mapped_region_allowed(self):
        # Flash is mapped at 0x200000; the firmware/handlers are read here.
        self.assertEqual(probe.validate_memory_range(0x00200000, 16), (0x00200000, 16))
        self.assertEqual(probe.validate_memory_range(0x00205ca2 & ~3, 8), (0x00205ca0, 8))

    def test_poke_address_must_be_in_an_allowed_page(self):
        self.assertEqual(probe.validate_write_address(0x002103d8), 0x002103d8)
        with self.assertRaises(ValueError):
            probe.validate_write_address(0x00000000)
        with self.assertRaises(ValueError):
            probe.validate_write_address(0x000a0000)
        with self.assertRaises(ValueError):
            probe.validate_write_address(0x002103d9)

    def test_context_ram_page_allowed(self):
        # 0x210000 window holds the device context the descriptor handler reads.
        self.assertEqual(
            probe.validate_memory_range(0x002103a8, 160), (0x002103a8, 160))

    def test_descriptor_table_page_allowed(self):
        self.assertEqual(
            probe.validate_memory_range(0x00288900, 192), (0x00288900, 192))

    def test_handler_code_page_allowed(self):
        # 0x205000 holds the descriptor handlers the callback vector points to.
        self.assertEqual(
            probe.validate_memory_range(0x00205c00, 128), (0x00205c00, 128))

    def test_callback_vector_page_allowed(self):
        # The 17-word vector at 0x285c14..0x285c54 (0x285c0c + 0x08..0x48).
        self.assertEqual(
            probe.validate_memory_range(0x00285c14, 17), (0x00285c14, 17))

    def test_unaligned_start_rejected(self):
        with self.assertRaises(ValueError):
            probe.validate_memory_range(0x00285c15, 1)

    def test_zero_or_too_many_words_rejected(self):
        with self.assertRaises(ValueError):
            probe.validate_memory_range(0x00285c14, 0)
        with self.assertRaises(ValueError):
            probe.validate_memory_range(0x00285c14, probe.MAX_MEMORY_WORDS + 1)

    def test_range_spanning_two_pages_rejected(self):
        # A read may not straddle from one allowed page into another or the gap.
        with self.assertRaises(ValueError):
            probe.validate_memory_range(0x00217ffc, 2)

    def test_hang_addresses_remain_outside_every_page(self):
        for bad in (0x000a0000, 0x0880a0a8):
            with self.assertRaises(ValueError):
                probe.validate_memory_range(bad, 1)


class CustomMarkerPatchTests(unittest.TestCase):
    def _patch(self):
        return probe.build_custom_marker_patch(
            probe.base64.b64decode(probe.STOCK_FIRMWARE_B64)[0x30:0x30 + 248])

    def test_entry_is_hooked_to_appended_code(self):
        import capstone
        patch = self._patch()
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        first = next(md.disasm(patch[:2], 0))
        self.assertEqual(first.mnemonic, "b")
        self.assertEqual(first.op_str, "#0xf8")  # branch to appended code at 248

    def test_appended_code_writes_marker_and_returns(self):
        import capstone
        patch = self._patch()
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        seq = [(i.mnemonic, i.op_str) for i in md.disasm(patch[248:248 + 16], 248)]
        self.assertEqual(seq[0], ("push", "{r0, r1}"))
        self.assertEqual(seq[3], ("str", "r0, [r1]"))
        self.assertEqual(seq[4], ("pop", "{r0, r1}"))
        self.assertEqual(seq[5], ("push", "{r4, r5, r6, lr}"))  # displaced original prologue
        self.assertEqual(seq[6], ("b", "#2"))                   # back into the patch body

    def test_marker_value_and_address_present(self):
        patch = self._patch()
        self.assertEqual(struct.unpack_from("<I", patch, 248 + 16)[0], probe.CUSTOM_MARKER_VALUE)
        self.assertEqual(struct.unpack_from("<I", patch, 248 + 20)[0], probe.CUSTOM_MARKER_ADDR)

    def test_marker_address_is_in_an_allowed_read_page(self):
        probe.validate_memory_range(probe.CUSTOM_MARKER_ADDR, 1)  # must not raise

    def test_refuses_unexpected_patch_entry(self):
        with self.assertRaises(RuntimeError):
            probe.build_custom_marker_patch(b"\x00\x00" + b"\x00" * 246)
