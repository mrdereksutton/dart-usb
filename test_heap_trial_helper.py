"""Check the exact temporary RAM helper before executing it on the dongle."""
from pathlib import Path
import importlib.util
import struct
import subprocess
import tempfile
import unittest

from native_flash_read import elf_text


class HeapTrialHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("unicorn") is None:
            raise unittest.SkipTest("Unicorn is required for the ARM helper replay")
        global uc, reg
        import unicorn as uc
        from unicorn import arm_const as reg
        with tempfile.TemporaryDirectory(prefix="dart-heap-helper-") as folder:
            obj = Path(folder) / "helper.o"
            subprocess.run([
                "xcrun", "clang", "-target", "armv8m.main-none-eabi",
                "-mcpu=cortex-m33", "-mthumb", "-c",
                str(Path(__file__).parent / "firmware/heap_trial_helper.S"), "-o", str(obj),
            ], check=True)
            cls.code = elf_text(obj.read_bytes())
            subprocess.run([
                "xcrun", "clang", "-target", "armv8m.main-none-eabi",
                "-mcpu=cortex-m33", "-mthumb", "-c",
                str(Path(__file__).parent / "firmware/resident_heap_helper.S"), "-o", str(obj),
            ], check=True)
            cls.resident_code = elf_text(obj.read_bytes())

    def execute(self, allocation=0x00312280, marker=0, descriptor=True):
        machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
        for base, size in ((0x18000, 0x1000), (0x211000, 0x1000),
                           (0x281000, 0x1000), (0x300000, 0x14000), (0x20be000, 0x1000)):
            machine.mem_map(base, size)
        machine.mem_write(0x211e30, self.code)
        machine.mem_write(0x281308, struct.pack("<I", 0x18c9b))
        machine.mem_write(0x281310, struct.pack("<I", 0x18d25))
        machine.mem_write(0x211f00, struct.pack("<II", marker, 0))
        registers = [getattr(reg, f"UC_ARM_REG_R{i}") for i in range(13)]
        registers += [reg.UC_ARM_REG_SP, reg.UC_ARM_REG_LR]
        initial = [0x10000000 + i * 0x1111 for i in range(13)] + [0x313f00, 0x20be701]
        initial[1] = 0x211000
        machine.mem_write(initial[1], bytes.fromhex('80 06 01 01 00 00 12 00') if descriptor else bytes.fromhex('20 00 00 00 00 00 08 00'))
        machine.mem_write(0x30d164, struct.pack('<I', 0x211e31))
        for key, value in zip(registers, initial):
            machine.reg_write(key, value)
        machine.reg_write(reg.UC_ARM_REG_APSR, 0xa8000000)
        calls = []

        def hook(cpu, address, size, context):
            if address == 0x20be8a0:
                cpu.emu_stop()
                return
            if address not in (0x18c9a, 0x18d24):
                return
            args = [cpu.reg_read(key) for key in registers[:4]]
            calls.append((address, args))
            self.assertEqual(cpu.reg_read(reg.UC_ARM_REG_SP) & 7, 0)
            if address == 0x18c9a:
                self.assertEqual(args, [5, 4096, 0x08812424, 0])
            else:
                self.assertEqual(args[0], allocation)
            for key in registers[:4] + [reg.UC_ARM_REG_R12]:
                cpu.reg_write(key, 0xdeadbeef)
            cpu.reg_write(reg.UC_ARM_REG_APSR, 0x50000000)
            cpu.reg_write(reg.UC_ARM_REG_R0, allocation if address == 0x18c9a else 0)
            cpu.reg_write(reg.UC_ARM_REG_PC, cpu.reg_read(reg.UC_ARM_REG_LR))

        machine.hook_add(uc.UC_HOOK_CODE, hook)
        machine.emu_start(0x211e31, 0x20be8a0, count=150)
        self.assertEqual(machine.reg_read(reg.UC_ARM_REG_PC), 0x20be8a0)
        self.assertEqual([machine.reg_read(key) for key in registers], initial)
        self.assertEqual(machine.reg_read(reg.UC_ARM_REG_APSR) & 0xf8000000, 0xa8000000)
        result = struct.unpack("<II", machine.mem_read(0x211f00, 8))
        if descriptor and not marker:
            self.assertEqual(struct.unpack('<I', machine.mem_read(0x30d164, 4))[0], 0x20be8a1)
        return calls, result

    def test_allocate_free_and_preserve_native_caller(self):
        calls, result = self.execute()
        self.assertEqual([entry for entry, args in calls], [0x18c9a, 0x18d24])
        self.assertEqual(result, (0xd47a5011, 0x312280))

    def test_completed_marker_prevents_a_second_allocation(self):
        calls, result = self.execute(marker=0xd47a5011)
        self.assertEqual(calls, [])
        self.assertEqual(result, (0xd47a5011, 0))

    def test_allocation_failure_does_not_free_null(self):
        calls, result = self.execute(allocation=0)
        self.assertEqual([entry for entry, args in calls], [0x18c9a])
        self.assertEqual(result, (0xd47a5011, 0))

    def test_hci_transport_does_not_trigger_the_helper(self):
        calls, result = self.execute(descriptor=False)
        self.assertEqual(calls, [])
        self.assertEqual(result, (0, 0))

    def test_actual_native_allocator_retains_then_releases_the_block(self):
        import native_usb_offline as native
        import hashlib
        root = Path(__file__).parent
        rom_path = root / "results/flash-backup/rom_dump_0x00001000-0x0009f000.bin"
        if not rom_path.is_file() or not all(p.is_file() for p in native.default_images()):
            self.skipTest("Pinned ROM/RAM/flash captures are required")
        ram, flash = (p.read_bytes() for p in native.default_images())
        self.assertEqual(hashlib.sha256(ram).hexdigest(), native.RAM_SHA256)
        self.assertEqual(hashlib.sha256(flash).hexdigest(), native.FLASH_SHA256)
        machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
        for base, size in ((0, 0xa0000), (0x200000, 0x200000), (0x400000, 0x10000),
                           (0x2000000, 0x200000), (0x500000, 0x10000)):
            machine.mem_map(base, size)
        for base, data in ((0x1000, rom_path.read_bytes()), (0x200000, ram), (0x2000000, flash)):
            machine.mem_write(base, data)
        machine.mem_write(0x211e30, self.resident_code)
        machine.mem_write(0x211f00, bytes(8))
        machine.mem_write(0x500100, bytes.fromhex("80 06 01 01 00 00 12 00"))

        def hook(cpu, address, size, context):
            if address == 0x20be8a0:
                cpu.emu_stop()
            # Scheduling/critical-section boundaries are modeled; the actual
            # native allocation/free, list split/merge and zero-fill all run.
            if address in (0x15890, 0x15750, 0xe90):
                cpu.reg_write(reg.UC_ARM_REG_PC, cpu.reg_read(reg.UC_ARM_REG_LR))

        def word(at): return struct.unpack("<I", machine.mem_read(at, 4))[0]

        def execute():
            machine.reg_write(reg.UC_ARM_REG_R0, 0x30cb6c)
            machine.reg_write(reg.UC_ARM_REG_R1, 0x500100)
            machine.reg_write(reg.UC_ARM_REG_SP, 0x50ff00)
            machine.reg_write(reg.UC_ARM_REG_LR, 0x50f001)
            machine.emu_start(0x211e31, 0x20be8a0, count=100000)
            self.assertEqual(machine.reg_read(reg.UC_ARM_REG_PC), 0x20be8a0)

        machine.hook_add(uc.UC_HOOK_CODE, hook)
        before = word(0x28199c)
        execute()
        self.assertEqual((word(0x211f00), word(0x211f04)), (0xd47a5211, 0x312280))
        self.assertEqual(word(0x28199c), before - 4104)
        self.assertEqual(bytes(machine.mem_read(0x312280, 4096)), bytes(4096))
        machine.mem_write(0x211f00, struct.pack("<I", 1))
        execute()
        self.assertEqual((word(0x211f00), word(0x211f04)), (0xd47a5212, 0x312280))
        self.assertEqual(word(0x28199c), before)
        self.assertEqual(word(0x30d164), 0x20be8a1)


if __name__ == "__main__":
    unittest.main()
