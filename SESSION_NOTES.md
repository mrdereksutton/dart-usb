# Session notes — 2026-10-17

## Where we are

The low-level controller work is done. Reading memory works across ROM
`0x00001000..0x0009efff` and RAM `0x00210000..0x0021ffff`; a word write at
`0x00210000` reads back and restores; loading the stock firmware runs and the
reported version changes from `0x000e8761` to `0x7bf15762`. Leave `0x0880a0a8`
and `0x000a0000` alone — they hang the controller.

## This session

- The USB descriptors are not stored as a contiguous block anywhere readable.
  A full `0x1000..0x9efff` read (647168 bytes) searched in four word layouts
  matched nothing. The firmware builds them in code.
- Added `rom_analyze.py`: reads a saved ROM image offline (no dongle) and finds
  the descriptor-building code by its constants — where the firmware loads VID
  `0x0b05` / PID `0x1d70` and the descriptor length+type signatures (`0x0112`
  device, `0x0209` config), as `MOVW` immediates or PC-relative literal loads,
  plus the `cmp #6` that marks the GET_DESCRIPTOR request check. Smoke-tested
  across all paths; `python3 -m unittest` is green (41 tests).
- Reworded `CLAUDE.md` into plain project language; no technical facts changed.

Pushed to draft PR #3, branch `claude/epic-gauss-dutrk1`.

## Exact next step (on the Mac, offline)

```
pip3 install capstone
python3 rom_analyze.py results/descriptor-20261017T002154.077318Z
```

The literal-load hits land inside the function that builds the device
descriptor. Walk back to that function's entry, then find the caller reached
from the `cmp #6` request check — that is the EP0 GET_DESCRIPTOR handler.
From there, see how the descriptor is staged and whether the isochronous IN
endpoint can be moved from 63 to 192 bytes per millisecond for 48 kHz stereo.

## Still open, not blocking

iPod Classic capture (`capture_ipod.py`) waits on finding the iPod. The
car-facing UAC1/iAP behavior comes after the descriptor handler is mapped.

---

# Session notes — 2026-10-16

## Prepared continuation: descriptor/RAM capture and iPod Classic reference

The owner has an iPod Classic but cannot locate it right now. Published source
already supplies the next protocol reference: see `IPOD_PROTOCOL.md` for the
pinned RockPod implementation, USB audio/HID layout, packet fragmentation,
IDPS/audio activation, and metadata/control command IDs. Continue without waiting
for the physical iPod. Two capture commands are now
prepared in this branch; their new capture output is still to be collected from
normal macOS Terminal:

- `python3 run_descriptor_experiment.py`: save the BT600's live device and
  configuration descriptors and one `0x00210000..0x0021ffff` RAM dump. Search
  complete descriptors and interface/endpoint records, preserving all matches
  and partial reads. No stock upload or memory-write retest is involved.
- `python3 capture_ipod.py`: save the iPod's device descriptor and every
  advertised configuration, with interface alternate settings and endpoint
  summaries. Standard read-only USB requests; no disk access or iAP commands.

Read results under `results/descriptor-*/` and `results/ipod-*/`. Reanalyze saved
RAM offline with `python3 descriptor_capture.py CAPTURE_DIRECTORY`. See
`IPOD_REFERENCE.md` for the iPod-to-Uconnect comparison and `CLAUDE.md` for the
current task. Offline regression checks cover unaligned/word-swapped matches,
USB read failures and interruptions, read-range limits, multi-configuration iPod
references, and USB string language selection.

The earlier session record follows.

Handoff for the RTL8761CU (ASUS USB-BT600, `0b05:1d70`) work. All hardware
runs were done by the user from macOS Terminal and pasted back.

## What this session established

### Controller capability map (confirmed on hardware)

| Capability | Opcode | Result |
| --- | --- | --- |
| Read local / ROM version | `0x1001` / `0xfc6d` | Works; ROM version 1 (selects patch chip ID 2) |
| Memory read | `0xfc61` | Works over `0x00001000..0x0009f000` and RAM near `0x0021xxxx`. `0x0` reads zero. `0x000a0000` and `0x0880a0a8` hang the controller (replug to recover). |
| Firmware download | `0xfc20` | Accepted; controller relaunches (version `0x000e8761` -> `0x7bf15762`). No HCI Reset needed, matching `btrtl.c`. The patch is **relocated/transformed on load** — its prologue bytes are not in any readable region. |
| Memory write | `0xfc62` | **Works.** read/flip/verify/restore at `0x00210000`: `00 00 00 00` -> wrote `ff ff ff ff` -> read back `ff ff ff ff` -> restored `00 00 00 00`. |

**Bottom line: full RAM read + write, plus a launching firmware-download path.**
That is the whole low-level foundation; changing the chip's behavior is now an
RE problem, not a "can we touch it" problem.

### Key corrected assumptions
- The stock upload reporting `0x7bf15762` (not the container `0x4618d3f3`) is
  **success, not failure**. `btrtl.c` never verifies the post-download version;
  it only logs it. The probe now treats "version changed from pre-download" as
  the success signal (`require_stock_version`).
- Our 263-byte payload is framed correctly (the patch already ends in the
  version bytes; substitution is a no-op). The earlier "bad framing" worry was
  wrong.
- The `0b05:1d70` USB identity is **not** in any readable region (searched all
  byte orders across `0x1000..0x9f000`), so it is config/efuse the read path
  can't reach. BUT the firmware stages the descriptor in RAM at enumeration, and
  RAM is writable — so changing what the dongle enumerates as is reachable in
  principle via a RAM write / hook.

### Three-dongle comparison (empirical, `usb_inspect.py`)
| | BT600 | MD301 (`0b05:1cd3`) | Logi Bolt (`046d:c548`) |
| --- | --- | --- | --- |
| USB class | `e0` Bluetooth | HID (5 iface) | HID (4 iface) |
| endpoint types | interrupt + bulk + **isochronous** | interrupt only (IN+OUT) | interrupt only (IN) |
| audio lane (isoc) | **yes** | no | no |
| radio | Bluetooth **Classic** | 2.4 GHz proprietary | BLE proprietary |
| reflashable | yes (`fc20`) | yes (ASUS GearLink, vendor HID chans `0xffef`/`0xff02`/`0xff01`/`0xffc1`) | no (signed) |

Only the BT600 has a Bluetooth-Classic radio + an isochronous (audio) USB lane.
The other two are input receivers with no audio path. Logitech Bolt FCC
`JNZCU0021` (DTS-BT LE + GFSK). MD301 is a capable reflashable HID gadget but
not part of any audio chain.

## Tools added to the repo this session
- `usb_inspect.py` — generic USB descriptor + HID report-descriptor dump (any device).
- `bt600_probe.py` new modes: `--map-memory`, `--find-descriptor`, `--find-patch`,
  `--write-test`; corrected `--load-stock` success check.
- Tests: `test_probe.py` (23) + `test_usb_inspect.py` (6) all pass:
  `python3 -m unittest -v`.

## Strategic read
- **Dongle-only bridge** (BT600 becomes the whole iPod/iAP + audio device):
  now plausible at the memory level (read+write+load all work) but still needs
  (a) locating/patching the descriptor staging in RAM, (b) an A2DP sink + iAP
  stack on a small BT-controller ROM — the capacity question is the real risk.
- **Radio + host** (BT600 as the Bluetooth radio, a small cheap board as the
  car-facing USB/iAP persona): the lower-risk path to actually shipping audio to
  the car. The car has no CarPlay, so the persona is iPod/iAP, which is
  MFi-licensed for a *product* but fine for a personal build.

## Exact next experiment
Find where the firmware stages the USB **device descriptor** in RAM during
enumeration — that is the specific `fc62` write target that would let the dongle
present as something the car accepts. Approach: dump/compare RAM around
enumeration, or search RAM (read) for the assembled 18-byte device-descriptor
pattern (`12 01 00 02 e0 01 01 ...`) rather than just the VID/PID, in all byte
orders, across the readable RAM region.

---

## Session handoff — 2026-10-17 (Opus 4.8)

This session mapped the firmware modification path end to end, found the public
prior art, and established the hard limits. It also corrected two wrong claims
made mid-session; read FIRMWARE.md top-to-bottom, the later "CORRECTION" and
"command discovery" sections supersede earlier ones.

### Verified this session (independently read from hardware + ROM)

- **EP0 / descriptor path.** The dongle builds its USB descriptors dynamically at
  enumeration (no static descriptor blob anywhere readable). Chain: EP0 handler
  `0x3c14c` -> callback vector at `0x285c0c+0x38` -> descriptor handler `0x205ca2`
  -> per-device context (pointer at `*0x285254`, stride `0x440`) and RAM handler
  tables. Captured descriptors parsed in FIRMWARE.md: it enumerates as a Bluetooth
  HCI controller, class e0/01/01, iso endpoints are SCO voice (max 63 B/frame).
- **Flash.** Winbond W25Q16, 2 MB, memory-mapped for reads at `0x200000`. fc61
  reads one 32-bit word per command and faults on unmapped holes (e.g. 0x225000),
  dropping the device (it re-enumerates). ROM has a full SPI flash driver; vtable
  at `0x20180` (read `0xcbb4`, write `0xcc34`, erase, DMA). Geometry table at
  `0x280734`; chip params `0x280374`.
- **Host vendor commands.** fc20 (download patch, RAM), fc61 (read mem), fc62
  (write mem, RAM), fc6b/fc6d (info), fc29/fc2a/fc2b (config read/write/erase of a
  FIXED block — fc29 ignores its address arg), fc2c, fc7e.
- **Chip audio.** ROM has real BT audio-link machinery: SCO/eSCO voice
  (`audio_sniff_*`, `lc_*esco*`) and LE Audio ISO (`ll_iso_*`, `bz_isoch_*`).

### Corrected / retracted (do not trust the superseded versions)

- fc62 RAM writes do NOT persist: proven by poking a marker and replugging.
- fc29/fc2a/fc2b are NOT general flash read/write/erase (earlier inference was
  wrong). fc29 returns a fixed config/efuse block regardless of address.
- The flash is NOT "only 148 KiB"; reads succeed at 0x300000/0x3ffffc, with holes.

### Hard limits established

- **No safe, confirmed way to write the dongle's permanent memory over USB.** RAM
  writes are wiped on power cycle. The flash driver has no static USB front door
  (called via a RAM-installed pointer). The config-write commands (fc2a/fc2b)
  might persist but could be write-once efuse — blind probing risks a permanent
  brick. The config field map is Realtek-internal.
- The car power-cycles the dongle every start, so RAM patches and host-downloaded
  firmware (the fc20 path) cannot change what the car sees; only a flash/efuse
  change would, and there is no safe host route to it.
- Making it a car audio bridge needs: an A2DP/LE-Audio SINK + decode, a USB-Audio
  (or iAP) presentation, AND persistence — none present in stock firmware, and
  the sink firmware is vendor-gated (Realtek RealMCU SDK).

### Prior art to build on (PRIOR_ART.md)

- Dark Mentor LLC / Xeno Kovah, "Reverse engineering Realtek RTL8761B* Bluetooth
  chips" (Hardwear.io 2025 / DistrictCon 2026):
  https://github.com/darkmentorllc/DarkFirmware_real_i — Ghidra analysis, config
  Kaitai parser, vendor-command DB (Bumble fork), memory reader, patch writer.
  NOTE: that work is the RTL8761B (MIPS core); this dongle is RTL8761CU (ARM), so
  their binaries/ASM do not run on it, but the method and config format transfer.
  Their custom firmware is ephemeral (host re-downloads each boot) — they did not
  solve standalone persistence either.

### Tooling added this session (all in bt600_probe.py, tests in test_probe.py)

- `--dump-flash OUT` (resumable, page-skips fault holes, records OUT.gaps)
- `--poke ADDR VALUE` (guarded persistent single-word write, whitelisted pages)
- `--flash-read OFFSET LEN` (fc29 debug)
- `--read-range` whitelist widened to flash + the config/RAM pages used here.

### Local-only artifacts (not in git, on this Mac)

- Partial flash backup (0x200000..0x225000, 148 KiB, verified; handler sector
  included) under `results/flash-backup/` (gitignored).
- Dark Mentor repo cloned in the session scratch dir (external code; not committed).

### Next steps (pick one)

1. **UART reflash route (the real persistence path).** The chip documents UART
   flash-programming pins; this is Realtek's intended, non-brick-prone way to
   write flash. Needs opening the dongle and wiring to those pins, plus Realtek's
   tool or a driver of the flash routines we mapped.
2. **Config-write persistence test (risky).** Back up config via fc29, then test
   whether an fc2a write survives a replug. Brick risk if the store is write-once
   efuse; do only with that risk accepted.
3. **Purpose-built hardware.** A standalone Bluetooth-to-USB-audio receiver (the
   Creative BT-W / Sennheiser BTD 600 architecture) reaches the music goal without
   this reverse-engineering; fastest path if the goal is just audio in the car.
