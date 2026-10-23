"""Minimal ELF32 ARM relocator for offline Unicorn tests, not a device loader.

Supports only the relocation types emitted by this project's clang/Thumb build.
Unsupported objects fail explicitly. Nothing here writes to a real device.
"""
from pathlib import Path
import struct


def aligned(value, alignment):
    return (value + alignment - 1) & -alignment


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def load_arm_objects(machine, paths, base=0x00700000):
    objects, globals_ = [], {}
    cursor = base
    for path in paths:
        data = Path(path).read_bytes()
        if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<HH", data, 16) != (1, 40):
            raise ValueError("Expected an ARM ELF32 relocatable object")
        offset = struct.unpack_from("<I", data, 32)[0]
        stride, count = struct.unpack_from("<HH", data, 46)
        if stride != 40 or offset + count * stride > len(data):
            raise ValueError("Invalid ARM section table")
        sections = [struct.unpack_from("<10I", data, offset + i * stride) for i in range(count)]
        addresses = {}
        for i, section in enumerate(sections):
            if section[2] & 2:
                cursor = aligned(cursor, max(1, section[8]))
                addresses[i] = cursor
                cursor += section[5]
        tables = {}
        for i, section in enumerate(sections):
            if section[1] != 2:
                continue
            strings = sections[section[6]]
            names = data[strings[4]:strings[4] + strings[5]]
            symbols = []
            for at in range(section[4], section[4] + section[5], section[9]):
                name_offset, value, size, info, other, index = struct.unpack_from("<IIIBBH", data, at)
                name = names[name_offset:].split(b"\0", 1)[0].decode("ascii") if name_offset else ""
                address = addresses[index] + value if index in addresses else value if index == 0xfff1 else None
                symbol = {"name": name, "address": address, "info": info, "index": index}
                symbols.append(symbol)
                if name and info >> 4 in (1, 2) and address is not None:
                    if name in globals_:
                        raise ValueError(f"Duplicate ARM symbol {name}")
                    globals_[name] = address
            tables[i] = symbols
        objects.append((data, sections, addresses, tables))
    length = aligned(cursor - base, 4096)
    if not length or length > 0x40000:
        raise ValueError("Offline ARM image is empty or exceeds its memory budget")
    image = bytearray(length)
    for data, sections, addresses, tables in objects:
        for i, address in addresses.items():
            section = sections[i]
            if section[1] == 8:
                continue
            if section[4] + section[5] > len(data):
                raise ValueError("Truncated ARM section")
            start = address - base
            image[start:start + section[5]] = data[section[4]:section[4] + section[5]]
    counts = {}
    for data, sections, addresses, tables in objects:
        for section in sections:
            if section[1] != 9 or section[7] not in addresses:
                continue
            symbols = tables[section[6]]
            for at in range(section[4], section[4] + section[5], section[9]):
                offset, info = struct.unpack_from("<II", data, at)
                kind, symbol = info & 255, symbols[info >> 8]
                place = addresses[section[7]] + offset
                p = place - base
                target = symbol["address"]
                if target is None:
                    target = globals_.get(symbol["name"])
                if target is None:
                    raise ValueError(f"Unresolved ARM symbol {symbol['name']}")
                counts[kind] = counts.get(kind, 0) + 1
                if kind in (2, 3, 42):  # ABS32, REL32, PREL31
                    value = struct.unpack_from("<I", image, p)[0]
                    if kind == 2: value = target + value
                    elif kind == 3: value = target + signed(value, 32) - place
                    else: value = (value & 0x80000000) | ((target + signed(value & 0x7fffffff, 31) - place) & 0x7fffffff)
                    struct.pack_into("<I", image, p, value & 0xffffffff)
                elif kind in (47, 48):  # THM_MOVW_ABS_NC, THM_MOVT_ABS
                    first, second = struct.unpack_from("<HH", image, p)
                    immediate = (first & 15) << 12 | ((first >> 10) & 1) << 11 | ((second >> 12) & 7) << 8 | (second & 255)
                    value = target + (immediate << 16 if kind == 48 else immediate)
                    immediate = (value >> 16 if kind == 48 else value) & 0xffff
                    first = (first & ~0x040f) | (immediate >> 12) | (((immediate >> 11) & 1) << 10)
                    second = (second & ~0x70ff) | (((immediate >> 8) & 7) << 12) | (immediate & 255)
                    struct.pack_into("<HH", image, p, first, second)
                elif kind in (10, 30):  # THM_CALL, THM_JUMP24
                    first, second = struct.unpack_from("<HH", image, p)
                    s = (first >> 10) & 1
                    i1 = (~(((second >> 13) & 1) ^ s)) & 1
                    i2 = (~(((second >> 11) & 1) ^ s)) & 1
                    addend = signed(s << 24 | i1 << 23 | i2 << 22 | (first & 1023) << 12 | (second & 2047) << 1, 25)
                    delta = (target & ~1) + addend - place
                    if delta & 1 or not -(1 << 24) <= delta < (1 << 24):
                        raise ValueError("ARM branch relocation is out of range")
                    s, i1, i2 = (delta >> 24) & 1, (delta >> 23) & 1, (delta >> 22) & 1
                    first = (first & 0xf800) | s << 10 | (delta >> 12 & 1023)
                    second = (second & 0xd000) | ((~i1 ^ s) & 1) << 13 | ((~i2 ^ s) & 1) << 11 | (delta >> 1 & 2047)
                    struct.pack_into("<HH", image, p, first, second)
                else:
                    raise ValueError(f"Unsupported ARM relocation {kind}")
    machine.mem_map(base, length)
    machine.mem_write(base, bytes(image))
    return globals_, {"base": base, "bytes": length, "relocations": counts}
