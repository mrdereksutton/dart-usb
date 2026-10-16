# Published iPod Classic USB/iAP implementation reference

The physical iPod is not needed to continue the protocol work. The most useful
new source is [nuxcodes/rockpod](https://github.com/nuxcodes/rockpod), a Rockbox
fork implementing USB digital audio on iPod Classic 6G/7G. Its README identifies
the OPPO HA-2SE as its primary tested accessory. The code gives us a device-side
implementation of USB audio, iAP HID transport, identification, and metadata.

This analysis pins RockPod to commit
[`951d17c0575fbb61f3c585b5f0c3a0a941dcb10f`](https://github.com/nuxcodes/rockpod/tree/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f).
It describes that public implementation, rather than a stock Apple firmware dump
or a captured Uconnect session. The owner's iPod capture can be added later.

## USB personality to reproduce

In this connection the car/accessory is the USB host and the emulated iPod is
the USB device. USB IN therefore carries audio and replies from dongle to car.

| Component | Reference behavior | Source |
| --- | --- | --- |
| USB device | Class determined per interface; EP0 maximum packet 64 bytes | [usb_core.c](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/firmware/usbstack/usb_core.c) |
| Configuration 1 | Storage/normal computer connection | Same file, class-driver configuration assignments |
| Configuration 2 | USB Audio Class 1 source plus iAP HID | Same file, audio and iAP HID drivers assigned to configuration 2 |
| Audio Control | Interface followed by source input/output terminal descriptors | [usb_audio.c](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/firmware/usbstack/usb_audio.c), source descriptor list |
| Audio Streaming | Alternate 0 idle; alternate 1 enables one isochronous IN endpoint | Same file, source AS descriptors |
| Audio format | Stereo, 16-bit PCM; 192-byte maximum packet; full-speed interval 1 ms | Same file, source format/endpoint and descriptor packing |
| iAP HID | One interrupt IN endpoint, maximum 64 bytes; host sends reports through EP0 SET_REPORT | [usb_iap_hid.c](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/firmware/usbstack/usb_iap_hid.c) |

The 192-byte packet supports `48000 * 2 channels * 2 bytes / 1000` per
millisecond. At 44.1 kHz, schedule whole four-byte stereo frames averaging
176.4 bytes/ms. Endpoint numbers in RockPod are allocated by its USB driver;
copy the roles and transfer requirements into the RTL8761C mapping.

## Full-speed HID transport

The reference uses a vendor HID usage page `0xff00`. Its report format starts
with report ID, then link-control byte, then the framed iAP data. The UART
`0xff` sync byte is omitted on USB; the iAP `0x55` marker remains.

| Direction | Report ID and declared report-data bytes, excluding report ID |
| --- | --- |
| iPod/device to car/host | `1:12`, `2:14`, `3:20`, `4:63` |
| Car/host to iPod/device | `5:8`, `6:10`, `7:14`, `8:20`, `9:63` |

One data byte is the link-control byte. Values are `0x00` single, `0x02` first,
`0x03` middle, and `0x01` last. A 63-byte report-data size therefore carries
62 iAP bytes. Keep the report ID/size for every fragment of one frame and pad
reports to their declared size. Continuations contain raw bytes and must not be
rescanned for a new marker. Transaction IDs become active at StartIDPS.

RockPod explicitly identifies its 96-byte full-speed report descriptor as a
compatibility construction derived from ipod-gadget; it is not Apple's stock
208-byte HID report descriptor. Use it as the reference implementation profile.

Source: `usb_iap_hid.c`, report tables, TX fragmentation, RX reassembly, and
GET_DESCRIPTOR/SET_REPORT handlers; transaction handling in
[iap-lingo0.c](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/apps/iap/iap-lingo0.c).

## Startup and audio activation

Implement these as states with replies, timeouts, and per-session transaction
IDs. This is the reference flow to compare against the car's requests:

1. Host enumerates descriptors and selects the audio/HID configuration.
2. General lingo `0x00`: receive StartIDPS `0x38`, SetFIDTokenValues `0x39`,
   and EndIDPS `0x3b`; return the corresponding identification replies.
3. Process the accessory certificate/challenge exchange. The device-side
   sequence uses `0x14..0x19` on General lingo. RockPod's `0x18` handler
   acknowledges the accessory signature without cryptographic verification;
   its behavior should not be mistaken for an Apple authentication implementation.
4. Digital Audio lingo `0x0a`: device sends GetAccessorySampleRateCaps `0x02`,
   receives RetAccessorySampleRateCaps `0x03`, and selects an advertised rate.
5. Device sends TrackNewAudioAttributes `0x04`; host acknowledges with
   AccessoryAck `0x00`. The reference retries unacknowledged attributes and
   announces track changes. Its Digital Audio lingo version is 1.02.
6. Host selects the streaming alternate setting; device supplies PCM on ISO IN.

Sources: `iap-lingo0.c` IDPS/auth handlers;
[iap-core.c](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/apps/iap/iap-core.c),
`iap_periodic`, `iap_send_audio_attrs`, and `iap_handlepkt_mode10`;
`usb_audio.c`, source endpoint and alternate-setting handlers.

## Track information and playback controls

The Extended Interface lingo is `0x04` and uses two-byte command IDs.
RockPod's
[iap-lingo4.c](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/apps/iap/iap-lingo4.c)
provides concrete request/reply behavior:

| Car request | Command | Device reply/event |
| --- | --- | --- |
| Playback time/status | `0x001c` | `0x001d` |
| Current track index | `0x001e` | `0x001f` |
| Track title | `0x0020` | `0x0021` |
| Artist | `0x0022` | `0x0023` |
| Album | `0x0024` | `0x0025` |
| Enable playback notifications | `0x0026` | Notifications `0x0027` |
| Playback control | `0x0029` | Command acknowledgment and requested playback action |

The Display Remote lingo (`0x03`) and Simple Remote (`0x02`) are additional
control paths. Start with the commands the car requests; map AVRCP metadata and
playback state into these iPod-side replies rather than into USB descriptors.

## What this changes for Dart USB

We now have published source for the USB topology, HID packet transport, digital
audio activation, and metadata/control commands. The BT600's next hardware step
remains finding its descriptor/EP0 data path using the saved RAM capture. Once
that path can be changed, the protocol work can use these handlers as a concrete
reference instead of designing the car-facing behavior from scratch.

RockPod is GPLv2; no RockPod source has been copied into this project's MIT code.
Keep source attribution and licensing with any future code port. The downloaded
analysis copies are under ignored `results/research/`, with a pinned source
manifest; this file records the protocol findings.
