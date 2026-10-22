# BT600 two-hour sprint — 2026-10-19

Started 12:44:24 UTC; dependency checkpoint 13:04:24 UTC; deadline 14:44:24 UTC.
The owner authorized live hardware work and the conditional fallback in this sprint.

## Continuation checkpoint — 2026-10-22

The five-minute physical stereo result below is complete. Receiver analysis now
identifies a signed SDK 2M stack with the matching ROM UUID and a layout that fits
before the current OTA header. Its real initializer passes isolated ARM replay.
Read [RECEIVER_PORT.md](RECEIVER_PORT.md) for placement, RAM ownership and linkage.

The first fixed-padding storage trial returned native completion but changed no
bytes. All padding remained FF; two full post-trial application copies match the
original hash. Read-only status measured SR1=0x34, SR2=0x02 and BP=5, explaining
the protected target. The revised temporary-protection path passes offline checks
and has not been run physically. Physical write/readback/restore, Bluetooth
reception, persistent startup and Uconnect acceptance remain unfinished.

All 230 current offline tests pass with zero skips and libusb loading forbidden.
The native host compiles with warnings as errors. Compact shareable results and
hashes are in [evidence/bt600-checkpoint-20261022.json](evidence/bt600-checkpoint-20261022.json);
the full raw captures remain local.

## Dependency decision at minute 20

Standalone iPhone → BT600 → Uconnect playback cannot be completed in this two-hour
window. At the checkpoint, no callable RTL8761CU A2DP initialization, pairing and
decoded-PCM interface had been resolved; persistent image validation and restoration
were also unresolved. The fallback branch below was selected. Image validation was
subsequently resolved; receiver and persistent startup remain unfinished.

`analyze_sprint_gate.py` reproduces the assessment using the freshly downloaded,
hash-pinned ASUS package and the related RTL87x3E A2DP header. The vendor driver
identifies the CU upgrade query (`0xfdbb`, subcommand 1, first 128 image bytes)
and firmware fragments (`0xfc20`, 252 data bytes, final-index bit 0x80). Those
commands were inspected as source; neither was executed. Container parsing gives
seven ECO-2 images, including application 0x2793 at 0x02167400. These vendor commands were not used to install firmware. The boot-format work
below now validates the captured images and identifies the application partition.

Local evidence: `results/sprint-20261019/dependency-gate.json`, downloaded vendor
source and firmware, and `results/asus-eco2/map.json`.

## Five-minute physical stream completed

The device-interrupt build received **300 seconds of 48 kHz stereo**, all
**300,000 consecutive 192-byte packets**, **57,600,000 bytes**, with no empty
frames, missing sequences or bad PCM samples. The BT600 refilled its native
queue in IRQ 48; the Mac sent no EP0 refill requests during streaming.
The target recorded 300,021 queued, 300,007 completed, 14 cancelled, zero errors,
zero pending and running zero. All native requests drained before the original
interrupt vector, endpoint, descriptor cache, callback, scratch and heap restored.
The 16-bit packet marker wrapped four times and every transition was correct.

- Report: `results/sprint-20261019/native-stream-irq-5min.json`
- Per-frame counters: `results/sprint-20261019/native-stream-irq-5min.frames.json`
- Analysis and audio: `results/sprint-20261019/native-stream-irq-5min.analysis.json`,
  `results/sprint-20261019/native-stream-irq-5min.wav`
- RAM image: 5448 bytes in a checked 6144-byte pool-5 allocation, SHA-256
  `311fd66e8eb91a963cc08c59e1dcccf13cf459af0652166d94bd90d98a36d349`
- Exact tested build and source hashes: `results/sprint-20261019/final-build/`

This is generated test audio. iPhone reception, persistent startup and the Dart's
five-minute music/two-cold-start acceptance remain unfinished.

## Earlier full-rate stereo capture

A later RAM-only descriptor handoff advertised 192-byte ISO IN packets. Native
re-enumeration selected that descriptor, then the existing native enable/queue
ABI sent **32 seconds of 48 kHz stereo**, **32,000 consecutive packets**,
**6,144,000 bytes**, with no empty frames, missing sequences or bad PCM.
The checked pool-5 allocation is 6144 bytes with fourteen buffers; measured free
heap while active is 1160 bytes. The initial eight-buffer build had 77 empty
frames during a longer capture; increasing buffering and shortening the host
pump interval resolved it. A subsequent chained USB interrupt handler refills the
queue entirely on the BT600, with no Mac EP0 refill pump. That mode also passed
32 seconds with all 32,000 frames and every PCM sample correct
(`native-stream-irq-32s.*`). SIGINT at 750 ms restored the original interrupt
vector and passed native drain, descriptor, callback and heap restoration
(`native-stream-irq-cancel.json`).

Report/analysis/WAV: `results/sprint-20261019/native-stream-192-32s-buffered.*`.
Tested RAM image SHA-256:
`318ae5400f6721adbf781d13ddc823c768167b7b2efcb4dee6bf10f9d9eac59f`.
The tool restored the stock 63-byte endpoint and host descriptor cache through
a second native re-enumeration before freeing the allocation. SIGINT during this
full-rate profile also passed drain, descriptor and heap restoration
(`native-stream-192-cancel.json`). The tested build is preserved under
`results/sprint-20261019/build-192-buffered/`.

Build with `python3 build_resident_stream192.py` and run `--stream-irq` for
device-side refill, or `--stream-192` for the earlier host-pumped comparison.
These captures use a temporary Bluetooth HCI configuration with a larger ISO
alternate, not the final UAC/iAP personality. The source is generated test tone;
iPhone Bluetooth music and Uconnect acceptance remain unfinished.

## Persistent boot: format and partition resolved

`bt600_image_format.py` now verifies all seven captured CU images and all seven
images in the official ASUS ECO-2 package. The verified CU layout is a 1024-byte
header, CRC16/IBM over bytes `0x132..end`, SHA-256 over `0x130..end`, and
RSA-2048 PSS with SHA-256 and a 32-byte salt over `0x110..end`. Signature and
public-key integers are big endian. The related SDK header supplied field names;
the actual CU bytes supplied the checks. Mutation tests reject changed payloads,
changed signatures, and payload changes with recomputed CRC/hash.

The signed OTA table identifies application image `0x2793` at CPU address
`0x02097000`, partition size `0x48000`, with entry `0x02097400`. A bounded live
probe compared 58 header words against the saved capture and matched every word.
`analyze_bt600_boot.py` saves the verified original application image and its
complete CPU-view partition under `results/sprint-20261019/boot-analysis/`.
Original partition SHA-256:
`f0f0c06f2a8342365dbb96542970a87953deaf2e72d339f9c15fb768b85e3673`.

On the October 20 continuation, the native ROM read path was traced through
its actual address translator and SPI transaction builder. Two 16-byte physical
header reads matched, then a bounded resident exporter read the complete
**294,912-byte application partition twice** through native SPI and EP0. Both
copies match the CPU partition byte for byte, including padding, and all 1,152
native transfer completions succeeded with zero errors. Callback, EP0, scratch,
allocation and heap restored. The application maps to physical SPI offset
`0x97000`; the verified raw original is now also saved as
`boot-analysis/original-app-partition.spi.bin`. Report:
`results/sprint-20261019/native-application-spi-final.json`.

Erase/program/restore, boot trust policy and custom startup integration remain.
These backup runs used read-only storage access. The later fixed-padding trial
and its protection diagnosis are recorded in the continuation checkpoint above.
No efuse change or full ASUS upgrade was performed.

Reproduce entirely offline:

```sh
python3 analyze_bt600_boot.py --vendor results/sprint-20261019/vendor/20251017_LINUX_BT_DRIVER/rtkbt-firmware/lib/firmware/rtl8761cu_mx_fw --live-report results/sprint-20261019/native-boot-headers.json --spi-report results/sprint-20261019/native-application-spi-final.json
```

Primary references: Realtek's related
[`patch_header_check.h`](https://github.com/rtkconnectivity/RTL87x3E-Common-SDK/blob/ae842d07494ac53cf966e34684804baeed86676e/inc/rtl87x3e/platform/patch_header_check.h)
and [RFC 8017, section 9.1.2](https://www.rfc-editor.org/rfc/rfc8017#section-9.1.2).
The local boot analysis records verified spans and the remaining installation gates.

## Initial physical USB PCM capture completed

The BT600 generated a tone in a checked 4096-byte pool-5 RAM allocation. Native
IOUSBHost selected interface 1 alternate 6 before opening valid ISO IN pipe 0x83.
A single foreground process captured the stream and issued bounded EP0 refills.
The existing public PCM/control APIs are unchanged.

The verified 32-second run received **32,000 consecutive 63-byte packets**,
**2,016,000 bytes**, with sequence 0 through 31,999, correct PCM and zero transfer
errors. Its 16 kHz mono WAV contains the first 32 bytes of each packet; the rest
is stock-endpoint transport padding. Initial samples encode a low-amplitude packet
counter. This is generated test audio; Bluetooth reception remains unfinished.

- Report: `results/sprint-20261019/native-stream-32s-final.json`
- Analysis: `results/sprint-20261019/native-stream-32s-final.analysis.json`
- Received USB bytes: `results/sprint-20261019/native-stream-32s-final.pcm`
- Playable audio: `results/sprint-20261019/native-stream-32s-final.wav`
- Raw SHA-256: `b03f8c22e155426507fffd5ba851170f86af64fe49193d3c3edd0048040c09cf`
- Resident image SHA-256: `d34b541784c893d921d2e1e502c0623d143997c8bb638148d9a6cc92a94bfa6e`

Final target counters: 32,021 queued, 32,007 completed, 14 cancelled, zero errors,
zero pending, running zero. All 14 request slots were free; the native request list
was empty and ring head equalled tail. The callback, endpoint, allocation, scratch,
heap free-byte count and initial configuration were restored.

A SIGINT injected after 750 ms exited with code 130 and independently verified the
same native drain and restoration. Its report is `native-stream-cancel.json` in
that results directory. No worker is intentionally left running between trials.

## Issues found and resolved during the trials

The native ISO path completes the full 63-byte stock packet size. The first
32-byte request produced one correct PCM packet, then stopped on a size mismatch.
The complete stock-size trial resolved that failure.

A changed build emitted an unaligned halfword store and optional DSP instruction.
Two longer-start trials stalled the dongle; the owner reconnected it after each.
Builds now disable unaligned accesses and DSP. Replay checks reject those accesses
and instructions. The base-ISA build then passed physical streaming.

An earlier 32-second run captured every packet but retained its allocation after
a lost pending-counter update. Direct inspection confirmed disabled endpoint,
empty native list/ring, all slots free and every request accounted for. A guarded
release restored the heap without another reconnect. Reports preserve both the
failed cleanup and `native-stream-recovery.json`. Counter updates now preserve
PRIMASK across native queue/completion operations; replay verifies that invariant.

The host rejects increasing the existing pipe's policy from 63 to 192 bytes.
Native device reset/re-enumeration and fresh HCI handles work when configuration
0 is explicitly selected before 1. The RAM USB context survived and free heap
remained 7624 bytes (`native-reset-context-forced-config.json`). The full-rate stream above uses that route to install and restore its descriptor.

## Regression checks

All 230 current offline tests pass with zero skips and an audit hook that rejects libusb
library loading. Native compilation uses warnings as errors.

## Reproduce the bounded capture

Requires the local pinned firmware captures and existing scoped hardware resume
record. Build the allocator helper with `build_resident_profile.py` if absent.
Do not use a legacy libusb claim script or remove either legacy USB pause marker.

```sh
python3 build_resident_stream.py
xcrun clang -fobjc-arc -fblocks -Wall -Wextra -Werror -Wno-nullability-completeness -framework Foundation -framework IOKit -framework IOUSBHost bt600_native_hci.m -o results/native-host-build/bt600-native-hci
BT600_CAPTURE_FRAMES=32000 results/native-host-build/bt600-native-hci "$PWD" results/NEW-REPORT.json --stream-trial
python3 analyze_stream_capture.py results/NEW-REPORT.json
```

Default capture is 2048 frames. The stock-63 host mode accepts 64 through 32000
frames, with a separate 32768-packet target bound. Full-rate modes accept up to
300000 frames, with a separate 300768-packet target bound. Long captures save
detailed frame counters in a separate `.frames.json` file referenced by the report. `BT600_CANCEL_AFTER_MS=750` injects SIGINT for a
cancellation/restoration trial. All device access stays in one foreground process.

## Reproduce the full-rate and read-only backup paths

```sh
python3 build_resident_stream192.py
BT600_CAPTURE_FRAMES=300000 results/native-host-build/bt600-native-hci "$PWD" results/NEW-STREAM.json --stream-irq
python3 analyze_stream_capture.py results/NEW-STREAM.json
python3 build_flash_map_read.py
results/native-host-build/bt600-native-hci "$PWD" results/NEW-MAP.json --flash-map-read
python3 build_resident_flash_read.py
results/native-host-build/bt600-native-hci "$PWD" results/NEW-SPI.json --application-spi-read
```

The backup path reads only the existing application's 576 pages of 512 bytes.
It saves two copies and compares every page with the preserved original. No
program/erase entry is linked into either reader. All hardware operations use
the single native worker lease. Existing PCM/control APIs and legacy pause guards
remain in place. No Uconnect firmware was changed.
