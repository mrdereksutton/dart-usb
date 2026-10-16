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
