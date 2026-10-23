#ifndef DART_USB_AUDIO_SOURCE_H
#define DART_USB_AUDIO_SOURCE_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t sample_rate;
    uint32_t remainder;
    uint32_t missing_frames;
    uint32_t tone_phase;
} dart_audio_source;

/* Stereo, signed 16-bit PCM. One call represents one full-speed USB millisecond. */
int dart_audio_init(dart_audio_source *source, uint32_t sample_rate);

/* Produce a complete packet, pad shortages with silence, and report consumed
 * stereo frames. A short output buffer returns zero without advancing time.
 * The caller owns buffering and must not overlap pcm with output. */
size_t dart_audio_packet(dart_audio_source *source, const int16_t *pcm,
                        size_t available_frames, uint8_t *output,
                        size_t output_capacity, size_t *consumed_frames);

/* Generate a modest-level 1 kHz square-wave diagnostic packet, on both channels. */
size_t dart_audio_test_tone(dart_audio_source *source, uint8_t *output,
                           size_t output_capacity);

#endif
