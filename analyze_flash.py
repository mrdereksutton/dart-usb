#!/usr/bin/env python3
"""Summarize and sanity-check a direct SPI-flash dump of the dongle.

For use with a flashrom read of the W25Q16 (see FLASH_ACCESS.md). The flash image
is the chip's raw contents; the firmware is mapped for execution at 0x00200000,
so pass --base 0x00200000 (the default) to put offsets into CPU address space.

It reports size, how much is real (non-0xFF) content, whether the known firmware
markers are present (the ">>> Platform Ext" string and the descriptor handler
bytes at 0x205ca2), interesting strings, and a sha256. It does NOT need a dongle.
Deep disassembly stays in rom_analyze.py:

    python3 analyze_flash.py flash.bin
    python3 rom_analyze.py flash.bin --base 0x00200000

A second image can be passed with --compare to diff two dumps (e.g. before/after
a write, or two reads to confirm a stable dump)."""

import argparse
import hashlib
import re
import struct
from pathlib import Path

FLASH_BASE = 0x00200000
# Descriptor handler bytes read live from the controller at 0x205ca2 this session.
HANDLER_ADDR = 0x00205CA2
HANDLER_BYTES = bytes.fromhex("0fb43eb504 46bdf82410 0b9da1f50071".replace(" ", ""))


def summarize(path, base):
    data = Path(path).read_bytes()
    nonff = sum(1 for b in data if b != 0xFF)
    non00 = sum(1 for b in data if b != 0x00)
    print(f"file: {path}")
    print(f"size: {len(data)} bytes (0x{len(data):x}); maps 0x{base:08x}..0x{base + len(data):08x}")
    print(f"content: {100 * nonff / len(data):.1f}% non-0xFF, {100 * non00 / len(data):.1f}% non-0x00")
    print(f"sha256: {hashlib.sha256(data).hexdigest()}")

    def at(addr, n):
        off = addr - base
        return data[off:off + n] if 0 <= off and off + n <= len(data) else b""

    print("\nknown markers:")
    print(f"  ' >>> Platform Ext' string present: {b'Platform Ext' in data}")
    got = at(HANDLER_ADDR, len(HANDLER_BYTES))
    print(f"  descriptor handler @0x{HANDLER_ADDR:08x} matches live read: {got == HANDLER_BYTES}"
          + ("" if got == HANDLER_BYTES else f"  (got {got.hex(' ') or 'out of range'})"))

    print("\ninteresting strings (flash/usb/audio/ipod):")
    seen = 0
    for m in re.finditer(rb"[ -~]{5,}", data):
        s = m.group()
        if re.search(rb"(?i)flash|usb|audio|ipod|iap|uac|a2dp|sco|iso|platform|realtek|version", s):
            print(f"  0x{base + m.start():08x} {s.decode()[:60]}")
            seen += 1
            if seen >= 25:
                print("  ...(truncated)")
                break
    return data


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", help="flashrom dump of the W25Q16")
    p.add_argument("--base", type=lambda v: int(v, 0), default=FLASH_BASE,
                   help="address the flash is mapped to (default 0x00200000)")
    p.add_argument("--compare", help="a second dump to diff against image")
    args = p.parse_args(argv)

    a = summarize(args.image, args.base)
    if args.compare:
        b = Path(args.compare).read_bytes()
        print(f"\ncompare vs {args.compare}:")
        if len(a) != len(b):
            print(f"  size differs: {len(a)} vs {len(b)}")
        n = min(len(a), len(b))
        diffs = [i for i in range(n) if a[i] != b[i]]
        if not diffs and len(a) == len(b):
            print("  identical")
        else:
            print(f"  {len(diffs)} differing bytes; first at 0x{args.base + diffs[0]:08x}" if diffs else "  (only size differs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
