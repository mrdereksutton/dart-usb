# RTL8761C native audio queue — October 19, 2026

`rtl8761c_audio_port.c` connects the portable audio bridge to the endpoint
operations reconstructed from this BT600's saved firmware. The compiled ARM
adapter runs alongside captured ARM driver routines in Unicorn. This checkpoint
uses local files and simulated memory; USB access remains paused.

The captured enable routine accepts the 192-byte ISO IN descriptor and updates
both the endpoint and controller's software endpoint state. The captured queue
wrapper and ISO software queue accept the adapter's request and stereo PCM.
Controller register programming, physical DMA and interrupt timing still need
device integration.

## Captured ABI

The implementation pins the CU profile below. A different endpoint, vtable or
operation address is rejected on the 32-bit target. The related 87x3E SDK has a
different request structure; its layout is unsuitable for this captured CU code.

| Object or operation | Captured address / layout |
| --- | --- |
| Endpoint `ep3in` | `0x0030cc08` |
| Endpoint operations | `0x0030cf58` |
| Enable | Thumb entry `0x020bd30d` |
| Disable | Thumb entry `0x020bd3b3` |
| Queue | Thumb entry `0x0020c7b1` |
| Dequeue | Thumb entry `0x020bd493` |
| Request | 44 bytes; buffer +0, length +4, DMA address +8, callback +0x0c, context +0x10, links +0x14/+0x18, status +0x1c, actual +0x20, flags +0x28 |
| Completion signature | `(endpoint *, request *)` |
| Queue wrapper's ISO arguments | `(pcd, endpoint, buffer, dma, length, zero, request, 1)` |

ARM static assertions check structure offsets. The replay also measures the
compiled sizes: 44 bytes per request, 244 per packet slot and **552 bytes for the
adapter**, including two 192-byte buffers. The portable bridge adds 4,168 bytes.
Stack, placement, alignment and any cache-line padding remain the native port's
responsibility.

## Ownership and lifecycle

Initialize fresh or fully stopped storage with an idle endpoint and an explicit
DMA mapping callback. Initialization calls no driver operation. Start rechecks
endpoint ownership and the pinned operation table, installs the descriptor, and
calls native enable. A partial enable failure requires explicit stop cleanup.

Call service once per full-speed millisecond from a serialized native service
context. It maps an available buffer before consuming PCM and submits the actual
bridge packet through native queue. If both buffers are in flight, it returns
zero without consuming audio or changing those buffers. Queue rejection retains
the prepared packet and faults the stream; transfer errors also halt submissions.

Call stop before reset, rate, alternate or configuration changes. Stop requests
cancellation once for each in-flight request, disables the endpoint, and waits
for all completion callbacks. Keep the port and its buffers alive until stop
returns zero. Only then are the original endpoint descriptor and capacity
restored. Calls, the PCM producer and completion callbacks require the native
interrupt/critical-section policy; the adapter supplies no scheduler or locking.

The DMA callback must supply a controller-visible, aligned address and arrange
the device's required cache maintenance. The test fixture explicitly maps virtual
CPU addresses to virtual DMA addresses. That fixture mapping is for emulation.

## Offline replay and results

The saved run is `results/native-audio-validation-20261019-final/`:

| Replay | Result |
| --- | --- |
| Captured enable + full ISO software enqueue | Endpoint and controller software state both select 192 bytes; request becomes pending (`-115`); queued PCM matches every sample. |
| 44.1 kHz through captured queue wrapper | 1,000 submissions/completions; 44,100 stereo frames; 900 packets of 176 bytes and 100 of 180 bytes. |
| 48 kHz through captured queue wrapper | 1,000 submissions/completions; 48,000 stereo frames; 1,000 packets of 192 bytes. |
| Adapter failure/lifecycle tests | 12 tests pass, including full native software ring, busy buffers, rejected DMA, transfer failure, late cancellation, failed enable, changed vtable, ownership and packet capacity. |
| Complete offline suite | 154 tests pass, zero skips, with a Python audit hook rejecting any libusb load. |

`native-audio-validation.json` records the source/object/capture hashes, measured
ABI sizes, exact queue arguments, packet counts and PCM hashes. The PCM files
contain stereo signed 16-bit little-endian ramps used for exact comparisons.
The six ARM objects include the test fixture. Their linked 12 KiB virtual image
includes fixture state and page padding; it is not a device installation image.

The emulator validates both capture hashes before execution. It maps controller
registers into virtual memory, clears the software queue, disables descriptor-DMA
allocation and dynamic FIFO resizing, and intercepts OS helpers plus activation
and transfer register programming. The first enqueue executes the native ISO
software queue. The longer stream runs intercept that lower queue boundary and
simulate completions after the real wrapper submits each request. Cancellation
and disable results in lifecycle tests are simulated too. Unexpected controller
register accesses fail the replay. There is no host USB API in this toolchain.

To reproduce with clang and Python, install the optional emulator into an ignored
local environment:

```sh
python3 -m venv results/offline-arm-venv
results/offline-arm-venv/bin/python -m pip install -r requirements-offline-arm.txt
DART_REQUIRE_NATIVE_REPLAY=1 results/offline-arm-venv/bin/python -m unittest -v test_rtl8761c_audio_port
results/offline-arm-venv/bin/python validate_native_audio.py --output results/native-audio-replay-new
```

Use a new output directory. The validator refuses to overwrite one. Some command
sandboxes block Unicorn's JIT; the saved replay ran outside that command sandbox.
It still executed only simulated ARM memory and opened no USB device.

The private capture inputs remain local and are omitted from the source bundle:

- RAM CPU view: `results/flash-backup/flash-20261017T023847Z.bin`, SHA-256
  `5b701222ea076e324a039b25ff79ada4fb843a0e50a444f9ff44f080f9b9c3df`.
- Flash CPU view: `results/bt600-targets-20261017T101939.145845Z.bin`, SHA-256
  `6ceb104173c7d474b42d62d501087e7933131c43deef03c706022f12a8c633c7`.

Use `validate_native_audio.py --ram PATH --flash PATH` when replaying a source
bundle stored elsewhere. The limited ELF relocator links the project's own
clang objects into Unicorn memory; it never uploads code.

## Next integration gate

The EP0/configuration/alternate/reset connection is now implemented in
`rtl8761c_control_port.c` and covered by combined native replay. Read
[CONTROL_PORT.md](CONTROL_PORT.md) for the current result and task entry.

Next: assign resident RAM, connect the millisecond task to the native scheduler,
establish device DMA/cache handling and add interrupt IN `0x81` delivery for iAP.
These precede a bounded hardware enumeration/audio experiment.

Bluetooth A2DP/SBC reception, AVRCP metadata, the full iAP session and persistent
startup follow that controller integration. The current USB pause files stay
active throughout this offline work.
