#!/usr/bin/env python3
"""Offline extraction of the pinned ASUS BT600 RTBTCore image; never opens USB.

Usage: python3 analyze_asus_firmware.py PATH/rtl8761cu_mx_fw --output results/asus-eco2
Firmware is supplied locally and is not redistributed by this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

FIRMWARE_SHA256 = 'bfadde9c084726cec144828fe6aaaa917047d39616efb66de298366993d13f46'
SOURCE_URL = 'https://dlcdnets.asus.com/pub/ASUS/wireless/USB-BT600/DR_USB-BT600_v3.1.07_Linux.zip'


def bounded(data, offset, length):
    if offset < 0 or length < 0 or offset + length > len(data):
        raise ValueError(f'Truncated data at {offset:#x}, requested {length:#x} bytes')
    return data[offset:offset+length]


def unpack(fmt, data, offset):
    return struct.unpack(fmt, bounded(data, offset, struct.calcsize(fmt)))


def select_snippet(data, eco=2):
    """Parse snippet sections; deliberately reject unsupported section opcodes."""
    if bounded(data, 0, 8) != b'RTBTCore':
        raise ValueError('Not an RTBTCore container')
    count, = unpack('<I', data, 16)
    offset, matches = 20, []
    for _ in range(count):
        opcode, length = unpack('<II', data, offset)
        body = bounded(data, offset+8, length)
        if opcode != 1:
            raise ValueError(f'Unsupported section opcode {opcode:#x}; no generic loader emulation')
        snippets, reserved = unpack('<HH', body, 0)
        if reserved:
            raise ValueError('Nonzero snippet table reserved field')
        cursor = 4
        for _ in range(snippets):
            chip, priority, reserved, size = unpack('<BBHI', body, cursor)
            payload = bounded(body, cursor+8, size)
            if reserved:
                raise ValueError('Nonzero snippet reserved field')
            if chip == eco:
                matches.append((offset+8+cursor+8, priority, payload))
            cursor += 8+size
        if cursor != len(body):
            raise ValueError('Snippet sizes do not account for section length')
        offset += 8+length
    if len(matches) != 1:
        raise ValueError(f'Expected one ECO {eco} snippet; found {len(matches)}')
    return matches[0]


def parse_images(snippet, file_offset):
    eco_marker, count = unpack('<BB', snippet, 0)
    if eco_marker != 1 or count != 7:
        raise ValueError('Expected the known ECO-2 seven-image package')
    cursor = 2+12*count
    images, seen = [], set()
    for index in range(count):
        image_id, reserved, size, version = unpack('<HHII', snippet, 2+12*index)
        if reserved or image_id in seen:
            raise ValueError('Reserved field or duplicate image ID')
        seen.add(image_id)
        image = bounded(snippet, cursor, size)
        if size < 0x400:
            raise ValueError('Image shorter than its 1024-byte header')
        execute, load, load_length = unpack('<III', image, 0x14c)
        images.append({'image_id': image_id, 'snippet_offset': cursor,
                       'file_offset': file_offset+cursor, 'size': size,
                       'version': version, 'payload_file_offset': file_offset+cursor+0x400,
                       'payload_size': size-0x400,
                       'header_0x14c': execute, 'header_0x150': load,
                       'header_0x154': load_length})
        cursor += size
    if cursor != len(snippet):
        raise ValueError('Image sizes do not account for the complete snippet')
    return images


def analyze(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest != FIRMWARE_SHA256:
        raise ValueError('Firmware SHA-256 differs from the analyzed ASUS release; refusing address map')
    offset, priority, snippet = select_snippet(data)
    images = parse_images(snippet, offset)
    app = next(i for i in images if i['image_id'] == 0x2793)
    payload = bounded(data, app['payload_file_offset'], app['payload_size'])
    base = app['header_0x14c']
    if base != 0x02167400 or app['header_0x150'] != base:
        raise ValueError('Unexpected application mapping')
    # Byte evidence at literal pools, not reads from the controller.
    literals = {}
    for address in (0x02177804, 0x02177838, 0x02188a80):
        value, = unpack('<I', payload, address-base)
        literals[f'0x{address:08x}'] = f'0x{value:08x}'
    anchors = {}
    for address, length in ((0x02177662, 4), (0x0217758a, 4), (0x021894c0, 10),
                            (0x0218964e, 40), (0x02189a6c, 8)):
        anchors[f'0x{address:08x}'] = bounded(payload, address-base, length).hex(' ')
    report = {'source_url': SOURCE_URL, 'firmware_sha256': digest,
              'firmware_size': len(data), 'eco': 2, 'snippet_file_offset': offset,
              'snippet_size': len(snippet), 'priority': priority,
              'images': images, 'application_base': base,
              'application_payload_sha256': hashlib.sha256(payload).hexdigest(),
              'offline_literals': literals, 'instruction_bytes': anchors,
              'live_layout_confirmed': False}
    return report, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New output directory')
    args = parser.parse_args()
    try:
        report, payload = analyze(args.firmware.read_bytes())
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output/'map.json').write_text(json.dumps(report, indent=2)+'\n')
        (args.output/'asus-app-payload.bin').write_bytes(payload)
        (args.output/'asus-app.S').write_text(
            '.syntax unified\n.thumb\n.section .text,"ax",%progbits\n'
            '.global asus_app\n.type asus_app,%function\n.thumb_func\nasus_app:\n'
            '.incbin "asus-app-payload.bin"\n.size asus_app, . - asus_app\n')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Extracted ECO 2, seven images, application base 0x02167400: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
