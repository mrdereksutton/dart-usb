#include "usb_audio_source.h"

static int supported(uint32_t rate)
{
    return rate == 44100 || rate == 48000;
}

int dart_audio_init(dart_audio_source *source, uint32_t sample_rate)
{
    if (!source || !supported(sample_rate)) return 0;
    source->sample_rate = sample_rate;
    source->remainder = 0;
    source->missing_frames = 0;
    source->tone_phase = 0;
    return 1;
}

static size_t packet_frames(dart_audio_source *source, size_t capacity)
{
    if (!source || !supported(source->sample_rate)) return 0;
    size_t frames = (source->remainder + source->sample_rate) / 1000;
    return frames * 4 <= capacity ? frames : 0;
}

static void sample_le(uint8_t *output, int16_t value)
{
    uint16_t bits = (uint16_t)value;
    output[0] = (uint8_t)bits;
    output[1] = (uint8_t)(bits >> 8);
}

size_t dart_audio_packet(dart_audio_source *source, const int16_t *pcm,
                        size_t available_frames, uint8_t *output,
                        size_t output_capacity, size_t *consumed_frames)
{
    if (consumed_frames) *consumed_frames = 0;
    if (!output || (!pcm && available_frames)) return 0;
    size_t frames = packet_frames(source, output_capacity);
    if (!frames) return 0;
    size_t used = available_frames < frames ? available_frames : frames;
    for (size_t frame = 0; frame < frames; ++frame) {
        int16_t left = frame < used ? pcm[frame * 2] : 0;
        int16_t right = frame < used ? pcm[frame * 2 + 1] : 0;
        sample_le(output + frame * 4, left);
        sample_le(output + frame * 4 + 2, right);
    }
    source->remainder = (source->remainder + source->sample_rate) % 1000;
    source->missing_frames += (uint32_t)(frames - used);
    if (consumed_frames) *consumed_frames = used;
    return frames * 4;
}

size_t dart_audio_test_tone(dart_audio_source *source, uint8_t *output,
                           size_t output_capacity)
{
    if (!output) return 0;
    size_t frames = packet_frames(source, output_capacity);
    if (!frames) return 0;
    for (size_t frame = 0; frame < frames; ++frame) {
        int16_t sample = source->tone_phase < source->sample_rate / 2 ? 4096 : -4096;
        sample_le(output + frame * 4, sample);
        sample_le(output + frame * 4 + 2, sample);
        source->tone_phase += 1000;
        if (source->tone_phase >= source->sample_rate)
            source->tone_phase -= source->sample_rate;
    }
    source->remainder = (source->remainder + source->sample_rate) % 1000;
    return frames * 4;
}
