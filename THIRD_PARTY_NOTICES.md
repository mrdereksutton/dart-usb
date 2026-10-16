# Third-party material and license scope

The root MIT LICENSE covers original project code and original documentation. Third-party material retains its own ownership and terms. References to other projects do not relicense their code or incorporate it into Dart USB.

## Realtek firmware

`bt600_probe.py` embeds unmodified copies of `rtl8761cu_fw.bin` and `rtl8761cu_config.bin` as base64 data. Their copyright and terms are reproduced in REALTEK_FIRMWARE_LICENSE.txt. These firmware bytes are excluded from the project's MIT license. Framing a payload for the controller does not grant additional rights in the underlying firmware.

| File | SHA-256 |
| --- | --- |
| `rtl8761cu_fw.bin` | `525bfa5ab9a3ed74b788f9ac494467c522a436c1bc5290ebcb05c7f920533c09` |
| `rtl8761cu_config.bin` | `3142c2732470e4edcdb68edf58cc505b581e38d56b3ec09c64eddcb1d5099507` |

Provenance: [linux-firmware, tag 20260221](https://kernel.googlesource.com/pub/scm/linux/kernel/git/firmware/linux-firmware/+/refs/tags/20260221/rtl_bt/). The recorded firmware Git blob is `475320d0bd5c982cc472422cb37d263f785a24f3`. FIRMWARE.md documents the image and protocol sources.

`rtl8761cu_patch_disassembly.txt` contains output derived from the vendor firmware, rather than original MIT-licensed machine code. It is also excluded from the project's MIT license. The project license grants no additional permissions for vendor firmware or derived vendor material; consult the vendor terms directly.

## Research and implementation references

FIRMWARE.md and USB_BRIDGE.md link Linux btrtl, Google Bumble, Realtek documentation, DarkFirmware research, and the iPod gadget projects. Those projects retain their respective licenses. Before copying source or adding another firmware image, record its origin and license explicitly. ASUS, Realtek, Apple, Dodge, and Uconnect names identify third-party products and protocols; this project makes no claim of affiliation or endorsement.
