# Dart USB — ASUS USB-BT600 / RTL8761C research

Open-source tools and hardware research toward a **standalone Bluetooth-to-USB/iPod audio bridge**, using an ASUS USB-BT600 and a 2016 Dodge Dart with the stock 8.4-inch Uconnect system.

The intended path is an iPhone sending wireless audio and track metadata to the dongle, with the dongle presenting the USB audio/iPod interface expected by the car. Making this work requires firmware execution, USB device behavior, Bluetooth audio and metadata handling, and a startup path that survives power loss.

**Status: experimental research. The standalone audio bridge is still in development.** The repository currently provides diagnostic tools, repeatable experiments, hardware observations, and firmware/USB protocol notes.

## What has answered on hardware

| Area | Result |
| --- | --- |
| Device identification | ASUS USB-BT600, USB `0b05:1d70`, Realtek RTL8761CU, ROM version 1 / patch chip ID 2 |
| USB and HCI access | Descriptor, local-version, and ROM-version queries succeeded from macOS Terminal |
| Memory command | Vendor command `0xfc61` returned `b4 88 3b c2` at `0x00217e88` before upload |
| Stock download | Both fragments of the 263-byte upstream payload were accepted; the reported runtime changed from `0x000e8761` to `0x7bf15762` |
| Container/runtime distinction | The file's `0x4618d3f3` container version differs from the runtime HCI version; the original equality check incorrectly reported failure |
| Address to exclude | A read at `0x0880a0a8` timed out and disconnected the controller; it was removed from routine probes |
| Complete bridge | Bluetooth audio reception, USB/iPod streaming, track metadata, and standalone persistence remain implementation milestones |

See [HARDWARE.md](HARDWARE.md) for recorded experiments and the [active pull requests](https://github.com/mrdereksutton/dart-usb/pulls) for newer development. These observations describe the tested adapter and revision; other revisions may differ.

## Current development

[Draft PR #3](https://github.com/mrdereksutton/dart-usb/pull/3) contains Claude-assisted descriptor-search and memory-mapping work, a runtime-version-check correction, and a generic USB descriptor inspection tool. Draft work is separate from `main`; consult its current commits and hardware results before using those options. A byte-pattern match or an unsuccessful scan alone does not determine whether USB behavior can be changed.

The highest-value contributions are:

1. Understand the RTL8761C memory map, patch startup, and larger ASUS `rtl8761cu_mx` firmware path.
2. Find the USB descriptor and EP0 handling path, then determine endpoint capabilities for USB audio.
3. Implement the car-facing UAC1/iAP transport and metadata/control behavior.
4. Implement the Bluetooth audio/metadata path and connect it to USB streaming.
5. Map persistent storage and boot behavior, then demonstrate end-to-end operation in the car.

The exact C-chip capabilities are research questions. References for the older RTL8761B use a different CPU architecture and need separate analysis before reuse.

## Get started

```bash
git clone https://github.com/mrdereksutton/dart-usb.git
cd dart-usb
python3 bt600_probe.py --inspect-stock
```

The inspection command is offline. Hardware tooling currently targets macOS with Python 3 and Homebrew libusb. Begin with the basic descriptor/version probe before selecting an upload or memory experiment. Hardware operations are explicit command-line options, and local transcripts go in the ignored `results/` directory.

## Contribute

Read [CONTRIBUTING.md](CONTRIBUTING.md) for experiment reports, pull requests, and collaboration practices. [CLAUDE.md](CLAUDE.md) is the assistant handoff. Contributions from embedded ARM, Bluetooth, USB device, audio, and firmware researchers are especially useful. Open an [issue](https://github.com/mrdereksutton/dart-usb/issues) with a reproducible finding or a focused proposal.

## License and third-party material

Original project code and documentation are available under the [MIT License](LICENSE). Embedded Realtek firmware has separate terms in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt); it is not relicensed under MIT. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for scope and provenance. This is an independent community project; product names identify the hardware and protocols under investigation.

## Tool reference

Repurpose an ASUS USB-BT600 so an iPhone can send wireless audio and song information to a 2016 Dodge Dart's stock 8.4-inch Uconnect through its USB input.

The current work is identifying how the RTL8761C controller loads code, accesses memory, and stores firmware. The USB/iPod bridge is still to be implemented.

### Research notes

- [CLAUDE.md](CLAUDE.md): project handoff and the next research task.
- [HARDWARE.md](HARDWARE.md): the dongle's actual USB/HCI responses.
- [FIRMWARE.md](FIRMWARE.md): stock image layout, sources, and the ARM disassembly question.
- [bt600_probe.py](bt600_probe.py): the working version probe and experimental upload/read options.
- [USB_BRIDGE.md](USB_BRIDGE.md): USB audio/iAP implementation references and the hardware work needed to port them.

### Run the probe

Use Python 3 on macOS with the existing Homebrew libusb installation. The script checks `/opt/homebrew/lib` and `/usr/local/lib`.

```bash
python3 bt600_probe.py
```

This command has been run on the actual dongle. Its output is recorded in `HARDWARE.md`.

Inspect the embedded stock patch without opening USB:

```bash
python3 bt600_probe.py --inspect-stock
python3 -m unittest -v test_probe.py
```

### Hardware experiment runner

Run the complete sequence from normal macOS Terminal:

```bash
python3 run_bt600_experiment.py
```

It collects a baseline, uploads the matching stock host-loaded patch, checks the resulting version, and reads the RAM address that answered on this dongle. It saves timestamped text and JSON output in `results/`, which is excluded from Git. Any failed phase stops the sequence. Use `--read-only` to collect only the baseline and the RAM query.

The chat process cannot open raw USB; normal Terminal has already queried this dongle successfully. The saved results can be read locally without copying Terminal output into chat.

Individual upload command:

```bash
python3 bt600_probe.py --load-stock
```

This sends the stock RTL8761CU driver patch selected for the detected ROM and reads the version back. For this dongle, ROM version 1 selects chip ID 2. The container version is `0x4618d3f3`; the actual runtime HCI version pair after this upload is `0x7bf15762`.

The upload ran on this dongle at 05:38 UTC on 2026-10-16. Both fragments were accepted and the runtime changed from `0x000e8761` to `0x7bf15762`. The main-branch version check originally required the container version as the runtime value and stopped. The correction is included in the active development work in [PR #3](https://github.com/mrdereksutton/dart-usb/pull/3); consult that PR before repeating an upload. This confirms the download/version transition; Bluetooth initialization and bridge operation remain separate work.

An additional experiment tests whether the C chip accepts the B family's memory-read command:

```bash
python3 bt600_probe.py --probe-memory
```

That option reads four bytes at `0x00217e88`. The actual dongle answered this query on 2026-10-16. The former `0x0880a0a8` candidate timed out and disconnected the controller, so it has been removed. Queries at zero and four returned zeroes and are also omitted from the normal run. It does not write memory.

An optional bounded range reader is available for the next mapping step:

```bash
python3 bt600_probe.py --read-range 0x00217e88 64
```

It permits 1..256 four-byte words, aligned to four bytes, entirely within `0x00217000..0x00217fff`. That page is an experiment boundary around the responding address, not a measured RAM map. Only `0x00217e88` has returned data so far. The default runner does not expand into a range read. Each completed word is printed immediately; any rejected, malformed, or timed-out read stops with an error. Finding the detected ROM's stock prologue identifies a candidate load address, which still needs execution/mapping evidence.

The loader reassembles HCI events across USB packets, reports Command Status errors, checks fragment acknowledgements, and returns an error if the version after upload does not match. Run the offline suite with `python3 -m unittest -v`.

### Firmware provenance

The script embeds the original `rtl8761cu_fw.bin` and `rtl8761cu_config.bin` from `linux-firmware`, with SHA-256 checks before use. The stock file is selected and framed in the same way as Linux `btrtl.c`. Realtek's binary license is in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt). Project-authored code is separate from those vendor firmware bytes.

### Working together

Keep changes focused on the dongle and USB bridge. Record actual hardware output alongside each experiment. Claude Code can begin with `CLAUDE.md`; no Claude session is launched by this repository.
