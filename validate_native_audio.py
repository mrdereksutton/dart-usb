#!/usr/bin/env python3
"""Compile ARM audio code and replay it with captured BT600 queue routines offline."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from arm_object_loader import load_arm_objects
import native_usb_offline as native


ROOT = Path(__file__).resolve().parent
SOURCES = ("firmware/usb_audio_source.c", "firmware/iap_hid.c", "firmware/iap_metadata.c",
           "firmware/usb_bridge.c", "firmware/rtl8761c_audio_port.c", "tests/rtl8761c_arm_fixture.c")
DISABLE = 0x020BD3B2
DEQUEUE = 0x020BD492


def build_objects(directory, sources=None):
    compiler = shutil.which("clang")
    if not compiler:
        raise RuntimeError("clang is required for the offline ARM replay")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    objects = []
    for relative in SOURCES if sources is None else sources:
        path = directory / (Path(relative).stem + ".o")
        result = subprocess.run([compiler, "-target", "armv8m.main-none-eabi", "-mcpu=cortex-m33+nodsp",
            "-mthumb", "-mno-unaligned-access", "-std=c11", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
            "-Os", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "firmware"),
            "-c", str(ROOT / relative), "-o", str(path)], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr)
        objects.append(path)
    return objects


def replay(objects, rate=48000, images=None):
    machine = native.NativeUsbEmulator(*(images or native.default_images()))
    symbols, layout = load_arm_objects(machine.machine, objects)
    if machine.call(symbols["fixture_init"], rate) != 0:
        raise RuntimeError("Compiled adapter rejected the saved CU profile")
    if machine.call(symbols["fixture_start"]) != 0:
        raise RuntimeError("Captured endpoint-enable routine rejected the descriptor")
    return machine, symbols, layout


def complete(machine, request, status=0, actual=None):
    if actual is None:
        actual = machine.word(request + 4)
    machine.put_word(request + 0x1c, status)
    machine.put_word(request + 0x20, actual)
    machine.call(machine.word(request + 0x0c), native.EP3, request)


def run_validation(output, milliseconds=1000, images=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    objects = build_objects(output / "build")
    # First, leave the ISO software queue intact, intercepting only its hardware
    # programming boundary and OS helpers. This verifies a real native enqueue.
    machine, symbols, layout = replay(objects, images=images)
    request_bytes = machine.call(symbols["fixture_size"], 0)
    port_bytes = machine.call(symbols["fixture_size"], 1)
    if machine.call(symbols["fixture_push"], 48, 100) != 48 or machine.call(symbols["fixture_service"]) != 1:
        raise RuntimeError("The compiled adapter failed to submit its first packet")
    pcd_request = machine.word(machine.ep3_state + 4)
    original_request = machine.word(pcd_request)
    buffer = machine.word(original_request)
    packet = bytes(machine.machine.mem_read(buffer, 192))
    if struct.unpack("<96h", packet) != tuple(v for i in range(100, 148) for v in (i, -i)):
        raise RuntimeError("Captured software queue received different PCM")
    native_result = {"endpoint_max_packet": machine.word(native.EP3 + 24),
                     "pcd_max_packet": (machine.word(machine.ep3_state + 20) >> 18) & 2047,
                     "native_queue_status": machine.word(original_request + 28),
                     "pcd_queue_entry": pcd_request, "request_address": original_request,
                     "packet_sha256": hashlib.sha256(packet).hexdigest(),
                     "hardware_boundary_calls": machine.calls,
                     "simulated_register_accesses": machine.register_accesses}
    if native_result["endpoint_max_packet"] != 192 or native_result["pcd_max_packet"] != 192:
        raise RuntimeError("Native endpoint and controller sizes disagree")
    streams = []
    for rate in (44100, 48000):
        machine, symbols, _ = replay(objects, rate, images=images)
        machine.iso_result = 0  # simulate transfer completion below the real queue wrapper
        pcm = bytearray()
        sizes = Counter()
        frames_sent = 0
        for ms in range(milliseconds):
            frames = (ms + 1) * rate // 1000 - ms * rate // 1000
            first = frames_sent % 30000
            if machine.call(symbols["fixture_push"], frames, first) != frames:
                raise RuntimeError("Audio producer overran its buffer")
            if machine.call(symbols["fixture_service"]) != 1:
                raise RuntimeError("Adapter failed to submit an available frame")
            call = machine.calls[-1]
            if call["entry"] != native.ISO_QUEUE:
                raise RuntimeError("Native wrapper did not select the ISO IN queue")
            driver, endpoint, buffer, dma, length, zero, request, transfer = call["arguments"]
            if (driver, endpoint, dma, length, zero, transfer) != (machine.pcd, native.EP3, buffer, frames * 4, 0, 1):
                raise RuntimeError("C request and native argument mapping disagree")
            packet = bytes(machine.machine.mem_read(buffer, length))
            expected = tuple(v for i in range(first, first + frames) for v in (i, -i))
            if struct.unpack("<" + str(frames * 2) + "h", packet) != expected:
                raise RuntimeError("Native wrapper received discontinuous or swapped PCM")
            pcm.extend(packet); sizes[length] += 1; frames_sent += frames
            complete(machine, request)
        queued = machine.call(symbols["fixture_stat"], 0)
        completed = machine.call(symbols["fixture_stat"], 1)
        if queued != milliseconds or completed != milliseconds:
            raise RuntimeError("Completion ownership accounting failed")
        (output / f"native-wrapper-{rate}.pcm").write_bytes(pcm)
        streams.append({"rate": rate, "milliseconds": milliseconds, "frames": frames_sent,
                        "queued": queued, "completed": completed,
                        "packet_histogram": dict(sorted(sizes.items())),
                        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
                        "low_level_transfer_completion": "intercepted and simulated"})
    report = {"execution": "Compiled ARM adapter + captured CU endpoint routines in Unicorn virtual memory",
              "hardware_access": False, "capture_hashes": {"ram": native.RAM_SHA256, "flash": native.FLASH_SHA256},
              "arm_image": layout, "native_request_bytes": request_bytes, "audio_port_bytes": port_bytes,
              "compiled_objects": [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                   for p in objects],
              "source_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES},
              "model": {"descriptor_dma": False, "dynamic_fifo_resize": False,
                        "controller_registers": "virtual, zero-initialized",
                        "activation_and_transfer_register_programming": "intercepted",
                        "stream_completions": "simulated after each native wrapper submission"},
              "native_first_enqueue": native_result, "stream_replays": streams,
              "remaining": ["Device-side DMA/cache mapping", "Native EP0 integration and session startup",
                            "Live controller/USB timing validation", "Bluetooth receiver and persistent boot"]}
    (output / "native-audio-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/native-audio-validation-20261019")
    ram, flash = native.default_images()
    parser.add_argument("--ram", type=Path, default=ram)
    parser.add_argument("--flash", type=Path, default=flash)
    args = parser.parse_args()
    report = run_validation(args.output, images=(args.ram, args.flash))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
