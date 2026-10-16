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

## First memory experiment: 2026-10-16 05:29 UTC

The user's normal Terminal completed the baseline and issued four `0xfc61` queries:

| Address | HCI return parameters | Result |
| --- | --- | --- |
| `0x00000000` | `00 00 00 00 00` | Success status, four zero bytes |
| `0x00000004` | `00 00 00 00 00` | Success status, four zero bytes |
| `0x00217e88` | `00 b4 88 3b c2` | Success status, data word `0xc23b88b4` in little-endian order |
| `0x0880a0a8` | No completion received | `LIBUSB_ERROR_TIMEOUT (-7)` |

After the last query, restoring the original USB configuration failed, and the next process could no longer enumerate the adapter. The stock-upload stage therefore sent no firmware. Recovery requires unplugging and reconnecting the dongle.

This gives an actual C-chip memory-read response at `0x00217e88`; the zero-filled responses do not provide usable boot-vector anchors. The last literal is no longer used as a read target. The runner now uploads stock firmware before its optional RAM query and stops after any failed phase.

The original local transcript is `results/bt600-20261016T052909.255079Z.txt`; results files are excluded from Git.

## Capability map collected 2026-10-16

| Capability | Opcode | Result |
| --- | --- | --- |
| Local version / ROM version | `0x1001` / `0xfc6d` | Works; ROM version 1 |
| Memory read | `0xfc61` | Works over `0x00001000..0x0009f000` and RAM near `0x0021xxxx`; `0x0` reads zero; `0x000a0000` and `0x0880a0a8` hang the controller |
| Firmware download | `0xfc20` | Accepted; the controller relaunches (running version `0x000e8761` -> `0x7bf15762`); the patch is relocated on load (its prologue is not in any readable region) |
| Memory write | `0xfc62` | **Works.** Read/flip/verify/restore at `0x00210000`: `00 00 00 00` -> wrote `ff ff ff ff`, read back `ff ff ff ff`, restored `00 00 00 00` |

So the controller exposes full RAM read and write plus a launching firmware-download path. The `0b05:1d70` USB identity is not in any readable region (searched in all byte orders), so it is config/efuse the read path cannot reach; but the firmware stages the descriptor in RAM at enumeration, which write access can reach in principle.

## Results still to collect

- Where the firmware stages the USB device descriptor in RAM at enumeration (the write target for changing what the dongle presents as).
- How the controller relocates a downloaded patch, and the real load base.
- Which changes survive USB reconfiguration and complete power loss.
- The car's supported USB/iPod protocol details needed for a working bridge.

## Latest handoff evidence and completed targeted read

The supplied 2026-10-16 Terminal record contains:

| Query | Parameters | Return parameters |
| --- | --- | --- |
| `0x1001` Local Version | none | `00 0e 0e 00 0e 5d 00 61 87` |
| `0xfc6d` ROM Version | none | `00 01` |
| `0xfc61` ASUS READ_SEC_PROJ | `10 a4 ad 00 b0` | `00 00 00` |

ASUS's loader uses the first data byte as key ID: zero here. This does not
measure all boot/signing policy. USB class remained `e0/01/01`; original USB
configuration was zero and the probe restored that unconfigured state.
The original JSON is preserved locally under
`results/handoff-2026-10-16/last_successful_probe.json`.

The prepared `bt600_vendor_read.py --descriptor-targets` run was completed at 23:16 UTC; see the measured result below.
It reads the firmware-derived pointer at `0x002c10b4`, conditionally follows it
for an 18-byte template descriptor, and reads VID/PID settings at `0x002808b8`.
It also captures standard GET_DESCRIPTOR for comparison. No new memory read,
write, upload, or car result is claimed by offline tests.

Evidence limits on earlier wording: not finding a prologue or VID/PID pattern
in sampled memory does not prove relocation, or that identity is exclusively
in efuse/config. The saved stock-upload transcript's obsolete `stock_running:
false`/exit 3 reflects the fixed version-comparison bug; its raw acknowledgments
and changed runtime version remain the observations. The failed
`descriptor-20261016T095759.183191Z` run has no completed descriptor/RAM capture.


### Direct Codex run — 2026-10-16 23:16:55 UTC (7:16 p.m. EDT)

The sandboxed command saw zero devices and sent no HCI queries. Rerunning the
same command through approved `require_escalated` execution succeeded. Normal
Terminal is no longer required for this session's approved hardware access.
No OS setting or driver attachment was changed.

Command: `python3 bt600_vendor_read.py --descriptor-targets`.
Result: `results/bt600-targets-20261016T231655.391813Z.json` (exit 0).
Probe SHA-256: `d6678851838513d2c47c9c9b344ae9ed8d261acae12256c15d760514445b6cc0`.
Identity replies matched the handoff: runtime `0x000e8761`, ROM 1, key ID zero.

| Read | HCI return parameters | Interpretation |
| --- | --- | --- |
| `0x002c10b4` | `00 07 00 00 00` | Word `0x00000007`; invalid candidate pointer, not followed |
| `0x002808b8` | `00 05 0b 70 1d` | Settings word contains VID/PID `0b05:1d70` |

Standard device descriptor from EP0:

```text
12 01 10 01 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01
```

Decoded: USB version `0x0110`, Bluetooth class `e0/01/01`, EP0 packet size 64,
device revision `0x0200`, manufacturer/product string indexes 1/2, no serial
string, one configuration. Original USB configuration zero was restored.
Exactly two memory words were read; no descriptor-pointer target was touched.

The VID/PID settings location matches, while the candidate descriptor template
location does not contain a usable pointer in this runtime. This is a layout
mismatch to investigate, not a failure of RAM access or a verdict on USB
repurposing. No memory write, firmware upload, reset, or car test was performed.
