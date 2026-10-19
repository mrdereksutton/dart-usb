# USB audio and iAP bridge core

The portable receiver component now handles an Audio Class 1 source and iAP HID
configuration, host setup requests, a bounded stereo PCM ring buffer, iAP frame
fragmentation/reassembly and checksums, and track title/artist/album/status replies.
It runs in host tests and cross-compiles for the dongle's ARM target. The native
RTL8761C endpoint driver and Bluetooth receiver still need to be connected.

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
The packetizer is ready for native endpoint queue integration; it has so far
run in host tests. The USB setup trampoline and a resident ROM flash-read call
have both executed successfully on the dongle.

`flash_read_helper.S` preserves the setup caller's registers and flags, reads
16 bytes through ROM entry `0x0000cbb5`, records its status, and tail-calls the
original handler. `native_flash_read.py` assembles and installs it with zero-word
checks, saved originals and automatic restoration. The hardware run returned the
expected data and status `0x18`; see SESSION_NOTES.md for the saved result.
