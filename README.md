# Dart USB

Repurpose an ASUS USB-BT600 so an iPhone can send wireless audio and song information to a 2016 Dodge Dart's stock 8.4-inch Uconnect through its USB input.

The current work is identifying how the RTL8761C controller loads code, accesses memory, and stores firmware. The USB/iPod bridge is still to be implemented.

## Start here

- [CLAUDE.md](CLAUDE.md): project handoff and the next research task.
- [HARDWARE.md](HARDWARE.md): the dongle's actual USB/HCI responses.
- [FIRMWARE.md](FIRMWARE.md): stock image layout, sources, and the ARM disassembly question.
- [bt600_probe.py](bt600_probe.py): the working version probe and experimental upload/read options.

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

```bash
python3 bt600_probe.py --load-stock
```

This sends the stock RTL8761CU driver patch selected for the detected ROM and reads the version back. For this dongle, ROM version 1 selects chip ID 2. The target version is `0x4618d3f3`.

The upload mode has been assembled and tested offline; it has not yet been run on the dongle. It leaves USB configuration 1 active after a successful upload so a second probe can query the running patch.

An additional experiment tests whether the C chip accepts the B family's memory-read command:

```bash
python3 bt600_probe.py --probe-memory
```

That option reads the ARM vector table at `0x00000000` first — its initial stack pointer and reset vector anchor the memory map and let us locate the patch's load base — then reads the patch's RAM-table and mapped-flash literals. Whether the C chip accepts the `0xfc61` format is an open research question. It does not write memory.

## Firmware provenance

The script embeds the original `rtl8761cu_fw.bin` and `rtl8761cu_config.bin` from `linux-firmware`, with SHA-256 checks before use. The stock file is selected and framed in the same way as Linux `btrtl.c`. Realtek's binary license is in [REALTEK_FIRMWARE_LICENSE.txt](REALTEK_FIRMWARE_LICENSE.txt). Project-authored code is separate from those vendor firmware bytes.

## Working together

Keep changes focused on the dongle and USB bridge. Record actual hardware output alongside each experiment. Claude Code can begin with `CLAUDE.md`; no Claude session is launched by this repository.
