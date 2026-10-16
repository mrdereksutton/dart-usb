# iPod Classic reference

The owner has an iPod Classic. It supplies a real device for comparing USB
interfaces and the behavior the Dart expects from an iPod.

## Capture its USB profile on the Mac

Connect the iPod in its normal mode and run from normal macOS Terminal:

```bash
python3 capture_ipod.py
```

The command finds an Apple USB device whose product name contains `iPod` and
saves `results/ipod-TIMESTAMP-N/reference.json` plus raw device/configuration
descriptor files. It reads every advertised configuration, so the saved table
keeps interface numbers, alternate settings, USB classes, endpoint directions,
transfer types, and maximum packet sizes. It does not select a configuration or
alternate setting, claim interfaces, read music files, sync, or send iAP commands.

Use the raw bytes and interface table to compare with the BT600 capture. A USB
mass-storage interface, an HID interface, and a USB audio interface have different
jobs; keep each configuration and alternate setting attached to its own endpoints.
The saved profile describes this iPod's current Mac connection. The car may send
Apple-specific requests that change its mode or choose another configuration.

## Observe the same iPod in the Dart

Connect it to the USB port used for this project and collect one short baseline:

| Action | Record |
| --- | --- |
| Connect the iPod | Source label shown by Uconnect and whether it becomes available |
| Play a known song | Whether audio plays; title, artist, album, and elapsed time shown |
| Press pause/play in Uconnect | Whether playback follows the command |
| Press next track in Uconnect | Whether the song and displayed information change together |

The [2016 Dart Uconnect 8.4/8.4N manual, USB Operation, pages 37–44](https://vehicleinfo.mopar.com/assets/publications/en-us/Dodge/2016/Dart/1104.pdf)
is the head-unit reference. Save actual observations separately from the manual's
feature descriptions.

The Mac descriptor capture and car observations give the interface reference and
the target behavior. A packet-by-packet record of the car's initialization/iAP
exchange would require capturing the USB connection between the car and iPod;
the Mac descriptor reader does not observe that separate connection.

## Next implementation decision

Compare the iPod interface table with `USB_BRIDGE.md` and the BT600's saved
descriptors. Use actual interface classes and endpoints to choose the USB
persona to implement. Use the car observations to prioritize audio, metadata,
and controls and to select the initialization sequence to investigate next.
