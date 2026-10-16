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
| RAM write | `0xfc62` changed one word at `0x00210000`; readback matched and the original word was restored |
| Stock download | Both fragments of the 263-byte upstream payload were accepted; the reported runtime changed from `0x000e8761` to `0x7bf15762` |
| Container/runtime distinction | The file's `0x4618d3f3` container version differs from the runtime HCI version; the original equality check incorrectly reported failure |
| Address to exclude | A read at `0x0880a0a8` timed out and disconnected the controller; it was removed from routine probes |
| Complete bridge | Bluetooth audio reception, USB/iPod streaming, track metadata, and standalone persistence remain implementation milestones |

See [HARDWARE.md](HARDWARE.md) for recorded experiments and the [active pull requests](https://github.com/mrdereksutton/dart-usb/pulls) for newer development. These observations describe the tested adapter and revision; other revisions may differ.

## Current development

[Draft PR #3](https://github.com/mrdereksutton/dart-usb/pull/3) contains descriptor search and memory mapping, the RAM write experiment, a runtime-version-check correction, USB inspection, saved USB/RAM capture, and an iPod Classic reference capture. Draft work is separate from `main`; use its branch for the new capture commands. The owner has an iPod Classic available for comparison with the BT600 and the Dart.

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
- [IPOD_REFERENCE.md](IPOD_REFERENCE.md): use the owner's iPod Classic as a USB/car reference.

### Run the probe

Use Python 3 on macOS with the existing Homebrew libusb installation. The script checks `/opt/homebrew/lib` and `/usr/local/lib`.

```bash
python3 bt600_probe.py
```

This command has been run on the actual dongle. Its output is recorded in `HARDWARE.md`.

### Compare dongles

`usb_inspect.py` dumps the real USB descriptors of any connected device, for comparing hardware in practice rather than from assumptions. Read-only standard requests only; no vendor or HCI commands.

```bash
python3 usb_inspect.py            # one-line summary of every USB device
python3 usb_inspect.py 0b05:1d70  # full dump of one VID:PID (class, interfaces, endpoints)
```

Plug in a dongle, run the summary to find its line, then re-run with its `VID:PID` for the full interface/endpoint breakdown.

Inspect the embedded stock patch without opening USB:

```bash
python3 bt600_probe.py --inspect-stock
python3 -m unittest -v test_probe.py
```

### Hardware experiment runner

Capture the actual USB descriptors and one RAM image from normal macOS Terminal:

```bash
python3 run_descriptor_experiment.py
```

This reads the live device and configuration descriptors over EP0, then saves
the same `0x00210000..0x0021ffff` RAM window previously scanned by Claude.
It searches for full descriptors, the device header, and individual configuration,
interface, and endpoint records in four word layouts. Interface/endpoint searches
can find USB structures even when the vendor/product bytes are absent.

Each run creates `results/descriptor-TIMESTAMP/` with `ram.bin`, raw descriptor
`.bin` files, `capture.json`, `run.json`, and `transcript.txt`. A failed read stops
immediately and preserves completed words. A Ctrl-C interruption also saves them.
Progress is printed every KiB. There is no firmware upload, memory write, reset,
or kernel-driver detach in this command. It works with the current ROM or already
loaded stock patch and records which version answered.

Analyze that same dump again without touching the dongle:

```bash
python3 descriptor_capture.py results/descriptor-TIMESTAMP
```

Matches identify a four-byte read address and a byte offset in the named layout;
`capture.json` includes the surrounding bytes. Use those addresses to inspect the
USB data path before choosing a descriptor edit. A search with no matches means
those structures were absent from the captured window at that time.

The chat process cannot open raw USB; normal Terminal can. Saved results can be
read locally without copying Terminal output into chat. Raw captures are excluded
from Git.

The owner also has an iPod Classic. With it connected to the Mac in normal mode:

```bash
python3 capture_ipod.py
```

This finds a USB product named iPod, captures its device descriptor and every
advertised configuration, and saves a readable interface/endpoint table plus raw
bytes under `results/ipod-TIMESTAMP-N/`. It uses standard descriptor requests;
it does not claim interfaces, change configuration, access the music disk, sync,
or send iAP commands. See [IPOD_REFERENCE.md](IPOD_REFERENCE.md) for the car comparison.

The earlier `run_bt600_experiment.py` remains available for baseline/upload/RAM
diagnostics. Those capabilities have already answered on hardware; the next step
is the saved descriptor/RAM capture above.

Individual upload command:

```bash
python3 bt600_probe.py --load-stock
```

This sends the stock RTL8761CU driver patch selected for the detected ROM and reads the version back. For this dongle, ROM version 1 selects chip ID 2. The container version is `0x4618d3f3`; the running version observed after upload is `0x7bf15762`.

The upload ran on this dongle at 05:38 UTC on 2026-10-16. Both fragments were acknowledged and the runtime changed from `0x000e8761` to `0x7bf15762`. This command leaves USB configuration 1 active after a successful upload so a second probe can query the running patch. The descriptor capture does not need another upload.

An additional experiment tests whether the C chip accepts the B family's memory-read command:

```bash
python3 bt600_probe.py --probe-memory
```

That option reads four bytes at `0x00217e88`. The actual dongle answered this query on 2026-10-16. The former `0x0880a0a8` candidate timed out and disconnected the controller, so it has been removed. Queries at zero and four returned zeroes and are also omitted from the normal run. It does not write memory.

An optional bounded range reader is available for the next mapping step:

```bash
python3 bt600_probe.py --read-range 0x00217e88 64
```

It permits 1..256 four-byte words, aligned to four bytes, entirely within `0x00217000..0x00217fff`. This older reader retains its original page boundary; the saved descriptor capture uses the wider 64 KiB RAM window subsequently scanned on this unit. Each completed word is printed immediately; any rejected, malformed, or timed-out read stops with an error.

To locate where the controller keeps its own USB identity — the gate for whether the dongle can be made to enumerate as anything other than a Bluetooth controller:

```bash
python3 bt600_probe.py --find-descriptor
```

This older mode searches four byte arrangements of the `0b05:1d70` vendor/product bytes. It defaults to `0x00210000` for `16384` words and accepts an explicit `START WORDS`; it stops on the first failed read and prints a context window around any hit. It does not write memory and does not read `0x0880a0a8`. On 2026-10-16 the signature was absent from that RAM window. The newer capture searches configuration/interface/endpoint structures as well and saves the memory for further analysis.

The earlier coarse memory-map mode is retained for reference:

```bash
python3 bt600_probe.py --map-memory
```

This samples one word per 4 KB page across `0x0..0x400000`. On this dongle, the read at `0x000a0000` hung the controller; do not repeat that sweep as preparation for the new capture. The new capture is limited to `0x00210000..0x0021ffff`.

The loader reassembles HCI events across USB packets, reports Command Status errors, checks fragment acknowledgements, and checks that the running version changes after upload. Run the offline suite with `python3 -m unittest -v`.

### Firmware provenance

The script embeds the original `rtl8761cu_fw.bin` and `rtl8761cu_config.bin` from `linux-firmware`, with SHA-256 checks before use. The stock file is selected and framed in the same way as Linux `btrtl.c`. Realtek's binary license is in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt). Project-authored code is separate from those vendor firmware bytes.

### Working together

Keep changes focused on the dongle and USB bridge. Record actual hardware output alongside each experiment. Claude Code can begin with `CLAUDE.md`; no Claude session is launched by this repository.
