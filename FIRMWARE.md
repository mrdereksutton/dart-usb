# RTL8761C firmware notes

## Live descriptor control and setup handler — 2026-10-17

A restored edit of `iProduct` at composite descriptor word `0x0030d198` changed
byte 15 of the actual USB reply from 2 to 1. Result:
`results/bt600-targets-20261017T101804.507832Z.json`. Both RAM and USB response
returned to baseline afterward. GET_DESCRIPTOR index 0 returned cached host data;
index 1 reached the device. The running code ignores the low descriptor index
for device descriptors. Use that request distinction for future bench tests.

The driver object at `0x0030d130` has setup callback `0x020be8a1` at offset 0x34.
A targeted 1 KiB read of entry `0x020be8a0` succeeded over fc61. Compare with ASUS
application offset `0x2218c`, linked at `0x0218958c`: 1000/1024 bytes are identical.
The live GET_DESCRIPTOR path at `0x020be962..0x020be986` serves `C+0x0c`, refreshing
configuration count and EP0 maximum packet size. The standard-request dispatch
is at `0x020be92e`. Saved code and annotated disassembly are in
`results/runtime-setup/`; source JSON is `...101448.581977Z.json`.

The host stack's control-transfer implementation calls IOKit DeviceRequestAsyncTO;
its cached descriptor helper is a separate path. The observed index distinction
is recorded as behavior of this macOS/device combination rather than assumed
from the libusb API name. Source:
https://github.com/libusb/libusb/blob/master/libusb/os/darwin_usb.c

## Related public SDK reference

Realtek publishes a related audio SDK at
https://github.com/rtkconnectivity/RTL87x3E-Common-SDK . This continuation pins it
to `ae842d07494ac53cf966e34684804baeed86676e` and checks out only selected headers
and samples under `/private/tmp/bt600-rtk-common-sdk`.

Useful files are `inc/usb/hal/hal_usb.h` (endpoint and isochronous request APIs),
`inc/usb/composite/usb_composite_dev.h` (device/interface registration),
`inc/usb/composite/usb_dev_driver.h` (descriptors and vendor callbacks),
`src/sample/usb_demo/usb/audio/usb_audio1.c` / `usb_audio_stream.c`, and
`inc/framework/bt/bt_a2dp.h` / `bt_avrcp.h`. The USB driver documents a default
512-byte control-transfer buffer. The audio headers describe SBC/AAC and stream
callbacks. These headers are for the related RTL87x3E family: compare their
layouts and APIs with the live CU code before binding an entry point.
No SDK source or prebuilt image has been copied into this repository or loaded.

The new actual flash capture contains `imp_patch_upperstack_btif_handle_command`
at `0x0208fb8b`, L2CAP/SDP patch names nearby, mSBC/PCM pipeline names around
`0x020a5b70`, and codec driver names around `0x020c4650`. These give specific
subsystems to inspect for reuse as the Bluetooth/audio work proceeds.

## Current corrections — 2026-10-17

Read this section before the chronological research below.

- The file named `flash-20261017T023847Z.bin` is a CPU-address-space capture at
  `0x00200000..0x00400000`, including known writable RAM and the USB heap.
  Its SHA-256 is `5b701222ea076e324a039b25ff79ada4fb843a0e50a444f9ff44f080f9b9c3df`.
  The 192 gaps describe failed reads, not physical flash coverage. SPI offsets
  cannot be calculated by subtracting `0x00200000` without another mapping step.
- The ROM flash-address classifier at `0x560c` recognizes regions beginning at
  `0x02000000`, `0x04000000`, `0x06000000`, and `0x10000000`. The read wrapper at
  `0xcbb4` rejects classifier result 4. Preserve that extra hexadecimal digit.
- The exact USB device descriptor is present at `0x0030d18c` in the capture.
  Candidate composite `C=0x0030d180` stores it at `C+0x0c`; `C+0x30` points to
  candidate driver `D=0x0030d130`; `D+4` points to template `0x0030d110`.
  Template EP0 size is 8; the composite copy reports 64, matching USB.
  Runtime addresses must be freshly checked before a reversible edit.
- The earlier “216 pointers” count is reproducible by counting all aligned
  four-byte integers in `0x00100000..0x00200000`. It includes Thumb instructions:
  `0x2e7c` is `ldrb.w r0,[sp,#0x10]`, and `0x4510` is
  `bfi r0,r5,#0,#0x18`. It does not locate the patch loader in that bank.
- Recorded fc29 completions beginning `1f` are errors. ROM `0x13ff6` generates
  that status when the task callback fails. The callback receives address/length
  arguments; its backing store remains to be traced. Avoid config/efuse writes.
- The custom-patch experiments recorded no marker. Version changes also happen
  with a `bx lr` replacement, so download acceptance and code execution need
  separate reporting. The marker's owner/lifetime and loader entry remain open.
- USB investigation remains active. An external clip depends on board/package
  inspection; an inaccessible CPU bank is not automatically external-flash data.

The earlier sections are retained as research history. These corrections
supersede contradictory conclusions about the memory map, descriptor absence,
fixed fc29 storage, patch execution, and exhaustion of USB options.

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

### ROM constant-scan result, 2026-10-17

Ran `rom_analyze.py` on the 647168-byte ROM block
(`results/descriptor-20261017T002154.077318Z`, `0x00001000..0x0009f000`). The
byte-constant heuristics do **not** locate the descriptor builder in this image;
their hits are coincidental. Checked each class against the actual code:

- **"PID 0x1d70" literals (49x, e.g. 0x27068).** The matched word is
  `0x00281d70`, used as a pointer, not a USB PID. At `0x00026c70` the code is
  `ldr r3,[pc]=0x281d70 ; ldr r3,[r3] ; blx r3` — it loads the word stored at
  address `0x00281d70` and calls it. `0x1d70` is only the low halfword of that
  address, which sits outside this ROM window. Every "PID" hit is this idiom.
- **"config-sig 0x0209" immediates (0x90f86, 0x982c8).** Both are
  `movw rN,#0x209 ; add.w rN,rN,rK,lsl#3 ; ldrb rN,[base,rN]` — `0x209` is a
  byte-table offset, not a `bLength 0x09 / bDescriptorType 0x02` signature.
- **"device-class 0x01e0" and bare-halfword hits.** These are low or high
  halfwords of unrelated 32-bit words, not descriptor bytes.

The ROM region is genuine ARM Thumb code (256k+ instructions decode cleanly,
with regular `push {..,lr}` / `pop {..,pc}` prologues), so the problem is the
heuristic, not the image. Two- and three-byte USB constants are too common to
pin a 32-bit RISC image. This agrees with the earlier result that the assembled
descriptors are not a contiguous blob in any `fc61`-readable region: they are
built at enumeration, and single-constant matching will not find the builder.

### USB descriptor ground truth (from the captured bytes, not disassembly)

Parsed `configuration_0.bin` directly. The stock dongle enumerates as its
Bluetooth HCI controller, class `e0/01/01` (Wireless / RF / Bluetooth), two
interfaces:

- **Interface 0, alt 0:** interrupt IN `0x81` (HCI events, 64 B), bulk OUT
  `0x02` / bulk IN `0x82` (ACL data, 64 B each). bInterval 1 on the interrupt EP.
- **Interface 1, alts 0-6:** isochronous IN `0x83` and iso OUT `0x03`, one alt
  per SCO voice bandwidth. `wMaxPacketSize` climbs 0, 9, 17, 25, 33, 49, 63
  bytes across the alt settings; bInterval 1 (one packet per 1 ms frame).

So the largest stock isochronous packet is **63 bytes/frame**, and it is an HCI
**SCO voice** endpoint, not a music-streaming endpoint. The car's USB input
wants an iPod/iAP or USB-audio device, which is a different device class
entirely; reshaping this HCI config is not the same as bumping one SCO alt.

On the 192 bytes/ms question: full-speed isochronous allows up to 1023
bytes/frame, so 192 B/frame (48 kHz x 16-bit x 2 ch = 192 B/ms) is well within
the USB budget. The constraint is not the bus. It is that the bytes must come
from a UAC1 streaming endpoint the firmware actually fills, which this stock
image does not expose. That endpoint has to be created, not resized.

### Better way to find the builder next

Single USB constants are too short. Search the ROM for the **distinctive
multi-byte fragments** of the real descriptors instead (config header
`09 02 c8 00 02 01`, the `09 04 ..` interface records, the ascending iso-size
table `00 09 11 19 21 31 3f`), and for code that references wherever those live.
`rom_analyze.py` now has a `--fragments` scan for exactly this; on this ROM it
reports none, which is the same negative result by a sharper method. The
remaining positive lead is to dump the `0x00210000` RAM window while audio is
actively streaming and diff it against the idle dump, to catch the descriptor
and endpoint buffers while they are populated.

### EP0 standard-request path located, 2026-10-17

Found the EP0 control path by its request-code structure, not by byte constants.
A window around `0x0003c1de` compares `bRequest` against the full standard
device-request set (CLEAR/SET_FEATURE 3, SET_ADDRESS 5, GET/SET_DESCRIPTOR 6/7,
GET/SET_CONFIG 8/9, GET/SET_INTERFACE 10/11). The surrounding block
`0x0003c14c..0x0003cb60` is the device-request handler. All addresses below are
read from the ROM dump; the `0x28xxxx` targets are pointers into the runtime data
region and have not been read yet.

- **USB device context.** Reached through the pointer at `0x00285254`:
  `ctx = *0x00285254 + devindex * 0x440` (the code is `r0*17 << 6`). Every
  EP0 function indexes this array.
- **Per-request state tables.** `0x0003c20c` and `0x0003c256` read/write a 3-bit
  field per `bRequest` in packed registers at context offsets `0x1cc..0x1d4`.
  These track request progress; they are not the descriptor source.
- **Control-transfer descriptor state.** At context offset `0x298`: the descriptor
  type is byte `+0x14`, the returned length is word `+4` (handler `0x0003ca8c`).
- **Descriptor selector.** `0x0003cad6` maps an internal 1/2/3 selector to the
  descriptor message IDs `0x2ca`, `0x2c8`, `0x2c9` and tail-calls `0x00076b7c`
  through the table at `0x00283e84`.
- **Descriptor delivery is a runtime callback, not ROM bytes.** `0x00076b7c`
  loads a callback from `*(0x00285c0c + 0x48)` and calls it (`blx r7`) to produce
  the descriptor, falling back to `0x00076b1e`. The callback pointer lives in the
  `0x28xxxx` data region and is registered at run time. This is why the device
  and configuration descriptors are not stored verbatim anywhere `fc61` reads:
  they are emitted by a registered handler, keyed by message ID, from RAM state.

So changing what the dongle enumerates as means changing that registered handler
or the data it reads, both in the `0x28xxxx` region, not patching a ROM table.

### The structure at 0x285c0c is a callback vector

Traced every access to `0x00285c0c` in the ROM. It is a dispatch vector: the
block `0x000769a4..0x00076fb0` loads a function pointer from a fixed offset and
calls it, one offset per message opcode, across `+0x08, +0x0c, +0x10 ... +0x48`
(17 slots), with byte flags at `+0x00` and `+0x01`. The descriptor path uses two
of these slots: `0x00076b7c` calls `*(0x285c0c+0x48)` and the fallback
`0x00076b1e` calls `*(0x285c0c+0x38)`. No ROM instruction writes these slots with
a literal; they are installed at init by a register call, so their values live
only in the live `0x28xxxx` RAM and cannot be resolved from this static dump.
Everything resolvable offline is now resolved; the builder address is behind
these slots.

### Next experiment (Mac, read-only, minimal)

The `0x28xxxx` bank is live: ROM code already loads `*0x00281d70` as a function
pointer and calls it. Read the callback vector with `fc61` to get the handler
addresses directly:

    0x00285c14 .. 0x00285c54   the 17-word vector (0x285c0c + 0x08 .. +0x48)
    0x00285254                 USB device-context array pointer (optional cross-check)

The word at `0x00285c0c + 0x48` is the primary descriptor handler and `+0x38` the
fallback. Both will point back into ROM, inside this dump, so once read they can
be disassembled offline to see how the descriptor bytes are staged and whether a
UAC1 streaming endpoint can be added.

The current `--read-range` reader is whitelisted to `0x00217000..0x00217fff`;
widen it to `0x00285000..0x00286000` for this read, a few aligned words at a time,
stopping on the first failed read (as the existing reader does). Do not read
`0x000a0000` or `0x0880a0a8`; those hang the controller.

### Hardware read of the callback vector, 2026-10-17

Ran `python3 bt600_probe.py --read-range 0x285c14 17` on the connected dongle
(read-only; no firmware load, no write). The `0x285c0c` vector, idle stock state:

    +0x20 (0x285c2c) = 0x00205c2b   handler, Thumb entry 0x00205c2a
    +0x38 (0x285c44) = 0x00205ca3   descriptor handler, Thumb entry 0x00205ca2
    +0x48 (0x285c54) = 0x00000000   primary descriptor slot, null while idle

The handlers live at `0x0020xxxx`, a code bank above the `0x1000..0x9f000` ROM
dump. That bank is `fc61`-readable: `--read-range 0x205c00 128` returned it.

### The descriptor handler at 0x205ca2 (read from hardware, disassembled offline)

`0x00205ca2` is the USB descriptor / device-state message handler reached through
vector slot `+0x38`. It:

- reads a 16-bit message code from the control block (`[sp,#0x24]`) and dispatches
  sub-messages in the `0x2xx` namespace (e.g. `0x276`, `0x5a`, `0x209`+offsets);
- indexes the **same device-context array as the ROM code**: `ldr r1,[0x285254];
  ldr r1,[r1]; r2 = r1 + devindex*0x440` (the `0x205c3e` sibling shows it plainly),
  confirming the `0x20xxxx` bank and the low ROM are one firmware image sharing
  one USB context;
- reads its descriptor state from a set of `0x28xxxx` RAM structures, resolved
  from its literal pool: `0x00288950`, `0x0028598c`, `0x00285da4`, `0x00281aac`.

So the descriptor bytes are assembled at run time by this handler from those RAM
structures, keyed by the per-device context. There is no static descriptor blob
to patch. The practical, reversible way to change what the dongle enumerates as
is to change those RAM structures (RAM word write/readback/restore at
`0x00210000` already works) or the state the handler reads, then re-enumerate on
the Mac and read the descriptors back. `0x00288950` is the largest of the
referenced structures and is the next read: it is the descriptor/config store the
handler indexes.

This answers the standing question: the EP0 GET_DESCRIPTOR path is
ROM `0x3c14c` -> message id -> vector `0x285c0c+0x38` -> handler `0x205ca2` ->
RAM structures `0x288950` / `0x28598c` / `0x285da4` / `0x281aac`.

### The descriptor store is a handler table, not bytes (end of the offline/read trail)

Read `0x00288900..0x00288c00`. `0x00288950` holds `0x00203f45` (Thumb entry
`0x203f44`), and the whole window is a table of `0x0020xxxx` code pointers. So
`0x288950` is another dispatch table of per-message handlers, not a descriptor
byte buffer. Chasing it leads to one more layer of the same message framework.

Conclusion, with the mechanism now mapped end to end: this is Realtek's layered
USB-device message stack. The device and configuration descriptors have no static
blob anywhere readable; they are serialized field by field at enumeration by a
chain of small handlers (ROM `0x3c14c` -> vector `0x285c0c+0x38` -> `0x205ca2` ->
handler table `0x288950` -> ...), driven by per-device RAM state. That is the
full answer to where the descriptors come from.

For the audio goal this fixes the approach: do not look for a descriptor table to
edit. To change what the dongle enumerates as (toward a UAC1 48 kHz stereo
streaming endpoint), change the RAM state these handlers read, or install a
handler, using the reversible word write at `0x00210000` that already works, and
confirm by re-enumerating on the Mac and reading the descriptors back with
`descriptor_capture.py`. Identifying the specific RAM state bytes that set the
interface/endpoint shape is the next concrete sub-task, approached by writing a
candidate word and observing the re-enumerated descriptor, not by more reading.

### Write channel into the descriptor-handler RAM confirmed, 2026-10-17

The device-context array pointer `*0x00285254 = 0x002103a8`, so device-0 context
is `0x002103a8` (stride `0x440`), inside the known-writable `0x210000` RAM window.
The handler at `0x205ca2` reads its descriptor state from this context.

Ran the reversible write primitive (`--write-test`: read / flip all bits / verify
/ restore), fc62, on the live dongle:

    0x00210000   read 00000000 -> wrote ffffffff -> read back ffffffff (WRITE WORKS) -> restored 00000000 ok
    0x002103d8   (device-0 context +0x30, a zero scratch word) -> same: WRITE WORKS, restored ok

So the write channel reaches the live USB device-context RAM the descriptor
handler uses, and the flips restored cleanly with the dongle still responding.
This is the mechanism needed to change what the dongle enumerates as.

What remains for an actual descriptor change is not a reading problem: the
descriptor shape (interface/endpoint layout, iso packet sizes) is computed by the
handler chain, so the specific context/state byte that moves it must be found by
writing a candidate and observing the re-enumerated descriptor. Observing the
change requires the host to re-enumerate, i.e. a physical unplug/replug, then
`descriptor_capture.py`. That persistent write + replug is the next step and is
done at the keyboard, since a wrong persistent value can wedge enumeration until
replug. The reversible write-test above leaves nothing changed.

### RAM writes do not survive a replug, 2026-10-17 (decisive for method)

Persistence probe: poked 0xdeadbeef into context scratch word 0x002103d8 with
`--poke` (left in place), the user unplugged and replugged the dongle, then
`--read-range 0x2103d8 1` returned 00000000. A replug power-cycles the controller
and clears RAM.

Consequences, and they reshape the project:

- The "write RAM, replug to re-enumerate" loop cannot work: the replug erases the
  write before enumeration. To observe a RAM poke's effect, re-enumeration must
  happen WITHOUT power loss (a logical USB bus reset, libusb_reset_device, which
  keeps firmware RAM) -- a bench-only technique.
- More importantly for the actual goal: the car power-cycles the dongle on every
  start. So a RAM change, and equally a host-downloaded fc20 patch (a car will
  never send Realtek vendor patches), cannot change what the dongle presents to
  the car. Both are bench instruments only.
- A change that works in the car must survive power-cycle and be loaded by the
  dongle itself at boot: it has to live in flash. The flash-write path is the
  real blocker (see "Persistence lead") and is now the critical sub-task.

Bench reverse-engineering can still use a logical-reset loop to learn how the
0x205ca2 handler builds descriptors from RAM, but that knowledge only reaches the
car once it can be written to flash.

### Flash layout and write path located in ROM, 2026-10-17

The mask ROM (`0x1000..0x9f000`) contains a complete SPI NOR flash driver, with
symbol strings: `flash_nor_get_erase_range`, `flash_nor_read_locked_rom`,
`flash_nor_write_locked_slice_rom`, `flash_nor_erase_locked_rom`,
`flash_nor_auto_dma_{read,write}_locked_rom`, `flash_task_init_rom`.

**The flash chip (read from the live geometry table at `0x00280734`).** JEDEC ID
`EF 40 15` = Winbond W25Q16, **2 MB (16 Mbit)**. The command set is stored inline
in that table: read `0x03`, page-program `0x02`, 4 KB erase `0x20`, 64 KB erase
`0xd8`, WREN `0x06`, RDSR `0x05`, WRSR `0x01`, RDID `0x9f`. Chip params are at
`0x00280374`; `0x00280390` holds `0x1000` (4 KB sector).

**The flash is memory-mapped at `0x00200000`.** A read of `0x200000` returns Thumb
code (`10 b5 ...`) followed by the string ">>> Platform Ext", i.e. the flash holds
the resident firmware image, mapped for reads at `0x200000` (2 MB window
`0x200000..0x400000`). This is the firmware that runs in the car: it boots from
flash with no host download. The USB descriptor handler at `0x205ca2` is therefore
flash offset `0x5ca2`.

**Write command (`flash_nor_write_locked_slice_rom` @ `0x0000cc34`).** It issues
WREN then Page-Program (`0x02`) in 256-byte pages (it masks addresses to 0x100
boundaries), choosing 3- or 4-byte addressing at the 16 MB threshold. It submits
SPIC command nodes through RAM function pointers `*0x00281114` (build/submit),
`*0x0028033c` (execute), `*0x00281118` (cleanup). Erase
(`flash_nor_erase_locked_rom`) uses the 4 KB (`0x20`) / 64 KB (`0xd8`) opcodes;
`flash_nor_get_erase_range` @ `0x0000b728` aligns to those sector sizes.
`flash_nor_read_locked_rom` @ `0x0000cbb4` is the read counterpart.

**What this means for the car goal.** The car-facing behaviour lives in this 2 MB
flash, not in RAM and not in a host-downloaded patch. A persistent, car-working
change = erase the affected 4 KB sector and Page-Program the modified bytes, e.g.
to alter the descriptor handler at flash `0x5ca2` or the config it reads. The ROM
exposes the full erase/program path; the flash is mapped at `0x200000` and is
2 MB. The one remaining unknown is the trigger from the host: the ROM flash
functions are called internally and the datasheet documents UART pins for flash
programming, so whether USB/HCI exposes a flash-write opcode (vs needing the UART
pins or an in-firmware hook) is the next thing to settle. Read-mapping and the
write routine itself are now known.

### Host trigger for flash: HCI vendor commands fc29/fc2a/fc2b, 2026-10-17

The HCI vendor-command dispatcher at `0x00013ec0` routes opcodes to the flash
task by posting a message on the queue at `*0x002810bc` (sent via the function
pointer loaded there). The flash commands and their argument layout in the HCI
command buffer (`r3` = params, little-endian):

- **0xfc29 -> message 0x2007 = flash READ.** `addr = [params+3]` (u32),
  `len = [params+7]` (u32). No data payload. Read-only.
- **0xfc2a -> message 0x2008 = flash WRITE.** `addr = [params+3]`,
  `len = [params+7]`, then a data block (params advanced by 0xb). Destructive.
- **0xfc2b -> message 0x2009 = flash ERASE.** `addr = [params+3]`,
  `count/type = [params+7]` (u8). Destructive.
- **0xfc2c -> a multi-field flash op** ([params+3] u16, [params+5] u16,
  [params+7] u32, [params+0xb] u32, [params+0xf] u32); likely auto-DMA transfer.

So flash read/write/erase are reachable from the Mac over USB/HCI, not only over
the datasheet's UART pins. This closes the path end to end:

    host fc2a/fc2b -> flash task -> flash_nor_write/erase_locked_rom -> SPIC -> W25Q16

**Backup first, and the brick risk.** The 2 MB flash is already readable with the
existing `fc61` path because it is mapped at `0x200000`, so a full backup is
`0x200000..0x400000` with `--read-range` / the capture tooling before any write.
A wrong `fc2a`/`fc2b` to the boot image bricks the dongle permanently; unlike a
RAM poke, a replug does not recover it. No write or erase should be issued without
a verified full-flash backup and a specific, confirmed target offset. `fc29`
(read) is safe to exercise; `fc2a`/`fc2b` are not, pending that preparation.

### Flash backup captured (mapped region), 2026-10-17

Backed up the flash via fc61 reads of the memory-mapped window. fc61 returns one
32-bit word per command (its 0x20 byte is a width qualifier, not a length). The
mapped window is readable for **0x200000..0x225000 (148 KiB)**; at 0x225000 fc61
faults and the controller drops off USB and re-enumerates (same class of hazard
as 0x000a0000 / 0x0880a0a8). So the full 2 MB chip is not reachable by fc61;
only the mapped active-firmware window is.

Backup file (gitignored, under results/flash-backup/): `flash-20261017T023847Z.bin`

    range   0x00200000..0x00225000  (151552 bytes)
    sha256  fa7211bea66a3caf5e80974dca77f956659a346741bf292d4e753132eee0fd54
    content 99.1% non-0xff (real firmware), contains ">>> Platform Ext"
    verified: bytes at 0x205ca2 match the live descriptor handler exactly

This window contains the descriptor handler (offset 0x5ca2) and essentially all
the active firmware code, so it is a valid restore image for an edit in this
range: the 4 KiB sector of the handler (offset 0x5000..0x6000) is fully backed
up. A full-chip image would need the flash-controller read path (vendor fc29),
whose bulk-data return format is not yet resolved: fc29's Command Complete is a
fixed status (identical across offsets) and no data event followed, so the read
mechanism differs from the simple addr+len guess and needs more work.

Net: the safety net for modifying the handler (erase sector 0x205000, reprogram)
exists, since that sector's original bytes are in this backup.

### Feasibility conclusion: no UAC1/iAP path exists in the stock flash, 2026-10-17

Searched the backed-up flash firmware (`0x200000..0x225000`, 99% of the active
image) for any USB-audio machinery. Results:

- No stored descriptors (the config header `09 02 c8 00`, the class triple
  `e0 01 01`, the ascending iso-size table, and the VID/PID pair are all absent;
  descriptors are built dynamically, as already established).
- **Zero audio-class interface descriptors** (`bInterfaceClass 0x01`) anywhere.
- No `UAC`, `audio`, `isoc`, `iAP`, `usb_desc` or similar strings.

So the stock firmware is only a Bluetooth HCI controller. There is no UAC1
isochronous-audio or iPod/iAP subsystem to enable, and no descriptor table to
edit toward one. Consequences:

- The flash **write mechanism is fully characterized and usable** (W25Q16 at
  `0x200000`; ROM driver `flash_nor_write/erase` @ `0xcc34`/erase; host triggers
  `fc2a`/`fc2b`; the handler's 4 KB sector is backed up). That part of the goal
  is done.
- But making the dongle **present as a UAC1/iPod device cannot be done by editing
  or patching this image**. It would require writing a complete custom firmware
  that implements the USB-audio device class (isochronous streaming), the iAP
  side, and the Bluetooth A2DP sink that feeds them, then flashing it. That is a
  ground-up firmware project, needs an RTL8761CU build toolchain (the Realtek SDK
  is behind a RealMCU login), and every flash write carries permanent-brick risk
  with no replug recovery.

This is the real blocker, now precisely located: not an unknown write path (that
is solved), but the absence of any audio capability in the stock firmware. The
project's next phase is firmware development with a proper toolchain, not a flash
edit of the stock image. No flash write should be attempted against the stock
firmware toward this goal; it cannot succeed and can only brick the device.

### CORRECTION, 2026-10-17: retracting two premature claims

Two earlier claims in this file were wrong and are retracted:

1. **"fc2a = flash write, fc2b = flash erase" is NOT established.** Testing fc29
   directly (--flash-read) shows it returns the SAME bytes for offset 0x0,
   0x1000, and 0x100000: `1f <len> 00 00 00` then a fixed `38 22 31 00 00 01 01
   08 ...` block. fc29 ignores the address argument and reads a fixed
   config/efuse structure, not addressable flash. So the fc29/fc2a/fc2b family
   (messages 0x2007/0x2008/0x2009) operates on a config store, and the earlier
   "host flash read/write/erase over USB" mapping was an unverified inference,
   now falsified. There is currently NO confirmed host command that invokes the
   ROM flash_nor_write/erase routines.

2. **"The mapped flash is only 0x200000..0x225000 (148 KiB)" is wrong.** Isolated
   reads succeed at 0x300000 (`1f 0f 0a 02`) and 0x3ffffc (`00 00 00 00`), so the
   flash window spans much further; 0x225000 is a fault hole, not the end. The
   follow-on "no audio capability" conclusion rested on only that first 148 KiB
   and is therefore unproven. It is retracted until a complete image is read.

What IS verified:
- The ROM contains a real SPI NOR flash driver (flash_nor_read/write/erase,
  W25Q16, 4K/64K sectors, geometry table at 0x280734) -- the firmware can write
  its own flash internally.
- fc61 reads memory-mapped flash but faults on holes (0x225000) and is flaky
  under sustained hammering; it is not a reliable whole-chip imager.
- The descriptor handler at 0x205ca2 and the EP0 path are real (independently
  read and disassembled).

Open, not yet solved: (a) a reliable full 2 MB flash image, (b) whether any host
path (USB/HCI) can trigger a flash write, or whether that needs the UART pins,
(c) therefore whether the audio-capability question can even be answered from the
host. These were overclaimed before; this is the accurate state.

### Command discovery: can the host write permanent memory? 2026-10-17

Did proper vendor-command discovery, cross-referenced with Dark Mentor's RTL8761B
toolkit, instead of guessing.

**Host vendor commands that exist:**
- `fc20` Download Patch, `fc61` Read Memory, `fc62` Write Memory. These are the
  only write/download primitives Dark Mentor's toolkit uses, and their code
  states the patches are RAM-only and must be re-downloaded every power cycle.
  We independently proved `fc62` writes do not survive a replug.
- `fc29`/`fc2a`/`fc2b` (config read/write/erase) and `fc2c`, `fc6b`, `fc6d`,
  `fc7e` in the CU dispatcher. `fc29` returns a FIXED config/efuse block (ignores
  the address argument), so these act on a config store, not arbitrary flash.

**The flash driver is present but indirect.** A flash-API vtable sits at
`0x00020180`: `flash_read` (0xcbb4) at +0x0c, `flash_write` (0xcc34) at +0x10,
then erase/DMA entries. It is invoked only through a RAM-resident struct pointer
installed at boot, so no fixed-ROM path statically connects a host command to
`flash_write`. Static analysis therefore can neither prove nor disprove a
host->flash route; the indirection hides it.

**Conclusion on permanent writes from the host (USB):**
- Confirmed persistent write: none demonstrated. `fc62` (RAM) is wiped by a
  power cycle; the most thorough public RE (Dark Mentor) also found no persistent
  host write and relies on the host re-loading firmware/config each boot.
- The only candidate is the config path (`fc2a` write / `fc2b` erase). Whether it
  persists is untested, and probing it blindly is risky: if the store is efuse it
  may be write-once/irreversible (brick-class); if it is flash-backed config it
  would be reversible with the backup. The config field map (e.g. whether USB
  identity is settable) is Realtek-internal and not public.

So: a safe, confirmed way to persistently rewrite this dongle from the host does
not currently exist. Persistence in practice needs either a host present at every
boot (not viable in the car) or factory/UART programming (physical pins). The one
untested lever (config write) must not be exercised blindly due to possible
one-time-programmable efuse.

### Chip audio capability (from ROM strings)

The ROM does contain Bluetooth audio machinery: `audio_sniff_*` and
`lc_*esco*` (classic SCO/eSCO voice links) and `ll_iso_*` / `bz_isoch_*`
(LE Audio isochronous streams / Auracast). So the chip genuinely handles
Bluetooth audio links at the controller level, consistent with Realtek's codec-
offload / Auracast claims. What is absent is an A2DP/LE-Audio SINK profile that
decodes to PCM and a USB-Audio-Class presentation to a host; those are the parts
a car-side bridge still needs and that no public firmware provides for this chip.

### B1 result: custom-patch delivery works; patch is NOT entered at offset 0, 2026-10-17

Built `--load-custom`: it takes the stock 248-byte ARM patch, hooks the entry
(offset 0) to appended Thumb that writes 0xDEADBEEF to 0x00211F00, and downloads
the modified patch over fc20. Hardware results:

- **Delivery works.** The modified patch downloads and launches with no brick;
  the running version changes to 0x7bf15762 exactly as the stock patch does. So
  we can deliver arbitrary modified patch bytes to the controller.
- **The entry hook did NOT execute.** The marker never appeared at 0x00211F00,
  and fc62 confirms 0x00211F00 is good writable RAM (write/readback/restore ok),
  so the address is fine; the write simply never happened.
- **The version is not an execution signal.** Replacing the entry with `bx lr`
  (patch should do nothing) still changed the version to 0x7bf15762, so the ROM
  updates the reported version during the download itself, independent of running
  the patch body from offset 0.

Conclusion: the RTL8761CU ROM does not invoke the downloaded patch as straight-
line code from offset 0. The patch is applied by a ROM mechanism (likely a
patch-apply routine that registers/▸calls specific entry points, or processes the
patch structure), so a hook must go where control actually flows, not at offset 0.

Next step (matches Dark Mentor's method for the B chip): trace the CU ROM's fc20
download-complete / patch-apply handler in the ROM dump to find (a) where the
patch is loaded in RAM and (b) the point where the ROM transfers control into it.
Hook there. The delivery path and the custom-patch builder are already in place;
only the correct hook location is missing.

### B1 final: entry-offset-0 code does not execute; need the patch-apply entry

Repeated the marker test with the stub placed IN PLACE at offset 0xA0 (inside the
248 bytes the controller loads, so no appended-region doubt). Result unchanged:
the marker never appears at 0x00211F00, during download, after enumeration, or
after subsequent reads, while the device stays patched (version 0x7bf15762).

So, definitively: the RTL8761CU ROM does not execute the downloaded patch as code
from offset 0. Hooking the entry does not run our code. The patch is almost
certainly applied as an on-demand hook (its code replaces/extends a specific ROM
function and runs only when that function is invoked during BT operation), or via
a patch-apply routine that enters at a computed point, not offset 0.

Where B1 stands:
- Delivering a modified patch over fc20 works and is safe (no brick). (DONE)
- Running our own code requires identifying the ROM's patch-apply mechanism:
  which ROM function the patch hooks (so it can be triggered) or the exact entry
  the ROM transfers control to. That is offline ROM reverse-engineering on the
  existing dump (no dongle needed), guided by Dark Mentor's B-chip write-up of
  the same mechanism. Until then, injected code cannot be shown to run.

This is the open sub-problem for the dongle-native track. The shippable Track A
(Raspberry Pi iPod-gadget + Bluetooth sink) does not depend on it.

### B1 drilldown: the patch is not in fc61-readable RAM, 2026-10-17

Guided by Dark Mentor's writer, which hooks a function epilog DEEP inside a large
patch loaded at a known base (0x8010a000 on the B chip), not offset 0:

- The CU patch is only 252 bytes yet its code makes PC-relative calls to base+0x220,
  +0x22a, ... (nine stubs 0xA apart) which lie BEYOND its own 252 bytes. So it is
  meant to load at a fixed base where that surrounding code is resident, not as a
  standalone blob at an arbitrary address.
- With a custom patch resident (version 0x7bf15762), scanning every fc61-readable
  bank (0x210000-0x21ffff, 0x280000-0x288fff, etc.) for the marker 0xDEADBEEF, the
  entry hook bytes, and the stock prologue 70 b5 4c 1f found NONE of them.

So the ROM loads the downloaded patch into a dedicated patch-RAM that fc61 cannot
read (analogous to the B chip's separate patch region) and/or transforms it on
apply. That is why hooking offset 0 does nothing and why the raw bytes are not
visible. Two consequences: (1) finding the real entry requires reversing the ROM's
fc20 download/apply handler to learn the patch-RAM base and the control-transfer
point; (2) even then, verifying via memory reads may be limited because the patch-
RAM is not fc61-readable. This is a multi-step ROM-RE effort with a real risk that
the patch-RAM is not observable with the current read primitive.

### B1 wall: the patch-apply code and patch-RAM are not fc61-readable, 2026-10-17

The ROM references 216+ distinct pointers into 0x00100000..0x00200000 (code it
calls), and the 252-byte patch's own calls to base+0x220.. land there. But fc61
cannot read that region: reads at 0x100000, 0x10f800, 0x140000, 0x17f360,
0x1f0000, 0x1ff000 all fault. fc61 only reaches 0x1000..0x9f000 (ROM) and the
0x21xxxx / 0x28xxxx RAM; 0x0 reads zero; 0xa0000 and 0x0880a0a8 hang.

So both things needed to make injected code run are outside the one working read
primitive:
- the ROM's fc20 download/apply handler and the surrounding firmware live in the
  unreadable 0x100000..0x200000 code bank, so the apply mechanism and the real
  patch entry cannot be traced from the readable dump; and
- the applied patch is not present in any fc61-readable RAM, so even a correct
  hook cannot be verified by reading it back.

Net for the dongle-native track: delivery of a modified patch works and is safe,
but running our own code is blocked by the read primitive. Progress requires
either a new read path that reaches 0x100000..0x200000 and the patch-RAM (itself
an open RE problem on this chip), or a different approach. The sibling-chip (B)
work succeeded partly because its patch-RAM (0x80xxxxxx) was readable; the CU's
equivalent regions are not, with the tools found so far. The shippable Track A
(Raspberry Pi iPod-gadget + Bluetooth A2DP sink) does not depend on any of this.

### Read-primitive hunt exhausted over USB, 2026-10-17

Tried to find any way to read 0x100000..0x200000 (where the patch-apply code and
the patch-RAM live) over USB:

- fc61 at 0x100000 does not soft-reject; it hangs the controller (USB timeout,
  needs replug), like 0xa0000 / 0x0880a0a8. So that region is outside fc61's
  read path entirely, not just bounds-checked. Access-byte variants are moot once
  it hangs.
- fc2c, disassembled, reads 5 fields and posts to the SAME config/flash task
  queue as fc29/fc2a/fc2b (0x2007-0x200a) -- it is a config/flash op on the fixed
  store, not a general memory reader.
- fc6b / fc6d / fc7e are info/misc, not memory readers.

So no vendor command available over USB can read the 0x100000..0x200000 code bank
or the patch-RAM. fc61 (the only general reader) hangs there. The region is
likely execute-only or on a bus the fc61 reader cannot touch. Reading it by
executing code there is circular (running code needs the apply mechanism we can't
read).

Conclusion for the dongle over USB: blocked. We can deliver a modified patch
safely, but we cannot read the apply mechanism, cannot verify injected code, and
have no read path to the regions that matter. The remaining dongle route is the
hardware UART programming pins (Realtek's intended flash interface), which can
reach what USB cannot but requires opening the dongle and wiring to those pins.
Track A (Pi iPod-gadget + Bluetooth sink) needs none of this.

### Flash firmware uses a DesignWare USB OTG device stack, 2026-10-17

Strings in the flash image name the USB core: `dwc_otg_pcd` (0x2c04d8) plus
`USB_OTG_T` / `USB_OTG_D` (0x3119f4 / 0x311ca4). So the controller's USB side is a
Synopsys DesignWare USB OTG core driven by a Peripheral Controller Driver (PCD) —
the same family as Linux's dwc2. The PCD is what presents the USB device to a
host; the descriptor handler at 0x205ca2 feeds it. This is the subsystem that
determines what the dongle enumerates as, and it is a documented core, so its
endpoint/descriptor registration follows a known pattern. Noted as a lead for
reading how the device identity is configured once the full flash is dumped.
