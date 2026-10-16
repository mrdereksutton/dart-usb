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

## Results still to collect

- Version response after stock-patch upload.
- Whether memory-read opcode `0xfc61` is implemented on this C chip.
- ROM/flash map, patch load address, and descriptor handling.
- Which changes survive USB reconfiguration and complete power loss.
- The car's supported USB/iPod protocol details needed for a working bridge.
