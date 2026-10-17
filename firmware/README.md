# USB audio source core

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
The packetizer is ready for the native endpoint queue integration; it has so far
run in host tests. The prepared USB setup marker is the next hardware code test.
