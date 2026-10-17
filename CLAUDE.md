# Dart USB handoff

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
A full device descriptor exists at `0x0030d18c`, with candidate composite object
`0x0030d180`, driver `0x0030d130`, and template `0x0030d110`. The next experiment
is a bounded fresh read and reversible EP0 descriptor edit with automatic restore.

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
