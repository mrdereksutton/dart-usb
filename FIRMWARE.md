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
