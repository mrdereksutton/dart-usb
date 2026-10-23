# Prior art: Realtek RTL8761 Bluetooth reverse engineering

Found existing public work on this chip family (2026-10-17). This corrects an
earlier defeatist stance: modifying these dongles' firmware is demonstrably
possible; what remains genuinely hard is standalone persistence and an audio
stack.

## Dark Mentor LLC (Xeno Kovah) — RTL8761B* reverse engineering

- Talk: "Reverse engineering Realtek RTL8761B* Bluetooth chips, to make better
  Bluetooth security tools & classes" (Hardwear.io 2025, DistrictCon 2026).
  https://darkmentor.com/publication/2025-11-hardweario/
- Repo: https://github.com/darkmentorllc/DarkFirmware_real_i
  - Full Ghidra analysis of the firmware+ROM (dumped via memory-read VSCs).
  - A patch writer that downloads custom firmware over vendor commands.
  - A memory reader (same style as our bt600_probe fc61 reads).
  - A Kaitai Struct spec + parser for the Realtek config-file format.
  - A database of vendor-specific commands (via a Bumble fork).

### What transfers to us, and what does not

- **Architecture differs.** RTL8761B = MIPS16e core; our RTL8761CU
  (USB 0b05:1d70) = ARM. Their patch bytes/ASM and Ghidra files are for the B
  (MIPS) and will NOT run on the CU. Their *method*, the config format, the VSC
  approach, and the overall ROM-patching mechanism do transfer. Our own ARM
  disassembly of the CU (FIRMWARE.md) is the CU-side equivalent.
- **Their custom firmware is EPHEMERAL.** It is re-downloaded by the Linux host
  every boot (dropped into /lib/firmware/rtl_bt/). They did not achieve
  standalone persistence across a power cycle. This matches our finding that the
  fc20 patch download lives in RAM and is wiped on replug.
- **Config-file lever.** The Realtek config is a simple header (55 AB 23 87) plus
  a Type-Length-Value list; offset 0x30 = BDADDR, for example. Settings can be
  changed via this data file without patching code. Whether USB identity/class is
  config-controlled is the next thing to check (it would let us change what the
  car sees without writing code).
- **Their goal was radio/security** (spoof BDADDR, send custom LMP), NOT audio.
  No public A2DP-sink / USB-audio-bridge firmware exists for this chip.

## Realtek RTL8761C capability

- RealMCU's page says the RTL8761C supports on-chip Codec Offloading and that
  Realtek offers "SINK-side device IC services" — i.e. audio-receiver firmware is
  made from this chip family, but by Realtek/product makers under their SDK
  (behind a RealMCU login), not published.
- Products that already do "present as a USB audio device + bridge Bluetooth
  on-chip, no host software": Creative BT-W series, Sennheiser BTD 600 (these are
  transmitters, but prove the standalone-USB-audio architecture is real).

## Honest status of the car goal

- Hacking/patching this dongle's firmware: possible, now with a real head start.
- Making it a standalone A2DP-sink + USB-audio device for the car: unsolved by
  anyone publicly; needs custom firmware that (a) persists in the dongle's flash
  (no host in the car to re-load it) and (b) implements the audio stack the host
  normally provides. The chip likely can (codec offload), but that firmware is
  vendor-gated.
- Tractable near-term step: use the config/VSC tooling to learn exactly what is
  configurable (especially USB identity/class), since a config change that
  persists could alter what the car enumerates without a full firmware rewrite.
