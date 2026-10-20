# Physical audio and application backup checkpoint — 2026-10-20

Five-minute physical BT600 capture passed: 300,000 consecutive 192-byte packets,
57,600,000 bytes, 48 kHz stereo, no gaps or bad PCM. Device IRQ 48 refills the
native queue without a Mac EP0 pump. The original IRQ, native request queue,
stock descriptors/cache, callback, allocation and heap restored. SIGINT cleanup
also passed. This is generated tone, not iPhone music.

Current and ASUS CU images now pass CRC16/IBM, SHA-256 and RSA-2048 PSS checks.
The signed OTA table locates the application at CPU 0x02097000, size 0x48000.
Two complete physical SPI reads at offset 0x97000 matched each other and the
CPU capture, SHA-256 f0f0c06f2a8342365dbb96542970a87953deaf2e72d339f9c15fb768b85e3673.
Both backups and full restoration passed. No flash/efuse writes were made.

Read BT600_SPRINT.md for exact builds, results and reproduction. All 222 offline
tests pass with libusb loads rejected. The one-worker native transport and both
legacy pause files remain. Bluetooth receive, storage erase/program/restore,
persistent boot, and Uconnect acceptance are the remaining work. Hardware work
remains authorized; do not ask again to resume routine reversible experiments.

# Hardware resumed; resident descriptors passed — 2026-10-19

The owner explicitly resumed hardware work and said to continue. This supersedes
the October 17 STOP and older pause statements below. Legacy `USB_ACCESS_DISABLED`
files stay in both checkouts to block the libusb interface-claim path. Use the
native IOUSBHost transport in `bt600_native_hci.m`; routine reversible hardware
work is already authorized. Read `HARDWARE_RESUME.md` and `UCONNECT_TARGET.md`.

Actual hardware success: ROM/context reads, checked pool-5 allocate/free of 4096
bytes at `0x00312280`, and a 1032-byte resident program returning our device,
configuration header/full configuration and HID report descriptors. Four native
completions, zero errors; every reply matches the existing portable core. The
program unloaded, callbacks/EP0/selector/scratch/configuration restored and free
heap returned to 7648 bytes. Report:
`results/native-hci-resident-profile-20261019-first.json`, `success: true`.

The first 16 KiB pool-6 trial was wrong: that alias points at occupied memory and
stalled the dongle. The owner's replug cleared it, and stock recovery was verified.
Use only a fresh checked walk of active pool 5. The resident probe also temporarily
selects pool 5 for native queue bookkeeping, then restores the selector.

Live EP0 uses descriptor-DMA, with identity CPU/DMA SRAM buffer addresses confirmed
from the stock request. Resident tests now include that mode. The physical trial
used descriptor index 126 to leave normal Mac enumeration stock. Audio streaming,
full iAP, Bluetooth receive and persistent startup remain. No flash/efuse writes.
Next: measured-memory integration of complete control/audio code, real periodic
service and continuous PCM, then the Uconnect acceptance session.

# Current continuation — 2026-10-17

## USB descriptor edit succeeded

Branch `codex/bt600-descriptor-targets` now merges Claude development through
`e549116` and preserves Codex's earlier probe/capture work. Earlier conclusions
below about descriptor absence and exhaustion of USB options are superseded.

The live composite/driver/template chain matched the saved image:
`C=0x0030d180`, device descriptor at `C+0x0c`, `D=*[C+0x30]=0x0030d130`, and
template `*[D+4]=0x0030d110`. The guarded read is saved as
`results/bt600-targets-20261017T101232.957104Z.json`.

A temporary product-string edit at `0x0030d198` read back correctly but the usual
GET_DESCRIPTOR reply stayed unchanged. A template edit also stayed invisible.
The running setup code clarified that this object really supplies the reply.
Using device descriptor index 1, which this firmware ignores, bypassed the host's
cached index-0 reply. The next edit **changed the USB response at byte 15 only**:

- Original RAM word: `00 02 01 02`.
- Temporary word: `00 02 01 01` (iProduct refers to existing manufacturer string).
- USB response temporarily contained `... 00 02 01 01 00 01`.
- Original RAM word and baseline USB descriptor both restored; configuration zero
  restored too. No reset or firmware download was required.

Successful result: `results/bt600-targets-20261017T101804.507832Z.json`.
The preceding negative index-0 tests are preserved as `...101239.708137Z.json`
and `...101319.355706Z.json`; do not repeat them without a new question.

## Actual running setup code is readable

The live setup pointer at `D+0x34=0x0030d164` is `0x020be8a1` (Thumb entry
`0x020be8a0`). A 32-byte read succeeded; a targeted 1024-byte capture succeeded
in `results/bt600-targets-20261017T101448.581977Z.json`. Its first 32 bytes match
the public ASUS image exactly, and 1000/1024 bytes match at the analogous handler.
Offline files are in `results/runtime-setup/`.

The actual code at `0x020be962..0x020be986` copies the descriptor at `C+0x0c`
into the control-response buffer. `0x020be92e` dispatches standard requests.
The flash driver's address region begins at `0x02000000`, not `0x00200000`.
The full **2,097,152-byte capture completed without gaps**:
`results/bt600-targets-20261017T101939.145845Z.bin`, with the same-name JSON report.
SHA-256: `6ceb104173c7d474b42d62d501087e7933131c43deef03c706022f12a8c633c7`.
Configuration zero was restored. This is a complete CPU view of that flash
address region; physical SPI offsets and boot image mapping still need analysis.
The earlier file at `0x00200000` remains a separate CPU/RAM capture.

## Custom RAM code and native flash read both succeeded

The 28-byte setup trampoline **ran on the dongle** and wrote marker `0xd47a6001`
before tail-calling the original handler. The USB descriptor remained correct;
the original callback, helper words, marker, and configuration zero all restored.
Result: `results/bt600-targets-20261017T103719.627567Z.json`.

The next 68-byte helper **called the resident flash-read routine successfully**:
Thumb entry `0x0000cbb5`, arguments `(0x020be8a0, 0x00211e90, 16)`. It returned
status `0x18` and the expected bytes
`2d e9 f3 4f 85 b0 4f f0 00 09 05 98 88 46 4f f0`.
Result: `results/bt600-targets-20261017T104350.210104Z.json`.
Every borrowed word and the callback restored; configuration zero restored too.
No flash or efuse erase/program operation was performed.

The native helper uses code at `0x00211e30`, output at `0x00211e90`, marker at
`0x00211f00`, and status at `0x00211f04`. Two earlier candidate layouts stopped
before writing because their scratch words were occupied (`...104032.973626Z`
and `...104054.864337Z`). Always recheck the selected words live. Both helpers
pass ARM emulation, including register/flag preservation; the native read runs
once even if setup is triggered again. Restore the callback before clearing code.

These experiments bypass the fc20 loader. The old failed entry-hook tests do
not need repeating. Next: map the native endpoint queues and configuration path,
connect the small stereo PCM/test-tone core, and test a controlled USB stream.
The full flash image can be analyzed offline for boot/persistence in parallel
with that work; do not start another long capture.

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

## Hardware continuation — 23:16 UTC / 7:16 p.m. EDT

The pending descriptor-target run completed directly from Codex after approving
execution outside the command sandbox. The sandboxed attempt saw zero devices;
the approved attempt exited 0 and restored configuration zero. Future agents
should use that approved execution path before asking the owner to run Terminal.

Saved result: `results/bt600-targets-20261016T231655.391813Z.json`.
`0x002c10b4` returned `07 00 00 00` (not a pointer, not followed).
`0x002808b8` returned `05 0b 70 1d` (expected settings VID/PID).
Standard GET_DESCRIPTOR: `12 01 10 01 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01`.
Identity remains runtime `0x000e8761`, ROM 1, key ID zero. No writes/uploads.

This supersedes the pending-run instructions below. The next work is reconciling
the running firmware's global layout with the ASUS image: settings match, the
template pointer does not. Do not rerun the completed probe or follow the
additional offline context chain without reviewing this mismatch. This update
changes documentation only; `git diff --check` passes and the preceding 56-test
code validation remains applicable.


## Codex continuation: ASUS descriptor targets and EP0 copy

Continued from the 2026-10-16 ZIP handoff on focused branch
`codex/bt600-descriptor-targets`, based on PR #3 head
`00623ad7efd399a9d8ed2cd690b8ffca183c31e8`. The remote draft was still open
at that head; `origin/main` is already included. Earlier local checkouts and the
original handoff ZIP were left intact.

Integrated `bt600_vendor_read.py` from the handoff. Added same-session standard
GET_DESCRIPTOR comparison, strict query lengths and ROM gating, first-timeout
abort, failed-address/partial-result preservation (including Ctrl-C), probe
source hash, and nonzero exit on cleanup failure. Memory scope is unchanged:
at most seven words, no reset/upload/write/detach. The two firmware-derived
addresses remain `0x002c10b4` and `0x002808b8`.

Added `analyze_asus_firmware.py` for hash-pinned, bounded extraction. Reproduced
the seven ECO-2 image records and payload hash from the original ASUS bytes;
compiled the extracted Thumb wrapper and regenerated disassembly using Apple's
Command Line Tools. No firmware binaries are tracked. FIRMWARE.md records the
source, selection and upgrade distinction, address arithmetic, and new EP0 trace.

New offline finding: the candidate descriptor pointer supplies a template.
Binding copies it into composite state `C + 0x0c`; GET_DESCRIPTOR serves that
copy and refreshes configuration count/EP0 packet size. A template write might
therefore have no effect on EP0. An inferred context chain through `0x002c1240`
is documented for future investigation but has not been added to the probe.

Validation: 56 offline unit tests pass, including 16 new probe/parser tests;
stock inspection still selects chip 2 / 263 bytes; packet preview and
`git diff --check` pass. Hardware: the supplied security-register result
`00 00 00` is preserved locally and summarized in HARDWARE.md. No new controller
result was collected by this continuation, and no completed experiment was
rerun. The older failed descriptor capture contains no RAM dump. The old
stock-upload JSON's failure label is from the corrected version-check bug.

**Next:** run `python3 bt600_vendor_read.py --descriptor-targets` in normal
macOS Terminal. Read `results/bt600-targets-*.json` directly. Compare the reported
template and standard descriptor before deciding whether a bounded active-copy
chain read is justified. Do not write candidate addresses, repeat broad scans,
or invoke the full ASUS upgrade based only on the offline map. The standalone
audio/metadata bridge still needs the USB persona, radio-side stack, codec,
and boot implementation.

The earlier session record below is retained for provenance; its broad capture
and stock-upload commands are superseded by the bounded next step above.


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

### Update — flash dump completed to full 2 MB

The resumable page-skipping dump finished: `results/flash-backup/flash-20261017T023847Z.bin`
is now the full 2 MB span (0x00200000..0x00400000), sha256
`5b701222ea076e324a039b25ff79ada4fb843a0e50a444f9ff44f080f9b9c3df`. 62.5% is real
readable flash; 37.5% (192 ranges in the `.gaps` file) are unmapped/fault pages
fc61 could not read, filled with 0xff — those are NOT true contents and must be
re-read before any restore/write-back. Copies of this image, the ROM dump
(0x1000..0x9f000) and the 0x210000 RAM window were exported to
`~/Documents/ChatGPT/fauxPod/dart-usb/results/flash-backup/` with a MANIFEST.md
(checksums + the flash-routine addresses for the RAM-helper approach).
