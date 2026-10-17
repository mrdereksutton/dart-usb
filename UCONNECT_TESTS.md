# Uconnect 8.4 field tests — Bluetooth, USB audio, and artwork

**Reported:** October 2026  
**Vehicle:** 2016 Dodge Dart, factory 8.4-inch Uconnect  
**Phone:** iPhone  
**Music app:** Apple Music

This is a record of the owner's direct observations, not a USB packet capture or a confirmed diagnosis.

## Objective

Provide wireless music playback with track information on the original Uconnect screen, without plugging the phone into the car's USB port. The phone can stay on a magnetic wireless charging mount. The project is investigating a Bluetooth-to-USB/iPod bridge using the ASUS USB-BT600.

## Current Bluetooth behavior

- Factory Bluetooth plays audio, but the Uconnect display shows only **"Derek's iPhone"**, not the current song title, artist, or album.
- Bluetooth auto-connection used to be inconsistent.
- **Deleting other devices from Uconnect's paired-device list fixed the auto-connection problem.** It is not currently an outstanding problem to solve.
- The main remaining reason for the project is to obtain **USB-like music metadata over a wireless connection**.

Whether the missing Bluetooth track information is caused by AVRCP compatibility, feature negotiation, Uconnect behavior, or something else remains unverified.

## Direct USB comparison

The tests used the **same iPhone, Apple Music app, song, and car USB port**.

| Observation | Cheap gas-station USB-A-to-USB-C cable | Focusrite USB-A-to-USB-C cable |
| --- | --- | --- |
| Charging | Continued charging | No charging problem reported |
| Audio | Worked briefly, then skipped tracks or paused almost immediately | Stable playback with good sound |
| Album art | **Actual album artwork appeared immediately** | **Generic music-note placeholder** |
| Track | Same Apple Music song | Same Apple Music song |

Additional details:

- Music through USB does supply track information that is missing through Bluetooth.
- The owner already experimented with **Music Info Cleanup**, without a confirmed resolution to the artwork difference.
- The Focusrite playback test may not have run for a full 20–30 seconds, but the inexpensive cable displayed artwork **immediately**, without waiting.
- Stable playback with the Focusrite cable demonstrates that the USB port can function as a reliable audio connection in at least this test.
- Charging over the inexpensive cable does not demonstrate that its USB data link was stable.

The reason for the different artwork behavior is **unknown**. Cable data integrity, iPhone/Uconnect initialization, caching, local artwork lookup, and media-control behavior are possibilities to test, not findings.

## Stock ASUS USB-BT600 test

When the **unmodified** ASUS USB-BT600 was plugged into the car's USB port, Uconnect displayed:

> USB — Cannot read USB Device

The USB-BT600 does not have a status light. This test shows the stock adapter was not accepted as usable media, but does not identify the stage of USB enumeration or media protocol handling that failed, nor whether a modified device could work.

## Confirmed takeaways

1. Bluetooth pairing/automatic connection is now working after deleting old pairings.
2. Factory Bluetooth audio works but does not display track metadata in the observed sessions.
3. USB playback can be stable with the Focusrite cable.
4. Uconnect can display actual album artwork during at least one direct USB playback session.
5. Artwork presentation varied across USB connection sessions even with the same Apple Music song.
6. The stock BT600 was rejected by Uconnect as a readable USB media device.

## Research questions / next experiments

- Inspect whether Uconnect and the iPhone exchange AVRCP metadata on factory Bluetooth, without assuming the failure mechanism.
- Characterize the working iPhone/iPod USB interface, including track title, artist, album and potential artwork handling.
- Compare USB connection initialization and Uconnect media screen behavior across repeated known-good cable sessions.
- If an iPod Classic becomes available, use it as a reference for USB/iPod communication with the vehicle.
- For the Bluetooth-to-USB bridge, map received Bluetooth metadata to the USB/iPod metadata responses actually requested by Uconnect.
- Keep observed behavior separate from protocol hypotheses until the relevant transactions are captured.

## Related documentation

- [README.md](README.md) — project purpose and progress.
- [USB_BRIDGE.md](USB_BRIDGE.md) — proposed USB/iPod bridge design.
- [HARDWARE.md](HARDWARE.md) — USB-BT600 controller observations.
- [Draft PR #3](https://github.com/mrdereksutton/dart-usb/pull/3) — active USB descriptor/iPod protocol research.
