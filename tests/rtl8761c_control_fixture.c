#include "rtl8761c_control_port.h"

dart_usb_bridge control_bridge;
dart_rtl_audio_port control_audio;
dart_rtl_control_port control_port;

static uint32_t simulated_dma(void *context, const uint8_t *buffer, size_t capacity)
{
    (void)context; (void)capacity;
    return (uint32_t)(uintptr_t)buffer;
}

int control_init(void)
{
    dart_usb_init(&control_bridge);
    int result = dart_rtl_audio_init(&control_audio, &control_bridge,
                                     (dart_rtl_endpoint *)(uintptr_t)0x0030cc08, simulated_dma, 0);
    if (result) return result;
    result = dart_rtl_control_init(&control_port, &control_audio,
                                   (dart_rtl_gadget *)(uintptr_t)0x0030cb6c,
                                   (dart_rtl_setup_fn *)(uintptr_t)0x0030d164,
                                   (dart_rtl_disconnect_fn *)(uintptr_t)0x0030d168);
    return result ? result : dart_rtl_control_bind(&control_port);
}

int control_service(void) { return dart_rtl_control_service(&control_port); }
int control_audio_service(void) { return dart_rtl_control_tick(&control_port); }
int control_unbind(void) { return dart_rtl_control_unbind(&control_port); }

int control_push(uint32_t first, uint32_t frames)
{
    if (frames > 48) return -1;
    int16_t pcm[96];
    for (size_t i = 0; i < frames; ++i) {
        pcm[i * 2] = (int16_t)(first + i);
        pcm[i * 2 + 1] = (int16_t)(-(int32_t)(first + i));
    }
    return (int)dart_usb_push_pcm(&control_bridge, pcm, frames);
}

uint32_t control_get(uint32_t field)
{
    switch (field) {
    case 0: return (uint32_t)(uintptr_t)&control_port.request;
    case 1: return control_bridge.configuration;
    case 2: return control_bridge.alternate;
    case 3: return control_bridge.audio.sample_rate;
    case 4: return control_port.state;
    case 5: return control_port.in_flight;
    case 6: return control_port.bound;
    case 7: return control_port.resetting;
    case 8: return control_port.completed_count;
    case 9: return control_audio.enabled;
    case 10: return control_bridge.queued_frames;
    case 11: return control_audio.completed_packets;
    case 12: return sizeof(control_port);
    case 13: return control_port.setup_count;
    case 14: return control_bridge.iap.rx_ready;
    case 15: return (uint32_t)control_port.last_error;
    case 16: return (uint32_t)(uintptr_t)control_port.data;
    case 17: return control_port.stalled;
    case 18: return control_port.reset_count;
    case 19: return control_audio.queued_packets;
    default: return UINT32_MAX;
    }
}
