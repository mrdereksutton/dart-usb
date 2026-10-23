# Receiver port checkpoint — 2026-10-22

The complete local suite passes 232 tests with zero failures/errors/skips and
libusb loads forbidden. The native host compiles with warnings as errors. The
temporary-protection revision below has now passed the physical fixed-padding
program/readback/erase/restore test. After physical power removal, stock startup,
protection and both complete application copies match the originals.

The official SDK contains executable AVDTP/A2DP objects, not only declarations.
Pinned references and SHA-256 records are in `results/receiver-references-20261020/`.
No reference Bluetooth code has been loaded on the BT600.

## Candidate stack

The 4M upper-stack image overlaps the current OTA header and must not be installed
at its linked address. The **2M image fits** at CPU `0x02015000..0x02045b57`,
with 1,192 bytes before the existing OTA header at `0x02046000`. The saved CU CPU
view is all FF across that candidate window. Two complete physical SPI reads of
0x02015000..0x02045fff now match it: 200,704 bytes each, entirely FF, SHA-256
`eaac8f7843b93aeb514f3c83f9da3a7f5cdb98242c6bf52608bbef18b8071930`.
All 784 transfers completed with zero errors and full restoration. Reports:
`results/receiver-references-20261020/native-receiver-window.*`.

The candidate's chip ID is 0x0b, ROM UUID exactly matches the CU application and
stack patch, and CRC16/SHA-256/RSA-PSS all verify under the same public key.
The re-signed 2M image uses a 222-byte PSS salt; current CU images use 32 bytes.
The parser now checks both using the PSS padding itself. The SDK package adds a
512-byte wrapper before the standard 1024-byte image header.

Actual ARM replay of entry `0x02015401` returned 1, copied 404 data bytes from
`0x020459c4` into `0x00287400`, and cleared 2,844 BSS bytes at `0x00287594`.
Every write stayed within `0x00287400..0x002880af`. Two live read-only copies
of that RAM range match (SHA-256 `79cb852b46d8dd040d91b7561361baf11d3e43384584a56e70541d21610f7991`),
and its receiver callback slots are uninitialized. The current system patch already
references the same variables and candidate function addresses. The mapped active
heaps and current patch/application startup data are outside that range. A live
initializer trial must save and restore the original RAM in the same call.
A linear instruction scan found no optional DSP instructions in this stack image;
it includes literal pools and is a supporting check. The native USB build remains
explicitly no-DSP/no-unaligned.

Reproduce: `python3 analyze_receiver_image.py PATH-TO-SDK-2M.bin --output REPORT.json`
and `python3 -m unittest -v test_receiver_image` with Unicorn available.

The 2M linker definitions identify `bte_init=0x0201549d`,
`hci_if_open=0x020185d1`, `btif_send_cmd=0x0202e625`,
`gap_start_bt_stack=0x02037125`, and `mpa_reg_l2c_proto=0x02038a87`.
These addresses refer to the candidate image, which is absent from current flash.
The official framework archive contains `avdtp.c.obj` and `bt_a2dp.c.obj`;
extracted copies and disassembly are saved for analysis. AVDTP's required interface
is MPA L2CAP plus memory, queue and timer services. Full bt_a2dp additionally pulls
BT manager/link/power state. Bind a minimal receiver after resolving that state.

## Storage prerequisite being prepared

The current application is CPU `0x02097000..0x020defff`, physical SPI offset
`0x97000`, partition size `0x48000`. Both raw copies have SHA-256
`f0f0c06f2a8342365dbb96542970a87953deaf2e72d339f9c15fb768b85e3673`.
The signed application image ends at `0x020ca854`; its last sector,
`0x020de000..0x020defff`, is outside that image and all FF in both raw copies.

The first bounded physical trial requested one fixed 32-byte pattern in that
padding sector, read the sector, issued a sector erase during cleanup, and read it
again. The native calls returned 0x18, but **no bytes changed**. Callback, EP0,
scratch and heap restoration passed. Two subsequent full physical application
reads again matched the preserved SHA-256 above, with 1,152 completions and zero
errors. Reports: `native-flash-restore.json` and
`native-application-after-restore.json` in the reference directory.

A separate read-only probe returned **SR1=0x34, SR2=0x02, BP level=5**
(`native-flash-status.json`). These protection bits cover the padding target.
The [Winbond W25Q16DV datasheet, section 7.1.11](https://content.arduino.cc/assets/Winbond_w25q16dv.pdf)
maps SEC=0/TB=1/BP=5/CMP=0 to the lower 1 MiB. The native geometry identifies
the Winbond EF/40/15 family. A completion code alone is insufficient as a
readback criterion; the host requires the exact pattern and original full sector.

The updated fixed trial temporarily sets native BP level 0, calls the existing
locked program/erase API, then restores BP level 5 before returning to USB.
The actual ROM setter was executed against a simulated protected SPI chip: it
selected **0x50 volatile-status enable**, changed only SR1 from 0x34 to 0x20 and
back, preserved SR2=0x02, wrote only the fixed 32 bytes and restored the sector.
The target checks the boot flag at 0x2803a1 and the geometry's 0x50 opcode before
changing protection, rejecting the nonvolatile-enable configuration. Program-error
tests also verify restoration of BP=5.

**Physical result:** `results/repo-checkpoint-20261022/native-flash-restore-volatile.json`
reports success. All 32 programmed bytes match the fixed pattern, and all other
sector bytes stayed FF. After erase, every one of the 4,096 bytes matches the
original. SR1=0x34/SR2=0x02 were restored after both operations. Native reads:
24 completions, zero errors. Callback, EP0, selector, scratch and heap restored.
The 1,868-byte executed RAM image has SHA-256
`2960be154aa98b32f9089bfb09cbc4bbc0770e028bb46af6c087b7290df29671`.
Its exact build is preserved in `verified-storage-build/` beside the report.

`native-application-after-volatile.json` records two further complete raw SPI
application copies, both retaining the original partition SHA-256, with 1,152
completions and zero errors. No receiver image or startup hook has been installed.
The subsequent power-cycle check passed, and two complete physical backups of
the receiver storage window are saved. Next is the bounded receiver initializer
trial before any receiver image or startup hook installation.

`--flash-status` only reads status and padding; `--flash-restore-trial` enables the
fixed program/erase sequence and requires its separate local operation scope.
The default `build_resident_flash_read.py` build still contains no write/erase
entry points; `--restore-trial` builds the diagnostic variant into an explicitly
selected output directory. Exact executed images are preserved locally in
`measured-storage-images/`; current pending builds have separate checkpoint paths.

ROM vtable entries: read at `0x2018c -> 0xcbb5`, sliced locked write at
`0x20190 -> 0xcc35`, write wrapper at `0x20194 -> 0xcd35`, locked erase at
`0x20198 -> 0xcd83`. Write-slice arguments are `(CPU address, data, bytes, slice)`;
use a fixed 32-byte slice. Erase arguments are `(CPU address, type)`.
Actual ROM disassembly selects **type 1 = opcode 0x20 (4 KiB sector)**,
type 2 = 0xd8 (64 KiB), and the default path = 0x60 (chip erase). Hard-code type 1
and the exact padding address; never pass an inferred enum value.

Native flash lock callbacks are `0x281114 -> 0xc3df` and
`0x281118 -> 0x202799`; raw SPI TX `0x2802f0 -> 0x202ce3`, RX
`0x2802ec -> 0x202c6f`, write-enable `0x28031c -> 0x4e59`.
Execute the real ROM wrapper in an offline SPI model first and assert its command,
address, length and write set. A RAM resident trial can extend the verified EP0
SPI reader with fixed program/erase triggers, keeping the allocation alive until
all native requests and storage work finish. Restore the padding even on SIGINT.

If a later SDK-code trial stalls the dongle and needs a replug, ask for that exact
physical action asynchronously, then continue decoder/packet and linkage work
while waiting. The owner explicitly requested continued independent progress.
