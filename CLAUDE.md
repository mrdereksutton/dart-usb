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

USB access update: on 2026-10-16 at 23:16 UTC, the sandboxed Codex command still saw zero USB devices, but the approved `require_escalated` execution successfully opened the BT600 and completed the targeted reads. Prefer the approved command path for future bounded experiments. Normal Terminal remains a fallback; no OS security settings changed.

Actual memory run at 05:29 UTC: `0xfc61` returned `b4 88 3b c2` at `0x00217e88`, while zero/four returned zeroes. Querying `0x0880a0a8` timed out and the dongle disappeared from USB before the stock upload. That address is removed. The runner now uploads stock first and stops on a failed phase. Read `HARDWARE.md` and the latest `results/` before changing the experiment; do not reintroduce the failed address as a flash dump target.

## Start with this task

1. Read `SESSION_NOTES.md`, `IPOD_PROTOCOL.md`, `IPOD_REFERENCE.md`, and the latest `results/descriptor-*/capture.json` and `results/ipod-*/reference.json` if present. Older results may also be in the sibling `../dart-usb/results/` working directory. Read saved files directly; do not ask the user to paste them.
2. RAM reads, a RAM word write/readback/restore at `0x00210000`, and the stock download have already worked. After upload the running version is `0x7bf15762`, while `0x4618d3f3` is the container version. Do not repeat those experiments just to reconfirm them.
3. The targeted experiment is now COMPLETE; do not repeat it. Read `results/bt600-targets-20261016T231655.391813Z.json`. At `0x002c10b4`, the controller returned `07 00 00 00`, so the pointer was not followed. At `0x002808b8`, it returned `05 0b 70 1d`, matching ASUS VID/PID. Standard GET_DESCRIPTOR was `12 01 10 01 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01`. Only two memory words were read; configuration zero was restored.
4. The latest successful vendor query returned `00 00 00` for `fc61` parameters `10 a4 ad 00 b0`: key ID zero under ASUS's loader interpretation. The latest probe is now in this branch. See HARDWARE.md for the measured evidence and FIRMWARE.md for full ASUS image hashes and offsets. The earlier descriptor capture exited with no device and contains no RAM dump.
5. Continue from FIRMWARE.md's descriptor/EP0 trace. The candidate pointer is an initialization template; the setup handler serves a copy at composite state `C + 0x0c`. A byte match is useful, but does not select an active write target. The additional context chain through `0x002c1240` is offline-only and is not part of the prepared run. The observed value 7 is not a usable pointer: the ASUS template mapping does not directly match the current runtime. Reconcile that layout before following additional chains; do not broaden into address scans.
6. `analyze_asus_firmware.py` reproduces the exact ASUS ECO-2 extraction and address evidence offline. No full ASUS firmware upgrade or `fdbb` negotiation has been sent; do not treat that path as an ordinary volatile patch. The owner cannot currently locate the iPod Classic; use IPOD_PROTOCOL.md's published source reference and continue without waiting for it.

The optional `--read-range START WORDS` reader is implemented and restricted to the candidate page `0x00217000..0x00217fff`, at most 256 aligned words. It stops on the first failed read and prints completed words as they arrive. Review the completed stock-upload result before running a wider read. A matching prologue is a candidate address, not proof of the CPU's execution mapping. The normal runner still reads just `0x00217e88`.

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
