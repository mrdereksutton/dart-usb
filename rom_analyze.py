#!/usr/bin/env python3
"""Find the RTL8761CU descriptor/EP0 handler in a saved ROM dump.

The USB descriptors are not stored as a contiguous blob anywhere fc61 can
read (confirmed: a full 0x1000..0x9efff dump searched in four word layouts
matched nothing). They are built by code. This tool reverses that code
offline, with no dongle, by its constants rather than its bytes:

  * the device-descriptor builder loads VID 0x0b05 and PID 0x1d70 as MOVW
    immediates or from a PC-relative literal pool;
  * descriptor records begin with a length+type signature halfword
    (0x0112 device, 0x0209 configuration, ...);
  * the setup-packet dispatch compares bRequest against 0x06 (GET_DESCRIPTOR)
    and bmRequestType against 0x80 (device-to-host).

Run it locally against the ram.bin from results/descriptor-*/:

    python3 rom_analyze.py results/descriptor-20261017T002154.077318Z
    python3 rom_analyze.py path/to/ram.bin --base 0x00001000

It reads a file only; it never opens USB.
"""

import argparse
import json
from pathlib import Path
import struct

import capstone
from capstone import arm as cs_arm


# Constants the descriptor builder is expected to materialize. 16-bit values
# are matched as MOVW immediates, as halfwords inside a PC-relative literal,
# and as raw little-endian occurrences in the image (literal pools / tables).
TARGETS = {
    0x0B05: "VID 0x0b05 (ASUS)",
    0x1D70: "PID 0x1d70 (USB-BT600)",
    0x0112: "device-descriptor signature (bLength 0x12, bDescriptorType 0x01)",
    0x0209: "configuration-descriptor signature (bLength 0x09, bDescriptorType 0x02)",
    0x01E0: "device class bytes (bDeviceClass 0xe0, next 0x01)",
}
# Full 32-bit words worth scanning the raw image for: the VID/PID pair as it
# sits in the live device descriptor (0x0b05 then 0x1d70, little-endian).
WORD_TARGETS = {
    0x1D700B05: "VID+PID little-endian pair (05 0b 70 1d)",
}
# Setup-packet dispatch comparisons.
DISPATCH = {
    0x06: "bRequest == GET_DESCRIPTOR (6)",
    0x80: "bmRequestType == 0x80 (device-to-host, standard, device)",
}


def load_image(target, base):
    """Return (bytes, base_address). Accepts a capture dir or a raw file."""
    path = Path(target)
    if path.is_dir():
        report = json.loads((path / "capture.json").read_text())
        blob = (path / "ram.bin").read_bytes()
        if "bytes_read" in report and len(blob) != report["bytes_read"]:
            raise SystemExit(f"ram.bin is {len(blob)} bytes, capture.json says {report['bytes_read']}")
        return blob, int(report["start_address"], 0)
    return path.read_bytes(), base


def read_word(blob, base, va):
    """Little-endian 32-bit word at virtual address va, or None if out of range."""
    off = va - base
    if off < 0 or off + 4 > len(blob):
        return None
    return struct.unpack_from("<I", blob, off)[0]


def immediate_hits(insn):
    """MOVW/MOVT/MOV immediates that equal a target 16-bit constant."""
    if insn.mnemonic not in ("movw", "movt", "mov", "movs"):
        return []
    hits = []
    for operand in insn.operands:
        if operand.type == cs_arm.ARM_OP_IMM and operand.imm in TARGETS:
            hits.append(operand.imm)
    return hits


def literal_hit(insn, blob, base):
    """For LDR Rt, [pc, #imm], resolve the literal and match it against targets.

    Returns (literal_va, word, label) or None. Thumb PC for a literal load is
    (instruction address + 4) aligned down to 4.
    """
    if not insn.mnemonic.startswith("ldr"):
        return None
    for operand in insn.operands:
        if operand.type != cs_arm.ARM_OP_MEM:
            continue
        if operand.mem.base != cs_arm.ARM_REG_PC:
            continue
        literal_va = ((insn.address + 4) & ~3) + operand.mem.disp
        word = read_word(blob, base, literal_va)
        if word is None:
            return None
        if word in WORD_TARGETS:
            return literal_va, word, WORD_TARGETS[word]
        low, high = word & 0xFFFF, (word >> 16) & 0xFFFF
        if word in TARGETS:
            return literal_va, word, TARGETS[word]
        if low in TARGETS:
            return literal_va, word, TARGETS[low] + " (low halfword)"
        if high in TARGETS:
            return literal_va, word, TARGETS[high] + " (high halfword)"
    return None


def dispatch_hit(insn):
    """CMP Rn, #imm comparisons against known setup-packet request fields."""
    if insn.mnemonic not in ("cmp", "cmp.w"):
        return None
    for operand in insn.operands:
        if operand.type == cs_arm.ARM_OP_IMM and operand.imm in DISPATCH:
            return operand.imm
    return None


def disassemble(blob, base):
    """Linear Thumb sweep. Data interleaved with code mis-decodes locally, but
    the constant/literal/dispatch hits we collect still surface the builder."""
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.detail = True
    immediates, literals, dispatches = [], [], []
    for insn in md.disasm(blob, base):
        for value in immediate_hits(insn):
            immediates.append((insn, value))
        hit = literal_hit(insn, blob, base)
        if hit:
            literals.append((insn, hit))
        request = dispatch_hit(insn)
        if request is not None:
            dispatches.append((insn, request))
    return immediates, literals, dispatches


def raw_scan(blob, base):
    """Little-endian occurrences of each target in the raw image (literal
    pools, descriptor tables). Independent of correct instruction decoding."""
    found = []
    for value, label in WORD_TARGETS.items():
        found += [(va, 4, value, label) for va in find_all(blob, base, struct.pack("<I", value))]
    for value, label in TARGETS.items():
        found += [(va, 2, value, label) for va in find_all(blob, base, struct.pack("<H", value))]
    found.sort()
    return found


def find_all(blob, base, needle):
    out, start = [], 0
    while True:
        index = blob.find(needle, start)
        if index < 0:
            return out
        out.append(base + index)
        start = index + 1


def line(insn):
    return f"0x{insn.address:08x}: {insn.mnemonic:<8} {insn.op_str}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="results/descriptor-*/ directory, or a raw ram.bin")
    parser.add_argument("--base", type=lambda v: int(v, 0), default=0x00001000,
                        help="load address of a raw .bin (default 0x00001000; ignored for a capture dir)")
    parser.add_argument("--context", type=int, default=3, help="instructions of context around each hit")
    args = parser.parse_args(argv)

    blob, base = load_image(args.target, args.base)
    print(f"Image: {len(blob)} bytes at 0x{base:08x}..0x{base + len(blob):08x}")

    immediates, literals, dispatches = disassemble(blob, base)

    print(f"\n== MOVW/MOV immediates matching descriptor constants ({len(immediates)}) ==")
    for insn, value in immediates:
        print(f"  {line(insn)}    <- 0x{value:04x} {TARGETS[value]}")
    if not immediates:
        print("  none")

    print(f"\n== PC-relative literal loads of descriptor constants ({len(literals)}) ==")
    for insn, (literal_va, word, label) in literals:
        print(f"  {line(insn)}")
        print(f"      literal @0x{literal_va:08x} = 0x{word:08x}  <- {label}")
    if not literals:
        print("  none")

    print(f"\n== Setup-dispatch comparisons (bRequest/bmRequestType) ({len(dispatches)}) ==")
    for insn, request in dispatches:
        print(f"  {line(insn)}    <- {DISPATCH[request]}")
    if not dispatches:
        print("  none")

    raw = raw_scan(blob, base)
    print(f"\n== Raw little-endian occurrences in image ({len(raw)}) ==")
    for va, size, value, label in raw:
        width = size * 2
        print(f"  0x{va:08x}: {value:0{width}x}  <- {label}")
    if not raw:
        print("  none")

    code_refs = {lit[0] for _, lit in literals}
    vidpid = [va for va, size, value, _ in raw if value in (0x0B05, 0x1D70) or value in WORD_TARGETS]
    print("\n== Where to read next ==")
    if literals:
        print("  Open the functions containing the literal loads above: those are the")
        print("  descriptor builders. Walk back to the function entry, then find the")
        print("  caller that reaches it from a GET_DESCRIPTOR (bRequest==6) dispatch.")
    elif vidpid:
        print("  No code referenced the VID/PID via a resolved literal, but the bytes")
        print(f"  appear raw at: {', '.join(f'0x{va:08x}' for va in vidpid[:8])}")
        print("  Disassemble around those addresses; the reference may be computed")
        print("  (ADD/ADR) rather than a plain PC-relative LDR.")
    else:
        print("  VID/PID not found as immediates, literals, or raw bytes. The device")
        print("  descriptor is likely assembled from a table in USB-peripheral memory")
        print("  (the region that hangs fc61), not from this ROM image.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
