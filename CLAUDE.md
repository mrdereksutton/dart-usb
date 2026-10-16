# Dart USB handoff

## Goal

Use the existing ASUS USB-BT600 as a standalone wireless iPhone audio + track-metadata bridge to the USB/iPod input of a 2016 Dodge Dart's stock 8.4-inch Uconnect. The user is exploring repurposing this hardware; focus on that engineering task.

## Communication

- Speak directly. Explain what an experiment does and what its output means.
- Work through technical unknowns instead of using them as reasons to stall.
- Do not repeatedly use "verified", "not verified", or "establish" in updates.
- Do not substitute shopping recommendations for this project.
- The user controls their Claude session. Do not launch or operate another assistant on their behalf unless asked.

## Current hardware

ASUS USB-BT600, USB `0b05:1d70`, Realtek RTL8761CU, class `e0/01/01`. The user successfully ran the probe from macOS Terminal on 2026-10-16. HCI revision `0x000e`, manufacturer `0x005d`, LMP subversion `0x8761`, ROM version 1, patch chip ID 2. Read `HARDWARE.md` for the full response.

The Codex app's process could read I/O Registry data but got IOKit `kIOReturnNotPermitted` when opening raw USB. The user's normal Terminal process opened and queried the dongle successfully. Use ordinary Terminal execution for hardware tests; do not change OS security settings.

## Start with this task

1. Read `bt600_probe.py`, `FIRMWARE.md`, `USB_BRIDGE.md`, and `rtl8761cu_patch_disassembly.txt`. `run_bt600_experiment.py` saves controller output under `results/`; inspect any existing results before repeating hardware work.
2. Independently review the stock-patch parser, USB/HCI framing, fragment handling, and cleanup. The diagnostic-only mode has worked on hardware. The upload and memory-read options have only been tested offline.
3. Investigate the patch's actual load address and calls to offsets outside the selected 252-byte payload. Determine how those targets relate to the chip's existing ROM/flash. The disassembly's base address is zero, not the controller's real load address.
4. Propose and implement a small next experiment that moves toward C-chip memory access, flash access, and USB descriptor changes. Keep the user's observed ROM revision in the selection logic.

## Concrete review outputs

- Put code findings and fixes in a focused commit, including a regression test for a reproducible failure.
- Record C-chip address calculations, byte offsets, and source links in `FIRMWARE.md`. Separate inferred addresses from values read from the controller.
- Inspect the stock image's unusually small payload: its second routine is cut off by the 252-byte selection and version replacement. Determine whether those bytes are an initializer, depend on resident code, or need another firmware revision. Do not blindly expand the upload into the zero padding.
- Use `USB_BRIDGE.md` for the iAP/UAC1 interface reference. Determine how the C chip exposes EP0 descriptor callbacks and whether its isochronous IN endpoint can carry 192 bytes per millisecond.
- End each work session with the changed files, test results, actual controller output collected, and the exact next experiment. A prepared repository or successful stock patch upload does not complete the audio bridge.

## Important distinctions

- RTL8761C uses a 32-bit ARMv8M Real-M300 core. The older RTL8761B research targets MIPS16e. Do not transplant B-chip code or memory addresses into the C chip.
- Realtek's C datasheet shows ROM, RAM, and FLASH and documents UART flash-programming pins. That is a lead for persistence; the on-dongle programming path and usable flash layout remain to be mapped.
- Stock HCI firmware upload is only a building block. The final bridge also needs Bluetooth audio/metadata handling and USB/iPod emulation.
- Do not describe offline parser tests as successful hardware uploads.

## Tests

```bash
python3 -m unittest -v
python3 bt600_probe.py --inspect-stock
```

The README lists the hardware commands. No kernel driver, persistent firmware write, or OS configuration change has been performed in this project.
