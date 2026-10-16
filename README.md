# Dart USB

Repurpose an ASUS USB-BT600 so an iPhone can send wireless audio and song information to a 2016 Dodge Dart's stock 8.4-inch Uconnect through its USB input.

The current work is identifying how the RTL8761C controller loads code, accesses memory, and stores firmware. The USB/iPod bridge is still to be implemented.

## Start here

- [CLAUDE.md](CLAUDE.md): project handoff and the next research task.
- [HARDWARE.md](HARDWARE.md): the dongle's actual USB/HCI responses.
- [FIRMWARE.md](FIRMWARE.md): stock image layout, sources, and the ARM disassembly question.
- [bt600_probe.py](bt600_probe.py): the working version probe and experimental upload/read options.
- [USB_BRIDGE.md](USB_BRIDGE.md): USB audio/iAP implementation references and the hardware work needed to port them.

## Run the probe

Use Python 3 on macOS with the existing Homebrew libusb installation. The script checks `/opt/homebrew/lib` and `/usr/local/lib`.

```bash
python3 bt600_probe.py
```

This command has been run on the actual dongle. Its output is recorded in `HARDWARE.md`.

## Compare dongles

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

## Next hardware experiment

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

This sends the stock RTL8761CU driver patch selected for the detected ROM and reads the version back. For this dongle, ROM version 1 selects chip ID 2. The target version is `0x4618d3f3`.

The upload mode has been assembled and tested offline; it has not yet been run on the dongle. It leaves USB configuration 1 active after a successful upload so a second probe can query the running patch.

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

To locate where the controller keeps its own USB identity — the gate for whether the dongle can be made to enumerate as anything other than a Bluetooth controller:

```bash
python3 bt600_probe.py --find-descriptor
```

This scans memory, read-only, for the little-endian `0b05:1d70` vendor/product bytes (`05 0b 70 1d`) as they appear inside a USB device descriptor. It defaults to `0x00210000` for `16384` words and accepts an explicit `START WORDS`; it stops on the first failed read and prints a context window around any hit. A match in writable RAM means the dongle's USB identity can likely be changed; a signature found only in locked ROM, or not at all, argues the dongle should be the radio while the USB persona runs elsewhere. It does not write memory and does not read `0x0880a0a8`. On 2026-10-16 the signature was **not** found in `0x00210000..0x00220000`, so the descriptor is not in that live-RAM window.

To see where readable memory actually lives before scanning further:

```bash
python3 bt600_probe.py --map-memory
```

This samples one word per 4 KB page across `0x0..0x400000` and prints coalesced `zero` / `data` / `fault` regions, read-only, stopping cleanly if a page blocks. It shows the RAM extent and whether `fc61` reaches ROM at all, which bounds where the descriptor could be and whether it is reachable by this read path.

The loader reassembles HCI events across USB packets, reports Command Status errors, checks fragment acknowledgements, and returns an error if the version after upload does not match. Run the offline suite with `python3 -m unittest -v`.

## Firmware provenance

The script embeds the original `rtl8761cu_fw.bin` and `rtl8761cu_config.bin` from `linux-firmware`, with SHA-256 checks before use. The stock file is selected and framed in the same way as Linux `btrtl.c`. Realtek's binary license is in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt). Project-authored code is separate from those vendor firmware bytes.

## Working together

Keep changes focused on the dongle and USB bridge. Record actual hardware output alongside each experiment. Claude Code can begin with `CLAUDE.md`; no Claude session is launched by this repository.
