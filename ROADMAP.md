# Dart USB — project status, findings, and the plan

Single-source overview as of 2026-10-17. Detailed, chronological notes (including
mid-session corrections) live in `FIRMWARE.md`; prior art in `PRIOR_ART.md`; the
hardware procedure in `FLASH_ACCESS.md`; session history in `SESSION_NOTES.md`.
This file is the clean summary and the rationale for the next step.

---

## 1. The goal

Use the ASUS USB-BT600 dongle to get the phone's audio (and ideally track
metadata) into the 2016 Dodge Dart's Uconnect USB port, standalone, with no
computer in the car.

## 2. What the car accepts (this sets the target)

The Dart's Uconnect USB input plays from exactly two kinds of device:
- **USB Mass Storage** (FAT32, MP3/WMA/AAC/WAV files), and
- **iPod over iAP** (the Apple accessory protocol).

It does **not** play a live "USB Audio Class" stream for general playback. So the
device we ultimately need the dongle to look like is an **iPod (iAP)**, not a USB
sound card. The owner has an iPod Classic that works in the car, which is a
ready-made reference for the protocol and proof the iAP path works.

## 3. What the dongle is

- ASUS USB-BT600, USB ID `0b05:1d70`, Realtek **RTL8761CU** (ARM core).
- It is a **Bluetooth HCI controller**: its USB job is to carry Bluetooth
  host-controller traffic to a computer. Standalone it enumerates as a Bluetooth
  controller (USB class `e0/01/01`), which the car cannot use as a media device.
- The chip genuinely handles Bluetooth audio **links** (classic SCO/eSCO voice and
  LE-Audio isochronous streams — confirmed by `audio_sniff_*`, `lc_*esco*`,
  `ll_iso_*` code in the ROM). What it lacks in stock firmware is the piece that
  decodes that audio and presents it to a host as an iPod/USB-audio device.

## 4. Firmware architecture we mapped (all independently verified)

- **USB descriptors are built dynamically** at enumeration, not stored as a blob.
  The EP0 path is ROM `0x3c14c` → a callback vector at `0x285c0c+0x38` → the
  descriptor handler at `0x205ca2` → per-device context (`*0x285254`, stride
  `0x440`) and RAM handler tables.
- **Firmware lives in a discrete Winbond W25Q16 SPI flash** (2 MB). The chip's own
  geometry table (live at `0x280734`) carries JEDEC ID `EF 40 15`, read from the
  real chip; the firmware image is mapped for reads at `0x200000`.
- **The ROM has a full SPI flash driver** (read `0xcbb4`, write `0xcc34`, erase;
  vtable at `0x20180`; 4 KiB/64 KiB sectors, 256-byte program pages).
- **Host vendor commands:** `fc20` download-patch (RAM, ephemeral), `fc61` read
  memory, `fc62` write memory (RAM), `fc29/fc2a/fc2b/fc2c` config/efuse store,
  `fc6b/fc6d/fc7e` info.

## 5. What we proved on hardware

1. **RAM changes don't persist.** A value written to RAM (via `fc62`) is gone
   after a replug — proven by writing a marker and power-cycling. The car
   power-cycles the dongle every start, so **nothing in RAM, and no
   host-downloaded patch, can change what the car sees.** Only a change in the
   flash can.
2. **We can deliver a modified firmware patch over USB** (`fc20`): a patch we edit
   downloads and launches with no brick. But **our injected code does not run** —
   the ROM does not execute the downloaded patch from its start, so hooking the
   entry does nothing, and the post-download version change is the ROM's own
   doing, not our code.
3. **The parts needed to go further are unreadable over USB.** The ROM's
   patch-apply handler and the patch-RAM live in `0x100000..0x200000`. `fc61`
   does not just refuse that region — it **hangs** the controller there. No other
   vendor command can read it (`fc2c` is config-only; `fc6b/6d/7e` are info). So
   over USB we cannot trace how the patch is applied, cannot verify injected code,
   and cannot reach the regions that matter.

**Net:** over USB the dongle is a dead end for the goal — we can deliver bytes but
can't make them run or persist, and can't read the firmware that would tell us
how.

## 6. The plan: direct SPI flash access

Read and write the dongle's flash chip **directly**, with a clip-on programmer,
bypassing the controller and USB entirely.

- Hardware: a ~$5 CH341A USB programmer (run at **3.3 V**), a SOIC-8 test clip,
  and `flashrom`.
- Steps (full detail in `FLASH_ACCESS.md`): open the dongle, find the 8-pin flash
  chip, clip on, `flashrom` read-twice-and-compare to get a stable dump, back it
  up, then modify and write back, verifying each time.

## 7. Why this is the right next step

- **It reaches what USB can't.** A direct SPI read returns the *entire* 2 MB flash,
  including the `0x100000..0x200000` code that `fc61` hangs on. That finally lets
  us read the descriptor builder and the patch-apply mechanism offline and
  understand how to change what the dongle presents as.
- **It persists, which the car requires.** The car reads the flash at every
  power-on. A flash change is therefore the *only* kind of change that survives
  into the car — unlike RAM pokes or host-loaded patches, which the car can't
  provide and a power cycle erases.
- **It is reversible.** With a verified backup of the original flash, any change
  can be undone by writing the backup back, so experiments are recoverable
  (unlike a blind, unverifiable USB patch).
- **It is cheap, standard, and low-risk** compared to the alternatives: the UART
  download route is undocumented for this chip and needs an unknown pin/mode; the
  USB route is blocked. Direct SPI is the well-trodden hardware-hacking path and
  needs no cooperation from the Realtek firmware.

In short: every capability the USB path lacked — full read, persistence, reversible
write — direct flash access provides, with commodity tools.

## 8. Honest scope beyond flash access

Getting read/write access to the flash unblocks the *investigation* and gives a
persistent write path. It does **not** by itself make music play. Turning the
dongle into something the car treats as an iPod still requires building firmware
that implements the iAP side and an audio path fed from Bluetooth — a substantial
custom-firmware effort on top of flash access. Flash access is the prerequisite
that makes that work possible and testable; it is not the finish line.

## 9. Prior art to build on

Dark Mentor LLC (Xeno Kovah) published a reverse-engineering toolkit for the
sibling **RTL8761B** (Ghidra analysis, config-format parser, vendor-command
database, patch writer): https://github.com/darkmentorllc/DarkFirmware_real_i .
Their methodology transfers, with caveats: their chip is MIPS (ours is ARM), and
their patch-RAM was host-readable (ours is not — which is exactly why we need
direct flash access). See `PRIOR_ART.md`.

## 10. Tooling in this repo

- `bt600_probe.py` — hardware probe: diagnostics, `fc61` reads (`--read-range`),
  `fc62` write-test, `--poke`, stock and custom patch download (`--load-stock`,
  `--load-custom`), `--dump-flash` (the memory-mapped, fc61-limited dump).
- `rom_analyze.py` — offline Thumb analysis of a saved ROM/flash image.
- Captures and the partial flash backup are under `results/` (gitignored); copies
  exported to the `fauxPod` working folder with a manifest.
