# Physical BT600 hardware progress — 2026-10-19

The owner explicitly resumed hardware work: “Yes resume, as the entire purpose
is to actually use the hardware,” then “Continue. Lets get this working.” Routine
reversible hardware work is authorized. Flash, efuse and full ASUS upgrades remain
outside the current experiment. Neither legacy pause file was removed.

## What passed on the dongle

`bt600_native_hci.m` uses Apple's IOUSBHost framework to open interface 0 and its
valid interrupt pipe 0x81 directly. It avoids libusb interface claims and their
endpoint-property discovery path. ROM version 1 and the live USB pointers match
the saved captures. It restores the configuration it found, including zero.

The checked pool-5 helper allocated and immediately freed 4096 bytes at
`0x00312280`. Free heap returned to 7648 bytes. Its setup callback, scratch words
and configuration restored. Local report:
`results/native-hci-allocator-20261019-pool5.json`.

A **1032-byte compiled resident program** was then uploaded/read back into a
4096-byte allocation at that address. On the real USB connection it returned:

| Request | Bytes | Result |
| --- | ---: | --- |
| Device descriptor, test index 126 | 18 | Exact portable-core descriptor |
| Configuration header, test index 126 | 9 | Three interfaces, configuration 2 |
| Complete configuration, test index 126 | 128 | UAC1 44.1/48 kHz stereo source plus iAP HID |
| HID report descriptor, test index 126 | 96 | Exact portable-core report layout |

All four native completions succeeded with zero resident errors. The normal stock
descriptor also still worked. Cleanup restored the setup callback and EP0
descriptor, freed the allocation, returned free heap to 7648 bytes, restored every
scratch word and restored configuration zero. The local report is
`results/native-hci-resident-profile-20261019-first.json` (`success: true`), image
SHA-256 `60d17588504faaaf24c4be5f956b557f1de4251e5d79dcff215c7315733eaeb9`.

The dongle currently runs stock again. The trial used explicit descriptor index
126 so the Mac's ordinary enumeration remained stock. No audio was streamed and
no code was made persistent. Those are the next hardware steps, along with the
remaining Bluetooth receiver and full iAP session.

## Corrected allocator and DMA assumptions

The first trial incorrectly chose pool 6 for 16384 bytes. Its stale head points
at occupied memory (`0x00300000`, header `0xdaa04008`); the dongle stopped answering
on the first helper request. The owner unplugged/replugged it and native reads
confirmed recovery. No Mac crash occurred during these native tests. Preserve
`results/native-hci-allocator-20261019-first.json` as the failed trial record.

Use the **active pool 5**, with a fresh walk requiring unallocated block headers
and sufficient contiguous bytes. Do not infer available space from stale alias
pools 0/4/6. The resident probe temporarily selects pool 5 for its native queue's
bookkeeping, then restores the original selector before returning.

Live EP0 has DMA and descriptor-DMA enabled (core word `0x01010020` at
`0x0030b888`). The stock request at `0x002c1354` uses identical CPU and DMA buffer
addresses, `0x0030d1c0`. The resident trial used SRAM in the same address range,
explicit DMA addresses and the existing native EP0 ring. Its successful transfers
validate that bounded EP0 path. ISO audio still needs its own DMA/timing test.

The helpers now run only on the explicit device-descriptor index-1 trigger;
HCI memory reads/write-readbacks pass through to the stock callback. They also
restore the callback themselves before tail-calling the original handler.
Offline checks execute the real saved ROM/flash allocator for retain/free, and
replay resident requests/cancellation in both buffer- and descriptor-DMA modes.
The complete offline suite passes **184 tests**, with zero skips and an audit
hook rejecting any libusb load. Both legacy pause-file hashes remain unchanged,
and the final process check found no running project USB process.

## Reproducing the completed trial

The local authorization record is `results/hardware-resume.json`. The native
tool requires explicit operation scopes. Keep all hardware actions in one
foreground tool process; do not start background USB workers.

```sh
python3 build_resident_profile.py
xcrun clang -fobjc-arc -fblocks -Wall -Wextra -Werror -Wno-nullability-completeness -framework Foundation -framework IOKit -framework IOUSBHost bt600_native_hci.m -o results/native-host-build/bt600-native-hci
results/native-host-build/bt600-native-hci "$PWD" results/NEW-REPORT.json --resident-profile
```

The manifest pins its allocation base. If a fresh free-block check chooses a
different address, rebuild with `--base ADDRESS` before a trial. Reports checkpoint
original values before writes. Never free resident code until its native request
has drained. A lost USB transport can prevent restoration; power cycling clears
these RAM-only changes. Normal successful runs restore everything automatically.

Next: fit the complete control/audio port into the measured heap budget, connect
the native periodic service and validate an actual continuous PCM transfer. Use
[UCONNECT_TARGET.md](UCONNECT_TARGET.md) for the car-facing acceptance target.
