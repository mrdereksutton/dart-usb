"""Replay the saved CU PCD setup dispatcher with the compiled control adapter.

Virtual controller, allocator and hardware completion events only. No USB API.
"""
from arm_object_loader import load_arm_objects
from native_usb_offline import NativeUsbEmulator, default_images, ROOT, EP3, BUFFER
from validate_native_audio import SOURCES, build_objects


CONTROL_SOURCES = (*SOURCES[:-1], "firmware/rtl8761c_control_port.c", "tests/rtl8761c_control_fixture.c")
EP0 = 0x0030CBB4
SETUP = 0x00501000
PCD_SETUP = 0x020BA71E
EP0_DISPATCH = 0x020BB4A0
PCD_COMPLETE = 0x020C35F0
GENERIC_QUEUE = 0x0020F19E
DISABLE = 0x020BD3B2
DEQUEUE = 0x020BD492
HALT = 0x020BD4DC
CONTROL_BOUNDARIES = frozenset({0x18C9A, 0x18D24, 0x020BDDDE, 0x020BDDDA,
    0x020B7542, 0x020B7046, 0x020B7488, 0x020B7958, 0x020B9F28, 0x020BD6FC})


class NativeControlEmulator(NativeUsbEmulator):
    def __init__(self, *images):
        super().__init__(*(images or default_images()))
        self.machine.mem_map(0x00018000, 0x2000)  # intercepted ROM allocator/free entries
        self.heap = 0x00508000
        self.allocations = []
        self.setup_results = []
        self.ep0_state = self.pcd + 0x2c
        self.put_word(self.ep0_state + 4, self.ep0_state + 4)
        self.put_word(self.ep0_state + 8, self.ep0_state + 4)
        self.put_word(self.pcd + 0x14, SETUP)
        self.put_word(0x0030d180 + 8, 0)  # model an unconfigured device after reset
        self.result_overrides.update({DISABLE: 0, DEQUEUE: 0, HALT: 0})

    def _register_access(self, machine, access, address, size, value, unused):
        if size != 4 or address not in (0x400C0800, 0x400C0808):
            raise RuntimeError(f"Unexpected virtual controller access: {address:#x}")
        if address == 0x400C0808 and access != self.uc.UC_MEM_READ:
            raise RuntimeError("Unexpected virtual status register write")
        self.register_accesses.append({"access": access, "address": address, "size": size, "value": value})

    def _instruction(self, machine, address, size, unused):
        if address not in CONTROL_BOUNDARIES:
            return super()._instruction(machine, address, size, unused)
        regs = [machine.reg_read(getattr(self.regs, f"UC_ARM_REG_R{i}")) for i in range(4)]
        if address == 0x020BD6FC:
            self.setup_results.append(regs[0] if regs[0] < 0x80000000 else regs[0] - 0x100000000)
            return
        self.calls.append({"entry": address, "arguments": regs, "intercepted": True})
        if address == 0x18C9A:
            length = regs[1]
            if length > 512 or self.heap + length > 0x00510000:
                raise RuntimeError("Virtual allocator exceeded its replay budget")
            pointer = self.heap
            self.heap += (length + 15) & ~15
            self.machine.mem_write(pointer, bytes(length))
            self.allocations.append(pointer)
            return self._return(pointer)
        self._return()

    def setup(self, packet):
        if len(packet) != 8:
            raise ValueError("A USB setup packet has eight bytes")
        self.machine.mem_write(SETUP, packet)
        # A simulated SETUP IRQ enters the captured EP0 idle/setup case. The
        # native dispatcher clears delayed-status state and aborts an older request.
        self.machine.mem_write(self.pcd + 0xc, b"\x01")
        previous = len(self.setup_results)
        self.call(EP0_DISPATCH, self.pcd)
        return self.setup_results[-1] if len(self.setup_results) > previous else None

    def finish_control(self, data=None, status=0, actual=None):
        entry = self.word(self.ep0_state + 4)
        if entry == self.ep0_state + 4:
            raise RuntimeError("No native EP0 request is pending")
        request = self.word(entry)
        length = self.word(request + 4)
        if data is not None:
            if len(data) > length:
                raise ValueError("OUT data exceeds the queued request")
            self.machine.mem_write(self.word(request), data)
        count = (len(data) if data is not None else length) if actual is None else actual
        self.put_word(entry + 0x10, count)  # simulated DMA completion's actual count
        self.call(PCD_COMPLETE, self.ep0_state, entry, status)
        # Virtual IRQ completes IN data + OUT status, or the explicit status IN.
        # OUT-data completion remains in its delayed data state until status is queued.
        if self.byte(self.pcd + 0xc) != 3:
            self.machine.mem_write(self.pcd + 0xc, b"\x01")
        return request


def build_control_objects(directory):
    return build_objects(directory, CONTROL_SOURCES)


def control_replay(objects, images=None):
    model = NativeControlEmulator(*(images or default_images()))
    symbols, layout = load_arm_objects(model.machine, objects)
    model.symbols = symbols
    if model.call(symbols["control_init"]) != 0:
        raise RuntimeError("Control adapter failed to bind the saved native callback")
    return model, symbols, layout
