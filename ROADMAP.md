# Dart USB — current development

## Target

Repurpose the ASUS USB-BT600 / RTL8761CU as a standalone iPhone audio and song-info
receiver for the 2016 Dart's factory 8.4-inch Uconnect USB/iPod input.

## Working now

- Direct approved USB/HCI access from Codex; ROM 1, ASUS `0b05:1d70`.
- Memory reads and reversible RAM writes.
- Stock/custom payload transport; earlier marker hooks produced no marker.
- A complete live USB descriptor, its driver and template, located in the heap.
- **A reversible RAM edit changes the USB device descriptor response.** The test
  changes only iProduct 2 to 1, then restores the RAM word and USB response.
- The actual setup handler at **0x020be8a0 is readable over USB**. A 1 KiB capture
  matches the analogous ASUS firmware code closely and exposes the active EP0 path.
- A complete **2 MiB flash-address-region capture**, starting at 0x02000000,
  with no missing bytes; see SESSION_NOTES.md for its hash.
- **Custom RAM code executes through the USB setup callback**, writes a marker,
  and returns to the original handler. All temporary changes restore.
- **A RAM helper calls the resident flash-read routine** at 0x0000cbb5, reads
  the expected 16 bytes, returns status 0x18, and restores all borrowed RAM.
- A freestanding stereo PCM packetizer and test tone compile for the CU core
  and pass host tests. Native endpoint integration is next.

For descriptor experiments, this macOS setup returns cached data for normal
GET_DESCRIPTOR device index 0. The firmware accepts index 1 and serves its live
RAM copy; this is the request used by the successful experiment.

## Next milestones

1. Map configuration construction and endpoint queues. Produce a controlled USB
   PCM test stream and the audio/HID/iAP persona the car accepts.
2. Map physical flash offsets, boot image structure and recovery using the saved
   complete capture and the working native read path.
3. Add standalone Bluetooth audio receive/decode plus metadata/control handling.
   Inspect existing SDP/L2CAP/upper-stack code before deciding what must be added.
4. Deliver persistent boot and pairings, then test end-to-end audio/metadata and
   controls in the Dart, including ignition power cycles.

The car-facing published reference combines UAC1 audio streaming with iAP over
HID for negotiation, metadata and controls. See USB_BRIDGE.md and IPOD_PROTOCOL.md.
The exact head-unit exchange remains a car test; do not block current firmware
work on finding the owner's iPod.

## Address and storage corrections

The old file named `flash-20261017T023847Z.bin` covers CPU addresses
0x00200000..0x00400000 and includes known RAM. Preserve it as a memory capture.
Its 192 gaps are failed reads; they are not physical flash coverage percentages.
ROM flash routines classify 0x02000000 and other higher regions. CPU addresses
and physical programming offsets need an explicit mapping.

The former “216 pointers” count includes Thumb instruction encodings. The fc29
replies beginning 1f indicate command failure; fixed config/efuse behavior was an
incorrect conclusion. The old failed marker tests leave the loader entry open.
Current USB progress supersedes the earlier “USB is exhausted” conclusion.

## Hardware access

The selected geometry is consistent with Winbond-compatible 2 MiB flash. Board
packaging and accessible SPI pads have not been inspected. UART programming pins
are documented, but a clip or UART is an optional investigation rather than the
only route. FLASH_ACCESS.md keeps these details separate from the USB work.

## Tools and evidence

- bt600_vendor_read.py: bounded heap/setup reads, restored descriptor edits,
  real flash-region capture, executed RAM callback and native flash-read tests.
- descriptor_edit.py, setup_marker.py, native_flash_read.py, capture_flash.py: transport-independent
  experiment logic with restoration and partial-result handling.
- analyze_asus_firmware.py, rom_analyze.py, analyze_flash.py: offline analysis.
- SESSION_NOTES.md: latest results and exact next command.
- FIRMWARE.md: address calculations and source references; older sections are
  chronological research and their conflicting claims are superseded at the top.
