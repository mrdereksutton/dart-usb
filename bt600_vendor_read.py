#!/usr/bin/env python3
"""Read BT600 identity, or inspect firmware-derived USB descriptor targets.

Run from macOS Terminal with python3. Uses the existing Homebrew libusb.
No firmware download, controller reset, kernel-driver detachment, or persistent
write commands are issued. USB configuration 1 is temporarily selected only
when the device is initially unconfigured, then the original state is restored.

--descriptor-targets reads two addresses derived from ASUS's ROM-1 image and
conditionally follows its descriptor pointer. It saves JSON under results/.
These are candidate locations for the installed firmware; no firmware update
or memory write is involved.
"""

import argparse
import ctypes as C
import ctypes.util
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import struct
import time


VID, PID = 0x0B05, 0x1D70
PTR = C.c_void_p
QUERIES = (
    ("local_version", 0x1001, b""),
    ("rom_version", 0xFC6D, b""),
    # rtk_misc.c: rtk_vendor_read(..., READ_SEC_PROJ).
    # First byte is the vendor's 16-bit-read selector; remaining bytes are
    # the little-endian register address 0xb000ada4.
    ("asus_security_register", 0xFC61, bytes.fromhex("10 a4 ad 00 b0")),
)

# ASUS DR_USB-BT600_v3.1.07_Linux.zip, SHA-256:
# 33eae0a21fd2153c5962cb3b4cc0fd7508924f0a929f262370ec22c81ada2ce8
# https://dlcdnets.asus.com/pub/ASUS/wireless/USB-BT600/DR_USB-BT600_v3.1.07_Linux.zip
# rtl8761cu_mx_fw selects ECO 2 (ROM 1). Its 537762-byte snippet contains
# seven images. Image 0x2793 starts at snippet offset 0x0f86, with a 1024-byte
# header and execute/load base 0x02167400 for the bytes at offset 0x1386.
# At 0x02177664, STR R0,[R1,#0x0c] stores the allocated 18-byte descriptor;
# the literal loaded into R1 at 0x02177662 is 0x002c10a8.
# At 0x021776ac..0x021776b2, VID/PID come from [0x002808a8+0x10/+0x12].
DESCRIPTOR_POINTER_ADDRESS = 0x002C10B4
USB_ID_CONFIG_ADDRESS = 0x002808B8


def validate_query(name, reply):
    expected = {"local_version": 9, "rom_version": 2, "asus_security_register": 3}
    if len(reply) != expected[name] or reply[0] != 0:
        raise RuntimeError(f"Rejected or malformed {name}: {reply.hex(' ')}")


def compare_descriptor(report, standard):
    """Compare the candidate with an actual EP0 GET_DESCRIPTOR response."""
    if len(standard) != 18 or standard[:2] != b"\x12\x01":
        raise RuntimeError("Malformed standard USB device descriptor")
    report["standard_device_descriptor"] = standard.hex(" ")
    if "descriptor" in report:
        candidate = bytes.fromhex(report["descriptor"]["raw"])
        report["matches_standard_descriptor"] = candidate == standard
        report["differing_byte_offsets"] = [
            i for i, (a, b) in enumerate(zip(candidate, standard)) if a != b
        ]


def memory_data(reply, address):
    """Require the complete status + four-byte response used by this chip."""
    if len(reply) != 5 or reply[0] != 0:
        raise RuntimeError(f"Rejected or malformed read at 0x{address:08x}: {reply.hex(' ')}")
    return reply[1:]


def inspect_descriptor_targets(read_word, report):
    """Follow one bounded firmware-derived pointer using an injected reader."""
    report.update(pointer_location=f"0x{DESCRIPTOR_POINTER_ADDRESS:08x}",
                  identity_config_location=f"0x{USB_ID_CONFIG_ADDRESS:08x}")
    pointer = int.from_bytes(read_word(DESCRIPTOR_POINTER_ADDRESS), "little")
    report["descriptor_pointer"] = f"0x{pointer:08x}"
    # This bound covers the C-image's RAM references. It is a plausibility
    # check on one pointer, not a claim that every address in it is readable.
    if not pointer:
        report["pointer_result"] = "null; this image's pointer is not populated"
    elif pointer & 3 or not 0x00200000 <= pointer <= 0x002FFFE8:
        report["pointer_result"] = "outside aligned candidate RAM; not followed"
    else:
        first = read_word(pointer)
        if first[:2] != b"\x12\x01":
            report["pointer_result"] = "target does not begin with a USB device descriptor"
        else:
            raw = first + b"".join(read_word(pointer + offset) for offset in (4, 8, 12, 16))
            descriptor = raw[:18]
            report["pointer_result"] = "USB device descriptor found"
            report["descriptor"] = {
                "raw": descriptor.hex(" "),
                "usb_version": f"0x{int.from_bytes(descriptor[2:4], 'little'):04x}",
                "device_class": f"{descriptor[4]:02x}/{descriptor[5]:02x}/{descriptor[6]:02x}",
                "ep0_max_packet": descriptor[7],
                "usb_id": f"{int.from_bytes(descriptor[8:10], 'little'):04x}:{int.from_bytes(descriptor[10:12], 'little'):04x}",
                "device_revision": f"0x{int.from_bytes(descriptor[12:14], 'little'):04x}",
                "configurations": descriptor[17],
            }
    ids = read_word(USB_ID_CONFIG_ADDRESS)
    report["config_usb_id"] = f"{int.from_bytes(ids[:2], 'little'):04x}:{int.from_bytes(ids[2:], 'little'):04x}"
    report["config_matches_adapter"] = ids == bytes.fromhex("05 0b 70 1d")


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true",
                        help="Print planned packets without accessing USB")
    parser.add_argument("--descriptor-targets", action="store_true",
                        help="Read the ASUS image's descriptor pointer and USB-ID config, then save the result")
    args = parser.parse_args()
    if args.describe:
        for name, opcode, params in QUERIES:
            print(f"{name}: {(struct.pack('<HB', opcode, len(params)) + params).hex(' ')}")
        if args.descriptor_targets:
            for address in (DESCRIPTOR_POINTER_ADDRESS, USB_ID_CONFIG_ADDRESS):
                print(f"Memory 0x{address:08x}: {(struct.pack('<HB', 0xfc61, 5) + struct.pack('<BI', 0x20, address)).hex(' ')}")
            print("Follow a plausible RAM pointer only if its first word starts with 12 01; at most five descriptor words.")
        return 0

    candidates = ["/opt/homebrew/lib/libusb-1.0.dylib",
                  "/usr/local/lib/libusb-1.0.dylib",
                  ctypes.util.find_library("usb-1.0")]
    library = next((p for p in candidates if p and Path(p).is_file()), None)
    if not library:
        print("Homebrew libusb was not found.", flush=True)
        return 1
    usb = C.CDLL(library)
    signatures = {
        "libusb_init": ([C.POINTER(PTR)], C.c_int),
        "libusb_exit": ([PTR], None),
        "libusb_get_device_list": ([PTR, C.POINTER(C.POINTER(PTR))], C.c_ssize_t),
        "libusb_free_device_list": ([C.POINTER(PTR), C.c_int], None),
        "libusb_get_device_descriptor": ([PTR, C.POINTER(DeviceDescriptor)], C.c_int),
        "libusb_open": ([PTR, C.POINTER(PTR)], C.c_int),
        "libusb_close": ([PTR], None),
        "libusb_get_configuration": ([PTR, C.POINTER(C.c_int)], C.c_int),
        "libusb_set_configuration": ([PTR, C.c_int], C.c_int),
        "libusb_claim_interface": ([PTR, C.c_int], C.c_int),
        "libusb_release_interface": ([PTR, C.c_int], C.c_int),
        "libusb_error_name": ([C.c_int], C.c_char_p),
        "libusb_control_transfer": ([PTR, C.c_uint8, C.c_uint8, C.c_uint16,
                                     C.c_uint16, PTR, C.c_uint16, C.c_uint], C.c_int),
        "libusb_interrupt_transfer": ([PTR, C.c_uint8, PTR, C.c_int,
                                       C.POINTER(C.c_int), C.c_uint], C.c_int),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(usb, name)
        function.argtypes, function.restype = argtypes, restype

    def checked(code, operation):
        if code < 0:
            raise RuntimeError(f"{operation}: {usb.libusb_error_name(code).decode()} ({code})")
        return code

    context, handle = PTR(), PTR()
    devices = C.POINTER(PTR)()
    claimed = changed_configuration = False
    initialized = False
    failed = False
    result = {"usb_id": "0b05:1d70", "queries": {},
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "descriptor_targets_requested": args.descriptor_targets,
              "started_utc": datetime.now(timezone.utc).isoformat()}
    try:
        checked(usb.libusb_init(C.byref(context)), "Initialize libusb")
        initialized = True
        count = checked(usb.libusb_get_device_list(context, C.byref(devices)), "List USB devices")
        matches = []
        for index in range(count):
            descriptor = DeviceDescriptor()
            if usb.libusb_get_device_descriptor(devices[index], C.byref(descriptor)) == 0:
                if (descriptor.vid, descriptor.pid) == (VID, PID):
                    matches.append((devices[index], descriptor))
        if count == 0:
            raise RuntimeError("libusb returned zero USB devices. Run this from macOS Terminal; the app sandbox can hide USB devices.")
        if len(matches) != 1:
            raise RuntimeError(f"Expected one BT600; found {len(matches)}. Keep one adapter connected.")
        device, descriptor = matches[0]
        result["device_class"] = f"{descriptor.device_class:02x}/{descriptor.subclass:02x}/{descriptor.protocol:02x}"
        checked(usb.libusb_open(device, C.byref(handle)), "Open ASUS BT600")
        configuration = C.c_int()
        checked(usb.libusb_get_configuration(handle, C.byref(configuration)), "Read USB configuration")
        result["original_configuration"] = configuration.value
        if configuration.value == 0:
            checked(usb.libusb_set_configuration(handle, 1), "Select configuration 1")
            changed_configuration = True
        elif configuration.value != 1:
            raise RuntimeError(f"Unexpected configuration {configuration.value}")
        checked(usb.libusb_claim_interface(handle, 0), "Claim Bluetooth HCI interface")
        claimed = True

        def hci(opcode, parameters):
            packet = struct.pack("<HB", opcode, len(parameters)) + parameters
            tx = C.create_string_buffer(packet)
            written = checked(usb.libusb_control_transfer(handle, 0x20, 0, 0, 0,
                                                         tx, len(packet), 2000), "Send HCI query")
            if written != len(packet):
                raise RuntimeError("Short HCI command transfer")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                rx = C.create_string_buffer(260)
                transferred = C.c_int()
                remaining = max(1, int((deadline - time.monotonic()) * 1000))
                code = usb.libusb_interrupt_transfer(handle, 0x81, rx, len(rx),
                                                     C.byref(transferred), min(remaining, 1000))
                checked(code, "Read HCI event")
                event = rx.raw[:transferred.value]
                if len(event) < 2 or len(event) != event[1] + 2:
                    raise RuntimeError(f"Malformed HCI event: {event.hex(' ')}")
                if event[0] == 0x0E and len(event) >= 6:
                    returned_opcode = struct.unpack_from("<H", event, 3)[0]
                    if returned_opcode == opcode:
                        return event[5:]
                if event[0] == 0x0F and len(event) >= 6:
                    returned_opcode = struct.unpack_from("<H", event, 4)[0]
                    if returned_opcode == opcode and event[2]:
                        return bytes((event[2],))
            raise RuntimeError(f"No reply to HCI 0x{opcode:04x}")

        for name, opcode, parameters in QUERIES:
            print(f"Reading {name} (0x{opcode:04x})...", flush=True)
            reply = hci(opcode, parameters)
            entry = {"opcode": f"0x{opcode:04x}", "reply": reply.hex(" "),
                     "status": reply[0] if reply else None}
            if name == "local_version" and len(reply) == 9 and reply[0] == 0:
                status, hv, hr, lv, manufacturer, subversion = struct.unpack("<BBHBHH", reply)
                entry.update(hci_version=hv, hci_revision=hr, lmp_version=lv,
                             manufacturer=manufacturer, lmp_subversion=f"0x{subversion:04x}")
            elif name == "rom_version" and len(reply) >= 2 and reply[0] == 0:
                entry.update(rom_version=reply[1], patch_chip_id=reply[1] + 1)
            result["queries"][name] = entry
            print(f"  {reply.hex(' ')}", flush=True)
            validate_query(name, reply)
        if args.descriptor_targets:
            if result["queries"]["rom_version"]["rom_version"] != 1:
                raise RuntimeError("Descriptor targets are derived only for ROM 1 / ECO 2")
            target_report = {"reads": []}
            result["descriptor_targets"] = target_report
            standard_buffer = C.create_string_buffer(18)
            size = checked(usb.libusb_control_transfer(
                handle, 0x80, 6, 0x0100, 0, standard_buffer, 18, 2000),
                "GET_DESCRIPTOR device")
            standard = standard_buffer.raw[:size]
            compare_descriptor(target_report, standard)

            def read_word(address):
                print(f"Reading memory 0x{address:08x}...", flush=True)
                record = {"address": f"0x{address:08x}"}
                target_report["reads"].append(record)
                try:
                    reply = hci(0xFC61, struct.pack("<BI", 0x20, address))
                    record["reply"] = reply.hex(" ")
                    data = memory_data(reply, address)
                except (Exception, KeyboardInterrupt) as error:
                    record["error"] = str(error) or "Interrupted by user"
                    raise
                print(f"  {data.hex(' ')}", flush=True)
                return data

            inspect_descriptor_targets(read_word, target_report)
            compare_descriptor(target_report, standard)
    except (Exception, KeyboardInterrupt) as error:
        failed = True
        result["error"] = str(error) or "Interrupted by user"
    finally:
        if handle:
            if claimed:
                code = usb.libusb_release_interface(handle, 0)
                if code < 0:
                    failed = True
                    result["release_warning"] = usb.libusb_error_name(code).decode()
            if changed_configuration:
                code = usb.libusb_set_configuration(handle, -1)
                result["unconfigured_state_restored"] = code >= 0
                if code < 0:
                    failed = True
                    result["restore_warning"] = usb.libusb_error_name(code).decode()
            usb.libusb_close(handle)
        if devices:
            usb.libusb_free_device_list(devices, 1)
        if initialized:
            usb.libusb_exit(context)
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    if args.descriptor_targets:
        try:
            output = Path(__file__).resolve().parent / "results"
            output.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            target = output / f"bt600-targets-{stamp}.json"
            target.write_text(json.dumps(result, indent=2) + "\n")
            print(f"Saved result: {target}", flush=True)
        except OSError as error:
            failed = True
            result["save_error"] = str(error)
    print(json.dumps(result, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
