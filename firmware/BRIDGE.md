# Portable USB receiver component — October 19, 2026

The project now has runnable C firmware for the car-facing transport, plus a
host-only executable that enumerates its USB profile, streams stereo audio, and
requests a track title over iAP HID. It builds on the existing PCM packetizer.
The USB pause remains in effect; this work uses no device access.

## Implemented behavior

| Component | Behavior |
| --- | --- |
| USB profile | One development configuration, value 2: Audio Control interface 0, Audio Streaming interface 1 with idle/active alternates, HID interface 2. Existing adapter VID/PID `0b05:1d70` is retained. |
| Audio format | Stereo signed 16-bit little-endian PCM, 44.1 or 48 kHz. Audio IN endpoint `0x83`, maximum 192 bytes, 1 ms interval. |
| Audio buffering | 512 stereo frames. The producer retains input that does not fit. Empty input becomes counted silence. A short output buffer or idle alternate consumes nothing. |
| EP0 | Device/configuration/string/HID descriptors; address/configuration/interface/status requests; endpoint sample-rate SET_CUR and GET_CUR/MIN/MAX/RES; HID SET_REPORT and per-report SET_IDLE/GET_IDLE. Unsupported requests stall. |
| iAP HID | Vendor report profile with device IDs 1–4 and host IDs 5–9. Short and extended frames, payloads up to 1,024 bytes, checksum validation, FIRST/MIDDLE/LAST reassembly, declared report sizes and zero-padded TX. |
| TX ownership | The caller can peek at a report repeatedly; only successful completion advances it. A pending frame blocks another frame, preventing interleaved fragments. |
| Metadata | Extended Interface status, track index, title, artist and album replies. Replies echo transaction IDs when the session owner enables that mode. Text is NUL-terminated UTF-8. |

The metadata function deliberately takes its session mode from the application.
IDPS, authentication, digital-audio negotiation, notifications and playback actions
are subsequent session work. AVRCP should supply the track data; it is currently
supplied by the offline demonstration.

At an unsupported sampling frequency, the control handler selects the nearest
advertised rate as specified by UAC1, then reports that rate through GET_CUR.
Rate changes, stopping streaming and configuration changes discard old-format
queued PCM. Starting the stream preserves audio prebuffered while idle.

## Build and replay

From the repository root:

```sh
python3 -m unittest -v test_usb_bridge
python3 run_offline_bridge_demo.py --output results/offline-bridge-20261019
```

Use a new output folder; the builder refuses to overwrite an existing one.
Python 3.9+ and clang are sufficient. No Python USB package or Homebrew libusb is
required. The demo runs a deterministic original melody through the C FIFO in
5 ms producer bursts and drains one packet per simulated USB millisecond.

For a four-second run, the saved output contains:

- 176,400 stereo frames at 44.1 kHz: 3,600 packets of 176 bytes and 400 of 180 bytes.
- 192,000 stereo frames at 48 kHz: 4,000 packets of 192 bytes.
- No missing or rejected input frames.
- A long title query received through EP0 SET_REPORT, handled by the metadata
  function and returned in two HID reports.
- ARM Cortex-M33/Thumb objects for all four C modules, with every external
  reference resolved within those modules and no OS/runtime dependency.

`*.usb-packets.bin` stores repeated little-endian uint16 length prefixes followed
by actual C-generated packet bytes. Python independently validates their sizes
and timing and reconstructs the WAVs from those bytes. It also independently
reassembles the metadata reports and checks their checksum and returned title.
`host-events.jsonl` records simulated host setup packets and replies; these files
are generated test traffic, not a hardware capture.

`demo.json` reports object sizes, state size, commands and results. The current
build has **3,998 bytes of ARM instruction text** plus read-only tables and unwind
sections, and **4,168 bytes of bridge state** including both iAP buffers and PCM.
The controller port must also provide transfer buffers and stack space.
`manifest.json` hashes the delivered files; the ZIP includes a self-contained
source copy, tests, host executable, ARM objects, traces and WAVs.

## Controller integration boundary

The portable code has no host USB API, fixed firmware addresses, register access,
allocator or OS calls. The separate `rtl8761c_audio_port.c` adapter now connects
its audio packets to the saved CU driver's endpoint operations in ARM emulation.
Read [NATIVE_AUDIO_PORT.md](NATIVE_AUDIO_PORT.md) for the pinned ABI and results.
The native controller integration must provide:

1. Enumeration/setup routing into `dart_usb_control`. The function accepts the
   complete OUT data stage and copies IN replies into port-owned memory. Address
   changes reach the controller only after the status stage.
2. Endpoint configuration for interrupt IN `0x81` and 192-byte ISO IN `0x83`.
   The audio adapter's descriptor is accepted by the captured native enable and
   ISO software queue with 192 bytes. Physical controller setup, interrupt IN
   configuration and DMA/cache integration remain.
3. One `dart_usb_audio_packet` call per full-speed millisecond **after** securing
   an available native transfer buffer. That buffer must remain valid during DMA.
   The call advances the stream; do not speculatively fill then discard packets
   when the hardware queue is busy.
4. Serialized producer, setup and completion calls. Cancel/drain endpoint DMA
   before resetting state or changing configuration, alternate or sample rate.
5. Delivery of checked iAP payloads to the session owner. Use
   `dart_iap_metadata_reply` for supported metadata queries, queue the reply, and
   advance each outgoing HID report only after successful transfer completion.

The listenable demo uses a host-side controller stand-in for this boundary;
`validate_native_audio.py` separately runs compiled ARM code against the captured
native endpoint routines with simulated controller memory and completions.
Bluetooth A2DP/SBC reception, AVRCP input, the full iAP session and persistent
startup remain necessary for the standalone dongle. Head-unit acceptance will be
measured in the Dart after the controller port is ready and hardware work resumes.

## Validation and provenance

The new C host tests run with AddressSanitizer and UndefinedBehaviorSanitizer.
They cover descriptor lengths/topology, lifecycle, invalid requests, every stereo
sample across a second at each rate, ring wrap/overrun/underrun, sample-rate
switches, a fixed iAP wire vector, every payload length from 1 through 1,024,
malformed/abandoned frames, TX backpressure, metadata and transaction IDs.

All implementation code is original project code under MIT. Protocol facts were
checked against [USB Audio Class 1.0](https://www.usb.org/sites/default/files/audio10.pdf)
and the pinned public RockPod reference described in IPOD_PROTOCOL.md:
[USB audio](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/firmware/usbstack/usb_audio.c),
[HID transport](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/firmware/usbstack/usb_iap_hid.c),
[Extended Interface commands](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/apps/iap/iap-lingo4.c)
and [transaction placement](https://github.com/nuxcodes/rockpod/blob/951d17c0575fbb61f3c585b5f0c3a0a941dcb10f/apps/iap/iap-core.c).
RockPod source has not been copied into the implementation.
