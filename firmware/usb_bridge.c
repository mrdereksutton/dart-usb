#include "usb_bridge.h"

static const uint8_t device_descriptor[] = {
    18, 1, 0x10, 0x01, 0, 0, 0, 64,
    0x05, 0x0b, 0x70, 0x1d, 0, 2, 1, 2, 0, 1
};

/* UAC1 stereo source, two discrete rates, idle/active streaming alternates,
 * and an iAP HID interface. Length fields are verified by the host test. */
static const uint8_t configuration_descriptor[] = {
    9, 2, DART_USB_CONFIG_DESCRIPTOR_SIZE, 0, 3, DART_USB_CONFIGURATION, 0, 0x80, 50,
    9, 4, 0, 0, 0, 1, 1, 0, 0,
    9, 0x24, 1, 0, 1, 30, 0, 1, DART_USB_AUDIO_INTERFACE,
    12, 0x24, 2, 1, 1, 2, 2, 2, 3, 0, 0, 0,
    9, 0x24, 3, 2, 1, 1, 1, 1, 0,
    9, 4, DART_USB_AUDIO_INTERFACE, 0, 0, 1, 2, 0, 0,
    9, 4, DART_USB_AUDIO_INTERFACE, 1, 1, 1, 2, 0, 0,
    7, 0x24, 1, 2, 1, 1, 0,
    14, 0x24, 2, 1, 2, 2, 16, 2, 0x44, 0xac, 0, 0x80, 0xbb, 0,
    9, 5, DART_USB_AUDIO_ENDPOINT, 1, DART_USB_AUDIO_MAX_PACKET, 0, 1, 0, 0,
    7, 0x25, 1, 1, 0, 0, 0,
    9, 4, DART_USB_HID_INTERFACE, 0, 1, 3, 0, 0, 0,
    9, 0x21, 0x11, 1, 0, 1, 0x22, DART_IAP_REPORT_DESCRIPTOR_SIZE, 0,
    7, 5, DART_USB_HID_ENDPOINT, 3, 64, 0, 1
};

_Static_assert(sizeof(configuration_descriptor) == DART_USB_CONFIG_DESCRIPTOR_SIZE,
               "configuration length must match its descriptor");

static uint16_t le16(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

void dart_usb_init(dart_usb_bridge *bridge)
{
    if (!bridge) return;
    dart_audio_init(&bridge->audio, 48000);
    dart_iap_init(&bridge->iap);
    bridge->packets = bridge->pcm_frames_sent = 0;
    bridge->discarded_frames = bridge->rejected_frames = 0;
    bridge->read_frame = bridge->queued_frames = 0;
    bridge->configuration = bridge->alternate = bridge->address = 0;
    for (size_t i = 0; i < 4; ++i) bridge->hid_idle[i] = 0;
}

static void restart_audio(dart_usb_bridge *bridge, uint32_t rate, int discard)
{
    if (discard) {
        bridge->discarded_frames += bridge->queued_frames;
        bridge->queued_frames = bridge->read_frame = 0;
    }
    dart_audio_init(&bridge->audio, rate);
}

static int response(const uint8_t *data, size_t size, uint16_t requested,
                    uint8_t *reply, size_t capacity, size_t *length)
{
    if (size > requested) size = requested;
    if (size > capacity || (!reply && size)) return DART_USB_STALL;
    for (size_t i = 0; i < size; ++i) reply[i] = data[i];
    *length = size;
    return DART_USB_DATA;
}

static int get_descriptor(uint8_t recipient, uint16_t value, uint16_t index,
                          uint16_t requested, uint8_t *reply, size_t capacity,
                          size_t *length)
{
    uint8_t type = (uint8_t)(value >> 8), number = (uint8_t)value;
    if (recipient == 0x80 && type == 1 && !number && !index)
        return response(device_descriptor, sizeof(device_descriptor), requested,
                        reply, capacity, length);
    if (recipient == 0x80 && type == 2 && !number && !index)
        return response(configuration_descriptor, sizeof(configuration_descriptor),
                        requested, reply, capacity, length);
    if (recipient == 0x80 && type == 3) {
        uint8_t string[64];
        if (!number && !index) {
            const uint8_t languages[] = {4, 3, 9, 4};
            return response(languages, sizeof(languages), requested, reply, capacity, length);
        }
        const char *text = number == 1 ? "Dart USB" :
                           number == 2 ? "Dart Audio Bridge" : (const char *)0;
        if (!text || index != 0x0409) return DART_USB_STALL;
        size_t n = 2;
        for (size_t i = 0; text[i] && n + 2 <= sizeof(string); ++i) {
            string[n++] = (uint8_t)text[i]; string[n++] = 0;
        }
        string[0] = (uint8_t)n; string[1] = 3;
        return response(string, n, requested, reply, capacity, length);
    }
    if (recipient == 0x81 && !number && index == DART_USB_HID_INTERFACE) {
        if (type == 0x21) {
            const uint8_t hid[] = {9, 0x21, 0x11, 1, 0, 1, 0x22,
                                   DART_IAP_REPORT_DESCRIPTOR_SIZE, 0};
            return response(hid, sizeof(hid), requested, reply, capacity, length);
        }
        if (type == 0x22) {
            uint8_t report[DART_IAP_REPORT_DESCRIPTOR_SIZE];
            size_t n = dart_iap_report_descriptor(report, sizeof(report));
            return response(report, n, requested, reply, capacity, length);
        }
    }
    return DART_USB_STALL;
}

int dart_usb_control(dart_usb_bridge *bridge, const uint8_t setup[8],
                     const uint8_t *out_data, size_t out_length,
                     uint8_t *reply, size_t reply_capacity, size_t *reply_length)
{
    if (reply_length) *reply_length = 0;
    if (!bridge || !setup || !reply_length) return DART_USB_STALL;
    uint8_t kind = setup[0], request = setup[1];
    uint16_t value = le16(setup + 2), index = le16(setup + 4), size = le16(setup + 6);
    if ((kind & 0x80) ? out_length != 0 : out_length != size) return DART_USB_STALL;
    if (out_length && !out_data) return DART_USB_STALL;
    if (request == 6 && (kind == 0x80 || kind == 0x81))
        return get_descriptor(kind, value, index, size, reply, reply_capacity, reply_length);
    if (kind == 0 && request == 5 && !index && !size && value <= 127 &&
        !bridge->configuration) {
        bridge->address = (uint8_t)value;
        return DART_USB_ACK;
    }
    if (kind == 0 && request == 9 && !index && !size &&
        (value == 0 || value == DART_USB_CONFIGURATION)) {
        bridge->configuration = (uint8_t)value;
        bridge->alternate = 0;
        restart_audio(bridge, 48000, 1);
        dart_iap_init(&bridge->iap);
        for (size_t i = 0; i < 4; ++i) bridge->hid_idle[i] = 0;
        return DART_USB_ACK;
    }
    if (kind == 0x80 && request == 8 && !value && !index && size == 1)
        return response(&bridge->configuration, 1, size, reply, reply_capacity, reply_length);
    if (request == 0 && !value && size == 2) {
        const uint8_t status[] = {0, 0};
        int valid = (kind == 0x80 && !index) ||
                    (kind == 0x81 && bridge->configuration && index < 3) ||
                    (kind == 0x82 && (index == 0 || index == 0x80 ||
                     (bridge->configuration && (index == DART_USB_HID_ENDPOINT ||
                      (bridge->alternate && index == DART_USB_AUDIO_ENDPOINT)))));
        if (valid) return response(status, 2, size, reply, reply_capacity, reply_length);
    }
    if (!bridge->configuration) return DART_USB_STALL;
    if (kind == 0x81 && request == 10 && !value && index < 3 && size == 1) {
        uint8_t alt = index == DART_USB_AUDIO_INTERFACE ? bridge->alternate : 0;
        return response(&alt, 1, size, reply, reply_capacity, reply_length);
    }
    if (kind == 1 && request == 11 && index < 3 && !size &&
        (value == 0 || (value == 1 && index == DART_USB_AUDIO_INTERFACE))) {
        if (index == DART_USB_AUDIO_INTERFACE) {
            int discard = !value || bridge->alternate;
            bridge->alternate = (uint8_t)value;
            restart_audio(bridge, bridge->audio.sample_rate, discard);
        }
        return DART_USB_ACK;
    }
    if (index == DART_USB_AUDIO_ENDPOINT && value == 0x0100 && size == 3) {
        if (kind == 0xa2 && request >= 0x81 && request <= 0x84) {
            uint32_t rate = request == 0x81 ? bridge->audio.sample_rate :
                            request == 0x82 ? 44100 : request == 0x83 ? 48000 : 3900;
            uint8_t data[] = {(uint8_t)rate, (uint8_t)(rate >> 8), (uint8_t)(rate >> 16)};
            return response(data, 3, size, reply, reply_capacity, reply_length);
        }
        if (kind == 0x22 && request == 1) {
            uint32_t rate = (uint32_t)out_data[0] | ((uint32_t)out_data[1] << 8) |
                            ((uint32_t)out_data[2] << 16);
            uint32_t selected = rate <= 46050 ? 44100 : 48000;
            if (selected != bridge->audio.sample_rate) restart_audio(bridge, selected, 1);
            return DART_USB_ACK;
        }
    }
    if (index == DART_USB_HID_INTERFACE) {
        if (kind == 0x21 && request == 9 && (value >> 8) == 2 &&
            dart_iap_out_report_size((uint8_t)value) == size && size &&
            out_data[0] == (uint8_t)value) {
            return dart_iap_receive(&bridge->iap, out_data, size) >= 0 ?
                   DART_USB_ACK : DART_USB_STALL;
        }
        uint8_t id = (uint8_t)value;
        if (kind == 0x21 && request == 10 && !size && id <= 4) {
            for (size_t i = 0; i < 4; ++i)
                if (!id || id == i + 1) bridge->hid_idle[i] = (uint8_t)(value >> 8);
            return DART_USB_ACK;
        }
        if (kind == 0xa1 && request == 2 && !(value >> 8) && id >= 1 && id <= 4 && size == 1)
            return response(&bridge->hid_idle[id - 1], 1, size, reply, reply_capacity, reply_length);
    }
    return DART_USB_STALL;
}

size_t dart_usb_push_pcm(dart_usb_bridge *bridge, const int16_t *pcm, size_t frames)
{
    if (!bridge || !bridge->configuration || !pcm) return 0;
    size_t room = DART_USB_PCM_FRAMES - bridge->queued_frames;
    size_t accepted = frames < room ? frames : room;
    for (size_t i = 0; i < accepted; ++i) {
        size_t position = (bridge->read_frame + bridge->queued_frames + i) % DART_USB_PCM_FRAMES;
        bridge->pcm[position * 2] = pcm[i * 2];
        bridge->pcm[position * 2 + 1] = pcm[i * 2 + 1];
    }
    bridge->queued_frames += (uint16_t)accepted;
    bridge->rejected_frames += (uint32_t)(frames - accepted);
    return accepted;
}

size_t dart_usb_audio_packet(dart_usb_bridge *bridge, uint8_t *output, size_t capacity)
{
    if (!bridge || !bridge->configuration || !bridge->alternate || !output) return 0;
    size_t need = (bridge->audio.remainder + bridge->audio.sample_rate) / 1000;
    if (capacity < need * 4) return 0;
    int16_t contiguous[48 * 2];
    size_t available = bridge->queued_frames < need ? bridge->queued_frames : need;
    for (size_t i = 0; i < available; ++i) {
        size_t position = (bridge->read_frame + i) % DART_USB_PCM_FRAMES;
        contiguous[i * 2] = bridge->pcm[position * 2];
        contiguous[i * 2 + 1] = bridge->pcm[position * 2 + 1];
    }
    size_t used = 0;
    size_t length = dart_audio_packet(&bridge->audio, contiguous, available,
                                     output, capacity, &used);
    if (!length) return 0;
    bridge->read_frame = (uint16_t)((bridge->read_frame + used) % DART_USB_PCM_FRAMES);
    bridge->queued_frames -= (uint16_t)used;
    bridge->pcm_frames_sent += (uint32_t)used;
    bridge->packets++;
    return length;
}
