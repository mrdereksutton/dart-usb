# USB audio and iAP bridge core

The portable receiver component now handles an Audio Class 1 source and iAP HID
configuration, host setup requests, a bounded stereo PCM ring buffer, iAP frame
fragmentation/reassembly and checksums, and track title/artist/album/status replies.
It runs in host tests and cross-compiles for the dongle's ARM target. The native
audio adapter now runs against the captured RTL8761C endpoint driver in ARM
emulation: a 192-byte request reaches its ISO software queue, and both sample
rates pass a 1,000-packet wrapper replay. The native control adapter now connects
host enumeration, configuration, rate changes, stream start/stop and reset to
that audio path. Resident RAM, task scheduling, device DMA/cache handling and
the Bluetooth receiver remain integration work.

Build a listenable demo, packet traces, ARM objects and a source bundle without
opening USB:

```sh
python3 -m unittest -v test_usb_bridge
python3 run_offline_bridge_demo.py
```

The generated folder contains `audio-44100.wav`, `audio-48000.wav`, `demo.json`,
the exact USB packet bytes, and `dart-usb-offline-bridge.zip`. The audio comes
through the same C FIFO and packetizer intended for firmware. The simulated host
also asks for a long track title and receives two checked HID reports.

See [BRIDGE.md](BRIDGE.md) for the port boundary, memory use and supported requests.
See [NATIVE_AUDIO_PORT.md](NATIVE_AUDIO_PORT.md) for the captured driver ABI,
adapter lifecycle, exact replay scope and reproducible native queue checks.
See [CONTROL_PORT.md](CONTROL_PORT.md) for the connected native enumeration and
stream-control path. `validate_native_control.py` replays it without USB access.

## PCM packetizer

`usb_audio_source.c` generates full-speed USB packets for stereo 16-bit PCM.
At 48 kHz every packet is 192 bytes. At 44.1 kHz packets contain 44 or 45 stereo
frames (176/180 bytes), totaling exactly 44,100 frames per second. Short input is
padded with silence and counted; a short output buffer consumes nothing.

`dart_audio_test_tone` produces a modest-level 1 kHz square wave for the first
USB streaming experiment. Its state is 16 bytes and the current ARM object has
488 bytes of text, no data/BSS and no unresolved external symbols.

Build with the existing macOS Command Line Tools:

```sh
mkdir -p results/firmware-build
xcrun clang -target armv8m.main-none-eabi -mcpu=cortex-m33 -mthumb \
  -std=c11 -ffreestanding -Os -Wall -Wextra -Werror \
  -c firmware/usb_audio_source.c -o results/firmware-build/usb_audio_source.o
python3 -m unittest -v test_usb_audio_source
```

The build targets ARMv8-M Mainline instructions used by the CU's Real-M300 core.
The packetizer now feeds the captured native queue through
`rtl8761c_audio_port.c` in ARM replay. Physical audio streaming is still pending.
The USB setup trampoline and a resident ROM flash-read call have both executed
successfully on the dongle in earlier experiments.

`flash_read_helper.S` preserves the setup caller's registers and flags, reads
16 bytes through ROM entry `0x0000cbb5`, records its status, and tail-calls the
original handler. `native_flash_read.py` assembles and installs it with zero-word
checks, saved originals and automatic restoration. The hardware run returned the
expected data and status `0x18`; see SESSION_NOTES.md for the saved result.
