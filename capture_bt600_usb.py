#!/usr/bin/env python3
"""Save the BT600's standard USB descriptors without HCI or interface claims."""
import ctypes as C
from datetime import datetime, timezone
import json
from pathlib import Path

from descriptor_capture import read_descriptors
import usb_inspect as usb_api


def main():
    output = Path(__file__).resolve().parent / 'results' / (
        'bt600-usb-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    report = {'usb_id': '0b05:1d70', 'started_utc': datetime.now(timezone.utc).isoformat()}
    context, handle = usb_api.P(), usb_api.P()
    devices = C.POINTER(usb_api.P)()
    initialized, failed = False, False
    usb = usb_api.load_libusb()
    try:
        if usb is None or usb.libusb_init(C.byref(context)) < 0:
            raise RuntimeError('Could not initialize libusb')
        initialized = True
        count = usb.libusb_get_device_list(context, C.byref(devices))
        if count < 0:
            raise RuntimeError(f'USB enumeration error {count}')
        matches = []
        for index in range(count):
            descriptor = usb_api.DeviceDescriptor()
            if usb.libusb_get_device_descriptor(devices[index], C.byref(descriptor)) == 0 and (descriptor.vid, descriptor.pid) == (0x0b05, 0x1d70):
                matches.append(devices[index])
        if len(matches) != 1:
            raise RuntimeError(f'Expected exactly one BT600; found {len(matches)}')
        code = usb.libusb_open(matches[0], C.byref(handle))
        if code < 0:
            raise RuntimeError(f'USB open error {code}')
        descriptors = read_descriptors(lambda kind, index, length: usb_api.get_descriptor(usb, handle, kind, index, length))
        report['descriptors'] = {name: data.hex(' ') for name, data in descriptors.items()}
        report['configurations'] = {name: usb_api.parse_config(data) for name, data in descriptors.items() if name.startswith('configuration_')}
    except (Exception, KeyboardInterrupt) as error:
        failed = True
        report['error'] = str(error) or 'Interrupted'
    finally:
        if handle:
            usb.libusb_close(handle)
        if devices:
            usb.libusb_free_device_list(devices, 1)
        if initialized:
            usb.libusb_exit(context)
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    output.mkdir(parents=True)
    (output/'usb.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    print(f'Saved: {output}/usb.json')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
