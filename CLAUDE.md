# Latest measured state — 2026-10-20

Five minutes of 48 kHz stereo USB PCM now pass with device-side IRQ refill,
zero missing packets/bad samples, and verified restoration. Two complete native
SPI reads preserve the actual application partition, and image CRC/SHA/RSA checks
pass. Read BT600_SPRINT.md before following older next-step notes below. Bluetooth
receive, verified flash restoration and persistent startup remain unfinished.

# Dart USB handoff

## Hardware resumed by the owner — 2026-10-19

The owner explicitly authorized resuming hardware and said to continue until it
works. That supersedes the October 17 STOP. Read [HARDWARE_RESUME.md](HARDWARE_RESUME.md)
for the working native IOUSBHost flow and the completed resident descriptor trial.
Do not ask again to resume routine reversible hardware work. The legacy
`USB_ACCESS_DISABLED` markers remain to block old libusb interface-claim paths
that triggered macOS panics; do not remove them broadly or rerun those claims.
Native HCI reads, checked pool-5 RAM allocation and the resident descriptor program
have now passed on the physical BT600, with restoration verified. No persistent
writes have been made. Continuous audio, Bluetooth receive and cold boot remain.

## Goal and communication

Repurpose the existing ASUS USB-BT600 into a standalone wireless iPhone audio
and song-metadata receiver for the 2016 Dart's factory 8.4-inch Uconnect USB/iPod
input. Continue useful engineering autonomously. Keep updates practical: what
worked, what failed, and the next action. Avoid repetitive “does not establish,”
“does not demonstrate,” and similar patronizing caveats. Do not substitute a
shopping project or another host computer for this dongle project.

## Current work

The focused branch integrates Claude's development through `e549116` with the
Codex probe work. Read FIRMWARE.md's **Current corrections** first, then the top
of SESSION_NOTES.md. Older chronological claims are superseded where they conflict.

The completed CPU-memory capture and ROM/RAM files are under
`results/flash-backup/`; inspect their manifest and hashes. These are local files.
The file named “flash” includes RAM; do not treat it as a raw physical SPI image.
A full device descriptor exists at `0x0030d18c`, with composite object
`0x0030d180`, driver `0x0030d130`, and template `0x0030d110`. A reversible edit
changed the actual USB reply. GET_DESCRIPTOR device index 1 reaches the live
copy; this macOS setup returns cached data for index 0.

Custom RAM code now runs through setup callback `0x020be8a1` at `D+0x34`.
Both a marker trampoline and a call to ROM flash-read entry `0x0000cbb5` ran
successfully, with all temporary RAM and configuration changes restored.
A complete 2 MiB capture at `0x02000000` is saved with no gaps; its exact path,
hash and test records are at the top of SESSION_NOTES.md. No dump is running.
Next: native USB endpoint queues and a controlled PCM stream. The small
freestanding packetizer/test tone in `firmware/` already compiles and passes tests.

RAM reads/write-readback-restore, stock download, vendor register query, and the
old descriptor-pointer experiment already ran. Do not repeat them merely to
reconfirm access. Custom-patch marker tests yielded no marker; follow the loader
and callback references instead of guessing more entry hooks.

Approved `require_escalated` execution can access USB directly from Codex. Use
normal Terminal only if that path fails. Check for other running USB probes first.
Do not read `0x0880a0a8`, `0x000a0000`, or the previously faulting bank samples.
Stop a bounded probe on its first failed transfer. Keep complete results locally.

No flash/efuse writes or full ASUS upgrade are authorized as routine experiments.
Prepare a concrete reversible plan and recovery path before proposing any such
step. RAM descriptor edits with saved originals and automatic restoration are
within the user's existing authorization.

## References and validation

Use USB_BRIDGE.md and the pinned IPOD_PROTOCOL.md for UAC1 streaming plus iAP/HID
metadata/control. The physical iPod is currently unavailable; continue without it.
ASUS full-image extraction is implemented in analyze_asus_firmware.py. The ARM
C-chip differs from the MIPS B-chip; reuse methods, not B-chip machine code.

Preserve earlier work. Commit focused changes, record actual hardware output and
exact next experiments in SESSION_NOTES.md, and run relevant offline checks:
`python3 -m unittest -v` and `python3 bt600_probe.py --inspect-stock`.
