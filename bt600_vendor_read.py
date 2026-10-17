#!/usr/bin/env python3
"""Inspect BT600 USB objects and run bounded experiments with RAM restoration.

Run from macOS Terminal with python3. Uses the existing Homebrew libusb.
No firmware download, controller reset, kernel-driver detachment, or persistent
write commands are issued. --test-product-string temporarily writes one RAM
word, reads the USB response, and restores the original in a finally block.
--test-setup-marker temporarily installs a RAM trampoline on the setup callback,
then restores the callback, helper words and marker. --capture-flash only reads.
USB configuration 1 is temporarily selected only
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
import os
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
# Registration at 0x02188a2a: R=*[0x002c1240], G=R+4.
# Bind stores composite state C at G+0x3c. GET_DESCRIPTOR uses C+0x0c.
USB_CONTEXT_POINTER_ADDRESS = 0x002C1240
# At 0x02168a42..0x02168a58, ASUS initializes allocation region 6 with
# base 0x00300000 and size 0x14000; 0x021719e6 records that pair at
# 0x002819c0. The first live context read yielded 0x0030fe28 in this pool.
CANDIDATE_RAM_WINDOWS = ((0x00200000, 0x00300000), (0x00300000, 0x00314000))


def plausible_ram_object(address, size):
    return not address & 3 and any(
        start <= address and address + size <= end
        for start, end in CANDIDATE_RAM_WINDOWS)


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


def inspect_active_descriptor(read_word, report):
    """Test the independently traced context chain, at most seven word reads."""
    report["context_pointer_location"] = f"0x{USB_CONTEXT_POINTER_ADDRESS:08x}"
    context = int.from_bytes(read_word(USB_CONTEXT_POINTER_ADDRESS), "little")
    report["context_pointer"] = f"0x{context:08x}"
    if not plausible_ram_object(context, 0x44):
        report["pointer_result"] = "invalid context pointer; not followed"
        return
    composite = int.from_bytes(read_word(context + 0x40), "little")
    report["composite_pointer"] = f"0x{composite:08x}"
    if not plausible_ram_object(composite, 0x20):
        report["pointer_result"] = "invalid composite pointer; not followed"
        return
    address = composite + 0x0C
    report["descriptor_address"] = f"0x{address:08x}"
    first = read_word(address)
    if first[:2] != b"\x12\x01":
        report["pointer_result"] = "active candidate lacks USB device descriptor header"
        return
    raw = first + b"".join(read_word(address + offset) for offset in (4, 8, 12, 16))
    report["pointer_result"] = "USB device descriptor found in active candidate"
    report["descriptor"] = {"raw": raw[:18].hex(" ")}


def inspect_usb_context(read_word, report):
    """Capture only the context header used by bind/setup, without following it."""
    report["context_pointer_location"] = f"0x{USB_CONTEXT_POINTER_ADDRESS:08x}"
    context = int.from_bytes(read_word(USB_CONTEXT_POINTER_ADDRESS), "little")
    report["context_pointer"] = f"0x{context:08x}"
    if not plausible_ram_object(context, 0x50):
        report["pointer_result"] = "invalid context header span; not followed"
        return
    report["context_words"] = {}
    for offset in range(0, 0x50, 4):
        data = read_word(context + offset)
        report["context_words"][f"0x{offset:02x}"] = f"0x{int.from_bytes(data, 'little'):08x}"


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
    parser.add_argument("--setup-code-bytes", type=int, choices=(32, 1024), default=32,
                        help="Prefix length for --setup-handler; stays within its flash page")
    parser.add_argument("--quiet-memory", action="store_true", help="Suppress individual memory-word output")
    parser.add_argument("--device-descriptor-index", type=int, choices=(0, 1), default=0,
                        help="Use index 1 for an uncached comparison; traced firmware ignores the device index")
    parser.add_argument("--flash-bytes", type=int, choices=(256, 4096, 65536, 2097152), default=256,
                        help="Length for --capture-flash, starting at the actual 0x02000000 flash region")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--descriptor-targets", action="store_true",
                        help="Read the ASUS image's descriptor pointer and USB-ID config, then save the result")
    modes.add_argument("--active-descriptor", action="store_true",
                       help="Test the independently traced USB context/composite descriptor chain (at most seven words)")
    modes.add_argument("--usb-context", action="store_true",
                       help="Capture the 0x50-byte bind/setup context header, without following its fields (21 words maximum)")
    modes.add_argument("--heap-descriptor", action="store_true",
                       help="Check the complete descriptor/composite/driver objects found in the saved heap (12 words)")
    modes.add_argument("--setup-handler", action="store_true",
                       help="Read 32 bytes from the validated driver's actual setup callback (21 words total)")
    modes.add_argument("--capture-flash", action="store_true",
                       help="Capture actual flash-region bytes to a new binary; stop on the first failed word")
    modes.add_argument("--test-setup-marker", action="store_true",
                       help="Temporarily install a RAM marker trampoline on the validated USB setup callback, then restore")
    modes.add_argument("--test-product-string", action="store_true",
                       help="Temporarily change the validated descriptor's iProduct index from 2 to 1; always restore")
    modes.add_argument("--test-template-string", action="store_true",
                       help="Run the same restored iProduct test on the validated driver's template")
    args = parser.parse_args()
    target_mode = (args.descriptor_targets or args.active_descriptor or args.usb_context
                   or args.heap_descriptor or args.setup_handler or args.capture_flash or args.test_setup_marker
                   or args.test_product_string or args.test_template_string)
    if args.describe:
        for name, opcode, params in QUERIES:
            print(f"{name}: {(struct.pack('<HB', opcode, len(params)) + params).hex(' ')}")
        if args.descriptor_targets:
            for address in (DESCRIPTOR_POINTER_ADDRESS, USB_ID_CONFIG_ADDRESS):
                print(f"Memory 0x{address:08x}: {(struct.pack('<HB', 0xfc61, 5) + struct.pack('<BI', 0x20, address)).hex(' ')}")
            print("Follow a plausible RAM pointer only if its first word starts with 12 01; at most five descriptor words.")
        if args.active_descriptor:
            print("Read R=*[0x002c1240]; if aligned candidate RAM, read C=*[R+0x40].")
            print("If C is aligned candidate RAM, read C+0x0c; follow only a 12 01 header, five descriptor words maximum.")
        if args.usb_context:
            print("Read R=*[0x002c1240]; if the full span fits candidate RAM, read R..R+0x4c (20 words). No field is followed.")
        if args.heap_descriptor or args.setup_handler or args.test_product_string or args.test_template_string:
            print("Check descriptor at 0x0030d18c, driver at *0x0030d1b0 and template at driver+4.")
        if args.setup_handler:
            print(f"Read callback at driver+0x34; follow only an odd pointer in 0x02000000..0x02200000 for {args.setup_code_bytes} code bytes.")
        if args.capture_flash:
            print(f"Read {args.flash_bytes} bytes at 0x02000000, within the selected 2 MiB flash region.")
        if args.test_setup_marker:
            print("Save zero scratch words at 0x00211f20 (28 bytes), marker 0x00211f00, and validated driver+0x34.")
            print("Write a register-preserving marker stub, temporarily redirect setup to it, then restore callback first and all RAM.")
        if args.test_product_string or args.test_template_string:
            print("After exact EP0/heap checks, save the original composite/template word to JSON.")
            print("Change only iProduct 2 -> existing string index 1, compare EP0, restore and compare again.")
        if target_mode:
            print("Standard GET_DESCRIPTOR: bmRequestType=80 request=06 value=0100 index=0000 length=18")
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
              "active_descriptor_requested": args.active_descriptor,
              "usb_context_requested": args.usb_context,
              "heap_descriptor_requested": args.heap_descriptor,
              "setup_handler_requested": args.setup_handler,
              "flash_capture_requested": args.capture_flash,
              "setup_marker_test_requested": args.test_setup_marker,
              "product_string_test_requested": args.test_product_string,
              "template_string_test_requested": args.test_template_string,
              "device_descriptor_test_index": args.device_descriptor_index,
              "started_utc": datetime.now(timezone.utc).isoformat()}
    target = None
    if target_mode:
        output = Path(__file__).resolve().parent / "results"
        output.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        target = output / f"bt600-targets-{stamp}.json"

    def checkpoint():
        temporary = target.with_suffix(".tmp")
        with temporary.open("w") as saved:
            saved.write(json.dumps(result, indent=2) + "\n")
            saved.flush()
            os.fsync(saved.fileno())
        temporary.replace(target)
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
        if target_mode:
            if result["queries"]["rom_version"]["rom_version"] != 1:
                raise RuntimeError("Descriptor targets are derived only for ROM 1 / ECO 2")
            mode = ("setup-marker-test" if args.test_setup_marker else
                    "flash-capture" if args.capture_flash else "setup-handler" if args.setup_handler else
                    "template-string-test" if args.test_template_string else
                    "product-string-test" if args.test_product_string else
                    "heap" if args.heap_descriptor else "context" if args.usb_context else
                    "active" if args.active_descriptor else "template")
            target_report = {"reads": [], "mode": mode}
            result["descriptor_targets"] = target_report
            standard_buffer = C.create_string_buffer(18)
            size = checked(usb.libusb_control_transfer(
                handle, 0x80, 6, 0x0100, 0, standard_buffer, 18, 2000),
                "GET_DESCRIPTOR device")
            standard = standard_buffer.raw[:size]
            compare_descriptor(target_report, standard)

            def get_descriptor():
                buf = C.create_string_buffer(18)
                size = checked(usb.libusb_control_transfer(
                    handle, 0x80, 6, 0x0100 | args.device_descriptor_index, 0,
                    buf, 18, 2000), "GET_DESCRIPTOR device")
                return buf.raw[:size]

            def read_word(address):
                if not args.quiet_memory:
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
                if not args.quiet_memory:
                    print(f"  {data.hex(' ')}", flush=True)
                return data

            def write_word(address, data):
                record = {"address": f"0x{address:08x}", "data": data.hex(" ")}
                target_report.setdefault("writes", []).append(record)
                try:
                    reply = hci(0xFC62, struct.pack("<BI", 0x20, address) + data)
                    record["reply"] = reply.hex(" ")
                    if not reply or reply[0]:
                        raise RuntimeError(f"Descriptor write rejected: {reply.hex(' ')}")
                except (Exception, KeyboardInterrupt) as error:
                    record["error"] = str(error) or "Interrupted"
                    raise

            if args.test_setup_marker:
                import setup_marker
                result["setup_marker_sha256"] = hashlib.sha256(
                    Path(setup_marker.__file__).read_bytes()).hexdigest()
                setup_marker.test_setup_marker(read_word, write_word, get_descriptor,
                                               target_report, checkpoint)
            elif args.capture_flash:
                import capture_flash
                result["capture_flash_sha256"] = hashlib.sha256(
                    Path(capture_flash.__file__).read_bytes()).hexdigest()

                def read_flash_word(address):
                    return memory_data(hci(0xFC61, struct.pack("<BI", 0x20, address)), address)

                capture_flash.capture_flash(
                    read_flash_word, target.with_suffix(".bin"), args.flash_bytes,
                    target_report, checkpoint)
            elif args.heap_descriptor or args.setup_handler or args.test_product_string or args.test_template_string:
                import descriptor_edit
                result["descriptor_edit_sha256"] = hashlib.sha256(
                    Path(descriptor_edit.__file__).read_bytes()).hexdigest()
                if args.setup_handler:
                    descriptor_edit.inspect_setup_handler(
                        read_word, standard, target_report, args.setup_code_bytes)
                elif args.test_product_string or args.test_template_string:
                    descriptor_edit.test_product_string(
                        read_word, write_word, get_descriptor, target_report, checkpoint,
                        template=args.test_template_string)
                else:
                    descriptor_edit.inspect_heap_descriptor(read_word, standard, target_report)
            elif args.usb_context:
                inspect_usb_context(read_word, target_report)
            elif args.active_descriptor:
                inspect_active_descriptor(read_word, target_report)
            else:
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
    if target_mode:
        try:
            checkpoint()
            print(f"Saved result: {target}", flush=True)
        except OSError as error:
            failed = True
            result["save_error"] = str(error)
    print(json.dumps(result, indent=2), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
