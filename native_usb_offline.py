"""Execute captured BT600 USB routines in isolated ARM memory, never on USB.

The RAM/flash snapshots are local inputs. All controller-register memory below
is simulated; hardware activation and OS helpers are intercepted inside Unicorn.
"""
from pathlib import Path
import hashlib
import struct


RAM_SHA256 = "5b701222ea076e324a039b25ff79ada4fb843a0e50a444f9ff44f080f9b9c3df"
FLASH_SHA256 = "6ceb104173c7d474b42d62d501087e7933131c43deef03c706022f12a8c633c7"
ROOT = 0x0030CB68
EP3 = 0x0030CC08
ENABLE = 0x020BD30C
QUEUE = 0x0020C7B0
ISO_QUEUE = 0x0020BCDE
REQUEST = 0x00500000
DESCRIPTOR = 0x00500100
BUFFER = 0x00500200
RETURN = 0x0061FFF0
STACK = 0x0061F000
INTERCEPTED_ENTRIES = frozenset({0xE90, 0x020C30D2, 0x0020F158, 0x0020F162,
                                0x020BDDE6, 0x020BDDE2, 0x0020B6F6, 0x0020B68B2})


class NativeUsbEmulator:
    def __init__(self, ram_path, flash_path):
        import unicorn as uc
        from unicorn import arm_const as regs
        self.uc, self.regs = uc, regs
        ram, flash = Path(ram_path).read_bytes(), Path(flash_path).read_bytes()
        for data, expected in ((ram, RAM_SHA256), (flash, FLASH_SHA256)):
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Capture hash differs from the pinned BT600 image")
        self.machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_THUMB | uc.UC_MODE_MCLASS)
        self.machine.mem_map(0, 0x1000)
        self.machine.mem_map(0x00200000, len(ram))
        self.machine.mem_write(0x00200000, ram)
        self.machine.mem_map(0x02000000, len(flash))
        self.machine.mem_write(0x02000000, flash)
        self.machine.mem_protect(0x02000000, len(flash), uc.UC_PROT_READ | uc.UC_PROT_EXEC)
        self.machine.mem_map(0x00500000, 0x10000)
        self.machine.mem_map(0x00600000, 0x20000)
        self.machine.mem_map(0x400C0000, 0x10000)  # simulated controller only
        self.calls = []
        self.register_accesses = []
        self.iso_result = None
        self.result_overrides = {}
        self.pcd = self.word(ROOT)
        self.core = self.word(self.pcd + 8)
        self.in_states = [self.pcd + 0xE4 + i * 0xB8 for i in range(5)]
        self.ep3_state = next(p for p in self.in_states if self.byte(p + 0x14) == 3)
        # Model a stopped controller with empty queues and buffer DMA, excluding
        # descriptor-DMA allocation and FIFO resize branches from this ABI test.
        self.machine.mem_write(self.core + 0x43, b"\0")
        self.machine.mem_write(self.core + 0x46, b"\0")
        self.put_word(self.ep3_state + 4, self.ep3_state + 4)
        self.put_word(self.ep3_state + 8, self.ep3_state + 4)
        self.machine.hook_add(uc.UC_HOOK_CODE, self._instruction)
        self.machine.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE,
                              self._register_access, begin=0x400C0000, end=0x400CFFFF)

    def byte(self, address):
        return self.machine.mem_read(address, 1)[0]

    def word(self, address):
        return struct.unpack("<I", self.machine.mem_read(address, 4))[0]

    def put_word(self, address, value):
        self.machine.mem_write(address, struct.pack("<I", value & 0xFFFFFFFF))

    def _return(self, result=0):
        self.machine.reg_write(self.regs.UC_ARM_REG_R0, result & 0xFFFFFFFF)
        self.machine.reg_write(self.regs.UC_ARM_REG_PC,
                               self.machine.reg_read(self.regs.UC_ARM_REG_LR))

    def _register_access(self, machine, access, address, size, value, unused):
        if access != self.uc.UC_MEM_READ or address != 0x400C0808 or size != 4:
            raise RuntimeError("Unexpected access beyond the modeled controller boundary")
        self.register_accesses.append({"access": access, "address": address, "size": size, "value": value})

    def _instruction(self, machine, address, size, unused):
        if address not in INTERCEPTED_ENTRIES and address not in self.result_overrides and not (
                address == ISO_QUEUE and self.iso_result is not None):
            return
        registers = [machine.reg_read(getattr(self.regs, f"UC_ARM_REG_R{i}")) for i in range(4)]
        if address in self.result_overrides:
            self.calls.append({"entry": address, "arguments": registers, "intercepted": True})
            self._return(self.result_overrides[address])
        elif address in (0xE90, 0x020C30D2, 0x0020F158, 0x0020F162, 0x020BDDE6):
            self._return()
        elif address == 0x020BDDE2:
            self.put_word(registers[1], 0)  # saved critical-section token
            self._return()
        elif address == 0x0020B6F6 or address == 0x0020B68B2:
            self.calls.append({"entry": address, "arguments": registers})
            self._return()
        elif address == ISO_QUEUE and self.iso_result is not None:
            sp = machine.reg_read(self.regs.UC_ARM_REG_SP)
            self.calls.append({"entry": address, "arguments": registers + [self.word(sp + i * 4) for i in range(4)]})
            self._return(self.iso_result)

    def call(self, entry, *arguments):
        regs = self.regs
        for i in range(4):
            self.machine.reg_write(getattr(regs, f"UC_ARM_REG_R{i}"), arguments[i] if i < len(arguments) else 0)
        for i in range(4, 12):
            self.machine.reg_write(getattr(regs, f"UC_ARM_REG_R{i}"), 0x11110000 + i)
        for i, value in enumerate(arguments[4:]): self.put_word(STACK + i * 4, value)
        self.machine.reg_write(regs.UC_ARM_REG_SP, STACK)
        self.machine.reg_write(regs.UC_ARM_REG_LR, RETURN | 1)
        self.machine.emu_start(entry | 1, RETURN, count=200000)
        if self.machine.reg_read(regs.UC_ARM_REG_PC) != RETURN:
            raise RuntimeError("Native routine exceeded its emulated instruction budget")
        if self.machine.reg_read(regs.UC_ARM_REG_SP) != STACK:
            raise RuntimeError("Native routine did not restore its stack")
        for i in range(4, 12):
            if self.machine.reg_read(getattr(regs, f"UC_ARM_REG_R{i}")) != 0x11110000 + i:
                raise RuntimeError("Native routine did not preserve callee-saved registers")
        result = self.machine.reg_read(regs.UC_ARM_REG_R0)
        return result if result < 0x80000000 else result - 0x100000000

    def enable(self, packet_size=192):
        descriptor = bytes([9, 5, 0x83, 1, packet_size & 255, packet_size >> 8, 1, 0, 0])
        self.machine.mem_write(DESCRIPTOR, descriptor)
        # The endpoint operations wrapper leaves ep->desc to its caller.
        self.put_word(EP3 + 0x14, DESCRIPTOR)
        return self.call(ENABLE, EP3, DESCRIPTOR)

    def prepare_request(self, length=192, callback=0x00500901, flags=0):
        data = bytearray(44)
        struct.pack_into("<5I", data, 0, BUFFER, length, 0xFFFFFFFF, callback, 0x00500A00)
        struct.pack_into("<2I", data, 0x14, REQUEST + 0x14, REQUEST + 0x14)
        data[0x28] = flags
        self.machine.mem_write(REQUEST, bytes(data))
        self.machine.mem_write(BUFFER, bytes(range(192)))


def default_images(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    return (root / "results/flash-backup/flash-20261017T023847Z.bin",
            root / "results/bt600-targets-20261017T101939.145845Z.bin")
