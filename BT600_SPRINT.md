# BT600 two-hour sprint — 2026-10-19

Started 12:44:24 UTC; dependency checkpoint 13:04:24 UTC; deadline 14:44:24 UTC.
The owner authorized live hardware work and the conditional fallback in this sprint.

## Dependency decision at minute 20

Standalone iPhone → BT600 → Uconnect playback cannot be completed in this two-hour
window. No callable RTL8761CU A2DP initialization, pairing and decoded-PCM interface
has been resolved. Persistent application image validation, physical bank offsets
and storage restoration also remain unresolved. No persistent installation was attempted.

`analyze_sprint_gate.py` reproduces the assessment using the freshly downloaded,
hash-pinned ASUS package and the related RTL87x3E A2DP header. The vendor driver
identifies the CU upgrade query (`0xfdbb`, subcommand 1, first 128 image bytes)
and firmware fragments (`0xfc20`, 252 data bytes, final-index bit 0x80). Those
commands were inspected as source; neither was executed. Container parsing gives
seven ECO-2 images, including application 0x2793 at 0x02167400. A boot validator
and reversible storage layout are still required before installing anything.

Local evidence: `results/sprint-20261019/dependency-gate.json`, downloaded vendor
source and firmware, and `results/asus-eco2/map.json`.

## Physical USB PCM capture completed

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
remained 7624 bytes (`native-reset-context-forced-config.json`). This is the route
being prepared for a larger endpoint descriptor.

## Regression checks

All 193 offline tests pass with zero skips and an audit hook that rejects libusb
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

Default capture is 2048 frames. The host accepts 64 through 32000. Target submission
has a separate 32768-packet bound. `BT600_CANCEL_AFTER_MS=750` injects SIGINT for a
cancellation/restoration trial. All device access stays in one foreground process.
