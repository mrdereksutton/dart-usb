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

## Memory-read probe: 2026-10-16

The user ran `python3 bt600_probe.py --probe-memory` on the dongle (still running
bare ROM, version `0x000e8761`; no patch uploaded). Relevant output:

```text
Memory 0x00000000: 00 00 00 00
Memory 0x00000004: 00 00 00 00
Memory 0x00217e88: b4 88 3b c2
Diagnostic stopped: Read query response fc61: LIBUSB_ERROR_TIMEOUT (-7)   (at 0x0880a0a8)
```

Findings:

- **`0xfc61` is implemented on this C chip.** Every read that returned used status
  zero and four data bytes, so the B-family memory-read interface is shared.
- **`0x00217e88` is live memory** (`b4 88 3b c2`), confirming the `0x0021xxxx`
  region the stock patch scans is readable RAM.
- **`0x0` / `0x4` read back as zero**, so the boot vectors are not exposed there
  (VTOR-relocated or an unmapped alias), and the vector-table anchor idea does not
  apply as written.
- **`0x0880a0a8` timed out and hung the controller** (the run could not restore the
  unconfigured state; a replug cleared it). That peripheral/flash window blocks on
  read and is now excluded from routine reads.

## Results still to collect

- Version response after stock-patch upload.
- Patch load base: sweep `0x0021xxxx` with `--read-range` after `--load-stock` and
  find where the chip-2 patch prologue becomes resident.
- ROM/flash map and descriptor handling (boot vectors are not at `0x0`).
- Which changes survive USB reconfiguration and complete power loss.
- The car's supported USB/iPod protocol details needed for a working bridge.
