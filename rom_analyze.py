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
    the constant/literal/dispatch hits we collect still surface the builder.

    skipdata keeps the sweep going past a byte capstone cannot decode; without
    it the linear scan halts at the first literal pool (around 0x1700 here) and
    the whole image past that point is never examined."""
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.detail = True
    md.skipdata = True
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


def captured_descriptors(target):
    """Return the raw descriptor bytes saved alongside a capture dir, if any.

    Returns a dict name -> bytes for every descriptor whose .bin file is present
    (device.bin, configuration_0.bin, ...). Empty for a raw .bin target.
    """
    path = Path(target)
    if not path.is_dir():
        return {}
    try:
        report = json.loads((path / "capture.json").read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for name, meta in report.get("descriptors", {}).items():
        blob_path = path / meta.get("file", "")
        if blob_path.is_file():
            out[name] = blob_path.read_bytes()
    return out


def descriptor_fragments(descriptors):
    """Distinctive multi-byte needles to search the ROM for.

    Single USB constants (VID, PID, a length+type halfword) are too short to pin
    a 32-bit image; they match unrelated words and table offsets. Multi-byte runs
    taken from the real descriptors are specific. Built from the captured bytes
    when present, else from the known BT600 layout.
    """
    needles = []
    cfg = descriptors.get("configuration_0")
    dev = descriptors.get("device")
    if cfg and len(cfg) >= 6:
        needles.append(("config header 09 02 wTotalLength..", cfg[:6]))
    if cfg:
        # The ascending isochronous wMaxPacketSize values, one per alt setting,
        # are the single most distinctive run in this device.
        iso = bytes(cfg[i + 4] for i in range(len(cfg) - 6)
                    if cfg[i] == 0x07 and cfg[i + 1] == 0x05 and (cfg[i + 2] & 0x80))
        seen, iso_sizes = set(), []
        for b in iso:
            if b not in seen:
                seen.add(b)
                iso_sizes.append(b)
        if len(iso_sizes) >= 3:
            needles.append(("ascending iso wMaxPacketSize run", bytes(iso_sizes)))
    if dev and len(dev) >= 8:
        needles.append(("device header 12 01 bcdUSB class..", dev[:8]))
    if not needles:
        # Fallback: the BT600 stock bytes, in case no capture dir was given.
        needles = [
            ("config header 09 02 c8 00 02 01", bytes([0x09, 0x02, 0xc8, 0x00, 0x02, 0x01])),
            ("ascending iso wMaxPacketSize run", bytes([0x00, 0x09, 0x11, 0x19, 0x21, 0x31, 0x3f])),
            ("device header 12 01 10 01 e0 01 01 40",
             bytes([0x12, 0x01, 0x10, 0x01, 0xe0, 0x01, 0x01, 0x40])),
        ]
    return needles


def line(insn):
    return f"0x{insn.address:08x}: {insn.mnemonic:<8} {insn.op_str}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="results/descriptor-*/ directory, or a raw ram.bin")
    parser.add_argument("--base", type=lambda v: int(v, 0), default=0x00001000,
                        help="load address of a raw .bin (default 0x00001000; ignored for a capture dir)")
    parser.add_argument("--context", type=int, default=3, help="instructions of context around each hit")
    parser.add_argument("--no-fragments", action="store_true",
                        help="skip the multi-byte descriptor-fragment scan")
    args = parser.parse_args(argv)

    blob, base = load_image(args.target, args.base)
    print(f"Image: {len(blob)} bytes at 0x{base:08x}..0x{base + len(blob):08x}")

    immediates, literals, dispatches = disassemble(blob, base)

    print(f"\n== MOVW/MOV immediates matching descriptor constants ({len(immediates)}) ==")
    for insn, value in immediates:
        print(f"  {line(insn)}    <- 0x{value:04x} {TARGETS[value]}")
    if not immediates:
        print("  none")

    # A literal is STRONG only when the whole 32-bit word is a target. When just
    # a halfword matched, the word is usually an address or an unrelated constant
    # (e.g. 0x00281d70, a function-pointer slot whose low half is 0x1d70), so it
    # is reported separately and not treated as a descriptor-builder lead.
    strong = [(i, h) for i, h in literals if "halfword" not in h[2]]
    weak = [(i, h) for i, h in literals if "halfword" in h[2]]

    print(f"\n== Strong literal loads (full word is a descriptor constant) ({len(strong)}) ==")
    for insn, (literal_va, word, label) in strong:
        print(f"  {line(insn)}")
        print(f"      literal @0x{literal_va:08x} = 0x{word:08x}  <- {label}")
    if not strong:
        print("  none")

    print(f"\n== Weak halfword matches (coincidental; a target is only a sub-halfword) ({len(weak)}) ==")
    for insn, (literal_va, word, label) in weak[:20]:
        note = "  (word is address-like -> pointer constant, not descriptor bytes)" if word >= 0x00100000 else ""
        print(f"  {line(insn)}  literal @0x{literal_va:08x} = 0x{word:08x}  <- {label}{note}")
    if len(weak) > 20:
        print(f"  ... and {len(weak) - 20} more")
    if not weak:
        print("  none")

    print(f"\n== Setup-dispatch comparisons (bRequest/bmRequestType) ({len(dispatches)}) ==")
    for insn, request in dispatches:
        print(f"  {line(insn)}    <- {DISPATCH[request]}")
    if not dispatches:
        print("  none")

    fragments = []
    if not args.no_fragments:
        needles = descriptor_fragments(captured_descriptors(args.target))
        print(f"\n== Multi-byte descriptor-fragment scan ({len(needles)} needles) ==")
        for label, needle in needles:
            hits = find_all(blob, base, needle)
            fragments += hits
            shown = " ".join(f"0x{va:08x}" for va in hits[:8]) if hits else "none"
            print(f"  {label} [{needle.hex()}]: {len(hits)} hit(s)  {shown}")

    raw = raw_scan(blob, base)
    print(f"\n== Raw little-endian occurrences in image ({len(raw)}, showing first 30) ==")
    for va, size, value, label in raw[:30]:
        width = size * 2
        print(f"  0x{va:08x}: {value:0{width}x}  <- {label}")
    if len(raw) > 30:
        print(f"  ... and {len(raw) - 30} more (noise at this width)")
    if not raw:
        print("  none")

    print("\n== Where to read next ==")
    if fragments:
        print("  A multi-byte descriptor fragment was found in the ROM. Disassemble")
        print("  around those addresses; code that references the fragment is the")
        print("  descriptor source. Walk back to the enclosing function entry.")
    elif strong:
        print("  Open the functions containing the strong literal loads above and")
        print("  walk back to the function entry; that is the descriptor-builder lead.")
    else:
        print("  No descriptor fragment and no strong constant load. Single USB")
        print("  constants (VID/PID/length+type) are too short to pin this image and")
        print("  match unrelated words. The descriptors are assembled at enumeration,")
        print("  not stored here: dump the 0x00210000 RAM window while audio is")
        print("  streaming and diff it against the idle dump to catch the buffers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
