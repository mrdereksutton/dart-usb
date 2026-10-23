# USB/iPod bridge implementation notes

## Usable protocol reference

The existing [oandrew/ipod-gadget](https://github.com/oandrew/ipod-gadget) implementation sends digital audio through an iPod-compatible USB connection. Its kernel side implements the USB interfaces; [oandrew/ipod](https://github.com/oandrew/ipod) implements the iAP conversation. This supplies a concrete interface reference for the ASUS firmware work. It is Linux software and cannot be flashed directly onto the RTL8761C.

The gadget's [`gadget/ipod.h`](https://github.com/oandrew/ipod-gadget/blob/master/gadget/ipod.h) defines:

| Interface | Role | Endpoint behavior |
| --- | --- | --- |
| 0 | USB Audio Class 1 audio control | No data endpoint |
| 1, alternate 0 | Audio streaming idle | No data endpoint |
| 1, alternate 1 | Audio streaming active | Isochronous IN; full-speed maximum packet 192 bytes, interval 1 ms |
| 2 | HID transport for iAP | Interrupt IN, maximum packet 64 bytes; host reports also arrive through EP0 SET_REPORT |

The PCM format is stereo, 16-bit, with discrete supported sample rates including 44,100 and 48,000 Hz. At 48 kHz this needs `48000 * 2 * 2 / 1000 = 192` audio bytes per millisecond. At 44.1 kHz the packet scheduler must average 176.4 bytes per millisecond while keeping complete four-byte stereo frames.

The gadget's README reports operation with an Onkyo receiver and notes an authentication limitation when a host requires the emulated iPod itself to authenticate. That is a separate compatibility question to observe on the Dart. The [Dart's own Uconnect 8.4/8.4N manual](https://vehicleinfo.mopar.com/assets/publications/en-us/Dodge/2016/Dart/1104.pdf) is the head-unit reference; this repository has no USB transaction capture from that head unit yet.

## Source comparison — 2026-10-22

Inspected actual source at these revisions, downloaded into ignored `results/`:

- [`oandrew/ipod-gadget`, ece6b7b](https://github.com/oandrew/ipod-gadget/tree/ece6b7b0b29dacb7be0cf9f6436fc390892969e8)
- [`oandrew/ipod`, 3762132](https://github.com/oandrew/ipod/tree/3762132cc9ad94c5301dddb9365a923350e0020f)

The first repo supplies Linux USB behavior; the companion Go client supplies the
iAP session. Both carry MIT licenses. No source was copied in this comparison.

| Finding | Reference behavior | Current Dart USB / next use |
| --- | --- | --- |
| USB identity/configurations | `gadget/ipod.h` uses Apple `05ac:1297`; `ipod_gadget.c` normally adds a storage configuration and audio/HID configuration 2, with `only_ipod` and `swap_configs` options | Our portable profile retains ASUS `0b05:1d70` and one configuration with value 2. Evaluate an iPod compatibility identity on the car; add another configuration only if the observed host requests require it. |
| Identification/session | `lingo-general/handler.go` handles StartIDPS, FID tokens, EndIDPS, identity/version queries and the accessory certificate exchange; `cmd.go` enables transaction IDs at StartIDPS and disables them for older identification | Our checked HID framing and metadata replies exist; a running session owner implementing these exchanges does not. Reuse that framing for a small C session handler. |
| Audio activation | `cmd/ipod/main.go` starts Digital Audio capability negotiation on the final accessory-certificate section; `lingo-audio/handler.go` sends sample-rate query `0a/02`, then attributes `0a/04` after reply `0a/03` | These iAP commands are missing from our C implementation. The PCM core already supports 44.1/48 kHz. Select a rate the host advertises; the Go example hardcodes 44.1 kHz and ignores the returned list. |
| Control requests | `gadget/ipod_hid.c` handles HID GET_REPORT and accepts Apple vendor request `0x40`, including its request-matching hook before configuration | Our portable control handler stalls both request types. Their need and exact setup fields must come from a host trace; avoid copying its broad request-number-only acceptance. |
| Authentication direction | The reference requests accessory credentials, but returns an empty iPod certificate and echoes the iPod-authentication challenge instead of signing it | Reuse the conversation structure. A host requiring a genuine iPod signature remains a compatibility blocker; Uconnect's requirement is unmeasured. |

The smallest useful port is the identification/audio-start session on the existing
C HID transport. Keep the current PCM/native USB adapters. No Linux kernel, ALSA,
Go runtime, generic command framework or extra mass-storage implementation is
needed for that port. Wire replies to the native HID IN endpoint, preserve
transaction IDs, and test the command sequence before a car trial.

Source pointers: [general handlers](https://github.com/oandrew/ipod/blob/3762132cc9ad94c5301dddb9365a923350e0020f/lingo-general/handler.go),
[session dispatch/audio trigger](https://github.com/oandrew/ipod/blob/3762132cc9ad94c5301dddb9365a923350e0020f/cmd/ipod/main.go),
[audio negotiation](https://github.com/oandrew/ipod/blob/3762132cc9ad94c5301dddb9365a923350e0020f/lingo-audio/handler.go),
[HID control handling](https://github.com/oandrew/ipod-gadget/blob/ece6b7b0b29dacb7be0cf9f6436fc390892969e8/gadget/ipod_hid.c).
The source review changed documentation only; no dongle or car test ran.

## What the ASUS implementation must add

Realtek's [RTL8761C user guide, section 2.1](https://www.realmcu.com/img/ipe/en_638481902108993028.pdf) describes the stock Bluetooth HCI transport: control EP0, event interrupt IN `0x81`, ACL bulk OUT/IN `0x02/0x82`, and SCO isochronous OUT/IN `0x03/0x83`. Its documented SCO alternates top out at 63 bytes per packet. Our native RAM profile now delivers 192-byte ISO IN packets for five minutes with device-side refill and verified cleanup; see [BT600_SPRINT.md](BT600_SPRINT.md). The final car-facing UAC1/HID personality and startup session still need live integration.

The standalone bridge needs these pieces to run on the dongle:

1. USB device/configuration/HID/audio descriptors and EP0 setup handling that the car accepts.
2. iAP framing, identification, digital-audio negotiation, track metadata replies, and playback commands.
3. A Bluetooth host stack with A2DP sink and AVRCP metadata/control, feeding a PCM buffer and the iAP state.
4. Codec decoding and USB audio scheduling that fit alongside the controller's radio firmware.
5. A flash image and startup path that boot all of this after power loss.

The iPod identity, audio/HID descriptors and session replies must work together.
Native endpoint access and the fixed-padding storage restoration test now pass;
Bluetooth receive, car-facing session integration and persistent startup remain.

## Additional reference, same data path

[IPOD_PROTOCOL.md](IPOD_PROTOCOL.md) maps a pinned version of RockPod's iPod
Classic USB digital-audio implementation. It adds a concrete embedded reference
for the audio/HID configuration, IDPS startup, full-speed report fragmentation,
Digital Audio lingo, and track metadata/playback commands. The physical iPod is
not required to continue this source analysis.

[`twinn1013/bt2iap`](https://github.com/twinn1013/bt2iap) connects a Linux A2DP receiver to the above iPod gadget implementation. It is useful for studying the audio routing and head-unit diagnostics. It runs on a Raspberry Pi; it does not supply RTL8761C firmware. No additional hardware is being selected or purchased as part of this project.

## Next controller evidence

The bounded `bt600_vendor_read.py --descriptor-targets` run completed at 23:16
UTC on 2026-10-16 through approved Codex execution outside the command sandbox.
The settings word matches `0b05:1d70`, but `0x002c10b4` contains 7 rather than a
descriptor pointer. See HARDWARE.md for the saved result and FIRMWARE.md for the
offline template/copy/EP0 trace. Reconcile the running firmware's layout before
choosing another pointer chain or write target. Earlier stock upload and RAM
write/restore experiments also do not need repeating. Record car acceptance
only from a car test or USB transactions captured at the head unit.
