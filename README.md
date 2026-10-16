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

It collects a baseline, tries the memory queries, uploads the matching stock host-loaded patch, and repeats the version and memory queries. It saves timestamped text and JSON output in `results/`, which is excluded from Git. A failed basic probe or upload stops the sequence. An unsupported memory-read command is recorded and does not skip the independent upload test. Use `--read-only` to collect only the baseline and memory queries.

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

That option queries candidate boot-vector words at `0x0` and `0x4`, then the two addresses found in the C-chip patch. Each `0xfc61` query requests four bytes, so the reset vector needs its own read. The C controller's reply determines whether this command is available. It does not write memory.

On this dongle, `0xfc61` works: `0x00217e88` returned live data and `0x0` read back as zero. Reading `0x0880a0a8` hung the controller, so that peripheral/flash window is excluded from routine reads.

To map a span of live memory, read-only:

```bash
python3 bt600_probe.py --read-range 0x00217e88 64
```

This dumps `WORDS` four-byte words from `START` (both hex or decimal) and stops on the first rejected or timed-out read. Once `--load-stock` has made the chip-2 patch resident, a `--read-range` sweep of the `0x0021xxxx` region locates the patch's prologue, and the address where it appears is the controller's real load base. It does not write memory, and it does not read `0x0880a0a8`.

The loader reassembles HCI events across USB packets, reports Command Status errors, checks fragment acknowledgements, and returns an error if the version after upload does not match. Run the offline suite with `python3 -m unittest -v`.

## Firmware provenance

The script embeds the original `rtl8761cu_fw.bin` and `rtl8761cu_config.bin` from `linux-firmware`, with SHA-256 checks before use. The stock file is selected and framed in the same way as Linux `btrtl.c`. Realtek's binary license is in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt). Project-authored code is separate from those vendor firmware bytes.

## Working together

Keep changes focused on the dongle and USB bridge. Record actual hardware output alongside each experiment. Claude Code can begin with `CLAUDE.md`; no Claude session is launched by this repository.
