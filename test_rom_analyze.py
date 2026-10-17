"""Regression tests for rom_analyze.py.

These pin two behaviours that were broken or misleading before 2026-10-17:

1. The linear Thumb sweep halted at the first literal pool (~0x1700 in the real
   image), so any descriptor constant further in was never examined. The sweep
   must now reach code placed well past an undecodable data word.
2. A halfword that only coincidentally matches a target (e.g. 0x1d70 as the low
   half of the pointer constant 0x00281d70) must be reported as a weak match,
   not as a descriptor-builder lead, and the multi-byte fragment scan must find
   a real descriptor run that is present and report none when it is absent.
"""

import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from contextlib import redirect_stdout

import rom_analyze


# Real Thumb encodings pulled from the captured ROM image.
MOVW_R2_0x209 = bytes.fromhex("40f20922")  # movw r2, #0x209
CMP_R0_6 = bytes.fromhex("0628")            # cmp r0, #6
BASE = 0x1000


class SweepReachesPastDataTests(unittest.TestCase):
    def test_sweep_finds_constant_after_a_literal_pool(self):
        # 0x400 bytes of 0xff (a data region capstone cannot decode as valid
        # code), then the movw. Pre-skipdata this halted the sweep and the movw
        # was missed.
        blob = b"\xff" * 0x400 + MOVW_R2_0x209
        immediates, _literals, _dispatches = rom_analyze.disassemble(blob, BASE)
        values = [v for _insn, v in immediates]
        self.assertIn(0x0209, values)

    def test_sweep_finds_dispatch_compare_after_data(self):
        # A nop (0xbf00) separates the data region from the compare, and a
        # trailing nop keeps the compare from being folded into a 32-bit decode
        # of the final halfwords.
        blob = b"\xff" * 0x400 + b"\x00\xbf" + CMP_R0_6 + b"\x00\xbf"
        _immediates, _literals, dispatches = rom_analyze.disassemble(blob, BASE)
        self.assertTrue(any(req == 6 for _insn, req in dispatches))


class WeakVersusStrongTests(unittest.TestCase):
    def test_pointer_constant_is_a_weak_halfword_match(self):
        # ldr r3,[pc,#0] ; (align) ; literal word 0x00281d70. The low half is the
        # PID, but the whole word is an address, so literal_hit must label it a
        # halfword match.
        code = bytes.fromhex("004b") + b"\x00\x00" + struct.pack("<I", 0x00281d70)
        _imm, literals, _disp = rom_analyze.disassemble(code, BASE)
        self.assertTrue(literals, "expected the literal load to be seen")
        labels = [h[2] for _insn, h in literals]
        self.assertTrue(any("halfword" in lbl for lbl in labels))


class FragmentScanTests(unittest.TestCase):
    def test_default_fragments_are_distinctive_runs(self):
        needles = rom_analyze.descriptor_fragments({})
        # Each fallback needle is multi-byte; single USB constants are what we
        # are moving away from.
        self.assertTrue(needles)
        self.assertTrue(all(len(n) >= 3 for _label, n in needles))

    def test_fragments_built_from_captured_bytes(self):
        cfg = bytes([0x09, 0x02, 0xc8, 0x00, 0x02, 0x01, 0x00, 0xe0, 0x32,
                     0x07, 0x05, 0x83, 0x01, 0x3f, 0x00, 0x01])
        needles = dict(rom_analyze.descriptor_fragments({"configuration_0": cfg}))
        self.assertIn("config header 09 02 wTotalLength..", needles)
        self.assertEqual(needles["config header 09 02 wTotalLength.."], cfg[:6])

    def test_find_all_locates_a_present_fragment_and_misses_an_absent_one(self):
        cfg = bytes([0x09, 0x02, 0xc8, 0x00, 0x02, 0x01])
        blob = b"\x00" * 0x50 + cfg + b"\x00" * 0x10
        self.assertEqual(rom_analyze.find_all(blob, BASE, cfg), [BASE + 0x50])
        self.assertEqual(rom_analyze.find_all(blob, BASE, b"\xde\xad\xbe\xef"), [])


class EndToEndTests(unittest.TestCase):
    def test_main_runs_on_a_capture_dir_and_reports_honestly(self):
        with tempfile.TemporaryDirectory() as d:
            dirp = Path(d)
            cfg = bytes([0x09, 0x02, 0xc8, 0x00, 0x02, 0x01])
            (dirp / "configuration_0.bin").write_bytes(cfg)
            (dirp / "ram.bin").write_bytes(b"\xff" * 0x100 + MOVW_R2_0x209)
            (dirp / "capture.json").write_text(json.dumps({
                "start_address": "0x00001000",
                "bytes_read": 0x100 + len(MOVW_R2_0x209),
                "descriptors": {"configuration_0": {"file": "configuration_0.bin"}},
            }))
            out = io.StringIO()
            with redirect_stdout(out):
                rc = rom_analyze.main([str(dirp)])
            text = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Multi-byte descriptor-fragment scan", text)
        self.assertIn("Weak halfword matches", text)


if __name__ == "__main__":
    unittest.main()
