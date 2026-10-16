# RTL8761C firmware notes

## Stock files examined

| Item | Value |
| --- | --- |
| Upstream tag | `linux-firmware`, `20260221` |
| Firmware | `rtl_bt/rtl8761cu_fw.bin` |
| Firmware Git blob | `475320d0bd5c982cc472422cb37d263f785a24f3` |
| Firmware size | 10,296 bytes |
| Firmware SHA-256 | `525bfa5ab9a3ed74b788f9ac494467c522a436c1bc5290ebcb05c7f920533c09` |
| Container signature | `Realtech` (v1 epatch) |
| Container version | `0x4618d3f3` |
| Project ID | 51, RTL8761C |
| Configuration size | 11 bytes |
| Configuration SHA-256 | `3142c2732470e4edcdb68edf58cc505b581e38d56b3ec09c64eddcb1d5099507` |

Configuration bytes:

```text
55 ab 23 87 05 00 f7 00 02 00 00
```

This is a config header followed by offset `0x00f7`, length 2, data `00 00`. The meaning of that C-chip setting has not been mapped in this project.

The bytes were retrieved from a firmware mirror and matched to the Git blob and size on the upstream kernel firmware site.

## Patch selection and framing

The container has four table entries: chip IDs 0, 1, 2, 3. All point to offset 48 with length 252. The remaining image bytes after offset 300 are zero until the extension trailer near the end.

The user's ROM version 1 selects entry 2. Linux `btrtl.c` copies the first `patch_length - 4` bytes, substitutes the container version in the last four bytes, and appends the configuration. The resulting payload is 263 bytes.

| Download index | Payload bytes |
| --- | --- |
| `0x00` | 252 |
| `0x81` | 11, final fragment |

HCI opcode `0xfc20` sends the fragments. The first parameter byte is the fragment index; bit 7 marks the final fragment. The code also preserves Linux's extra final fragment when the total length is exactly divisible by 252.

## ARM code and the next question

The disassembly is in `rtl8761cu_patch_disassembly.txt`. It uses ARM Thumb instructions, consistent with Realtek's C-chip datasheet.

The selected patch is only 252 bytes, but the main routine calls offsets outside it. Decoding every `bl` in the real patch bytes gives a fixed, load-base-independent picture, because a Thumb `bl` encodes a PC-relative displacement: if the patch loads at base `B`, each call lands at `B + T0`, where `T0` is the disassembler's zero-based target.

| Call sites | Zero-based target(s) `T0` | Resolves to |
| --- | --- | --- |
| `0x10`, `0x48` | `0xffde9290` (displacement −0x216d84) | one helper at `B − 0x216d70` |
| `0x50` | `0xffff2400` (displacement −0xdc00) | one helper at `B − 0xdc00` |
| `0x54`–`0x74` | `0x220, 0x22a, 0x234, 0x23e, 0x248, 0x252, 0x25c, 0x266, 0x270` | nine entries at `B + 0x220`, spaced exactly 10 bytes |

None of those targets is inside the 252-byte patch, and all four chip entries point to the same 252 bytes, so there is no larger patch image in the file to supply them. The nine evenly spaced 10-byte targets look like a trampoline/jump table in existing code, and the two negative-displacement calls hit code below the patch. For `B − 0x216d70` to be a valid positive code address, `B` must sit at roughly `0x0021xxxx` — the same region as the patch's RAM data literals. The main routine confirms that region is live memory: it scans a table from `0x00217e88` up to `0x0021a400` (loaded from literals at offsets `0x80`/`0x98`), reading short records. The other probe literal, `0x0880a0a8`, is a mapped-flash/peripheral-window address.

The load base `B` cannot be pinned from the zero-based disassembly alone; it has to be read from the chip. The `--probe-memory` experiment reads the ARM vector table at `0x00000000` first: word 0 (initial stack pointer) gives the top of RAM and word 1 (reset vector) gives the ROM entry, which together anchor the map and let us test the `0x0021xxxx` bracket for `B`. It then reads `0x00217e88` and `0x0880a0a8`. All reads use the B family's `0xfc61` format, so the controller's reply also tells us whether that interface is shared; nothing is written.

Do not use the older B-family MIPS code as C-chip machine code. Its research is useful for protocol ideas and tooling, while C needs its own memory map and ARM hooks.

## Persistence lead

Realtek's datasheet lists an ARMv8M Real-M300 core and shows ROM/RAM/FLASH. It documents `Program_RX` and `Program_TX` on pins 19 and 20 as a UART flash-programming interface. The amount/layout of usable flash and the programming path exposed by the ASUS board are the next hardware questions.

## Primary sources and research

- [Linux firmware blob](https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/+/refs/tags/20260221/rtl_bt/rtl8761cu_fw.bin)
- [Linux Realtek Bluetooth driver](https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btrtl.c)
- [ASUS USB-BT600 Linux USB-ID support](https://git.zx2c4.com/linux-rng/commit/drivers/bluetooth/btusb.c?id=6f0624b4427e38c3bb63a951c536cf8adaee1238)
- [Google Bumble Realtek driver](https://github.com/google/bumble/blob/main/bumble/drivers/rtk.py)
- [Realtek RTL8761C datasheet, rev. 1.0](https://www.realmcu.com/img/ipa/en_638499006805399246.pdf)
- [Realtek RTL8761C user guide](https://www.realmcu.com/img/ipe/en_638481902108993028.pdf)
- [Realtek RTL8761C SDK listing](https://www.realmcu.com/en/Resources/SDK/RTL8761C-Series)
- [DarkFirmware_real_i: RTL8761B research](https://github.com/darkmentorllc/DarkFirmware_real_i)
- [Firmware mirror used to obtain bytes](https://github.com/thegwchr/RealtekBluetoothFirmware/tree/main/fw)
