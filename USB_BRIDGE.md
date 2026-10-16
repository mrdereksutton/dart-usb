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

## What the ASUS implementation must add

Realtek's [RTL8761C user guide, section 2.1](https://www.realmcu.com/img/ipe/en_638481902108993028.pdf) describes the current Bluetooth HCI transport: control EP0, event interrupt IN `0x81`, ACL bulk OUT/IN `0x02/0x82`, and SCO isochronous OUT/IN `0x03/0x83`. Its documented SCO alternate settings top out at 63 bytes per packet. Those stock settings do not implement the UAC1 source above. The USB controller's ability to be reprogrammed for a 192-byte isochronous IN endpoint still needs to be mapped.

The standalone bridge needs these pieces to run on the dongle:

1. USB device/configuration/HID/audio descriptors and EP0 setup handling that the car accepts.
2. iAP framing, identification, digital-audio negotiation, track metadata replies, and playback commands.
3. A Bluetooth host stack with A2DP sink and AVRCP metadata/control, feeding a PCM buffer and the iAP state.
4. Codec decoding and USB audio scheduling that fit alongside the controller's radio firmware.
5. A flash image and startup path that boot all of this after power loss.

An Apple VID/PID change by itself implements none of those behaviors. The iAP-over-HID and audio descriptors are implementation targets, while endpoint/firmware access on this C chip is the immediate dependency.

## Additional reference, same data path

[IPOD_PROTOCOL.md](IPOD_PROTOCOL.md) maps a pinned version of RockPod's iPod
Classic USB digital-audio implementation. It adds a concrete embedded reference
for the audio/HID configuration, IDPS startup, full-speed report fragmentation,
Digital Audio lingo, and track metadata/playback commands. The physical iPod is
not required to continue this source analysis.

[`twinn1013/bt2iap`](https://github.com/twinn1013/bt2iap) connects a Linux A2DP receiver to the above iPod gadget implementation. It is useful for studying the audio routing and head-unit diagnostics. It runs on a Raspberry Pi; it does not supply RTL8761C firmware. No additional hardware is being selected or purchased as part of this project.

## Next controller evidence

Run `python3 bt600_vendor_read.py --descriptor-targets` in normal Terminal and
read its saved JSON. This is the bounded next experiment; the earlier stock
upload and RAM write/restore have already succeeded. FIRMWARE.md now traces
ASUS ECO-2's template allocation, binding-time descriptor copy, setup callback,
and EP0 response. Matching the template to GET_DESCRIPTOR does not alone locate
the active descriptor copy. Keep the full ASUS upgrade path separate from the
prior small stock upload. Record car acceptance only from a car test or USB
transactions captured at the head unit.
