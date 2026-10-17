from pathlib import Path
import struct
import unittest
from unittest.mock import Mock

import descriptor_edit
import setup_marker as helper

try:
    import unicorn as uc
    from unicorn import arm_const as regs
except ImportError:
    uc = None

DEVICE = bytes.fromhex("12 01 10 01 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01")
D, T, CALLBACK = 0x0030D130, 0x0030D110, 0x020BE8A1


class SetupMarkerTests(unittest.TestCase):
    def fixture(self, fail_install=False):
        memory = {descriptor_edit.COMPOSITE + 0x30: D.to_bytes(4, "little"),
                  D + 4: T.to_bytes(4, "little"), D + 0x34: CALLBACK.to_bytes(4, "little"),
                  helper.MARKER_ADDRESS: bytes(4)}
        for address, raw in ((descriptor_edit.COMPOSITE + 12, DEVICE),
                             (T, DEVICE[:7] + b"\x08" + DEVICE[8:])):
            padded = raw + bytes(2)
            memory.update({address + i: padded[i:i + 4] for i in range(0, 20, 4)})
        for offset in range(0, 28, 4):
            memory[helper.CODE_ADDRESS + offset] = bytes(4)
        writes = []

        def write(address, data):
            writes.append((address, data))
            memory[address] = data
            if fail_install and address == D + 0x34 and data != CALLBACK.to_bytes(4, "little"):
                raise RuntimeError("lost callback ack")

        def trigger():
            if int.from_bytes(memory[D + 0x34], "little") == helper.CODE_ADDRESS | 1:
                memory[helper.MARKER_ADDRESS] = helper.MARKER_VALUE.to_bytes(4, "little")
            return DEVICE

        return memory, writes, Mock(side_effect=memory.__getitem__), write, trigger

    def test_marker_and_every_original_word_are_restored(self):
        memory, writes, read, write, trigger = self.fixture()
        original, report = memory.copy(), {}
        helper.test_setup_marker(read, write, trigger, report, Mock())
        self.assertEqual(memory, original)
        self.assertTrue(report["marker_hook"]["marker_matched"])
        self.assertFalse(report["marker_hook"]["restore_required"])
        restore = writes.index((D + 0x34, CALLBACK.to_bytes(4, "little")))
        self.assertTrue(all(address == D + 0x34 or data == bytes(4)
                            for address, data in writes[restore:]))

    def test_install_failure_restores_callback_before_removing_helper(self):
        memory, writes, read, write, trigger = self.fixture(fail_install=True)
        original, report = memory.copy(), {}
        with self.assertRaisesRegex(RuntimeError, "lost callback ack"):
            helper.test_setup_marker(read, write, trigger, report, Mock())
        self.assertEqual(memory, original)
        self.assertEqual(writes[8], (D + 0x34, CALLBACK.to_bytes(4, "little")))

    def test_used_scratch_prevents_all_writes(self):
        memory, writes, read, write, trigger = self.fixture()
        memory[helper.CODE_ADDRESS] = b"used"
        with self.assertRaisesRegex(RuntimeError, "scratch words are in use"):
            helper.test_setup_marker(read, write, trigger, {}, Mock())
        self.assertEqual(writes, [])

    def test_overlapping_scratch_prevents_all_writes(self):
        memory, writes, read, write, trigger = self.fixture()
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            helper.test_setup_marker(read, write, trigger, {}, Mock(),
                                     extra_addresses=(helper.CODE_ADDRESS,))
        self.assertEqual(writes, [])

    def test_relocated_helper_restores_the_selected_words(self):
        memory, writes, read, write, trigger = self.fixture()
        address = 0x00211E30
        for offset in range(0, 28, 4):
            memory[address + offset] = bytes(4)
        original, report = memory.copy(), {}

        def relocated_trigger():
            if int.from_bytes(memory[D + 0x34], "little") == address | 1:
                memory[helper.MARKER_ADDRESS] = helper.MARKER_VALUE.to_bytes(4, "little")
            return DEVICE

        helper.test_setup_marker(read, write, relocated_trigger, report, Mock(), code_address=address)
        self.assertEqual(memory, original)
        self.assertEqual(report["marker_hook"]["code_address"], "0x00211e30")
        self.assertTrue(any(a == address for a, _ in writes))
        self.assertFalse(any(a == helper.CODE_ADDRESS for a, _ in writes))

    def test_checkpoint_failure_prevents_all_writes(self):
        memory, writes, read, write, trigger = self.fixture()
        with self.assertRaises(OSError):
            helper.test_setup_marker(read, write, trigger, {}, Mock(side_effect=OSError()))
        self.assertEqual(writes, [])

    def test_failed_callback_restore_keeps_helper_in_place(self):
        memory, writes, read, write, trigger = self.fixture()
        real_write, report = write, {}

        def write(address, data):
            if address == D + 0x34 and data == CALLBACK.to_bytes(4, "little"):
                raise RuntimeError("restore failed")
            real_write(address, data)

        with self.assertRaisesRegex(RuntimeError, "restore failed"):
            helper.test_setup_marker(read, write, trigger, report, Mock())
        self.assertTrue(report["marker_hook"]["restore_required"])
        self.assertEqual(memory[helper.CODE_ADDRESS], helper.marker_trampoline(CALLBACK)[:4])

    @unittest.skipIf(uc is None, "Optional Unicorn ARM emulator is not installed")
    def test_machine_code_writes_marker_preserves_registers_and_tail_calls(self):
        emulator = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
        emulator.mem_map(0x00211000, 0x1000)
        emulator.mem_map(CALLBACK & ~0xFFF, 0x1000)
        emulator.mem_write(helper.CODE_ADDRESS, helper.marker_trampoline(CALLBACK))
        registers = [getattr(regs, f"UC_ARM_REG_R{i}") for i in range(13)]
        registers += [regs.UC_ARM_REG_SP, regs.UC_ARM_REG_LR]
        values = list(range(0x1110, 0x111D)) + [0x00211EF0, 0x00210001]
        for register, value in zip(registers, values):
            emulator.reg_write(register, value)
        emulator.reg_write(regs.UC_ARM_REG_XPSR, 0xA1000000)
        arrived = []

        def stop_at_original(machine, address, size, unused):
            if address == CALLBACK & ~1:
                arrived.append(address)
                machine.emu_stop()

        emulator.hook_add(uc.UC_HOOK_CODE, stop_at_original)
        emulator.emu_start(helper.CODE_ADDRESS | 1, CALLBACK & ~1, count=32)
        # Unicorn stops before the requested end address, so PC is the tail-call destination.
        self.assertEqual(emulator.reg_read(regs.UC_ARM_REG_PC), CALLBACK & ~1)
        self.assertEqual([emulator.reg_read(register) for register in registers], values)
        self.assertEqual(emulator.reg_read(regs.UC_ARM_REG_XPSR) & 0xF0000000, 0xA0000000)
        self.assertEqual(struct.unpack("<I", emulator.mem_read(helper.MARKER_ADDRESS, 4))[0],
                         helper.MARKER_VALUE)


if __name__ == "__main__":
    unittest.main()
