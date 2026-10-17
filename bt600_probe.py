#!/usr/bin/env python3
"""Query an ASUS USB-BT600 from macOS Terminal: python3 bt600_probe.py.

Uses the existing Homebrew libusb installation. Queries USB descriptors,
HCI Read Local Version Information (0x1001), and Realtek Read ROM Version
(0xFC6D). Default mode does not download firmware. --load-stock sends the
stock linux-firmware RTL8761CU driver patch for the detected ROM revision.
--probe-memory additionally reads the RAM-table address that answered on this dongle.
--read-range START WORDS reads a bounded span in the same candidate RAM page.
These modes do not reset the controller or detach a kernel driver.
If the device is unconfigured, configuration 1 is selected for the query and
the original unconfigured state is restored on exit.
"""

import argparse
import base64
import ctypes as C
import ctypes.util
import hashlib
from pathlib import Path
import struct
import sys
import time


VID, PID = 0x0B05, 0x1D70
P = C.c_void_p

# The C chip answered this four-byte RAM read on 2026-10-16. The former
# 0x0880A0A8 candidate timed out and disconnected the controller, so it is
# excluded. Boot-vector reads at 0 and 4 returned only zeroes.
MEMORY_READ_OPCODE = 0xFC61
MEMORY_READ_ACCESS = 0x20
# Counterpart write opcode on the B family. Untested on this C chip; --write-test
# probes it with a read/flip/verify/restore cycle on one word so the footprint is
# a single briefly-changed value that is put back, and a replug clears anything odd.
MEMORY_WRITE_OPCODE = 0xFC62
MEMORY_PROBE_ADDRESSES = (
    (0x00217E88, "patch data-table literal"),
)
# This is an experiment boundary around the one responding address, not a
# measured RAM map. Do not expand it into untested flash/peripheral windows.
MEMORY_RANGE_START, MEMORY_RANGE_END = 0x00217000, 0x00218000
# Pages a --read-range read may touch. Each is an experiment boundary around a
# specific lead, not a measured RAM map: 0x217000 is the one address that
# answered earlier; 0x285000 holds the USB callback vector at 0x285c0c traced in
# FIRMWARE.md (slots +0x38/+0x48 are the descriptor handlers to resolve). A read
# must stay inside ONE page. Do not expand into untested flash/peripheral
# windows, and never target 0x000a0000 or 0x0880a0a8 (they hang the controller).
MEMORY_READ_PAGES = (
    (0x00200000, 0x00206000),
    (0x00210000, 0x00212000),
    (0x00217000, 0x00218000),
    (0x00225000, 0x00226000),
    (0x00230000, 0x00231000),
    (0x00280000, 0x00281000),
    (0x00285000, 0x00286000),
    (0x00288000, 0x00289000),
    (0x00300000, 0x00301000),
    (0x003ff000, 0x00400000),
)
MAX_MEMORY_WORDS = 256
# idVendor/idProduct bytes as they appear inside a USB device descriptor
# (little-endian 0b05, 1d70). Finding this in readable memory shows where the
# controller keeps its USB identity; whether that location is writable decides
# whether the dongle can be made to enumerate as something else.
USB_VID_PID_SIGNATURE = struct.pack("<HH", VID, PID)
# fc61 word byte order is unconfirmed, so search every plausible arrangement of
# the vendor/product shorts rather than risk a byte-order false negative.
USB_SIGNATURE_VARIANTS = tuple(dict.fromkeys((
    struct.pack("<HH", VID, PID),           # 05 0b 70 1d
    struct.pack(">HH", VID, PID),           # 0b 05 1d 70
    struct.pack("<HH", VID, PID)[::-1],     # 1d 70 0b 05
    struct.pack(">HH", VID, PID)[::-1],     # 70 1d 05 0b
)))

# Exact linux-firmware blob 475320d0bd5c982cc472422cb37d263f785a24f3.
# Source: kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/
#         +/refs/tags/20260221/rtl_bt/rtl8761cu_fw.bin
# Firmware remains subject to Realtek's LICENCE.rtlwifi_firmware.txt.
STOCK_FIRMWARE_B64 = "UmVhbHRlY2jz0xhGBAAAAAEAAgADAPwA/AD8APwAMAAAADAAAAAwAAAAMAAAAAAAcLUfTB9IIU0jGAEiHkkoRun1PvkeSUD2CBAIgB1JQvIlAAiAHEiEQibS4XggaGHzH2AaSYhCH9GgiBNJgB2GsjNGASIkMShG6fUi+TFGIEby99b5APDk+ADw5/gA8Or4APDt+ADw8PgA8PP4APD2+ADw+fgA8Pz4CkkJSAhgcL2IfiEAAITe/6iggAgCMBBvFgAsABgALAAApCEAVasjh/98IQAQBiwALen8QQAkTU/f+DSBBUYBJs3pAGUH60QAAiMBItj4AMBAeAAh4EdkHOSyKCzw073o/IEQtQAhQUoLRhL4EUCEQgPRAutBAEN4A+BJHMmyKCnz0xhGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP8zAQBRBP13"
STOCK_CONFIG_B64 = "VasjhwUA9wACAAA="


def stock_payload(rom_version):
    if not 0 <= rom_version <= 254:
        raise RuntimeError("A successful ROM-version query is required before selecting a patch")
    firmware = base64.b64decode(STOCK_FIRMWARE_B64, validate=True)
    config = base64.b64decode(STOCK_CONFIG_B64, validate=True)
    if hashlib.sha256(firmware).hexdigest() != "525bfa5ab9a3ed74b788f9ac494467c522a436c1bc5290ebcb05c7f920533c09":
        raise RuntimeError("Embedded stock firmware checksum mismatch")
    if hashlib.sha256(config).hexdigest() != "3142c2732470e4edcdb68edf58cc505b581e38d56b3ec09c64eddcb1d5099507":
        raise RuntimeError("Embedded stock configuration checksum mismatch")
    if not firmware.startswith(b"Realtech") or not firmware.endswith(bytes.fromhex("51 04 fd 77")):
        raise RuntimeError("Unexpected stock firmware container")
    if firmware[-7:-4] != bytes((51, 1, 0)):
        raise RuntimeError("Stock firmware does not identify RTL8761C project 51")
    version, count = struct.unpack_from("<IH", firmware, 8)
    if len(firmware) < 14 + 8 * count:
        raise RuntimeError("Truncated firmware patch table")
    for index in range(count):
        chip_id = struct.unpack_from("<H", firmware, 14 + 2 * index)[0]
        if chip_id != rom_version + 1:
            continue
        length = struct.unpack_from("<H", firmware, 14 + 2 * count + 2 * index)[0]
        offset = struct.unpack_from("<I", firmware, 14 + 4 * count + 4 * index)[0]
        if length < 4 or offset + length > len(firmware):
            raise RuntimeError("Firmware patch range is invalid")
        # Mirrors btrtl.c: substitute container version for the patch's last
        # four bytes, then append the chip's configuration blob.
        payload = firmware[offset:offset + length - 4] + struct.pack("<I", version) + config
        return version, chip_id, payload
    raise RuntimeError(f"No stock patch for ROM version {rom_version}")


CUSTOM_MARKER_ADDR = 0x00211F00  # RAM, inside the known 0x210000 window, past the
CUSTOM_MARKER_VALUE = 0xDEADBEEF  # device context at 0x2103a8 so it is not reused.


def build_custom_marker_patch(code, marker_addr=CUSTOM_MARKER_ADDR,
                              marker_value=CUSTOM_MARKER_VALUE):
    """Insert an entry hook into the stock patch code that runs appended Thumb
    code at launch: it writes marker_value to marker_addr, performs the patch's
    displaced first instruction, then returns into the patch. Proves custom code
    runs on the controller. All intra-patch branches are PC-relative (no load
    address needed); only the marker address is absolute. Returns the larger
    patch bytes. Verified by disassembly in test_probe.py."""
    code = bytearray(code)
    entry = bytes(code[0:2])
    if entry != b"\x70\xb5":            # push {r4, r5, r6, lr}
        raise RuntimeError("Unexpected patch entry; refusing to build custom patch")
    base = len(code)
    if base % 4:
        raise RuntimeError("Patch code length must be four-byte aligned")

    def branch(frm, to):                # Thumb T2 unconditional branch (b.n)
        return struct.pack("<H", 0xE000 | (((to - (frm + 4)) >> 1) & 0x7FF))

    code[0:2] = branch(0, base)         # hook: entry -> appended code
    extra = bytearray()
    extra += b"\x03\xb4"                # push {r0, r1}
    extra += b"\x00\x48"                # ldr r0, [pc, #v]   (fixed up below)
    extra += b"\x00\x49"                # ldr r1, [pc, #a]
    extra += b"\x08\x60"                # str r0, [r1]
    extra += b"\x03\xbc"                # pop {r0, r1}
    extra += entry                      # push {r4, r5, r6, lr}  (displaced original)
    extra += branch(base + 12, 2)       # b back to patch+2
    extra += b"\x00\xbf"                # nop (align data to 4)
    val_off = len(extra); extra += struct.pack("<I", marker_value)
    addr_off = len(extra); extra += struct.pack("<I", marker_addr)

    def ldr_literal(at, rt, target):
        pc = (base + at + 4) & ~3
        imm8 = (base + target - pc) // 4
        if not 0 <= imm8 < 256:
            raise RuntimeError("ldr literal out of range")
        return struct.pack("<H", 0x4800 | (rt << 8) | imm8)

    extra[2:4] = ldr_literal(2, 0, val_off)
    extra[4:6] = ldr_literal(4, 1, addr_off)
    return bytes(code) + bytes(extra)


def custom_marker_payload(rom_version, marker_addr=CUSTOM_MARKER_ADDR,
                          marker_value=CUSTOM_MARKER_VALUE):
    """Like stock_payload, but the patch code carries the marker-write hook."""
    version, chip_id, payload = stock_payload(rom_version)
    firmware = base64.b64decode(STOCK_FIRMWARE_B64, validate=True)
    config = base64.b64decode(STOCK_CONFIG_B64, validate=True)
    code = payload[:len(payload) - len(config) - 4]   # strip appended version+config
    custom = build_custom_marker_patch(code, marker_addr, marker_value)
    return version, chip_id, custom + struct.pack("<I", version) + config


def download_fragments(payload):
    # Mirrors Linux's extra final fragment when length is a multiple of 252.
    count = len(payload) // 252 + 1
    index = 0
    for fragment in range(count):
        command_index = index
        index += 1
        if command_index == 0x7F:
            index = 1
        start = fragment * 252
        data = payload[start:start + 252]
        if fragment == count - 1:
            command_index |= 0x80
        yield bytes((command_index,)) + data


def parse_vector_table(data):
    """Decode available boot-vector words; this does not validate their mapping."""
    initial_sp = struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else None
    reset = struct.unpack_from("<I", data, 4)[0] if len(data) >= 8 else None
    return initial_sp, reset


class DeviceDescriptor(C.Structure):
    _fields_ = [
        ("length", C.c_uint8), ("kind", C.c_uint8), ("usb", C.c_uint16),
        ("device_class", C.c_uint8), ("subclass", C.c_uint8),
        ("protocol", C.c_uint8), ("max_packet", C.c_uint8),
        ("vid", C.c_uint16), ("pid", C.c_uint16),
        ("revision", C.c_uint16), ("manufacturer", C.c_uint8),
        ("product", C.c_uint8), ("serial", C.c_uint8),
        ("configurations", C.c_uint8),
    ]


class HCIEvents:
    """Reassemble HCI events across USB packets without losing adjacent events."""

    def __init__(self):
        self.pending = bytearray()

    def feed(self, packet):
        self.pending.extend(packet)
        events = []
        while len(self.pending) >= 2:
            length = self.pending[1] + 2
            if len(self.pending) < length:
                break
            events.append(bytes(self.pending[:length]))
            del self.pending[:length]
        return events


def command_result(event, opcode):
    """Return a matching completion; surface explicit command rejections."""
    if len(event) < 2 or len(event) != event[1] + 2:
        raise RuntimeError("Malformed HCI event length")
    if event[0] == 0x0E:
        if len(event) < 5:
            raise RuntimeError("Truncated HCI Command Complete")
        if struct.unpack_from("<H", event, 3)[0] == opcode:
            return event[5:]
    elif event[0] == 0x0F:
        if len(event) != 6:
            raise RuntimeError("Malformed HCI Command Status")
        if struct.unpack_from("<H", event, 4)[0] == opcode and event[2]:
            raise RuntimeError(f"HCI {opcode:04x} rejected with status 0x{event[2]:02x}")
    return None


def require_stock_version(response, before):
    # btrtl.c never checks the post-download version against a fixed value; it
    # re-reads it and only logs it (rtl_download_firmware -> btrtl_read_local_
    # version), and sends no HCI Reset -- the controller relaunches on the
    # final fragment. The epatch container fw_version is written into the
    # download buffer but is not an expected reported value. So the success
    # signal is that the running version changed from the pre-download value,
    # not that it equals the container version (which this C chip does not
    # report back).
    if len(response) != 9 or response[0] != 0:
        raise RuntimeError("No successful version response after upload")
    _, _, revision, _, maker, subversion = struct.unpack("<BBHBHH", response)
    observed = (revision << 16) | subversion
    print(f"Running version after upload: 0x{observed:08x} (was 0x{before:08x})")
    if maker != 0x005D:
        raise RuntimeError("Controller manufacturer changed unexpectedly after upload")
    if observed == before:
        raise RuntimeError("Download was acknowledged but the running version did not change; the patch did not launch")


def require_download_ack(response, index):
    if len(response) != 2 or response[0] != 0:
        raise RuntimeError(f"Download fragment {index:02x} was rejected: {response.hex()}")
    # Controllers may echo the final marker or only the seven-bit index.
    if response[1] & 0x7F != index & 0x7F:
        raise RuntimeError(f"Download fragment {index:02x} got an acknowledgement for {response[1]:02x}")


def find_patch_base(blob, start, needle):
    """Return a matching patch-byte address, which is a candidate load base."""
    if not needle:
        raise ValueError("Patch signature must not be empty")
    index = bytes(blob).find(bytes(needle))
    return None if index < 0 else start + index


def validate_write_address(address):
    """A --poke target must be aligned and sit inside one allowed read page, so a
    persistent write can never reach an untested or hang-prone address."""
    if address % 4:
        raise ValueError("Use a four-byte-aligned ADDR")
    if not any(lo <= address < address + 4 <= hi for lo, hi in MEMORY_READ_PAGES):
        pages = ", ".join(f"0x{lo:08x}..0x{hi - 1:08x}" for lo, hi in MEMORY_READ_PAGES)
        raise ValueError(f"ADDR must be inside one allowed page ({pages})")
    return address


def validate_memory_range(start, words):
    if start % 4 or not 1 <= words <= MAX_MEMORY_WORDS:
        raise ValueError(f"Use a four-byte-aligned START and 1..{MAX_MEMORY_WORDS} WORDS")
    end = start + words * 4
    if not any(lo <= start < end <= hi for lo, hi in MEMORY_READ_PAGES):
        pages = ", ".join(f"0x{lo:08x}..0x{hi - 1:08x}" for lo, hi in MEMORY_READ_PAGES)
        raise ValueError(f"Range must stay within one allowed page ({pages})")
    return start, words


def read_memory_word(command, address, quiet=False):
    result = command(MEMORY_READ_OPCODE, struct.pack("<BI", MEMORY_READ_ACCESS, address), quiet=quiet)
    if not result or result[0]:
        status = f"0x{result[0]:02x}" if result else "empty response"
        raise RuntimeError(f"Memory read at 0x{address:08x} returned {status}")
    if len(result) != 5:
        raise RuntimeError(f"Memory read at 0x{address:08x} returned {len(result) - 1} data bytes; expected four")
    return result[1:]


def read_memory_block(command, address, length, quiet=True):
    """fc61 read of `length` bytes at `address`. The fc61 access byte is a byte
    count; the firmware returns that many data bytes after the status. Returns
    the data bytes actually returned (may be fewer than requested)."""
    result = command(MEMORY_READ_OPCODE, struct.pack("<BI", length, address), quiet=quiet)
    if not result or result[0]:
        status = f"0x{result[0]:02x}" if result else "empty response"
        raise RuntimeError(f"Memory read at 0x{address:08x} returned {status}")
    return result[1:]


def write_memory_word(command, address, data, quiet=False):
    if len(data) != 4:
        raise RuntimeError("Memory write expects exactly four data bytes")
    result = command(MEMORY_WRITE_OPCODE,
                     struct.pack("<BI", MEMORY_READ_ACCESS, address) + bytes(data), quiet=quiet)
    if not result or result[0]:
        status = f"0x{result[0]:02x}" if result else "empty response"
        raise RuntimeError(f"Memory write at 0x{address:08x} returned {status}")
    return result


def read_memory_range(command, start, words):
    validate_memory_range(start, words)
    blob = bytearray()
    for address in range(start, start + words * 4, 4):
        # Let a failure escape immediately: no next address or diagnostic
        # phase may run after the controller stops answering.
        data = read_memory_word(command, address, quiet=True)
        blob.extend(data)
        print(f"Memory 0x{address:08x}: {data.hex(' ')}", flush=True)
    return bytes(blob)


def coalesce_runs(samples):
    """Merge consecutive equal-kind (address, kind) samples into regions,
    returning [(start, last, kind)] so a page sweep prints a few lines."""
    runs = []
    for address, kind in samples:
        if runs and runs[-1][2] == kind:
            runs[-1] = (runs[-1][0], address, kind)
        else:
            runs.append((address, address, kind))
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load-stock", action="store_true", help="Upload the matching stock RTL8761CU driver patch")
    parser.add_argument("--load-custom", action="store_true",
                        help="Upload the stock patch with an added marker-write hook (proves custom code runs); "
                             "RAM-only, reverted by a replug")
    parser.add_argument("--probe-memory", action="store_true", help="Read four bytes at the RAM-table address that answered on this dongle")
    parser.add_argument("--read-range", nargs=2, metavar=("START", "WORDS"),
                        help="Read 1..256 four-byte words within one allowed RAM page (0x00217000..0x00217fff or 0x00285000..0x00285fff)")
    parser.add_argument("--map-memory", action="store_true",
                        help="Sample one word per 4 KB page over 0x0..0x400000 and report readable regions, read-only")
    parser.add_argument("--find-descriptor", nargs="*", metavar="ARG",
                        help="Scan memory for the 0b05:1d70 USB signature, read-only; optional START WORDS (default 0x00210000 16384)")
    parser.add_argument("--find-patch", nargs=2, metavar=("START", "WORDS"),
                        help="Scan START..+WORDS for the resident stock patch prologue (run after --load-stock), read-only")
    parser.add_argument("--write-test", nargs="?", const="0x00210000", metavar="ADDR",
                        help="Probe memory write: read/flip/verify/restore one word at ADDR (default 0x00210000)")
    parser.add_argument("--poke", nargs=2, metavar=("ADDR", "VALUE"),
                        help="PERSISTENT write of one 32-bit VALUE at ADDR (no restore); ADDR must be aligned "
                             "and inside one allowed read page. Used for the write-and-reenumerate experiment.")
    parser.add_argument("--dump-flash", metavar="OUTPUT",
                        help="Read-only: back up the memory-mapped SPI flash (0x200000..0x400000) to OUTPUT "
                             "via fc61 block reads, with a sha256 at the end.")
    parser.add_argument("--flash-read", nargs=2, metavar=("OFFSET", "LEN"),
                        help="Debug: send the fc29 flash-read vendor command for LEN bytes at flash OFFSET and "
                             "print the raw HCI response (read-only).")
    parser.add_argument("--capture-usb-ram", metavar="OUTPUT",
                        help="Save live USB descriptors and a RAM dump under OUTPUT, then search descriptor structures")
    parser.add_argument("--capture-range", nargs=2, metavar=("START", "WORDS"),
                        help="Optional range for --capture-usb-ram, within 0x00001000..0x0009efff or 0x00210000..0x0021ffff")
    parser.add_argument("--inspect-stock", action="store_true", help="Inspect the ROM-1 stock payload without opening USB")
    args = parser.parse_args(argv)
    if args.capture_usb_ram:
        if (args.load_stock or args.load_custom or args.probe_memory or args.read_range or args.map_memory
                or args.find_descriptor is not None or args.find_patch
                or args.write_test is not None or args.inspect_stock):
            parser.error("--capture-usb-ram runs alone; use a separate command for other probe modes")
        from descriptor_capture import validate_range
        try:
            args.capture_range = validate_range(*(int(value, 0) for value in (args.capture_range or ("0x00210000", "16384"))))
        except ValueError as error:
            parser.error(str(error))
    elif args.capture_range:
        parser.error("--capture-range requires --capture-usb-ram")
    if args.find_patch:
        try:
            start, words = (int(value, 0) for value in args.find_patch)
        except ValueError as error:
            parser.error(str(error))
        if start % 4 or not 1 <= words <= 0x40000:
            parser.error("Use a four-byte-aligned START and 1..262144 WORDS")
        args.find_patch = (start, words)
    if args.read_range:
        try:
            args.read_range = validate_memory_range(*(int(value, 0) for value in args.read_range))
        except ValueError as error:
            parser.error(str(error))
    if args.poke:
        try:
            poke_addr = validate_write_address(int(args.poke[0], 0))
            poke_value = int(args.poke[1], 0)
            if not 0 <= poke_value <= 0xFFFFFFFF:
                raise ValueError("VALUE must be a 32-bit integer")
        except ValueError as error:
            parser.error(str(error))
        args.poke = (poke_addr, poke_value)
    if args.find_descriptor is not None:
        if len(args.find_descriptor) == 0:
            args.find_descriptor = (0x00210000, 16384)
        elif len(args.find_descriptor) == 2:
            try:
                start, words = (int(value, 0) for value in args.find_descriptor)
            except ValueError as error:
                parser.error(str(error))
            if start % 4 or not 1 <= words <= 0x40000:
                parser.error("Use a four-byte-aligned START and 1..262144 WORDS")
            args.find_descriptor = (start, words)
        else:
            parser.error("--find-descriptor takes no arguments or START WORDS")
    if args.inspect_stock:
        version, chip_id, payload = stock_payload(1)
        fragments = list(download_fragments(payload))
        print(f"Stock version: 0x{version:08x}; chip ID: {chip_id}; payload: {len(payload)} bytes")
        print("Download fragments:", [(hex(p[0]), len(p) - 1) for p in fragments])
        return 0
    print("ASUS USB-BT600 diagnostic (USB 0b05:1d70)", flush=True)
    candidates = [
        "/opt/homebrew/lib/libusb-1.0.dylib",
        "/usr/local/lib/libusb-1.0.dylib",
        ctypes.util.find_library("usb-1.0"),
    ]
    library = next((p for p in candidates if p and Path(p).is_file()), None)
    if not library:
        print("The libusb library could not be found.")
        return 1
    usb = C.CDLL(library)

    signatures = {
        "libusb_init": ([C.POINTER(P)], C.c_int),
        "libusb_exit": ([P], None),
        "libusb_get_device_list": ([P, C.POINTER(C.POINTER(P))], C.c_ssize_t),
        "libusb_free_device_list": ([C.POINTER(P), C.c_int], None),
        "libusb_get_device_descriptor": ([P, C.POINTER(DeviceDescriptor)], C.c_int),
        "libusb_open": ([P, C.POINTER(P)], C.c_int),
        "libusb_close": ([P], None),
        "libusb_error_name": ([C.c_int], C.c_char_p),
        "libusb_get_configuration": ([P, C.POINTER(C.c_int)], C.c_int),
        "libusb_set_configuration": ([P, C.c_int], C.c_int),
        "libusb_claim_interface": ([P, C.c_int], C.c_int),
        "libusb_release_interface": ([P, C.c_int], C.c_int),
        "libusb_control_transfer": (
            [P, C.c_uint8, C.c_uint8, C.c_uint16, C.c_uint16, P, C.c_uint16, C.c_uint],
            C.c_int,
        ),
        "libusb_interrupt_transfer": (
            [P, C.c_uint8, P, C.c_int, C.POINTER(C.c_int), C.c_uint], C.c_int,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(usb, name)
        function.argtypes, function.restype = arguments, result

    def checked(code, operation):
        if code < 0:
            label = usb.libusb_error_name(code).decode()
            raise RuntimeError(f"{operation}: {label} ({code})")
        return code

    ctx, handle = P(), P()
    devices = C.POINTER(P)()
    count = -1
    claimed = changed_configuration = keep_configuration = False
    checked(usb.libusb_init(C.byref(ctx)), "Initialize USB")
    try:
        count = checked(usb.libusb_get_device_list(ctx, C.byref(devices)), "List USB devices")
        found = False
        for index in range(count):
            desc = DeviceDescriptor()
            if usb.libusb_get_device_descriptor(devices[index], C.byref(desc)) != 0:
                continue
            if (desc.vid, desc.pid) != (VID, PID):
                continue
            found = True
            print(f"Device class: {desc.device_class:02x}/{desc.subclass:02x}/{desc.protocol:02x}")
            print(f"USB device revision: {desc.revision:04x}")
            checked(usb.libusb_open(devices[index], C.byref(handle)), "Open ASUS dongle")
            break
        if not found:
            if count == 0:
                print("USB access returned zero devices. Run this from the macOS Terminal app.")
            else:
                print("The ASUS dongle was not found. Check that it is plugged in.")
            return 2

        configuration = C.c_int()
        checked(usb.libusb_get_configuration(handle, C.byref(configuration)), "Read USB configuration")
        print("Original USB configuration:", configuration.value)
        if configuration.value == 0:
            checked(usb.libusb_set_configuration(handle, 1), "Select USB configuration 1")
            changed_configuration = True
        checked(usb.libusb_claim_interface(handle, 0), "Open Bluetooth command interface")
        claimed = True

        events = HCIEvents()

        def command(opcode, parameters=b"", quiet=False):
            if len(parameters) > 255:
                raise RuntimeError("HCI command parameters exceed 255 bytes")
            payload = struct.pack("<HB", opcode, len(parameters)) + parameters
            outgoing = C.create_string_buffer(payload)
            sent = checked(
                usb.libusb_control_transfer(handle, 0x20, 0, 0, 0, outgoing, len(payload), 2000),
                f"Send query {opcode:04x}",
            )
            if sent != len(payload):
                raise RuntimeError(f"Short command transfer: {sent}/{len(payload)}")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                incoming = C.create_string_buffer(64)
                actual = C.c_int()
                remaining_ms = max(1, min(2000, int((deadline - time.monotonic()) * 1000)))
                checked(
                    usb.libusb_interrupt_transfer(handle, 0x81, incoming, 64, C.byref(actual), remaining_ms),
                    f"Read query response {opcode:04x}",
                )
                matching = None
                for event in events.feed(incoming.raw[:actual.value]):
                    result = command_result(event, opcode)
                    if result is not None:
                        matching = result
                if matching is not None:
                    if not quiet:
                        print(f"HCI {opcode:04x} response:", matching.hex(" "))
                    return matching
            raise RuntimeError(f"No matching response for query {opcode:04x}")

        version = command(0x1001)
        if len(version) < 9 or version[0] != 0:
            raise RuntimeError("Controller did not return a successful local-version response")
        status, hci_version, hci_revision, lmp_version, maker, lmp_subversion = struct.unpack_from("<BBHBHH", version)
        print(f"HCI version: 0x{hci_version:02x}; revision: 0x{hci_revision:04x}")
        print(f"LMP version: 0x{lmp_version:02x}; subversion: 0x{lmp_subversion:04x}")
        print(f"Controller manufacturer: 0x{maker:04x}")
        rom = command(0xFC6D)
        if len(rom) >= 2 and rom[0] == 0:
            print(f"Realtek ROM version: {rom[1]} (patch chip ID {rom[1] + 1})")
        else:
            print("The ROM-version query was not accepted; the local-version result above is still useful.")
        if args.capture_usb_ram:
            if maker != 0x005D or hci_version != 0x0E or len(rom) != 2 or rom != b"\x00\x01":
                raise RuntimeError("The controller does not match this ROM-1 BT600 capture")

            def get_descriptor(kind, index, length):
                buffer = C.create_string_buffer(length)
                actual = checked(usb.libusb_control_transfer(
                    handle, 0x80, 0x06, (kind << 8) | index, 0, buffer, length, 2000,
                ), f"Read live USB descriptor {kind}:{index}")
                return buffer.raw[:actual]

            from descriptor_capture import capture
            capture(lambda address: read_memory_word(command, address, quiet=True),
                    get_descriptor, args.capture_usb_ram, *args.capture_range,
                    metadata={"local_version_hex": version.hex(" "), "rom_version_hex": rom.hex(" "),
                              "original_usb_configuration": configuration.value})
        if args.load_stock:
            if len(rom) < 2 or rom[0] != 0:
                raise RuntimeError("No ROM version returned; no firmware was sent")
            expected_version, chip_id, payload = stock_payload(rom[1])
            current_version = (hci_revision << 16) | lmp_subversion
            if maker != 0x005D or hci_version != 0x0E:
                raise RuntimeError("The controller does not match this RTL8761C experiment")
            if current_version == expected_version:
                print(f"Stock patch 0x{expected_version:08x} is already running.")
            else:
                if (hci_revision, lmp_subversion) != (0x000E, 0x8761):
                    raise RuntimeError("Controller has another patch loaded. Unplug/replug it, then rerun.")
                print(f"Uploading stock patch: chip ID {chip_id}, {len(payload)} bytes, version 0x{expected_version:08x}", flush=True)
                for fragment in download_fragments(payload):
                    response = command(0xFC20, fragment)
                    require_download_ack(response, fragment[0])
                after = command(0x1001)
                require_stock_version(after, current_version)
                print("Patch launched: the running firmware version changed after download.")
            keep_configuration = True
        if args.load_custom:
            if len(rom) < 2 or rom[0] != 0:
                raise RuntimeError("No ROM version returned; no firmware was sent")
            if maker != 0x005D or hci_version != 0x0E:
                raise RuntimeError("The controller does not match this RTL8761C experiment")
            if (hci_revision, lmp_subversion) != (0x000E, 0x8761):
                raise RuntimeError("Controller has another patch loaded. Unplug/replug it, then rerun.")
            marker_addr, marker_value = CUSTOM_MARKER_ADDR, CUSTOM_MARKER_VALUE
            expected_version, chip_id, payload = custom_marker_payload(rom[1], marker_addr, marker_value)
            current_version = (hci_revision << 16) | lmp_subversion
            print(f"Uploading CUSTOM patch (stock + marker hook): chip ID {chip_id}, {len(payload)} bytes. "
                  f"It writes 0x{marker_value:08x} to 0x{marker_addr:08x} at launch. "
                  "RAM-only; a replug fully reverts it.", flush=True)
            for fragment in download_fragments(payload):
                response = command(0xFC20, fragment)
                require_download_ack(response, fragment[0])
            after = command(0x1001)
            require_stock_version(after, current_version)
            print("Custom patch launched: the running firmware version changed after download.")
            data = read_memory_word(command, marker_addr, quiet=True)
            got = struct.unpack("<I", data)[0]
            if got == marker_value:
                print(f"  MARKER VERIFIED: read 0x{got:08x} at 0x{marker_addr:08x} -> "
                      "our custom code executed on the controller.")
            else:
                print(f"  marker not found: read 0x{got:08x} (expected 0x{marker_value:08x}). "
                      "The custom code may not have run, or that RAM was reused after launch.")
            keep_configuration = True
        if args.map_memory:
            map_start, map_end, map_step = 0x00000000, 0x00400000, 0x1000
            print(f"Mapping 0x{map_start:08x}..0x{map_end:08x}, one word per 0x{map_step:x}, read-only", flush=True)
            samples = []
            for address in range(map_start, map_end, map_step):
                try:
                    data = read_memory_word(command, address, quiet=True)
                except RuntimeError as error:
                    print(f"Stopped at 0x{address:08x}: {error}")
                    samples.append((address, "fault"))
                    break
                samples.append((address, "zero" if data == b"\x00\x00\x00\x00" else "data"))
            print("Readable regions (one word per page):")
            for region_start, region_last, kind in coalesce_runs(samples):
                print(f"  0x{region_start:08x}..0x{region_last:08x}  {kind}")
        if args.read_range:
            if len(rom) < 2 or rom[0] != 0:
                raise RuntimeError("No ROM version returned; no memory range was read")
            start, words = args.read_range
            print(f"Reading {words} four-byte words from 0x{start:08x}", flush=True)
            blob = read_memory_range(command, start, words)
            prologue = stock_payload(rom[1])[2][:16]
            candidate = find_patch_base(blob, start, prologue)
            if candidate is not None:
                print(f"Stock patch bytes found at 0x{candidate:08x}; candidate load base (execution address still needs confirmation)")
            elif not any(blob):
                print("The requested range returned only zeroes.")
            else:
                print("Stock patch prologue was not found in this range.")
        if args.find_descriptor is not None:
            if len(rom) < 2 or rom[0] != 0:
                raise RuntimeError("No ROM version returned; no scan was run")
            scan_start, scan_words = args.find_descriptor
            variants = " ".join(v.hex() for v in USB_SIGNATURE_VARIANTS)
            print(f"Scanning {scan_words} words from 0x{scan_start:08x} for USB signature "
                  f"(any byte order: {variants}), read-only", flush=True)
            blob = bytearray()
            for address in range(scan_start, scan_start + scan_words * 4, 4):
                try:
                    blob.extend(read_memory_word(command, address, quiet=True))
                except RuntimeError as error:
                    print(f"Stopped at 0x{address:08x}: {error}")
                    break
                if len(blob) % 0x2000 == 0:
                    print(f"  ...scanned through 0x{address:08x}", flush=True)
            hit = None
            for variant in USB_SIGNATURE_VARIANTS:
                candidate = find_patch_base(blob, scan_start, variant)
                if candidate is not None:
                    hit = (candidate, variant)
                    break
            if hit is not None:
                address, variant = hit
                window_start = max(0, (address - scan_start) - 8)
                window = bytes(blob)[window_start:window_start + 32]
                print(f"USB vendor/product bytes {variant.hex(' ')} found at 0x{address:08x}")
                print(f"  context 0x{scan_start + window_start:08x}: {window.hex(' ')}")
                print("  If this sits in writable RAM, the dongle's USB identity can likely be changed.")
            else:
                scanned_end = scan_start + len(blob)
                print(f"No byte order of the signature found in 0x{scan_start:08x}..0x{scanned_end:08x}; "
                      "the identity is likely in config/efuse this read path cannot reach.")
        if args.find_patch:
            if len(rom) < 2 or rom[0] != 0:
                raise RuntimeError("No ROM version returned; no scan was run")
            needle = stock_payload(rom[1])[2][:16]
            patch_start, patch_words = args.find_patch
            print(f"Scanning {patch_words} words from 0x{patch_start:08x} for the resident patch prologue "
                  f"{needle.hex(' ')}, read-only", flush=True)
            blob = bytearray()
            for address in range(patch_start, patch_start + patch_words * 4, 4):
                try:
                    blob.extend(read_memory_word(command, address, quiet=True))
                except RuntimeError as error:
                    print(f"Stopped at 0x{address:08x}: {error}")
                    break
                if len(blob) % 0x2000 == 0:
                    print(f"  ...scanned through 0x{address:08x}", flush=True)
            base = find_patch_base(blob, patch_start, needle)
            if base is not None:
                print(f"Patch prologue found: controller load base = 0x{base:08x}")
            else:
                print(f"Patch prologue not in 0x{patch_start:08x}..0x{patch_start + len(blob):08x}; "
                      "widen or move the window (and confirm the patch is still resident).")
        if args.write_test is not None:
            if len(rom) < 2 or rom[0] != 0 or maker != 0x005D:
                raise RuntimeError("Controller does not match this experiment; no write attempted")
            write_address = int(args.write_test, 0)
            if write_address % 4:
                raise RuntimeError("Write address must be four-byte aligned")
            original = read_memory_word(command, write_address, quiet=True)
            flipped = bytes(b ^ 0xFF for b in original)
            print(f"Write test at 0x{write_address:08x}: read {original.hex(' ')}, writing {flipped.hex(' ')}", flush=True)
            write_memory_word(command, write_address, flipped)
            try:
                after = read_memory_word(command, write_address, quiet=True)
                took = after == flipped
                print(f"  read back: {after.hex(' ')}  ->  "
                      f"{'WRITE WORKS' if took else 'unchanged (read-only region or write ignored)'}")
            finally:
                write_memory_word(command, write_address, original)
                restored = read_memory_word(command, write_address, quiet=True)
                print(f"  restored:  {restored.hex(' ')}  ->  "
                      f"{'ok' if restored == original else 'RESTORE FAILED, replug the dongle'}")
        if args.flash_read is not None:
            off = int(args.flash_read[0], 0)
            length = int(args.flash_read[1], 0)
            params = struct.pack("<II", off, length)
            print(f"fc29 flash-read: offset 0x{off:08x}, len {length}; params {params.hex(' ')}", flush=True)
            try:
                cc = command(0xFC29, params, quiet=True)
                print(f"  Command Complete payload: {cc.hex(' ')}")
            except RuntimeError as err:
                print(f"  fc29 command error: {err}")
            # Capture any follow-up async events carrying the data.
            for _ in range(8):
                incoming = C.create_string_buffer(64)
                actual = C.c_int()
                rc = usb.libusb_interrupt_transfer(handle, 0x81, incoming, 64, C.byref(actual), 500)
                if rc != 0 or actual.value == 0:
                    break
                print(f"  event: {incoming.raw[:actual.value].hex(' ')}")
        if args.dump_flash is not None:
            if len(rom) < 2 or rom[0] != 0:
                raise RuntimeError("No ROM version returned; no flash read")
            flash_start, flash_end = 0x00200000, 0x00400000

            def read_word_retry(addr, tries=6):
                last = None
                for attempt in range(tries):
                    try:
                        return read_memory_word(command, addr, quiet=True)
                    except RuntimeError as err:
                        last = err
                        time.sleep(0.02 * (attempt + 1))
                raise RuntimeError(f"read at 0x{addr:08x} failed after {tries} tries: {last}")

            # fc61 returns one 32-bit word per command (the 0x20 access byte is a
            # fixed width qualifier, not a length). So the dump is word-by-word.
            # Resumable: a long fc61 run can make the controller drop off USB and
            # re-enumerate, so an existing partial file is continued, not
            # restarted. Run the command again (fresh enumeration) to resume.
            import os as _os, hashlib as _h
            resume = 0
            if _os.path.exists(args.dump_flash):
                resume = _os.path.getsize(args.dump_flash) & ~3
            mode = "r+b" if resume else "wb"
            print(f"Dumping flash 0x{flash_start:08x}..0x{flash_end:08x} word-by-word "
                  f"to {args.dump_flash} (resume at +0x{resume:x})", flush=True)
            digest = _h.sha256()
            t0 = time.monotonic()
            gaps_path = args.dump_flash + ".gaps"
            with open(args.dump_flash, mode) as out:
                out.seek(resume)
                address = flash_start + resume
                while address < flash_end:
                    try:
                        data = read_word_retry(address, tries=3)
                    except RuntimeError as err:
                        # Faulting addresses (unmapped holes, e.g. 0x225000) drop
                        # the device off USB. Skip the REST of this 4 KiB page with
                        # a gap marker so a large hole costs one rerun per page, not
                        # per word, then stop so a fresh enumeration resumes.
                        page_end = (address & ~0xFFF) + 0x1000
                        fill = page_end - address
                        out.write(b"\xff" * fill)
                        out.flush()
                        with open(gaps_path, "a") as g:
                            g.write(f"0x{address:08x}..0x{page_end:08x} {err}\n")
                        print(f"  gap 0x{address:08x}..0x{page_end:08x} ({fill} B): {err}; "
                              f"rerun resumes at 0x{page_end:08x}", flush=True)
                        break
                    out.write(data)
                    digest.update(data)
                    address += 4
                    done = address - flash_start
                    if done % 0x10000 == 0:
                        rate = (done - resume) / max(1e-6, time.monotonic() - t0)
                        eta = (flash_end - address) / max(1.0, rate)
                        print(f"  ...0x{address:08x} ({done // 1024} KiB, {rate / 1024:.1f} KiB/s, "
                              f"ETA {eta / 60:.1f} min)", flush=True)
            size = _os.path.getsize(args.dump_flash)
            whole = _h.sha256(open(args.dump_flash, "rb").read()).hexdigest()
            if size >= flash_end - flash_start:
                print(f"Flash backup complete: {size} bytes, sha256 {whole}")
            else:
                print(f"Flash backup PARTIAL: {size}/{flash_end - flash_start} bytes so far "
                      f"(resume by rerunning); sha256-so-far {whole}")
        if args.poke is not None:
            if len(rom) < 2 or rom[0] != 0 or maker != 0x005D:
                raise RuntimeError("Controller does not match this experiment; no write attempted")
            poke_addr, poke_value = args.poke
            before = read_memory_word(command, poke_addr, quiet=True)
            data = struct.pack("<I", poke_value)
            print(f"Persistent poke at 0x{poke_addr:08x}: was {before.hex(' ')}, writing {data.hex(' ')} "
                  "(NOT restored)", flush=True)
            write_memory_word(command, poke_addr, data)
            after = read_memory_word(command, poke_addr, quiet=True)
            print(f"  read back: {after.hex(' ')}  ->  "
                  f"{'written' if after == data else 'write ignored (read-only or latched)'}")
            print("  value left in place; replug to power-cycle, or re-read to check persistence.")
        if args.probe_memory:
            for address, label in MEMORY_PROBE_ADDRESSES:
                print(f"Trying four-byte memory read at 0x{address:08x} ({label})", flush=True)
                data = read_memory_word(command, address)
                print(f"Memory 0x{address:08x}: {data.hex(' ')}")
        print("Diagnostic complete.")
        return 0
    except RuntimeError as error:
        print("Diagnostic stopped:", error)
        print("Paste the output back into our chat.")
        return 3
    finally:
        if handle:
            if claimed:
                usb.libusb_release_interface(handle, 0)
            if changed_configuration and not keep_configuration:
                result = usb.libusb_set_configuration(handle, -1)
                if result < 0:
                    print("The original unconfigured state could not be restored. Unplug and replug the dongle.")
            usb.libusb_close(handle)
        if count >= 0:
            usb.libusb_free_device_list(devices, 1)
        usb.libusb_exit(ctx)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDiagnostic interrupted.")
        sys.exit(130)
