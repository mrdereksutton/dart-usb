#!/usr/bin/env python3
"""Dump USB descriptors of connected devices, for comparing hardware in practice.

    python3 usb_inspect.py                 # one-line summary of every USB device
    python3 usb_inspect.py 0b05:1d70       # full descriptor dump of that VID:PID

Uses the Homebrew libusb (same paths as bt600_probe.py). Sends only standard
read-only GET_DESCRIPTOR requests on endpoint 0 -- no vendor or HCI commands,
nothing device-specific, so it is safe to point at any dongle. Run from the
macOS Terminal app; the chat process is denied raw USB.
"""

import ctypes as C
import ctypes.util
from pathlib import Path
import struct
import sys

P = C.c_void_p

DEVICE_CLASSES = {
    0x00: "per-interface", 0x02: "CDC-comm", 0x03: "HID", 0x08: "mass-storage",
    0x09: "hub", 0x0A: "CDC-data", 0x0E: "video", 0x01: "audio",
    0xE0: "wireless (Bluetooth)", 0xEF: "misc", 0xFF: "vendor-specific",
}
INTERFACE_CLASSES = {
    0x01: "audio", 0x02: "CDC-comm", 0x03: "HID", 0x08: "mass-storage",
    0x0A: "CDC-data", 0x0B: "smart-card", 0x0E: "video", 0xE0: "wireless",
    0xFE: "application", 0xFF: "vendor-specific",
}
TRANSFER_TYPES = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}


def class_label(code, table):
    return f"0x{code:02x} {table.get(code, '?')}"


def parse_config(blob):
    """Walk a raw configuration descriptor into interfaces and their endpoints.

    Returns a list of dicts: {number, class, subclass, protocol, report_len,
    endpoints: [...]}, where each endpoint is {address, dir, type, max_packet}
    and report_len is the HID report-descriptor length (0 if none). Pure.
    """
    interfaces = []
    i = 0
    while i + 1 < len(blob):
        length = blob[i]
        kind = blob[i + 1]
        if length == 0:
            break
        if kind == 0x04 and i + 8 <= len(blob):  # interface descriptor
            interfaces.append({
                "number": blob[i + 2], "class": blob[i + 5],
                "alternate": blob[i + 3],
                "subclass": blob[i + 6], "protocol": blob[i + 7],
                "report_len": 0, "endpoints": [],
            })
        elif kind == 0x21 and i + 9 <= len(blob) and interfaces:  # HID descriptor
            # wDescriptorLength of the first class descriptor (the report).
            interfaces[-1]["report_len"] = blob[i + 7] | (blob[i + 8] << 8)
        elif kind == 0x05 and i + 6 <= len(blob) and interfaces:  # endpoint
            address = blob[i + 2]
            attributes = blob[i + 3]
            max_packet = blob[i + 4] | (blob[i + 5] << 8)
            interfaces[-1]["endpoints"].append({
                "address": address,
                "dir": "IN" if address & 0x80 else "OUT",
                "type": TRANSFER_TYPES.get(attributes & 0x03, "?"),
                "max_packet": max_packet & 0x7FF,
            })
        i += length
    return interfaces


USAGE_PAGES = {0x01: "Generic Desktop", 0x0C: "Consumer", 0x0B: "Telephony"}


def hid_usage_pages(report):
    """Light HID item walk: return the ordered list of Usage Page values in a
    report descriptor. Vendor-defined pages are 0xFF00-0xFFFF. Pure function."""
    pages = []
    i = 0
    while i < len(report):
        prefix = report[i]
        if prefix in (0xFE, 0xFF):  # long item: [prefix][dataSize][tag][data...]
            size = report[i + 1] if i + 1 < len(report) else 0
            i += 3 + size
            continue
        size = {0: 0, 1: 1, 2: 2, 3: 4}[prefix & 0x03]
        data = report[i + 1:i + 1 + size]
        if prefix & 0xFC == 0x04:  # Usage Page (global item)
            pages.append(int.from_bytes(data, "little") if data else 0)
        i += 1 + size
    return pages


def usage_page_label(page):
    if 0xFF00 <= page <= 0xFFFF:
        return f"0x{page:04x} vendor-defined"
    return f"0x{page:04x} {USAGE_PAGES.get(page, '?')}"


class DeviceDescriptor(C.Structure):
    _fields_ = [
        ("length", C.c_uint8), ("kind", C.c_uint8), ("usb", C.c_uint16),
        ("device_class", C.c_uint8), ("subclass", C.c_uint8),
        ("protocol", C.c_uint8), ("max_packet", C.c_uint8),
        ("vid", C.c_uint16), ("pid", C.c_uint16), ("revision", C.c_uint16),
        ("manufacturer", C.c_uint8), ("product", C.c_uint8),
        ("serial", C.c_uint8), ("configurations", C.c_uint8),
    ]


def load_libusb():
    candidates = [
        "/opt/homebrew/lib/libusb-1.0.dylib",
        "/usr/local/lib/libusb-1.0.dylib",
        ctypes.util.find_library("usb-1.0"),
    ]
    library = next((p for p in candidates if p and Path(p).is_file()), None)
    if not library:
        print("The libusb library could not be found.")
        return None
    usb = C.CDLL(library)
    signatures = {
        "libusb_init": ([C.POINTER(P)], C.c_int),
        "libusb_exit": ([P], None),
        "libusb_get_device_list": ([P, C.POINTER(C.POINTER(P))], C.c_ssize_t),
        "libusb_free_device_list": ([C.POINTER(P), C.c_int], None),
        "libusb_get_device_descriptor": ([P, C.POINTER(DeviceDescriptor)], C.c_int),
        "libusb_open": ([P, C.POINTER(P)], C.c_int),
        "libusb_close": ([P], None),
        "libusb_control_transfer": (
            [P, C.c_uint8, C.c_uint8, C.c_uint16, C.c_uint16, P, C.c_uint16, C.c_uint], C.c_int),
    }
    for name, (args, res) in signatures.items():
        fn = getattr(usb, name)
        fn.argtypes, fn.restype = args, res
    return usb


def get_descriptor(usb, handle, desc_type, index, length, language=0):
    buf = C.create_string_buffer(length)
    n = usb.libusb_control_transfer(
        handle, 0x80, 0x06, (desc_type << 8) | index, language, buf, length, 1000)
    return buf.raw[:n] if n > 0 else b""


def get_report_descriptor(usb, handle, interface, length):
    # GET_DESCRIPTOR of the HID report (type 0x22), recipient = interface.
    # May fail if the OS HID driver owns the interface; caller handles that.
    buf = C.create_string_buffer(length)
    n = usb.libusb_control_transfer(
        handle, 0x81, 0x06, (0x22 << 8), interface, buf, length, 1000)
    return buf.raw[:n] if n > 0 else b""


def read_string(usb, handle, index):
    if not index:
        return ""
    languages = get_descriptor(usb, handle, 0x03, 0, 255)
    if len(languages) < 4 or languages[1] != 3:
        return ""
    language = int.from_bytes(languages[2:4], "little")
    raw = get_descriptor(usb, handle, 0x03, index, 255, language=language)
    if len(raw) < 2:
        return ""
    try:
        return raw[2:].decode("utf-16-le", errors="replace").strip("\x00")
    except Exception:
        return ""


def dump_device(usb, device, desc, full):
    vid_pid = f"{desc.vid:04x}:{desc.pid:04x}"
    handle = P()
    opened = usb.libusb_open(device, C.byref(handle)) == 0
    product = manufacturer = ""
    config = b""
    if opened:
        manufacturer = read_string(usb, handle, desc.manufacturer)
        product = read_string(usb, handle, desc.product)
        head = get_descriptor(usb, handle, 0x02, 0, 9)
        if len(head) >= 4:
            total = struct.unpack_from("<H", head, 2)[0]
            config = get_descriptor(usb, handle, 0x02, 0, total)
    name = (manufacturer + " " + product).strip() or "(unnamed; could not open)"
    if not full:
        print(f"  {vid_pid}  class {class_label(desc.device_class, DEVICE_CLASSES):<24}  {name}")
    else:
        print(f"Device {vid_pid}  {name}")
        print(f"  USB {desc.usb >> 8:x}.{desc.usb & 0xff:02x}; device revision {desc.revision:04x}")
        print(f"  device class/subclass/protocol: "
              f"{class_label(desc.device_class, DEVICE_CLASSES)} / 0x{desc.subclass:02x} / 0x{desc.protocol:02x}")
        print(f"  max packet (EP0): {desc.max_packet}; configurations: {desc.configurations}")
        if config:
            for n, iface in enumerate(parse_config(config)):
                print(f"  interface {n}: class {class_label(iface['class'], INTERFACE_CLASSES)}"
                      f" / 0x{iface['subclass']:02x} / 0x{iface['protocol']:02x}")
                for ep in iface["endpoints"]:
                    print(f"    endpoint 0x{ep['address']:02x} {ep['dir']:<3} {ep['type']:<11}"
                          f" max {ep['max_packet']} bytes")
                if iface["report_len"] and opened:
                    report = get_report_descriptor(usb, handle, iface["number"], iface["report_len"])
                    if not report:
                        print(f"    HID report descriptor: {iface['report_len']} bytes, "
                              "unreadable (the OS HID driver likely owns this interface)")
                    else:
                        pages = hid_usage_pages(report)
                        seen = ", ".join(dict.fromkeys(usage_page_label(p) for p in pages)) or "none"
                        print(f"    HID report descriptor: {len(report)} bytes; usage pages: {seen}")
                        print(f"      raw: {report[:48].hex(' ')}" + (" ..." if len(report) > 48 else ""))
        elif opened:
            print("  (configuration descriptor unavailable)")
    if opened:
        usb.libusb_close(handle)


def main():
    target = None
    if len(sys.argv) > 1:
        try:
            vid, pid = sys.argv[1].split(":")
            target = (int(vid, 16), int(pid, 16))
        except ValueError:
            print("Usage: python3 usb_inspect.py [VID:PID]   (hex, e.g. 0b05:1d70)")
            return 1
    usb = load_libusb()
    if not usb:
        return 1
    ctx = P()
    devices = C.POINTER(P)()
    count = -1
    if usb.libusb_init(C.byref(ctx)) != 0:
        print("Could not initialize USB.")
        return 1
    try:
        count = usb.libusb_get_device_list(ctx, C.byref(devices))
        if count <= 0:
            print("USB access returned zero devices. Run this from the macOS Terminal app.")
            return 2
        print(f"{count} USB devices" + (f"; full dump of {target[0]:04x}:{target[1]:04x}:" if target else ":"))
        shown = False
        for index in range(count):
            desc = DeviceDescriptor()
            if usb.libusb_get_device_descriptor(devices[index], C.byref(desc)) != 0:
                continue
            if target and (desc.vid, desc.pid) != target:
                continue
            dump_device(usb, devices[index], desc, full=bool(target))
            shown = True
        if target and not shown:
            print("  That VID:PID is not plugged in.")
        return 0
    finally:
        if count >= 0:
            usb.libusb_free_device_list(devices, 1)
        usb.libusb_exit(ctx)


if __name__ == "__main__":
    sys.exit(main())
