#!/usr/bin/env python3
"""Build and exercise portable receiver firmware entirely offline.

Only standard Python, clang, and our host-only executable are used. This script
does not import the USB probes, load libusb, or open any USB device.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import wave
import zipfile


ROOT = Path(__file__).resolve().parent
SOURCES = ("usb_audio_source.c", "iap_hid.c", "iap_metadata.c", "usb_bridge.c")
PUBLIC_FILES = (
    *(f"firmware/{name}" for name in SOURCES),
    "firmware/usb_audio_source.h", "firmware/iap_hid.h", "firmware/iap_metadata.h",
    "firmware/usb_bridge.h", "tests/offline_bridge_demo.c", "tests/usb_bridge_host_test.c",
    "test_usb_bridge.py", "run_offline_bridge_demo.py", "LICENSE",
    "firmware/README.md", "firmware/BRIDGE.md",
)


def run(command, commands):
    commands.append([str(part) for part in command])
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"Build/demo failed ({result.returncode}):\n{result.stdout}{result.stderr}")
    return result.stdout


def decode_audio_packets(data, rate, seconds):
    """Independently check every USB packet boundary before reconstructing PCM."""
    offset = 0
    pcm = bytearray()
    sizes = Counter()
    for millisecond in range(seconds * 1000):
        if offset + 2 > len(data):
            raise ValueError("Truncated USB packet length")
        length = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        expected = (((millisecond + 1) * rate // 1000) - (millisecond * rate // 1000)) * 4
        if length != expected or offset + length > len(data):
            raise ValueError(f"Invalid audio packet at millisecond {millisecond}")
        pcm.extend(data[offset:offset + length])
        offset += length
        sizes[length] += 1
    if offset != len(data) or len(pcm) != rate * seconds * 4:
        raise ValueError("Extra packet bytes or incorrect audio duration")
    return bytes(pcm), dict(sorted(sizes.items()))


def decode_iap_reports(reports):
    """Decode device reports without using the C encoder/decoder implementation."""
    data_sizes = {1: 12, 2: 14, 3: 20, 4: 63}
    if not reports:
        raise ValueError("No HID reports")
    report_id = reports[0][0]
    frame = bytearray()
    for i, report in enumerate(reports):
        if not report or report[0] != report_id or len(report) != data_sizes.get(report_id, -2) + 1:
            raise ValueError("Inconsistent HID report ID or declared size")
        expected_control = 0 if len(reports) == 1 else 2 if i == 0 else 1 if i == len(reports) - 1 else 3
        if report[1] != expected_control:
            raise ValueError("Incorrect HID fragment sequence")
        frame.extend(report[2:])
    if len(frame) < 3 or frame[0] != 0x55:
        raise ValueError("Missing iAP frame header")
    if frame[1]:
        header, size = 2, frame[1]
    else:
        if len(frame) < 5:
            raise ValueError("Truncated extended iAP header")
        header, size = 4, int.from_bytes(frame[2:4], "big")
    end = header + size + 1
    if not size or len(frame) < end or sum(frame[1:end]) % 256:
        raise ValueError("Invalid iAP length or checksum")
    if any(frame[end:]):
        raise ValueError("Device report padding is not zero")
    return bytes(frame[header:end - 1])


def inspect_configuration(data):
    if len(data) < 9 or data[:2] != b"\x09\x02" or int.from_bytes(data[2:4], "little") != len(data):
        raise ValueError("Configuration descriptor length mismatch")
    interfaces, endpoints = [], []
    offset = 0
    while offset < len(data):
        size = data[offset]
        if size < 2 or offset + size > len(data):
            raise ValueError("Malformed descriptor boundary")
        part = data[offset:offset + size]
        if part[1] == 4:
            if size != 9:
                raise ValueError("Malformed interface")
            interfaces.append({"number": part[2], "alternate": part[3], "endpoint_count": part[4],
                               "class": part[5], "subclass": part[6]})
        if part[1] == 5:
            if size not in (7, 9):
                raise ValueError("Malformed endpoint")
            endpoints.append({"address": f"0x{part[2]:02x}", "attributes": part[3],
                              "max_packet_bytes": int.from_bytes(part[4:6], "little"),
                              "interval_ms": part[6]})
        offset += size
    if {(i["number"], i["alternate"]) for i in interfaces} != {(0, 0), (1, 0), (1, 1), (2, 0)}:
        raise ValueError("Incorrect audio/HID interface topology")
    if {(e["address"], e["max_packet_bytes"]) for e in endpoints} != {("0x83", 192), ("0x81", 64)}:
        raise ValueError("Incorrect endpoint topology")
    return {"configuration_value": data[5], "descriptor_bytes": len(data),
            "interfaces": interfaces, "endpoints": endpoints}


def inspect_arm_object(path):
    """Read ELF32 symbol/section tables; do not load or execute the object."""
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 40:
        raise ValueError("Expected a little-endian ARM ELF32 object")
    table = struct.unpack_from("<I", data, 32)[0]
    stride, count = struct.unpack_from("<HH", data, 46)
    sections = [struct.unpack_from("<10I", data, table + i * stride) for i in range(count)]
    defined, undefined = set(), set()
    allocated = sum(s[5] for s in sections if s[2] & 2)
    text = sum(s[5] for s in sections if s[2] & 4)
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for offset in range(section[4], section[4] + section[5], section[9]):
            name, _, _, info, _, index = struct.unpack_from("<IIIBBH", data, offset)
            if not name or info >> 4 not in (1, 2):
                continue
            symbol = names[name:].split(b"\0", 1)[0].decode("ascii")
            (defined if index else undefined).add(symbol)
    return {"file": path.name, "text_bytes": text, "allocated_section_bytes": allocated,
            "defined_symbols": sorted(defined), "undefined_symbols": sorted(undefined)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=4, help="audio seconds at each rate (1..30)")
    parser.add_argument("--output", type=Path, help="new output folder; existing folders are never overwritten")
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 30:
        parser.error("--seconds must be between 1 and 30")
    compiler = shutil.which("clang")
    if not compiler:
        parser.error("clang is required (macOS Command Line Tools)")
    output = (args.output or ROOT / "results" / ("offline-bridge-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))).resolve()
    if output == ROOT or ROOT.is_relative_to(output) or output.is_relative_to(ROOT / "firmware") or output.is_relative_to(ROOT / "tests"):
        parser.error("choose a separate artifact folder, normally under results/")
    output.mkdir(parents=True, exist_ok=False)
    build = output / "build"
    build.mkdir()
    commands = []
    common = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "firmware")]
    executable = build / "offline-bridge-demo"
    run([*common, "-O2", str(ROOT / "tests/offline_bridge_demo.c"),
         *(str(ROOT / "firmware" / name) for name in SOURCES), "-lm", "-o", str(executable)], commands)
    trace = run([str(executable), str(output), str(args.seconds)], commands)
    (output / "host-events.jsonl").write_text(trace)
    events = [json.loads(line) for line in trace.splitlines()]
    if any(event.get("hardware_access") for event in events):
        raise ValueError("Unexpected hardware-access event")
    audio = []
    for event in events:
        if event["event"] != "audio":
            continue
        rate = event["sample_rate"]
        pcm, histogram = decode_audio_packets((output / event["packet_file"]).read_bytes(), rate, args.seconds)
        if event["frames"] != len(pcm) // 4 or event["missing_frames"] or event["rejected_frames"]:
            raise ValueError("C firmware reported dropped or missing audio")
        wav_path = output / f"audio-{rate}.wav"
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm)
        audio.append({**event, "wav_file": wav_path.name, "packet_size_histogram": histogram,
                      "pcm_sha256": hashlib.sha256(pcm).hexdigest()})
    if {item["sample_rate"] for item in audio} != {44100, 48000}:
        raise ValueError("Both audio rates must have been exercised")
    metadata = next(event for event in events if event["event"] == "metadata")
    reports = [bytes.fromhex(report) for report in metadata["reports_hex"]]
    payload = decode_iap_reports(reports)
    if payload.hex() != metadata["payload_hex"] or payload[:3] != bytes([4, 0, 0x21]) or payload[-1] != 0:
        raise ValueError("Metadata reply did not survive HID transport")
    title = payload[3:-1].decode("utf-8")
    if len(reports) < 2:
        raise ValueError("Demo title must exercise fragmentation")
    profile = inspect_configuration((output / "configuration.bin").read_bytes())
    arm_objects = []
    for name in SOURCES:
        object_path = build / (Path(name).stem + ".o")
        run([*common, "-target", "armv8m.main-none-eabi", "-mcpu=cortex-m33+nodsp", "-mthumb", "-mno-unaligned-access",
             "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-Os", "-c",
             str(ROOT / "firmware" / name), "-o", str(object_path)], commands)
        arm_objects.append(inspect_arm_object(object_path))
    defined = {name for obj in arm_objects for name in obj["defined_symbols"]}
    unresolved = {name for obj in arm_objects for name in obj["undefined_symbols"]} - defined
    if unresolved:
        raise ValueError(f"Unexpected ARM runtime dependencies: {sorted(unresolved)}")
    state_bytes = next(event["bridge_state_bytes"] for event in events if event["event"] == "build")
    report = {"generated_utc": datetime.now(timezone.utc).isoformat(),
              "execution": "Offline host executable using the portable C firmware; no USB backend",
              "hardware_access": False, "bridge_state_bytes": state_bytes,
              "profile": profile, "audio": audio,
              "metadata": {"title": title, "hid_report_count": len(reports), "payload_hex": payload.hex(),
                           "session_mode": "legacy, without transaction IDs; IDPS is not simulated"},
              "arm_target": "armv8m.main-none-eabi / ARMv8-M Mainline without DSP / Thumb", "arm_objects": arm_objects,
              "combined_unresolved_symbols": [], "build_commands": commands,
              "remaining_integration": ["RTL8761C endpoint queues and EP0 controller port",
                  "iAP IDPS/authentication and digital-audio session", "Bluetooth A2DP/SBC and AVRCP",
                  "Persistent startup and testing in the Dart"]}
    (output / "demo.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "README.txt").write_text(
        "Dart USB receiver firmware: offline demo\n\n"
        "Listen to audio-48000.wav or audio-44100.wav. They contain an original stereo\n"
        "tone melody generated on this computer, passed through the actual C firmware's\n"
        "PCM ring buffer and USB packetizer, then decoded from the saved packet files.\n\n"
        "The simulated host enumerates audio/HID interfaces, selects a sample rate,\n"
        "starts/stops streaming, and asks for a track title through a real iAP frame.\n"
        "The firmware returns the title in multiple HID reports; Python independently\n"
        "checks their sequence and checksum. demo.json and host-events.jsonl record it.\n\n"
        "build/ contains ARM object files and the host demo. source/ contains the\n"
        "portable implementation, tests and builder. From source/, rerun with:\n"
        "  python3 -m unittest -v test_usb_bridge\n"
        "  python3 run_offline_bridge_demo.py\n\n"
        "This run does not touch the BT600. The device endpoint port, Bluetooth\n"
        "receiver, full iAP session and persistent boot still need integration.\n")
    for relative in PUBLIC_FILES:
        destination = output / "source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            files.append({"path": str(path.relative_to(output)), "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
    (output / "manifest.json").write_text(json.dumps(files, indent=2) + "\n")
    archive = output / "dart-usb-offline-bridge.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for item in files:
            bundle.write(output / item["path"], item["path"])
        bundle.write(output / "manifest.json", "manifest.json")
    print(json.dumps({"output": str(output), "archive": str(archive), "audio": audio,
                      "metadata_title": title, "metadata_reports": len(reports),
                      "bridge_state_bytes": state_bytes,
                      "arm_text_bytes": sum(obj["text_bytes"] for obj in arm_objects),
                      "unresolved_arm_symbols": sorted(unresolved)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
