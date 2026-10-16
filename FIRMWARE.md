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

The selected patch is only 252 bytes, but the main routine calls offsets such as `+0x220`, `+0x22a`, and `+0x270`. Some literal-pool references also extend beyond the selected region. These offsets need to be related to the actual controller load address and its existing ROM/flash code. The zero-based disassembly alone does not supply that map.

Literals include `0x00217e88` and `0x0880a0a8`; the optional memory probe uses these as candidate RAM and mapped-flash addresses. It tries the B family's `0xfc61` four-byte read format, allowing the C controller's reply to tell us whether that interface is shared.

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
