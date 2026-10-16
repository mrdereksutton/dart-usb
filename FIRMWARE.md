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

## Upload result on hardware: the download launches

On 2026-10-16 the stock chip-2 patch was uploaded to the dongle. Both fragments were acknowledged (`0xfc20` returned `00 00` then `00 81`), and `0x1001` Read Local Version afterward returned a running version of `0x7bf15762`, changed from the ROM's `0x000e8761`.

An earlier check treated this as a failure because it expected the container `fw_version` `0x4618d3f3`. That expectation was wrong. Confirmed against Linux `btrtl.c` (`rtl_download_firmware` → `btrtl_read_local_version`):

- The driver sends **no HCI Reset** after the fragments; the controller relaunches on the final fragment. Our flow matches it.
- The post-download version is **re-read and only logged**; `btrtl` never compares it to any expected value. The container `fw_version` is written into the download buffer's last four bytes but is used otherwise only in the crashdump header, not as a reported version.
- There is no defined "correct" post-patch `lmp_subversion`/`hci_rev`.

Offline dissection of the embedded image confirms the payload is framed correctly: the chip-2 patch already ends in `f3 d3 18 46` (= `0x4618d3f3`), so the version substitution is a no-op, and the 263-byte payload places the version and the 11-byte config exactly where `btrtl` does. `0x7bf15762` appears nowhere in the image, so it is a value the running patch reports, not an echo of uploaded bytes.

Conclusion: the `0xfc20` download path works on this C chip and the controller launches the downloaded firmware. The success signal is that the running version changes from the pre-download value; the probe now checks for that change rather than a fixed value. This is the foundation for loading a custom patch; it does not by itself prove the patch does useful work beyond relaunching.

## ARM code and the next question

The disassembly is in `rtl8761cu_patch_disassembly.txt`. It uses ARM Thumb instructions, consistent with Realtek's C-chip datasheet.

The selected patch is only 252 bytes, but the main routine calls offsets such as `+0x220`, `+0x22a`, and `+0x270`. Some literal-pool references also extend beyond the selected region. These offsets need to be related to the actual controller load address and its existing ROM/flash code. The zero-based disassembly alone does not supply that map.

Claude's [PR #1](https://github.com/mrdereksutton/dart-usb/pull/1) analyzes those relative branches. For an execution base `B`, the decoded targets are:

| Call offsets | Runtime target |
| --- | --- |
| `0x10`, `0x48` | `B - 0x216d70` |
| `0x50` | `B - 0xdc00` |
| `0x54` through `0x74`, step 4 | `B + 0x220` through `B + 0x270`, step 10 |

The regular target spacing suggests small resident entry stubs. The binary alone does not distinguish ROM, flash, or already initialized RAM at those addresses. A non-wrapping positive first target implies `B >= 0x216d70`; it does not by itself fix `B` to the `0x0021xxxx` region.

Literals include `0x00217e88` and `0x0880a0a8`; the optional memory probe uses these as candidate RAM and mapped-flash addresses. It tries the B family's `0xfc61` four-byte read format, allowing the C controller's reply to tell us whether that interface is shared.

Do not use the older B-family MIPS code as C-chip machine code. Its research is useful for protocol ideas and tooling, while C needs its own memory map and ARM hooks.

### Additional checks, 2026-10-16

Recomputing the Git object SHA-1 from the local bytes (`blob <length>\0<bytes>`) gives `475320d0bd5c982cc472422cb37d263f785a24f3`, the recorded upstream blob. The small payload is therefore present in that upstream object, rather than being caused by the base64 packaging in this script. Bytes 300 through 10,287 are zero; only the extension trailer follows.

At code offset `0x84`, the literal `0xffde8400` is signed `-0x00217c00`. Adding it to the pointer `0x00217e88` gives `0x288`. This makes `0x00217c00` a useful candidate for investigating the image layout, but this arithmetic alone does not give the CPU execution address. The initializer calls beyond offset `0xfc`; the routine at offset `0xa8` also references literals beyond the selected payload. The loader substitutes the version at offsets `0xf8..0xfb`, overlapping the end of the zero-based disassembly. Resolve the resident-code/layout question before building a custom hook.

The official C user guide describes configuration download over `0xfc20`, while its firmware-update section directs developers to Realtek's FAE. The SDK listing currently offers `RTL8761C linux SDK`, version `v20250813`; its download endpoint returns HTTP/application code 401 without a RealMCU login. The C-series Tools page lists no downloads. These are the current access points, not evidence that a standalone USB application SDK is included.

The `0xfc61` query format was checked against the research project's `RTL8761B_usbbluetooth_Memory_Reader.py`: size byte `0x20`, followed by the little-endian 32-bit address. The C-chip experiment now rejects a successful response unless it contains exactly four data bytes.

The probe incorporates PR #1's boot-vector idea, with a separate query at `0x4`: a four-byte read at `0x0` only returns the candidate initial stack pointer, never the reset vector. Values at zero and four are interpreted as candidate boot vectors; a relocated vector table, boot-memory alias, or dummy response still needs to be distinguished using subsequent reads. Initial SP is a stack address, not necessarily the physical top of all RAM; the reset handler is a code pointer, not necessarily a ROM address.

### Hardware result superseding the candidate reads

The 05:29 UTC Terminal run returned four zeroes at both zero and four, and `b4 88 3b c2` at `0x00217e88`. The read at `0x0880a0a8` then timed out; USB cleanup failed and the adapter disappeared from enumeration before any firmware upload. Treating that literal as a readable flash address was premature. It has been removed from the probe. The normal memory query now uses only the RAM address that answered; see `HARDWARE.md`. The stock upload is now attempted before the RAM query.

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
- [Realtek RTL8761C tools listing](https://www.realmcu.com/en/Resources/Tools/RTL8761C-Series)
- [Research memory-reader source](https://github.com/darkmentorllc/DarkFirmware_real_i/blob/master/04_custom_patch_writer/RTL8761B_usbbluetooth_Memory_Reader.py)
- [Researchers' newer Bluetooth firmware analysis tooling](https://github.com/darkmentorllc/bt-re-mad-skillz) (reference only; not installed or launched by this project)

## Full ASUS RTBTCore image — 2026-10-16 continuation

This supersedes the small upstream patch as the immediate source for USB code
analysis. The upstream upload result above remains a separate experiment.

Source: [ASUS Linux driver v3.1.07](https://dlcdnets.asus.com/pub/ASUS/wireless/USB-BT600/DR_USB-BT600_v3.1.07_Linux.zip),
archive SHA-256 `33eae0a21fd2153c5962cb3b4cc0fd7508924f0a929f262370ec22c81ada2ce8`.
Inside `USB-BT600_Linux driver/20251017_LINUX_BT_DRIVER.tar.gz`, the relevant
files are `usb/bluetooth_usb_driver/rtk_misc.c` and
`rtkbt-firmware/lib/firmware/rtl8761cu_mx_fw` / `rtl8761cu_mx_config`.
The driver table at line 650 selects these files for PID `0x1d70`.

The firmware is 1,075,583 bytes, signature `RTBTCore`, SHA-256
`bfadde9c084726cec144828fe6aaaa917047d39616efb66de298366993d13f46`.
The config is the same 11 bytes recorded above. Both the local archive and
firmware hashes matched the handoff on continuation.

### Selection and upgrade semantics

`insert_patch` / `rtb_get_patch_header` (lines 2299–2435) choose ECO equal to
ROM revision plus one. The observed ROM 1 selects ECO 2, priority 15, snippet
file offset `0x834d2`, size `0x834a2` (537,762 bytes). The snippet begins
`01 07`, followed by seven `<HHII>` records: image ID, reserved halfword,
size, version. Data begins at snippet offset `0x56`.

| Image | Snippet offset | Size | Version |
| --- | --- | --- | --- |
| `0x2790` | `0x56` | `0x400` | `0x1` |
| `0x2791` | `0x456` | `0xb30` | `0x002c4002` |
| `0x2793` | `0xf86` | `0x336b8` | `0x4bc010b3` |
| `0x2794` | `0x3463e` | `0xb780` | `0x0200050a` |
| `0x2795` | `0x3fdbe` | `0xb6a0` | `0x0200050a` |
| `0x279c` | `0x4b45e` | `0xe450` | `0x002c4002` |
| `0x279d` | `0x598ae` | `0x29bf4` | `0x002a5002` |

`rtk_vendor_read(..., READ_SEC_PROJ)` (lines 2769–2859) sends `fc61` with
`10 a4 ad 00 b0`. The user's `00 00 00` return means success and key ID zero,
according to the first data byte the loader uses. It does not describe all
boot/signing policy. The driver's separate `rtk_vendor_read_reg32` uses selector
`0x21`; this project's targeted probe retains the already working `0x20` format.

`needs_hci_upgrade` (lines 2872–2916) sends `fdbb`, subcommand 1 and up to 128
bytes of selected data. At lines 3441–3458 a positive state selects firmware
without config; a nonpositive return selects config only (or a short zero block
when config is absent). No `fdbb` negotiation or full ASUS image upload has been
performed. Do not equate this upgrade path with the prior 263-byte stock upload,
or assume it is volatile. The offline extractor has no USB or upload code.

### Reproduce extraction and disassembly

```sh
python3 analyze_asus_firmware.py /path/to/rtl8761cu_mx_fw --output results/asus-eco2
cd results/asus-eco2
xcrun clang -target armv8m.main-none-eabi -c asus-app.S -o asus-app.o
xcrun llvm-objdump -d --no-show-raw-insn --adjust-vma=0x02167400 asus-app.o > asus-app-disassembly.txt
```

Choose a new output directory for each extraction. The tool requires the exact
firmware hash, checks section/snippet/image bounds, and writes `map.json`, the
application payload, and an assembly wrapper. Firmware outputs remain ignored
under `results/`; no vendor firmware is added to Git. Python alone suffices for
extraction; the two disassembly commands use Apple's Command Line Tools.

Image `0x2793` has a 1024-byte header. Header words at image offsets `0x14c`
and `0x150` both contain `0x02167400`. Mapping its payload at this address gives
coherent Thumb instructions and literal references. Payload file offset is
`0x84858` (`0x834d2 + 0x1386`), length 209,592, SHA-256
`a3126e4a3922d8d46da8ce94c6024994130c9f2980395d0ae196f80fac008e17`.
For an address `A` in this payload, file offset is
`0x84858 + A - 0x02167400`. This is an offline execution-map interpretation;
no read from the dongle has matched it yet. Literal pools and strings can be
printed as instructions by linear disassembly; follow control flow and resolve
Thumb PC-relative loads using `Align(A + 4, 4) + immediate`.

### Descriptor template and the active EP0 copy

All addresses below refer to the pinned ECO-2 application above, not measured
live locations. `B = 0x002c10a8` is a global USB state block.

| Instruction address | Evidence / inferred role |
| --- | --- |
| `0x02177650..0x02177660` | Allocation requests 18 bytes; name string resolves to `alloc_assign_device_descriptor_content` |
| `0x02177662..0x02177664` | Loads `B` from literal pool `0x02177804`, stores descriptor pointer at `B + 0x0c = 0x002c10b4` |
| `0x02177692..0x02177698` | Fills Bluetooth device class `e0/01/01` |
| `0x021776ac..0x021776b2` | VID/PID copied from `0x002808a8 + 0x10/+0x12` (word at `0x002808b8`) |
| `0x0217756e..0x0217758c` | Allocates a `0x48`-byte driver object `D`, stores it at `B + 8`, copies template pointer to `D + 4` |
| `0x021776d6..0x021776fe` | Initializes template, builds driver, passes `D` to registration at `0x02189a46` |
| `0x02189a6c..0x02189a70` | Stores Thumb callback `0x0218958d` at `D + 0x34`; setup-handler entry is `0x0218958c` |
| `0x02189418..0x02189460` | Bind allocates composite state `C` of size `0x38`; gadget object `G` stores `C` at `G + 0x3c`; bind setup keeps `D` at `C + 0x30` |
| `0x021894c0..0x021894c6` | Calls descriptor-copy helper with destination `C + 0x0c` and source `[D + 4]` |
| `0x021893b0..0x021893fa` | Copies 18 bytes, preserving nonzero destination identity/string fields |
| `0x0218549c..0x021854e2` | EP0 dispatcher routes standard request 6 through driver setup, as well as class/vendor requests |
| `0x021851ea..0x0218520c` | Indirect setup callback via the registered driver |
| `0x0218961a` | TBB dispatch: request 6 resolves to `0x0218962a` |
| `0x0218962a..0x0218964e` | Checks request type `0x80`, selects descriptor type 1 |
| `0x0218964e..0x02189672` | Refreshes configuration count and EP0 packet size in `C + 0x0c`, then copies `min(wLength, 18)` bytes from that active descriptor into the EP0 request buffer |
| `0x021898a0..0x021898ac` | Queues response through endpoint operations callback |

**Implication:** `*[0x002c10b4]` is the initialization template. EP0 serves the
copy at `C + 0x0c`. Editing the template after binding may leave GET_DESCRIPTOR
unchanged. Do not choose a write target solely because its 18 bytes match USB.
The probe now compares the candidate template against a standard GET_DESCRIPTOR
response collected in the same configured session, without changing memory.

An additional offline chain can locate the active copy if the live image matches:
registration at `0x02188a2a` loads context `R = *[0x002c1240]`, stores the driver
at `R + 0x48`, then passes `G = R + 4` to its bind callback. Thus the inferred
active descriptor is `*[R + 0x40] + 0x0c`. The literal `0x002c1240` is at
`0x02188a80`. **This chain has not been read on hardware and is not added to
`--descriptor-targets`.** First interpret the prepared target result; then, if
appropriate, design a separate bounded chain read with null/alignment/range
checks at every hop. No write or guessed MMIO read follows from this map.

Configuration descriptor construction is also visible at `0x02188e9e`: it
builds the nine-byte header and appends per-function descriptors through
`0x02188c84`. The GET_DESCRIPTOR configuration path calls `0x02188f1c` at
`0x02189720`. This gives a specific next offline target for the UAC1/HID persona.
The 192-byte/ms audio endpoint capacity, A2DP/AVRCP stack, and persistent boot
implementation remain unresolved.


### Live result qualifying this map

The 23:16 UTC targeted read returned word `0x00000007` at `0x002c10b4`, and
`05 0b 70 1d` at `0x002808b8`. The former was not followed. Standard EP0
reported USB `0x0110`, class `e0/01/01`, VID/PID `0b05:1d70`. See HARDWARE.md
for exact bytes and saved result. The probe ran with the original `0x000e8761`
runtime and ROM 1; the full ASUS image has never been uploaded.

The matching identity settings support that specific address calculation, but
not the whole application-global map. The template pointer and active-copy
context chain remain unlocated in the running firmware. Next analyze differences
between the installed runtime and the downloadable application's initialization
and global layout before preparing another narrowly justified read. Do not
interpret the value 7 as a pointer or edit it.
