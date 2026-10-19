#!/usr/bin/env python3
"""One BT600 device-descriptor control read; no interface claim or state change."""
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from usb_access_guard import require_usb_access

P = C.c_void_p
LIBRARY = "/opt/homebrew/lib/libusb-1.0.dylib"
SIGNATURES = {
    "libusb_init": ([C.POINTER(P)], C.c_int),
    "libusb_exit": ([P], None),
    "libusb_get_device_list": ([P, C.POINTER(C.POINTER(P))], C.c_ssize_t),
    "libusb_free_device_list": ([C.POINTER(P), C.c_int], None),
    "libusb_get_device_descriptor": ([P, P], C.c_int),
    "libusb_open": ([P, C.POINTER(P)], C.c_int),
    "libusb_close": ([P], None),
    "libusb_control_transfer": ([P, C.c_uint8, C.c_uint8, C.c_uint16,
                                 C.c_uint16, P, C.c_uint16, C.c_uint], C.c_int),
    "libusb_error_name": ([C.c_int], C.c_char_p),
}


def main():
    require_usb_access("device_descriptor_read")
    folder = Path(__file__).resolve().parent / "results"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    target = folder / f"hardware-resume-descriptor-{stamp}.json"
    report = {"pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat(),
              "request": {"type": 0x80, "request": 6, "value": 0x0100,
                          "index": 0, "length": 18, "timeout_ms": 1500},
              "interface_claim": False, "device_writes": False,
              "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def save(stage):
        report["stage"] = stage
        with target.with_suffix(".tmp").open("w") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
            stream.flush(); os.fsync(stream.fileno())
        target.with_suffix(".tmp").replace(target)

    save("before_library_load")
    usb = C.CDLL(LIBRARY)
    for name, (args, result) in SIGNATURES.items():
        getattr(usb, name).argtypes = args
        getattr(usb, name).restype = result

    def checked(value, operation):
        if value < 0:
            raise RuntimeError(f"{operation}: {usb.libusb_error_name(value).decode()} ({value})")
        return value

    context, handle, devices = P(), P(), C.POINTER(P)()
    initialized = False
    success = False
    try:
        checked(usb.libusb_init(C.byref(context)), "Initialize libusb")
        initialized = True
        count = checked(usb.libusb_get_device_list(context, C.byref(devices)), "List devices")
        matches = []
        for i in range(count):
            cached = C.create_string_buffer(18)
            if usb.libusb_get_device_descriptor(devices[i], cached) == 0:
                if cached.raw[8:12] == bytes.fromhex("05 0b 70 1d"):
                    matches.append((devices[i], cached.raw))
        report["matching_devices"] = len(matches)
        report["enumerated_devices"] = count
        save("devices_listed")
        if len(matches) != 1:
            raise RuntimeError(f"Expected one connected BT600; found {len(matches)}")
        device, cached = matches[0]
        report["cached_device_descriptor"] = cached.hex(" ")
        checked(usb.libusb_open(device, C.byref(handle)), "Open BT600")
        save("before_control_transfer")
        response = C.create_string_buffer(18)
        length = checked(usb.libusb_control_transfer(handle, 0x80, 6, 0x0100, 0, response, 18, 1500),
                         "Read device descriptor")
        report["descriptor"] = response.raw[:length].hex(" ")
        if length != 18 or response.raw[:2] != bytes([18, 1]) or response.raw[8:12] != bytes.fromhex("05 0b 70 1d"):
            raise RuntimeError("Unexpected or incomplete BT600 descriptor")
        success = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        if handle: usb.libusb_close(handle)
        if devices: usb.libusb_free_device_list(devices, 1)
        if initialized: usb.libusb_exit(context)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save("complete" if success else "failed")
    print(json.dumps({"report": str(target), **report}, indent=2), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
