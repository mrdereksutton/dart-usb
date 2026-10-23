# macOS USB crash incident — 2026-10-17

**October 19 update:** the owner explicitly resumed hardware work. The native
IOUSBHost transport and a reversible resident descriptor program have passed on
the physical BT600; see [HARDWARE_RESUME.md](HARDWARE_RESUME.md). Both legacy
`USB_ACCESS_DISABLED` files remain to block the old libusb interface-claim path.
The incident findings below describe the earlier crashes and investigation.

## What the local crash reports say

Three full Mac kernel panics were recorded on October 17, Eastern time:

| Time | Python PID | Parent process chain |
| --- | --- | --- |
| 06:48:19 | 16692 | Python → codex (7881) → ChatGPT (7839) |
| 16:45:32 | 5869 | Python → codex (855) → ChatGPT (479) |
| 16:46:56 | 1611 | Python → codex (871) → ChatGPT (481) |

All three panic in `com.apple.iokit.IOUSBHostFamily` with a kernel data abort
accessing address `0x3`. The kernel extension UUID is the same in all three:
`77B0E357-BD11-3B86-997D-985D392F9CD7`. The fault is at the same offset, `0xa8cc`,
relative to the extension's recorded load address.

The calling thread's saved user frames were symbolicated offline against the
installed `/opt/homebrew/lib/libusb-1.0.dylib`. Its UUID exactly matches the panic
images: `0FD95C30-6469-3C52-83CA-1059F9591751`. All three have the same sequence:

```text
darwin_get_pipe_properties + 112
get_endpoints + 228
darwin_claim_interface + 836
libusb_claim_interface + 172
```

These were USB calls made by Codex-launched Python processes. The parent-process
records identify Codex/ChatGPT, rather than Claude, as the execution source. The
precise interface number is not recorded in the symbolicated frames. An empty
`results/iso-inspect-live.log` was created at 16:46:27, before the final panic.
No successful endpoint-inspection result exists. Do not rerun it on this Mac.

The Mac reports macOS 27.0 build `26A5421a`. Investigate the interface/pipe
descriptor handling offline before considering any hardware retry. The current
evidence locates the triggering API path; the exact driver defect is still open.

## Containment and preserved evidence

- `bt600_vendor_read.py`, `bt600_probe.py`, and `usb_inspect.load_libusb()` in the
  Codex checkout stop before loading libusb when the local pause file exists.
  Capture scripts that use these entry points inherit the block.
- The separate Claude checkout at `/Users/mrdereksutton/dart-usb` has the same
  guard and pause file on its two available library entry points. Its original
  source files were backed up before modification.
- No USB probe was running in the process snapshots during this investigation.
  No device open, USB enumeration through libusb, firmware operation, or hardware
  reproduction was performed to diagnose the crashes.
- Three original panic files were copied byte-for-byte to
  `results/crash-diagnostics-20261017/`. `panic-manifest.json` records original
  paths, sizes and SHA-256 hashes. Backups of the second checkout's edited files
  are in `claude-checkout-backups/` beneath that directory.
- 59 focused offline tests pass, including checks that each guarded entry point
  refuses access before calling `CDLL`, and that offline modes remain available.

Raw crash reports and machine identifiers remain local in the ignored results
directory. No crash data has been published or sent to another chat.
