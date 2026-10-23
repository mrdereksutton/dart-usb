#!/usr/bin/env python3
"""Replay native enumeration, stream start and rate changes without USB access."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

import native_usb_offline as native
from native_control_offline import build_control_objects, control_replay, CONTROL_SOURCES, EP0

ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_validation(output, images=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    objects = build_control_objects(output / "build")
    m, symbols, layout = control_replay(objects, images)
    get = lambda field: m.call(symbols["control_get"], field)
    events = []

    def transact(name, kind, request, value=0, index=0, length=0, data=None):
        packet = struct.pack("<BBHHH", kind, request, value, index, length)
        result = m.setup(packet)
        require(result is None or result >= 0, f"Native setup rejected {name}")
        response = b""
        if not kind & 0x80 and length:
            require(data is not None and get(5) == 1, "OUT data was not armed")
            m.finish_control(data)
            require(m.call(symbols["control_service"]) == 0, "OUT data application failed")
        if get(5):
            current = get(0)
            response = bytes(m.machine.mem_read(m.word(current), m.word(current + 4))) if kind & 0x80 else b""
            m.finish_control()
        events.append({"host_request": name, "setup_hex": packet.hex(), "setup_callback_result": result,
                       "reply_hex": response.hex(), "configuration": get(1), "alternate": get(2),
                       "rate": get(3), "audio_enabled": bool(get(9))})
        return response

    require(len(transact("device prefix", 0x80, 6, 0x100, length=8)) == 8, "Short descriptor failed")
    device = transact("device descriptor", 0x80, 6, 0x100, length=18)
    require(device[4:8] == bytes([0, 0, 0, 64]), "Profile still advertises Bluetooth class")
    transact("set address", 0, 5, 7)
    address = (m.word(0x400C0800) >> 4) & 127
    require(address == 7, "Captured PCD did not set the virtual device address")
    header = transact("configuration header", 0x80, 6, 0x200, length=9)
    config = transact("configuration descriptor", 0x80, 6, 0x200, length=255)
    require(struct.unpack_from("<H", header, 2)[0] == len(config) == 128, "Configuration length differs")
    transact("configure audio and HID", 0, 9, 2)
    hid = transact("HID report descriptor", 0x81, 6, 0x2200, 2, 96)
    require(len(hid) == 96, "HID report descriptor failed")
    streams = []
    m.iso_result = 0  # stream hardware completion boundary is simulated
    for rate in (44100, 48000):
        transact(f"set rate {rate}", 0x22, 1, 0x100, 0x83, 3, rate.to_bytes(3, "little"))
        require(get(3) == rate, "Rate control did not reach the bridge")
        transact("start audio alternate", 1, 11, 1, 1)
        require(get(9) == 1, "SET_INTERFACE did not start the native endpoint")
        pcm = bytearray(); histogram = Counter(); frames_sent = 0
        initial = get(11)
        for ms in range(32):
            frames = (ms + 1) * rate // 1000 - ms * rate // 1000
            require(m.call(symbols["control_push"], frames_sent, frames) == frames, "PCM input was rejected")
            require(m.call(symbols["control_audio_service"]) == 1, "Native audio service failed")
            call = next(c for c in reversed(m.calls) if c["entry"] == native.ISO_QUEUE)
            driver, endpoint, buffer, dma, length, zero, request, transfer = call["arguments"]
            require((driver, endpoint, dma, length, zero, transfer) ==
                    (m.pcd, native.EP3, buffer, frames * 4, 0, 1), "Native queue arguments differ")
            packet = bytes(m.machine.mem_read(buffer, length))
            require(struct.unpack("<" + str(frames * 2) + "h", packet) ==
                    tuple(v for i in range(frames_sent, frames_sent + frames) for v in (i, -i)),
                    "Native queue received different stereo samples")
            pcm.extend(packet); histogram[length] += 1; frames_sent += frames
            m.call(0x020BD7D8, m.pcd, native.EP3, request, 0, length)
        require(get(11) - initial == 32, "Native completion wrapper did not release every packet")
        transact("stop audio alternate", 1, 11, 0, 1)
        (output / f"enumerated-audio-{rate}.pcm").write_bytes(pcm)
        streams.append({"rate": rate, "packets": 32, "frames": frames_sent,
                        "packet_histogram": dict(sorted(histogram.items())),
                        "pcm_sha256": hashlib.sha256(pcm).hexdigest()})
    report = bytes.fromhex("05 00 55 04 00 38 12 34 7e")
    transact("receive checked iAP frame", 0x21, 9, 0x205, 2, len(report), report)
    require(get(14) == 1, "EP0 did not deliver the checked HID payload")
    transact("unconfigure", 0, 9, 0)
    control_bytes = get(12)
    require(m.call(symbols["control_unbind"]) == 0, "Native callbacks failed to restore")
    restored = {"setup": m.word(0x0030D164), "disconnect": m.word(0x0030D168), "ep0_descriptor": m.word(EP0 + 20)}
    require(restored == {"setup": 0x020BE8A1, "disconnect": 0x020BE7E3, "ep0_descriptor": 0},
            "Restored native ownership differs from the original")
    # Exercise a full native ISO software enqueue after the same host startup,
    # independently of the stream-completion boundary used above.
    probe, ps, _ = control_replay(objects, images)
    for packet in (struct.pack("<BBHHH", 0, 9, 2, 0, 0), struct.pack("<BBHHH", 1, 11, 1, 1, 0)):
        require(probe.setup(packet) == 0, "Native queue probe failed to enumerate")
        probe.finish_control()
    require(probe.call(ps["control_push"], 100, 48) == 48 and
            probe.call(ps["control_audio_service"]) == 1, "Full ISO queue probe failed")
    entry = probe.word(probe.ep3_state + 4)
    queued_request = probe.word(entry)
    first_packet = bytes(probe.machine.mem_read(probe.word(queued_request), 192))
    require(struct.unpack("<96h", first_packet) == tuple(v for i in range(100, 148) for v in (i, -i)),
            "Full native ISO queue received different samples")
    result = {"hardware_access": False, "execution": "compiled ARM setup/audio adapters + captured CU software",
        "control_port_bytes": control_bytes, "arm_image": layout, "native_device_address": address,
        "capture_hashes": {"ram": native.RAM_SHA256, "flash": native.FLASH_SHA256},
        "source_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in CONTROL_SOURCES},
        "compiled_objects": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in objects},
        "host_events": events, "streams": streams, "restored": restored,
        "full_native_iso_enqueue": {"bytes": probe.word(queued_request + 4),
            "endpoint_capacity": probe.word(native.EP3 + 24),
            "packet_sha256": hashlib.sha256(first_packet).hexdigest()},
        "native_paths": ["EP0 dispatcher 0x020bb4a0", "setup dispatcher 0x020ba71e",
            "gadget setup dispatch 0x020bd6e6", "endpoint queue 0x0020c7b0",
            "generic PCD queue and completion", "ISO software queue (first enqueue)",
            "gadget completion dispatch 0x020bd7d8"],
        "model": ["virtual MMIO; intercepted controller activation/transfer programming",
            "virtual allocator and serialized OS helpers; descriptor DMA and FIFO resize disabled",
            "unconfigured composite at bind; fixture supplies virtual identity DMA mapping",
            "simulated DMA completion events; stream ISO boundary intercepted",
            "disable, dequeue and halt operation results simulated"],
        "remaining": ["resident RAM placement and target entry/service scheduling", "device DMA/cache integration",
            "native interrupt IN delivery for metadata", "physical USB enumeration and audio",
            "Bluetooth reception, full iAP session and persistent boot"]}
    for name, data in (("device-descriptor.bin", device), ("configuration-descriptor.bin", config),
                       ("hid-report-descriptor.bin", hid)):
        (output / name).write_bytes(data)
    (output / "native-control-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/native-control-validation-20261019")
    ram, flash = native.default_images()
    parser.add_argument("--ram", type=Path, default=ram)
    parser.add_argument("--flash", type=Path, default=flash)
    args = parser.parse_args()
    report = run_validation(args.output, (args.ram, args.flash))
    print(json.dumps({"output": str(args.output), "host_transactions": len(report["host_events"]),
                      "stream_packets": sum(s["packets"] for s in report["streams"]),
                      "control_port_bytes": report["control_port_bytes"], "hardware_access": False}, indent=2))


if __name__ == "__main__":
    main()
