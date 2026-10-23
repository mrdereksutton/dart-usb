#include "rtl8761c_audio_port.h"

dart_usb_bridge fixture_bridge;
dart_rtl_audio_port fixture_port;
static uint32_t bad_dma;

static uint32_t simulated_dma(void *context, const uint8_t *buffer, size_t capacity)
{
    (void)context; (void)capacity;
    return bad_dma ? UINT32_MAX : (uint32_t)(uintptr_t)buffer; /* explicit virtual mapping */
}

int fixture_init(uint32_t rate)
{
    uint8_t reply[4]; size_t length;
    const uint8_t configure[] = {0, 9, 2, 0, 0, 0, 0, 0};
    const uint8_t sample_rate[] = {0x22, 1, 0, 1, 0x83, 0, 3, 0};
    const uint8_t stream[] = {1, 11, 1, 0, 1, 0, 0, 0};
    const uint8_t frequency[] = {(uint8_t)rate, (uint8_t)(rate >> 8), (uint8_t)(rate >> 16)};
    dart_usb_init(&fixture_bridge);
    if (dart_usb_control(&fixture_bridge, configure, 0, 0, reply, sizeof(reply), &length) < 0 ||
        dart_usb_control(&fixture_bridge, sample_rate, frequency, 3, reply, sizeof(reply), &length) < 0 ||
        dart_usb_control(&fixture_bridge, stream, 0, 0, reply, sizeof(reply), &length) < 0) return -1;
    return dart_rtl_audio_init(&fixture_port, &fixture_bridge,
                               (dart_rtl_endpoint *)(uintptr_t)0x0030cc08,
                               simulated_dma, 0);
}

int fixture_start(void) { return dart_rtl_audio_start(&fixture_port); }
int fixture_service(void) { return dart_rtl_audio_service(&fixture_port); }
int fixture_stop(void) { return dart_rtl_audio_stop(&fixture_port); }
void fixture_bad_dma(uint32_t invalid) { bad_dma = invalid; }

int fixture_push(uint32_t frames, uint32_t first_sample)
{
    if (frames > 48) return -1;
    int16_t pcm[96];
    for (size_t i = 0; i < frames; ++i) {
        pcm[i * 2] = (int16_t)(first_sample + i);
        pcm[i * 2 + 1] = (int16_t)(-(int32_t)(first_sample + i));
    }
    return (int)dart_usb_push_pcm(&fixture_bridge, pcm, frames);
}

uint32_t fixture_size(uint32_t object)
{
    return object == 0 ? sizeof(dart_rtl_request) : object == 1 ? sizeof(dart_rtl_audio_port) :
           object == 2 ? sizeof(dart_rtl_audio_slot) : sizeof(dart_usb_bridge);
}

uint32_t fixture_stat(uint32_t index)
{
    if (index == 0) return fixture_port.queued_packets;
    if (index == 1) return fixture_port.completed_packets;
    if (index == 2) return fixture_port.queue_failures;
    if (index == 3) return fixture_port.transfer_failures;
    if (index == 4) return fixture_bridge.queued_frames;
    if (index == 5) return fixture_bridge.packets;
    if (index == 6) return fixture_port.discarded_packets;
    if (index == 7) return fixture_port.faulted;
    return UINT32_MAX;
}
