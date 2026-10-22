# Dart USB — ASUS USB-BT600 / RTL8761C research

Build a standalone **iPhone → Bluetooth → ASUS USB-BT600 → USB/iPod → Uconnect**
audio bridge for a 2016 Dodge Dart with the factory 8.4-inch system. The existing
dongle should start from the car's USB power, without the Mac or a firmware reload.

**Current status — October 22, 2026:** five-minute physical USB test audio works.
Bluetooth music reception, persistent startup and playback in the car remain unfinished.

## Measured progress

| Component | Latest result |
| --- | --- |
| Native macOS transport | IOUSBHost opens the existing HCI interface directly; one foreground worker owns a device lease |
| Target RAM code | Checked pool-5 allocation, upload/readback, native USB callbacks and verified cleanup |
| Physical USB audio | 300 seconds of 48 kHz stereo test tone: 300,000 consecutive packets, 57,600,000 bytes, zero missing packets or bad PCM |
| Streaming service | The BT600 refills the native USB queue from IRQ 48; the Mac sends no refill requests during capture |
| Cancellation | Bounded SIGINT trials drained requests and restored callbacks, descriptors, scratch and heap |
| Application backup | Two complete native SPI copies of the 294,912-byte application match the preserved CPU capture |
| Image validation | Captured CU images pass CRC16, SHA-256 and RSA-PSS checks; parser also handles the SDK stack's 222-byte PSS salt |
| Receiver candidate | The SDK 2M stack fits the blank address window and matches the CU ROM UUID; its initializer passes isolated ARM replay |
| Storage trial | The first fixed-padding program returned completion but changed no bytes; live status reads show protection over that address |
| Post-trial verification | All padding bytes and two new full application copies match the originals; callbacks and heap restored |

The USB capture contains generated test audio. End-to-end iPhone music and the
required two cold starts are pending. The new temporary-unlock path passes offline
checks and has **not been executed on hardware**.

Read [BT600_SPRINT.md](BT600_SPRINT.md) for the physical stream and backup results,
[RECEIVER_PORT.md](RECEIVER_PORT.md) for the receiver/storage continuation, and
[the compact evidence record](evidence/bt600-checkpoint-20261022.json) for measured
counts and hashes. Raw firmware, audio captures and device logs remain local in
ignored `results/` directories.

## Development

Current implementation branch:
[`codex/bt600-descriptor-targets`](https://github.com/mrdereksutton/dart-usb/tree/codex/bt600-descriptor-targets).
It includes the portable PCM/iAP core, native USB audio and control adapters,
restored RAM trials, physical capture tooling, image validation and receiver analysis.

The next integration work is:

1. Complete the fixed-padding write/readback/erase/restore trial with the original
   protection state restored after each operation.
2. Back up the candidate stack's physical storage window and establish ownership
   of its RAM data/BSS before loading it.
3. Bind one-phone SBC reception to the existing PCM buffer and USB adapters.
4. Implement verified persistent startup, then test Uconnect negotiation and
   five minutes of music followed by two Mac-disconnected cold starts.

The 4M SDK stack overlaps the active OTA header; use the evaluated 2M candidate.
Keep Uconnect firmware unchanged. Efuse changes and blind full-image upgrades
are outside this implementation path.

## Build and check offline

```sh
git clone https://github.com/mrdereksutton/dart-usb.git
cd dart-usb
git checkout codex/bt600-descriptor-targets
python3 bt600_probe.py --inspect-stock
python3 -m unittest -v
```

The stock inspection reads the embedded patch only. The complete local suite
passes **230 tests with zero failures, errors or skips** using the pinned captures
and SDK references. Tests that require those local files or optional ARM tools
may skip in a fresh clone. [requirements-offline-arm.txt](requirements-offline-arm.txt)
lists the emulator/disassembler dependencies. Native compilation uses warnings as
errors and targets ARMv8-M without optional DSP or unaligned accesses.

See [firmware/README.md](firmware/README.md),
[firmware/NATIVE_AUDIO_PORT.md](firmware/NATIVE_AUDIO_PORT.md) and
[firmware/CONTROL_PORT.md](firmware/CONTROL_PORT.md) for module APIs and replay checks.

## Hardware workflow

Hardware work resumed with the owner's authorization on October 19. Use the
native IOUSBHost flow in [HARDWARE_RESUME.md](HARDWARE_RESUME.md). Each trial requires
the scoped local resume record, verified capture/build inputs and a unique output
report; it exits after restoring the owned USB/RAM state. Build commands alone
never start a hardware trial.

The legacy `USB_ACCESS_DISABLED` files remain active in both local checkouts.
They block the older libusb claim paths involved in the incidents recorded in
[CRASH_INCIDENT.md](CRASH_INCIDENT.md). Older libusb scripts are retained as research
history; the current BT600 trials use `bt600_native_hci.m`.

## Research and collaboration

- [SESSION_NOTES.md](SESSION_NOTES.md): chronological results and handoff.
- [FIRMWARE.md](FIRMWARE.md): memory map, firmware captures and corrected findings.
- [USB_BRIDGE.md](USB_BRIDGE.md) and [IPOD_PROTOCOL.md](IPOD_PROTOCOL.md): USB/iAP references.
- [UCONNECT_TARGET.md](UCONNECT_TARGET.md): the car and acceptance target.
- [IPOD_REFERENCE.md](IPOD_REFERENCE.md): the physical iPod reference work.
- [CONTRIBUTING.md](CONTRIBUTING.md): reproducible reports and contributions.
- [CLAUDE.md](CLAUDE.md): assistant handoff and working constraints.

Contributions from embedded ARM, Bluetooth, USB device and audio developers are
welcome through [issues](https://github.com/mrdereksutton/dart-usb/issues) and
[pull requests](https://github.com/mrdereksutton/dart-usb/pulls).

## License and third-party material

Original code and documentation use the [MIT License](LICENSE). Realtek firmware
has separate terms in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt)
and is not relicensed under MIT. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for provenance. This is an independent community project; product names identify
the hardware and protocols being investigated.
