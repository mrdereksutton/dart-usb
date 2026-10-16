# Contributing to Dart USB

Help move the ASUS USB-BT600 / RTL8761C from observable controller behavior toward a standalone wireless audio and metadata bridge for the Dart's USB/iPod input. Read the README, HARDWARE.md, FIRMWARE.md, USB_BRIDGE.md, and current pull requests before starting.

## Coordinate work

- Use a focused branch and pull request. Read active drafts so experiments and fixes build on current work.
- Sync with `main` before editing. Preserve other contributors' changes, hardware observations, source references, and credit.
- Keep this repository's specific hardware and bridge objective in scope. Explain how a change advances a concrete milestone.
- Contributions assisted by Claude, Codex, or another tool are welcome. The contributor remains responsible for reviewing the code, sources, and claims. Record substantial assistance in the PR or commit when appropriate.
- Use CLAUDE.md as the assistant handoff. Update the handoff when new hardware evidence changes the next task.

## Report a hardware experiment

Include the adapter model and VID/PID, USB revision, ROM/chip revision, OS, exact command, baseline state, relevant responses, and recovery behavior. Distinguish measured bytes, calculations, hypotheses, and behavior that still needs a hardware run. Describe whether the experiment reads, loads a runtime patch, or writes persistent storage.

Keep complete transcripts locally in `results/`. Share a concise relevant excerpt after removing personal paths, device addresses, credentials, and unrelated device information. Do not commit local result folders or unrelated captures.

Memory reads can also stop a controller. Keep experiments bounded, stop after the first rejected/malformed/timed-out response, and document any address that causes a fault. The failed `0x0880a0a8` address is excluded from routine probes. Widen an experiment because evidence supports the next range.

## Submit a change

Describe the concrete problem, resulting behavior, relevant sources, validation performed, actual hardware output collected, and the next unresolved question. For a reproducible code failure, add a focused regression check. Run the checks relevant to the change; documentation-only updates do not need a hardware run. Offline checks do not demonstrate controller execution or car compatibility.

The existing offline checks can be run from the repository root:

```bash
python3 -m unittest -v
python3 bt600_probe.py --inspect-stock
```

Do not silently replace the observed ROM-based image selection, treat RTL8761B code as RTL8761C code, equate the epatch container version with the runtime HCI version, or infer USB descriptor control from a VID/PID pattern alone.

## Sources and licensing

Link primary sources and identify the specific file, revision, offset, or command behind a claim. Retain attribution and licenses. Submit original work under this repository's MIT license, or clearly identify separate third-party terms before adding that material. The MIT license does not apply to the embedded Realtek firmware; see THIRD_PARTY_NOTICES.md and REALTEK_FIRMWARE_LICENSE.txt.
