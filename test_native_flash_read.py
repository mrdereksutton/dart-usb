import struct
import unittest

import native_flash_read as native
import setup_marker

try:
    import unicorn as uc
    from unicorn import arm_const as regs
except ImportError:
    uc = None

CALLBACK = 0x020BE8A1
EXPECTED = bytes.fromhex("2d e9 f3 4f 85 b0 4f f0 00 09 05 98 88 46 4f f0")


class NativeFlashHelperTests(unittest.TestCase):
    def test_build_is_bounded_and_rejects_wrong_callback(self):
        code = native.build_helper(CALLBACK)
        self.assertGreater(len(code), 28)
        self.assertEqual(len(code) % 4, 0)
        self.assertLessEqual(len(code), 192)
        for value in (native.SOURCE_ADDRESS, native.RESULT_ADDRESS, CALLBACK):
            self.assertIn(struct.pack("<I", value), code)
        with self.assertRaisesRegex(RuntimeError, "Unexpected"):
            native.build_helper(0x00100001)

    def test_rejects_non_arm_object(self):
        with self.assertRaisesRegex(RuntimeError, "ELF32"):
            native.elf_text(bytes(64))

    @unittest.skipIf(uc is None, "Optional Unicorn ARM emulator is not installed")
    def test_calls_rom_read_once_with_correct_args_and_preserves_context(self):
        code = native.build_helper(CALLBACK)
        emulator = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
        emulator.mem_map(0x00211000, 0x1000)
        emulator.mem_map(0x0000C000, 0x1000)
        emulator.mem_map(CALLBACK & ~0xFFF, 0x1000)
        emulator.mem_write(native.CODE_ADDRESS, code)
        registers = [getattr(regs, f"UC_ARM_REG_R{i}") for i in range(13)]
        registers += [regs.UC_ARM_REG_SP, regs.UC_ARM_REG_LR]
        values = list(range(0x1110, 0x111D)) + [0x00211DF0, 0x00210001]
        calls = []

        def flash_read(machine, address, size, unused):
            if address == 0xCBB4:
                args = [machine.reg_read(r) for r in
                        (regs.UC_ARM_REG_R0, regs.UC_ARM_REG_R1, regs.UC_ARM_REG_R2)]
                calls.append(args)
                machine.mem_write(args[1], EXPECTED)
                machine.reg_write(regs.UC_ARM_REG_R0, 0x18)
                machine.reg_write(regs.UC_ARM_REG_XPSR, 0x51000000)
                machine.reg_write(regs.UC_ARM_REG_PC, machine.reg_read(regs.UC_ARM_REG_LR))

        emulator.hook_add(uc.UC_HOOK_CODE, flash_read)
        for _ in range(2):
            for register, value in zip(registers, values):
                emulator.reg_write(register, value)
            emulator.reg_write(regs.UC_ARM_REG_XPSR, 0xA1000000)
            emulator.emu_start(native.CODE_ADDRESS | 1, CALLBACK & ~1, count=100)
            self.assertEqual(emulator.reg_read(regs.UC_ARM_REG_PC), CALLBACK & ~1)
            self.assertEqual([emulator.reg_read(register) for register in registers], values)
            self.assertEqual(emulator.reg_read(regs.UC_ARM_REG_XPSR) & 0xF0000000, 0xA0000000)
        self.assertEqual(calls, [[native.SOURCE_ADDRESS, native.RESULT_ADDRESS, 16]])
        self.assertEqual(bytes(emulator.mem_read(native.RESULT_ADDRESS, 16)), EXPECTED)
        self.assertEqual(struct.unpack("<I", emulator.mem_read(native.STATUS_ADDRESS, 4))[0], 0x18)


if __name__ == "__main__":
    unittest.main()
