# Hardware observations

## Device and objective

| Item | Value |
| --- | --- |
| Adapter | ASUS USB-BT600 |
| USB vendor/product | `0b05:1d70` |
| Controller family | Realtek RTL8761CU |
| USB class/subclass/protocol | `e0/01/01` |
| USB device revision | `0200` |
| USB speed reported by macOS | 12 Mbps |
| Car | 2016 Dodge Dart, stock 8.4-inch Uconnect |
| Desired result | Wireless iPhone audio + track information delivered through the car's USB input |

The unmodified adapter produced "Cannot read USB Device" in the car, as reported in the prior project discussion.

## Successful Terminal probe: 2026-10-16

The user ran `python3 bt600_probe.py` from macOS Terminal and supplied this output:

```text
ASUS USB-BT600 diagnostic (USB 0b05:1d70)
Device class: e0/01/01
USB device revision: 0200
Original USB configuration: 0
HCI 1001 response: 00 0e 0e 00 0e 5d 00 61 87
HCI version: 0x0e; revision: 0x000e
LMP version: 0x0e; subversion: 0x8761
Controller manufacturer: 0x005d
HCI fc6d response: 00 01
Realtek ROM version: 1 (patch chip ID 2)
Diagnostic complete.
```

`0x1001` is HCI Read Local Version Information. `0xfc6d` is Realtek Read ROM Version. Both replies have status zero. Linux selects the patch entry whose chip ID is `rom_version + 1`, giving chip ID 2 here.

The probe selected USB configuration 1 to communicate, claimed interface 0, and restored the original unconfigured state at exit. It did not upload firmware.

## Access from the chat process

`ioreg` exposed the USB descriptors. libusb returned zero devices. A small native IOUSBHost probe found this adapter but opening it returned error `0xe00002e2`, defined by Apple's SDK as `kIOReturnNotPermitted`. The same adapter was accessible from the user's Terminal, as the output above shows.

## First memory experiment: 2026-10-16 05:29 UTC

The user's normal Terminal completed the baseline and issued four `0xfc61` queries:

| Address | HCI return parameters | Result |
| --- | --- | --- |
| `0x00000000` | `00 00 00 00 00` | Success status, four zero bytes |
| `0x00000004` | `00 00 00 00 00` | Success status, four zero bytes |
| `0x00217e88` | `00 b4 88 3b c2` | Success status, data word `0xc23b88b4` in little-endian order |
| `0x0880a0a8` | No completion received | `LIBUSB_ERROR_TIMEOUT (-7)` |

After the last query, restoring the original USB configuration failed, and the next process could no longer enumerate the adapter. The stock-upload stage therefore sent no firmware. Recovery requires unplugging and reconnecting the dongle.

This gives an actual C-chip memory-read response at `0x00217e88`; the zero-filled responses do not provide usable boot-vector anchors. The last literal is no longer used as a read target. The runner now uploads stock firmware before its optional RAM query and stops after any failed phase.

The original local transcript is `results/bt600-20261016T052909.255079Z.txt`; results files are excluded from Git.

## Results still to collect

- Version response after stock-patch upload.
- RAM contents after the stock upload and bounded RAM mapping.
- ROM/flash map, patch load address, and descriptor handling.
- Which changes survive USB reconfiguration and complete power loss.
- The car's supported USB/iPod protocol details needed for a working bridge.
