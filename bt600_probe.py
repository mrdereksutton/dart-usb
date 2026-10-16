#!/usr/bin/env python3
"""Query an ASUS USB-BT600 from macOS Terminal: python3 bt600_probe.py.

Uses the existing Homebrew libusb installation. Queries USB descriptors,
HCI Read Local Version Information (0x1001), and Realtek Read ROM Version
(0xFC6D). Default mode does not download firmware. --load-stock sends the
stock linux-firmware RTL8761CU driver patch for the detected ROM revision.
--probe-memory additionally queries two boot-vector words and two patch literals.
Neither mode resets the controller or detaches a kernel driver.
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

# The B-family command reads four bytes at a time. Query both candidate
# boot-vector words separately; reading only address zero cannot yield the
# reset vector. Absolute zero is a candidate boot mapping, not a VTOR read.
MEMORY_READ_OPCODE = 0xFC61
MEMORY_READ_ACCESS = 0x20
MEMORY_PROBE_ADDRESSES = (
    (0x00000000, "candidate boot initial stack pointer"),
    (0x00000004, "candidate boot reset vector"),
    (0x00217E88, "patch data-table literal"),
    (0x0880A0A8, "patch flash/peripheral-window literal"),
)

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


def require_stock_version(response, expected):
    if len(response) != 9 or response[0] != 0:
        raise RuntimeError("No successful version response after upload")
    _, _, revision, _, maker, subversion = struct.unpack("<BBHBHH", response)
    observed = (revision << 16) | subversion
    print(f"Version after upload: 0x{observed:08x}; expected: 0x{expected:08x}")
    if maker != 0x005D or observed != expected:
        raise RuntimeError("Download was acknowledged but the expected stock patch is not running")


def require_download_ack(response, index):
    if len(response) != 2 or response[0] != 0:
        raise RuntimeError(f"Download fragment {index:02x} was rejected: {response.hex()}")
    # Controllers may echo the final marker or only the seven-bit index.
    if response[1] & 0x7F != index & 0x7F:
        raise RuntimeError(f"Download fragment {index:02x} got an acknowledgement for {response[1]:02x}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load-stock", action="store_true", help="Upload the matching stock RTL8761CU driver patch")
    parser.add_argument("--probe-memory", action="store_true", help="Query both candidate boot-vector words and two patch literals")
    parser.add_argument("--inspect-stock", action="store_true", help="Inspect the ROM-1 stock payload without opening USB")
    args = parser.parse_args()
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

        def command(opcode, parameters=b""):
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
                require_stock_version(after, expected_version)
                print("Stock patch is running.")
            keep_configuration = True
        if args.probe_memory:
            words = {}
            for address, label in MEMORY_PROBE_ADDRESSES:
                print(f"Trying four-byte memory read at 0x{address:08x} ({label})", flush=True)
                result = command(MEMORY_READ_OPCODE, struct.pack("<BI", MEMORY_READ_ACCESS, address))
                if len(result) == 5 and result[0] == 0:
                    words[address] = result[1:]
                    print(f"Memory 0x{address:08x}: {result[1:].hex(' ')}")
                elif result and result[0] == 0:
                    raise RuntimeError(f"Memory read returned {len(result) - 1} data bytes; expected four")
                else:
                    status = f"0x{result[0]:02x}" if result else "empty response"
                    print(f"Memory-read command returned {status}.")
                    if result and result[0] == 1:
                        break
            if 0 in words:
                sp, reset = parse_vector_table(words[0] + words.get(4, b""))
                print(f"Candidate initial stack pointer: 0x{sp:08x}")
                if reset is not None:
                    print(f"Candidate reset handler: 0x{reset & ~1:08x}; Thumb bit: {reset & 1}")
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
