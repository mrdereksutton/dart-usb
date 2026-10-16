#!/usr/bin/env python3
"""Save an iPod's live USB descriptors from normal macOS Terminal.

Uses standard GET_DESCRIPTOR requests. Does not claim interfaces, change USB
configuration, read the music disk, sync, or send iAP commands.
"""

import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import descriptor_capture
import usb_inspect as inspect


def save_reference(descriptors, output, product, manufacturer):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "product": product, "manufacturer": manufacturer,
        "descriptors": {}, "configurations": [],
        "scope": "USB descriptors in the current iPod mode, connected to the Mac",
    }
    for name, raw in descriptors.items():
        filename = name + ".bin"
        (output / filename).write_bytes(raw)
        report["descriptors"][name] = {
            "file": filename, "hex": raw.hex(" "), "length": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if name.startswith("configuration_"):
            # Keep raw bytes as well as the readable summary, including every
            # alternate setting; no SET_CONFIGURATION is needed to read them.
            report["configurations"].append({
                "descriptor": name, "value": raw[5],
                "interfaces": inspect.parse_config(raw),
            })
    (output / "reference.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    usb = inspect.load_libusb()
    if usb is None:
        return 1
    context, handle = inspect.P(), inspect.P()
    devices = C.POINTER(inspect.P)()
    count = -1
    if usb.libusb_init(C.byref(context)) != 0:
        print("Could not initialize USB.")
        return 1
    found, failed = 0, False
    root = Path(__file__).resolve().parent / "results"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    try:
        count = usb.libusb_get_device_list(context, C.byref(devices))
        if count <= 0:
            print("USB access returned no devices. Run this from normal macOS Terminal.")
            return 2
        for index in range(count):
            desc = inspect.DeviceDescriptor()
            if usb.libusb_get_device_descriptor(devices[index], C.byref(desc)) != 0 or desc.vid != 0x05AC:
                continue
            handle = inspect.P()
            if usb.libusb_open(devices[index], C.byref(handle)) != 0:
                print(f"Could not open Apple USB device 05ac:{desc.pid:04x} to read its product name.")
                continue
            try:
                product = inspect.read_string(usb, handle, desc.product)
                if "ipod" not in product.lower():
                    print(f"Skipping Apple 05ac:{desc.pid:04x}: {product or 'product name unavailable'}")
                    continue
                found += 1
                print(f"iPod found: {product}; USB 05ac:{desc.pid:04x}", flush=True)
                manufacturer = inspect.read_string(usb, handle, desc.manufacturer)
                descriptors = descriptor_capture.read_descriptors(
                    lambda kind, number, length: inspect.get_descriptor(usb, handle, kind, number, length),
                    expected_identity=(0x05AC, desc.pid),
                )
                output = root / f"ipod-{run_id}-{found}"
                report = save_reference(descriptors, output, product, manufacturer)
                for config in report["configurations"]:
                    print(f"  Configuration {config['value']}:")
                    for iface in config["interfaces"]:
                        print(f"    Interface {iface['number']}, alternate {iface['alternate']}: "
                              f"{inspect.class_label(iface['class'], inspect.INTERFACE_CLASSES)}")
                        for endpoint in iface["endpoints"]:
                            print(f"      0x{endpoint['address']:02x} {endpoint['dir']} "
                                  f"{endpoint['type']}, {endpoint['max_packet']} bytes")
                print(f"Saved iPod reference: {output}", flush=True)
            except (RuntimeError, ValueError, OSError) as error:
                failed = True
                print(f"iPod capture stopped: {error}")
            finally:
                usb.libusb_close(handle)
                handle = inspect.P()
        if not found:
            print("No iPod product name was found. Connect the iPod in its normal mode, then rerun.")
            return 2
        return 3 if failed else 0
    finally:
        if handle:
            usb.libusb_close(handle)
        if count >= 0:
            usb.libusb_free_device_list(devices, 1)
        usb.libusb_exit(context)


if __name__ == "__main__":
    sys.exit(main())
