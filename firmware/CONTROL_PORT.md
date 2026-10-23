# Native enumeration and stream control

`rtl8761c_control_port.c` binds the existing portable USB bridge and audio
adapter to this CU firmware's gadget setup/disconnect callbacks. It supplies a
single millisecond task entry, `dart_rtl_control_tick`, which services controls
even while audio is idle. The integration runs as compiled ARM code alongside
the saved native USB stack in offline replay. It has not been installed on the
dongle; live USB testing remains paused.

## Implemented path

Host SETUP enters the captured EP0 dispatcher, then the captured gadget wrapper
calls the new C setup callback. That callback queues its own 44-byte request
through the captured endpoint and PCD software queues. Replies use a stable
128-byte buffer. Descriptor replies include the 192-byte stereo audio endpoint
and HID interface. Short descriptor reads and required terminating zero-length
packets are handled. SET_ADDRESS remains owned by the lower native PCD path.

SET_CONFIGURATION and SET_INTERFACE connect to the bridge and native audio
adapter. Before changing stream state, the port cancels/drains outstanding audio.
For sample-rate SET_CUR, it receives data into its control buffer, waits for the
old audio to drain, applies the rate and queues status. The combined tick withholds
new-format audio until status completes. HID SET_REPORT validates the frame before
status; invalid or short OUT data stalls without queuing a success status.

The CU's delayed-status return value is **1255**. OUT data must be queued before
returning that value: a later OUT submission while delayed is interpreted by the
captured generic queue as status IN. The tests caught and corrected this ordering.
The task queues status after the completion callback returns, avoiding native
queue mutation while completion cleanup still owns its previous request.

New SETUP packets abort older EP0 requests through native cancellation. Disconnect
and unbind wait for both control and audio callbacks before resetting state or
restoring callback pointers. A descriptor query that replaces a pending idle
change is served normally; the unchanged stream resumes after cancellation drains.
Stopping an idle audio adapter now preserves endpoint state owned by another user.

## Target contract

| Field | Pinned CU value |
| --- | --- |
| Gadget / EP0 | `0x0030cb6c` / `0x0030cbb4` |
| Setup slot / original entry | `0x0030d164` / `0x020be8a1` |
| Disconnect slot / original entry | `0x0030d168` / `0x020be7e3` |
| Native EP0 / setup dispatch | `0x020bb4a0` / `0x020ba71e` |
| Gadget setup / completion dispatch | `0x020bd6e6` / `0x020bd7d8` |
| EP0 packet size | 64 bytes |
| Additional control state and buffer | 244 bytes on ARM32 |

Bind requires the pinned gadget, endpoint operations and original callback slots,
an unconfigured composite, idle EP0 and an initialized audio adapter. It owns
EP0's descriptor and the two callbacks until unbind finishes. One bound instance
is supported. The bridge, audio adapter and control port together occupy 4,964
bytes, excluding stack and code.

The native task must call `dart_rtl_control_tick` once per millisecond, serialize
it with setup/completion/producer events, and keep storage alive until unbind
returns zero. Use this combined entry for audio while bound. The caller supplies
the verified DMA mapping/cache policy through the audio adapter; the replay
fixture supplies virtual identity mapping.

## Reproduce and inspect

Using the optional Unicorn environment described in NATIVE_AUDIO_PORT.md:

```sh
DART_REQUIRE_NATIVE_REPLAY=1 python3 -m unittest -v test_rtl8761c_control_port
python3 validate_native_control.py --output results/native-control-replay-new
```

The saved final run is `results/native-control-validation-20261019-final/`.
Its JSON trace records 15 simulated host transactions, 64 checked packets across
44.1/48 kHz, native address 7, checked iAP OUT reception and restored callbacks.
A separate request after the same enumeration/startup path reaches the full
native ISO software queue with 192 matching bytes. Source/object/capture hashes,
descriptors and exact PCM outputs are saved beside the trace.

Sixteen control integration tests cover enumeration, address ownership, stream
start, delayed rate/idle changes, preemption, valid/malformed HID OUT, short data,
failed enable, reset, unbind and status-before-new-audio ordering. All 171 offline
tests pass with libusb loads rejected. ARM static analysis reports no diagnostics.

The replay executes native PCD setup, generic queue and completion software.
Controller registers and hardware completion events are virtual; allocators, OS
helpers, register programming and disable/dequeue/halt results are modeled.
Descriptor DMA and dynamic FIFO resizing are disabled in the model. Longer audio
runs intercept the ISO transfer boundary, while the separate first enqueue runs
the actual ISO software queue. Original private firmware captures remain local.

## Next device-run work

Assign resident RAM and a target entry, connect the millisecond entry to the
dongle's native scheduler, and establish DMA/cache handling for those buffers.
That enables preparation of a bounded device enumeration/test-tone experiment.
Interrupt IN metadata delivery, Bluetooth reception, the complete iAP session
and persistent startup remain separate work toward the car receiver.
