#ifndef DART_USB_BRIDGE_H
#define DART_USB_BRIDGE_H

#include "usb_audio_source.h"
#include "iap_hid.h"

#define DART_USB_CONFIGURATION 2
#define DART_USB_AUDIO_INTERFACE 1
#define DART_USB_HID_INTERFACE 2
#define DART_USB_AUDIO_ENDPOINT 0x83
#define DART_USB_HID_ENDPOINT 0x81
#define DART_USB_AUDIO_MAX_PACKET 192
#define DART_USB_PCM_FRAMES 512
#define DART_USB_CONFIG_DESCRIPTOR_SIZE 128

typedef struct {
    dart_audio_source audio;
    dart_iap_hid iap;
    int16_t pcm[DART_USB_PCM_FRAMES * 2];
    uint32_t packets, pcm_frames_sent, discarded_frames, rejected_frames;
    uint16_t read_frame, queued_frames;
    uint8_t configuration, alternate, address, hid_idle[4];
} dart_usb_bridge;

enum dart_usb_result { DART_USB_STALL = -1, DART_USB_ACK = 0, DART_USB_DATA = 1 };

/* Development identity preserves this adapter's ASUS 0b05:1d70 VID/PID. The
 * single configuration has value 2 (audio + HID), with no storage persona.
 * No hardware register, USB host API, memory allocation, or OS call is used. */
void dart_usb_init(dart_usb_bridge *bridge);

/* Handle a complete EP0 transaction. OUT data must already be available; data
 * returned for IN is bounded by wLength and reply_capacity. SET_ADDRESS must be
 * applied by the controller port only AFTER its status stage. The port must
 * cancel/drain endpoint DMA before reset, configuration, alternate, or rate
 * changes; serialize this API with producer/consumer calls. */
int dart_usb_control(dart_usb_bridge *bridge, const uint8_t setup[8],
                     const uint8_t *out_data, size_t out_length,
                     uint8_t *reply, size_t reply_capacity, size_t *reply_length);

/* PCM is interleaved stereo signed 16-bit. Returns accepted whole frames;
 * caller retains any remainder. Configured idle accepts prebuffered audio.
 * A rate change or stopping the alternate discards buffered old-format audio. */
size_t dart_usb_push_pcm(dart_usb_bridge *bridge, const int16_t *pcm, size_t frames);

/* Call once per full-speed millisecond, only when the native driver has a free
 * transfer buffer it can accept. Output belongs to the caller (including during
 * DMA). A short buffer/idle stream consumes nothing. Short input is silenced.
 * Filling a buffer advances the stream; a port must not fill buffers speculatively
 * and discard them when its endpoint queue is busy. */
size_t dart_usb_audio_packet(dart_usb_bridge *bridge, uint8_t *output, size_t capacity);

#endif
