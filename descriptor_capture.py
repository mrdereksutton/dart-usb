#!/usr/bin/env python3
"""Capture USB descriptors and RAM once; search saved bytes again offline."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct


RAM_START, RAM_END = 0x00210000, 0x00220000
# Ranges this dongle has answered reads across in full. A capture must sit
# entirely inside one of them. 0x000a0000 and 0x0880a0a8 hang the controller
# and lie outside both; keep them out.
ROM_START, ROM_END = 0x00001000, 0x0009F000
READABLE_RANGES = ((ROM_START, ROM_END), (RAM_START, RAM_END))
WORD_LAYOUTS = {
    "native": (0, 1, 2, 3),
    "swap16": (1, 0, 3, 2),
    "reverse32": (3, 2, 1, 0),
    "swap16_halves": (2, 3, 0, 1),
}


def validate_range(start, words):
    end = start + words * 4
    inside = any(lo <= start < end <= hi for lo, hi in READABLE_RANGES)
    if start % 4 or words < 1 or not inside:
        raise ValueError("Use aligned four-byte words entirely within "
                         "0x00001000..0x0009efff or 0x00210000..0x0021ffff")
    return start, words


def read_descriptors(get_descriptor, expected_identity=(0x0B05, 0x1D70)):
    """Read on EP0, rather than searching for a guessed/cached descriptor."""
    device = bytes(get_descriptor(1, 0, 18))
    if len(device) != 18 or device[:2] != b"\x12\x01":
        raise RuntimeError("The device descriptor must contain exactly 18 bytes")
    if struct.unpack_from("<HH", device, 8) != expected_identity:
        raise RuntimeError("The live USB descriptor identity changed unexpectedly")
    if not device[17]:
        raise RuntimeError("The device advertised no USB configurations")
    descriptors = {"device": device}
    for index in range(device[17]):
        head = bytes(get_descriptor(2, index, 9))
        if len(head) != 9 or head[:2] != b"\x09\x02":
            raise RuntimeError("The configuration descriptor header must contain nine bytes")
        total = struct.unpack_from("<H", head, 2)[0]
        if total < 9:
            raise RuntimeError("Invalid configuration descriptor length")
        config = bytes(get_descriptor(2, index, total))
        if len(config) != total or config[:9] != head:
            raise RuntimeError("Incomplete or changing configuration descriptor")
        # Validate every record before treating its bytes as a search target.
        offset = 0
        while offset < total:
            length = config[offset]
            if length < 2 or offset + length > total:
                raise RuntimeError(f"Malformed configuration descriptor record at offset {offset}")
            offset += length
        descriptors[f"configuration_{index}"] = config
    return descriptors


def descriptor_patterns(descriptors):
    patterns = {name: bytes(data) for name, data in descriptors.items()}
    if "device" in descriptors:
        patterns["device/header"] = bytes(descriptors["device"][:8])
    for name, config in descriptors.items():
        if not name.startswith("configuration_"):
            continue
        offset = 0
        while offset + 2 <= len(config):
            length, kind = config[offset:offset + 2]
            if length < 2 or offset + length > len(config):
                raise ValueError("Malformed saved configuration descriptor")
            if kind in (2, 4, 5) and length >= 7:
                label = {2: "header", 4: "interface", 5: "endpoint"}[kind]
                patterns[f"{name}/{label}@{offset:04x}"] = bytes(config[offset:offset + length])
            offset += length
    return patterns


def find_descriptors(blob, start, descriptors):
    """Search complete descriptors and records, including unaligned matches.

    Transform whole four-byte read words, not the descriptor itself: a pattern
    can start halfway through a read word and span any number of words.
    Addresses identify the read word; byte offsets are in the named layout.
    """
    if len(blob) % 4:
        raise ValueError("RAM dump must contain complete four-byte read responses")
    patterns = descriptor_patterns(descriptors)
    hits = []
    for layout, order in WORD_LAYOUTS.items():
        view = bytes(blob[base + index] for base in range(0, len(blob), 4) for index in order)
        for name, needle in patterns.items():
            if len(needle) < 7:
                continue
            offset = view.find(needle)
            while offset >= 0:
                context_start = max(0, (offset // 4) * 4 - 8)
                hits.append({
                    "pattern": name,
                    "layout": layout,
                    "word_address": f"0x{start + (offset // 4) * 4:08x}",
                    "offset_in_word": offset % 4,
                    "length": len(needle),
                    "context_word_address": f"0x{start + context_start:08x}",
                    "context_hex": view[context_start:offset + min(len(needle), 32) + 8].hex(" "),
                })
                offset = view.find(needle, offset + 1)
    return hits


def print_findings(report):
    print(f"RAM saved: {report['bytes_read']}/{report['words_requested'] * 4} bytes; {report['status']}", flush=True)
    hits = report["hits"]
    if not hits:
        print("No descriptor structures matched the saved bytes.", flush=True)
        return
    print(f"Descriptor matches: {len(hits)} (all contexts are in capture.json)", flush=True)
    for hit in hits[:16]:
        print(f"  {hit['pattern']}: word {hit['word_address']} +{hit['offset_in_word']}, layout {hit['layout']}", flush=True)


def capture(read_word, get_descriptor, output, start=RAM_START, words=16384, metadata=None):
    validate_range(start, words)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report_path, ram_path = output / "capture.json", output / "ram.bin"
    if report_path.exists() or ram_path.exists():
        raise ValueError("Capture directory already contains results; use a new directory")
    report = {
        "schema_version": 1,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "start_address": f"0x{start:08x}",
        "words_requested": words,
        "bytes_read": 0,
        "status": "started",
        "metadata": metadata or {},
        "descriptors": {},
        "hits": [],
        "address_note": "word_address is a four-byte fc61 read address; offset_in_word refers to the named byte layout",
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    descriptors = {}
    blob = bytearray()
    try:
        descriptors = read_descriptors(get_descriptor)
        for name, data in descriptors.items():
            filename = name + ".bin"
            (output / filename).write_bytes(data)
            report["descriptors"][name] = {
                "file": filename, "length": len(data), "hex": data.hex(" "),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            print(f"Live {name}: {len(data)} bytes; saved {filename}", flush=True)
        print(f"Reading {words * 4} RAM bytes at 0x{start:08x}; read-only", flush=True)
        with ram_path.open("xb") as dump:
            for address in range(start, start + words * 4, 4):
                data = bytes(read_word(address))
                if len(data) != 4:
                    raise RuntimeError(f"Short RAM word at 0x{address:08x}")
                dump.write(data)
                blob.extend(data)
                if len(blob) % 1024 == 0:
                    dump.flush()
                    print(f"  {len(blob)}/{words * 4} bytes through 0x{address + 3:08x}", flush=True)
        report["status"] = "complete"
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        report["error"] = "Interrupted by user"
        raise
    except (RuntimeError, ValueError, OSError) as error:
        report["status"] = "partial" if blob else "failed"
        report["error"] = str(error)
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["bytes_read"] = len(blob)
        report["ram_sha256"] = hashlib.sha256(blob).hexdigest()
        report["patterns"] = {name: data.hex(" ") for name, data in descriptor_patterns(descriptors).items()}
        report["hits"] = find_descriptors(blob, start, descriptors)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print_findings(report)
        print(f"Capture: {output}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description="Search a saved descriptor/RAM capture without opening USB")
    parser.add_argument("capture_directory", type=Path)
    args = parser.parse_args()
    root = args.capture_directory
    report = json.loads((root / "capture.json").read_text())
    blob = (root / "ram.bin").read_bytes()
    if len(blob) != report["bytes_read"] or hashlib.sha256(blob).hexdigest() != report["ram_sha256"]:
        parser.error("RAM dump length/checksum does not match capture.json")
    descriptors = {}
    for name, record in report["descriptors"].items():
        # The hex and checksum also allow analysis if a descriptor .bin was moved.
        data = bytes.fromhex(record["hex"])
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            parser.error(f"Descriptor checksum mismatch: {name}")
        descriptors[name] = data
    report["hits"] = find_descriptors(blob, int(report["start_address"], 0), descriptors)
    print_findings(report)
    for hit in report["hits"]:
        print(f"  context {hit['context_word_address']}: {hit['context_hex']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
