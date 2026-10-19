#include "usb_bridge.h"
#include "iap_metadata.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "%s:%d: %s\n", __func__, __LINE__, #condition); exit(1); \
} } while (0)

static dart_usb_bridge bridge;
static uint8_t reply[256];
static size_t reply_length;

static int control(uint8_t kind, uint8_t request, uint16_t value, uint16_t index,
                   uint16_t size, const uint8_t *data, size_t data_size)
{
    const uint8_t setup[] = {kind, request, (uint8_t)value, (uint8_t)(value >> 8),
        (uint8_t)index, (uint8_t)(index >> 8), (uint8_t)size, (uint8_t)(size >> 8)};
    return dart_usb_control(&bridge, setup, data, data_size, reply, sizeof(reply), &reply_length);
}

static void configured(void)
{
    dart_usb_init(&bridge);
    CHECK(control(0, 5, 7, 0, 0, NULL, 0) == DART_USB_ACK);
    CHECK(control(0, 9, DART_USB_CONFIGURATION, 0, 0, NULL, 0) == DART_USB_ACK);
}

static void streaming(uint32_t rate)
{
    configured();
    uint8_t data[] = {(uint8_t)rate, (uint8_t)(rate >> 8), (uint8_t)(rate >> 16)};
    CHECK(control(0x22, 1, 0x100, DART_USB_AUDIO_ENDPOINT, 3, data, 3) == DART_USB_ACK);
    CHECK(control(1, 11, 1, DART_USB_AUDIO_INTERFACE, 0, NULL, 0) == DART_USB_ACK);
}

static void descriptors(void)
{
    dart_usb_init(&bridge);
    CHECK(control(0x80, 6, 0x100, 0, 8, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == 8 && reply[0] == 18 && reply[7] == 64);
    CHECK(control(0x80, 6, 0x100, 0, 255, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == 18 && reply[8] == 5 && reply[9] == 11 && reply[17] == 1);
    CHECK(control(0x80, 6, 0x200, 0, 9, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == 9 && reply[2] == DART_USB_CONFIG_DESCRIPTOR_SIZE);
    CHECK(control(0x80, 6, 0x200, 0, 255, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == DART_USB_CONFIG_DESCRIPTOR_SIZE && reply[4] == 3 && reply[5] == 2);
    unsigned interfaces = 0, endpoints = 0, formats = 0, ac_size = 0;
    for (size_t offset = 0; offset < reply_length; offset += reply[offset]) {
        CHECK(reply[offset] >= 2 && offset + reply[offset] <= reply_length);
        if (reply[offset + 1] == 4) interfaces++;
        if (reply[offset + 1] == 5) {
            endpoints++;
            if (reply[offset + 2] == 0x83) {
                CHECK(reply[offset + 3] == 1 && reply[offset + 4] == 192 && reply[offset + 6] == 1);
            } else CHECK(reply[offset + 2] == 0x81 && reply[offset + 4] == 64);
        }
        if (reply[offset + 1] == 0x24 && offset >= 18 && offset < 48) ac_size += reply[offset];
        if (reply[offset + 1] == 0x24 && reply[offset] == 14) {
            formats++;
            CHECK(reply[offset + 4] == 2 && reply[offset + 5] == 2 && reply[offset + 6] == 16);
            CHECK(reply[offset + 7] == 2 && reply[offset + 8] == 0x44 && reply[offset + 9] == 0xac);
            CHECK(reply[offset + 11] == 0x80 && reply[offset + 12] == 0xbb);
        }
    }
    CHECK(interfaces == 4 && endpoints == 2 && formats == 1 && ac_size == 30);
    CHECK(control(0x80, 6, 0x300, 0, 255, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == 4 && reply[2] == 9 && reply[3] == 4);
    CHECK(control(0x80, 6, 0x302, 0x409, 255, NULL, 0) == DART_USB_DATA);
    CHECK(reply[0] == reply_length && reply[2] == 'D' && reply[3] == 0);
    CHECK(control(0x80, 6, 0x302, 0x411, 255, NULL, 0) == DART_USB_STALL);
    CHECK(control(0x80, 6, 0x201, 0, 255, NULL, 0) == DART_USB_STALL);
    CHECK(control(0x81, 6, 0x2200, 2, 255, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == 96 && reply[reply_length - 1] == 0xc0);
    uint8_t id = 0, count = 0;
    unsigned inputs = 0, outputs = 0;
    for (size_t i = 0; i < reply_length;) {
        uint8_t tag = reply[i++];
        size_t size = tag & 3u; if (size == 3) size = 4;
        CHECK(i + size <= reply_length);
        if (tag == 0x85) id = reply[i];
        if (tag == 0x95) count = reply[i];
        if (tag == 0x82) { CHECK(id >= 1 && id <= 4 && count <= 63); inputs++; }
        if (tag == 0x92) { CHECK(id >= 5 && id <= 9 && count <= 63); outputs++; }
        i += size;
    }
    CHECK(inputs == 4 && outputs == 5);
}

static void lifecycle(void)
{
    dart_usb_init(&bridge);
    CHECK(control(1, 11, 1, 1, 0, NULL, 0) == DART_USB_STALL);
    CHECK(control(0, 9, 1, 0, 0, NULL, 0) == DART_USB_STALL);
    configured();
    CHECK(control(0x80, 8, 0, 0, 1, NULL, 0) == DART_USB_DATA && reply[0] == 2);
    CHECK(control(1, 11, 1, 2, 0, NULL, 0) == DART_USB_STALL);
    CHECK(control(1, 11, 1, 1, 0, NULL, 0) == DART_USB_ACK);
    CHECK(control(0x81, 10, 0, 1, 1, NULL, 0) == DART_USB_DATA && reply[0] == 1);
    CHECK(control(0x82, 0, 0, 0x83, 2, NULL, 0) == DART_USB_DATA && reply_length == 2);
    CHECK(control(0, 5, 8, 0, 0, NULL, 0) == DART_USB_STALL);
    CHECK(control(0, 9, 0, 0, 0, NULL, 0) == DART_USB_ACK);
    CHECK(bridge.alternate == 0 && bridge.iap.tx_length == 0);
    CHECK(control(0x82, 0, 0, 0x83, 2, NULL, 0) == DART_USB_STALL);
    CHECK(control(0x80, 8, 0, 0, 1, NULL, 0) == DART_USB_DATA && reply[0] == 0);
    CHECK(control(0x80, 6, 0x100, 0, 18, NULL, 0) == DART_USB_DATA);
}

static void invalid_requests(void)
{
    configured();
    uint8_t setup[] = {0x80, 6, 0, 1, 0, 0, 18, 0};
    uint8_t buffer[20]; memset(buffer, 0xa5, sizeof(buffer));
    size_t length = 99;
    CHECK(dart_usb_control(&bridge, setup, NULL, 0, buffer, 17, &length) == DART_USB_STALL);
    CHECK(length == 0 && buffer[0] == 0xa5 && buffer[19] == 0xa5);
    CHECK(control(0x80, 6, 0x100, 0, 18, buffer, 1) == DART_USB_STALL);
    CHECK(control(0, 9, 0x102, 0, 0, NULL, 0) == DART_USB_STALL);
    CHECK(control(1, 11, 0x101, 1, 0, NULL, 0) == DART_USB_STALL);
    CHECK(control(0x82, 0, 0, 0x183, 2, NULL, 0) == DART_USB_STALL);
    uint8_t rate[] = {0x80, 0xbb, 0};
    CHECK(control(0x22, 1, 0x100, 0x83, 3, rate, 2) == DART_USB_STALL);
    CHECK(control(0x22, 1, 0x100, 0x83, 3, NULL, 3) == DART_USB_STALL);
    CHECK(bridge.audio.sample_rate == 48000 && bridge.configuration == 2 && bridge.alternate == 0);
}

static void sample_rates(void)
{
    streaming(48000);
    int16_t data[200] = {0};
    CHECK(dart_usb_push_pcm(&bridge, data, 100) == 100);
    uint8_t rate[] = {0x44, 0xac, 0};
    CHECK(control(0x22, 1, 0x100, 0x83, 3, rate, 3) == DART_USB_ACK);
    CHECK(bridge.queued_frames == 0 && bridge.discarded_frames == 100 && bridge.audio.sample_rate == 44100);
    CHECK(control(0xa2, 0x81, 0x100, 0x83, 3, NULL, 0) == DART_USB_DATA);
    CHECK(reply_length == 3 && memcmp(reply, rate, 3) == 0);
    for (uint8_t request = 0x82; request <= 0x84; ++request) {
        CHECK(control(0xa2, request, 0x100, 0x83, 3, NULL, 0) == DART_USB_DATA);
        unsigned value = reply[0] | ((unsigned)reply[1] << 8) | ((unsigned)reply[2] << 16);
        CHECK(value == (request == 0x82 ? 44100u : request == 0x83 ? 48000u : 3900u));
    }
    const uint8_t unsupported[] = {0, 0x77, 1}; /* 96000 rounds to 48000 per UAC1 */
    CHECK(control(0x22, 1, 0x100, 0x83, 3, unsupported, 3) == DART_USB_ACK);
    CHECK(bridge.audio.sample_rate == 48000);
    CHECK(control(0xa2, 0x81, 0x200, 0x83, 3, NULL, 0) == DART_USB_STALL);
}

static void audio_seconds(void)
{
    for (uint32_t rate = 44100; rate <= 48000; rate += 3900) {
        streaming(rate);
        uint8_t output[192];
        size_t total = 0, large = 0;
        for (uint32_t ms = 0; ms < 1000; ++ms) {
            size_t frames = ((ms + 1) * rate / 1000) - (ms * rate / 1000);
            int16_t pcm[96];
            for (size_t f = 0; f < frames; ++f) {
                pcm[f * 2] = (int16_t)((total + f) % 30000);
                pcm[f * 2 + 1] = (int16_t)(-pcm[f * 2]);
            }
            CHECK(dart_usb_push_pcm(&bridge, pcm, frames) == frames);
            size_t length = dart_usb_audio_packet(&bridge, output, sizeof(output));
            CHECK(length == frames * 4);
            for (size_t f = 0; f < frames; ++f) {
                CHECK((int16_t)(output[f * 4] | ((uint16_t)output[f * 4 + 1] << 8)) == pcm[f * 2]);
                CHECK((int16_t)(output[f * 4 + 2] | ((uint16_t)output[f * 4 + 3] << 8)) == pcm[f * 2 + 1]);
            }
            if (length == 180) large++;
            total += frames;
        }
        CHECK(total == rate && bridge.pcm_frames_sent == rate && bridge.packets == 1000);
        CHECK(bridge.audio.missing_frames == 0 && bridge.queued_frames == 0);
        CHECK(large == (rate == 44100 ? 100u : 0u));
    }
}

static void audio_buffering(void)
{
    streaming(48000);
    int16_t input[1200];
    for (size_t i = 0; i < 600; ++i) { input[i * 2] = (int16_t)i; input[i * 2 + 1] = (int16_t)(-((int)i)); }
    CHECK(dart_usb_push_pcm(&bridge, input, 600) == 512 && bridge.rejected_frames == 88);
    uint8_t output[192];
    CHECK(dart_usb_audio_packet(&bridge, output, 191) == 0 && bridge.queued_frames == 512);
    CHECK(bridge.packets == 0 && bridge.audio.remainder == 0);
    for (size_t packet = 0; packet < 10; ++packet) {
        CHECK(dart_usb_audio_packet(&bridge, output, sizeof(output)) == 192);
        CHECK((output[0] | ((unsigned)output[1] << 8)) == packet * 48);
    }
    CHECK(bridge.queued_frames == 32);
    CHECK(dart_usb_push_pcm(&bridge, input + 512 * 2, 88) == 88); /* wraps the ring */
    CHECK(dart_usb_audio_packet(&bridge, output, sizeof(output)) == 192);
    CHECK((output[0] | ((unsigned)output[1] << 8)) == 480);
    CHECK((output[128] | ((unsigned)output[129] << 8)) == 512);
    CHECK(control(1, 11, 0, 1, 0, NULL, 0) == DART_USB_ACK);
    CHECK(bridge.queued_frames == 0 && bridge.discarded_frames == 72);
    CHECK(dart_usb_audio_packet(&bridge, output, sizeof(output)) == 0);
    CHECK(dart_usb_push_pcm(&bridge, input, 2) == 2); /* prebuffer while idle */
    CHECK(control(1, 11, 1, 1, 0, NULL, 0) == DART_USB_ACK);
    CHECK(dart_usb_audio_packet(&bridge, output, sizeof(output)) == 192);
    CHECK(bridge.audio.missing_frames == 46 && bridge.queued_frames == 0);
    for (size_t i = 8; i < sizeof(output); ++i) CHECK(output[i] == 0);
}

static size_t host_frame(const uint8_t *payload, size_t size, uint8_t *frame)
{
    size_t n = 0; frame[n++] = 0x55;
    if (size <= 255) frame[n++] = (uint8_t)size;
    else { frame[n++] = 0; frame[n++] = (uint8_t)(size >> 8); frame[n++] = (uint8_t)size; }
    for (size_t i = 0; i < size; ++i) frame[n++] = payload[i];
    unsigned sum = 0;
    for (size_t i = 1; i < n; ++i) sum += frame[i];
    frame[n++] = (uint8_t)(256u - (sum & 255u));
    return n;
}

static void iap_known_vector(void)
{
    configured();
    const uint8_t report[] = {5, 0, 0x55, 4, 0, 0x38, 0x12, 0x34, 0x7e};
    const uint8_t payload[] = {0, 0x38, 0x12, 0x34};
    CHECK(control(0x21, 9, 0x205, 2, sizeof(report), report, sizeof(report)) == DART_USB_ACK);
    uint8_t received[16];
    CHECK(dart_iap_take_payload(&bridge.iap, received, 3) == 0 && bridge.iap.rx_ready);
    CHECK(dart_iap_take_payload(&bridge.iap, received, sizeof(received)) == 4);
    CHECK(memcmp(received, payload, 4) == 0);
    CHECK(dart_iap_queue_payload(&bridge.iap, payload, 4) == 1);
    uint8_t tx[64], again[64];
    CHECK(dart_iap_peek_report(&bridge.iap, tx, sizeof(tx)) == 13);
    const uint8_t expected[] = {1, 0, 0x55, 4, 0, 0x38, 0x12, 0x34, 0x7e, 0, 0, 0, 0};
    CHECK(memcmp(tx, expected, sizeof(expected)) == 0);
    CHECK(dart_iap_queue_payload(&bridge.iap, payload, 4) == 0);
    CHECK(dart_iap_peek_report(&bridge.iap, again, sizeof(again)) == 13 && memcmp(tx, again, 13) == 0);
    CHECK(dart_iap_peek_report(&bridge.iap, tx, 12) == 0 && bridge.iap.tx_offset == 0);
    dart_iap_report_sent(&bridge.iap);
    CHECK(dart_iap_peek_report(&bridge.iap, tx, sizeof(tx)) == 0);
}

static void iap_roundtrip(void)
{
    uint8_t payload[1024], frame[1029], output[1024];
    for (size_t i = 0; i < sizeof(payload); ++i) payload[i] = (uint8_t)(i * 37 + 0x55);
    for (size_t size = 1; size <= sizeof(payload); ++size) {
        configured();
        size_t total = host_frame(payload, size, frame);
        for (size_t offset = 0; offset < total; offset += 62) {
            size_t chunk = total - offset; if (chunk > 62) chunk = 62;
            uint8_t report[64]; memset(report, 0xcd, sizeof(report));
            report[0] = 9;
            report[1] = offset ? (offset + chunk == total ? 1 : 3) : (chunk == total ? 0 : 2);
            memcpy(report + 2, frame + offset, chunk);
            CHECK(control(0x21, 9, 0x209, 2, 64, report, 64) == DART_USB_ACK);
        }
        CHECK(dart_iap_take_payload(&bridge.iap, output, sizeof(output)) == size);
        CHECK(memcmp(payload, output, size) == 0);
        CHECK(dart_iap_queue_payload(&bridge.iap, payload, size));
        size_t offset = 0;
        while (bridge.iap.tx_length) {
            uint8_t report[64];
            size_t length = dart_iap_peek_report(&bridge.iap, report, sizeof(report));
            CHECK(length >= 13 && length <= 64);
            size_t chunk = length - 2; if (chunk > total - offset) chunk = total - offset;
            CHECK(memcmp(report + 2, frame + offset, chunk) == 0);
            CHECK(report[1] == (offset ? (offset + chunk == total ? 1 : 3) : (chunk == total ? 0 : 2)));
            for (size_t i = chunk + 2; i < length; ++i) CHECK(report[i] == 0);
            if (total > 62) CHECK(report[0] == 4 && length == 64);
            offset += chunk;
            dart_iap_report_sent(&bridge.iap);
        }
        CHECK(offset == total);
    }
}

static void iap_malformed(void)
{
    configured();
    uint8_t report[64] = {9, 0, 0x55, 1, 0, 0xff};
    CHECK(dart_iap_receive(&bridge.iap, report, 63) == -1);
    report[0] = 4; CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1); report[0] = 9;
    report[1] = 1; CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1);
    report[1] = 3; CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1);
    report[1] = 2; CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1); /* falsely fragmented short frame */
    report[1] = 4; CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1);
    report[1] = 0; report[5] = 1; CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1); /* bad checksum */
    report[5] = 0xff; CHECK(dart_iap_receive(&bridge.iap, report, 64) == 1);
    CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1 && bridge.iap.rx_ready);
    uint8_t payload[1025] = {0};
    CHECK(dart_iap_take_payload(&bridge.iap, payload, sizeof(payload)) == 1 && payload[0] == 0);
    CHECK(dart_iap_queue_payload(&bridge.iap, payload, 0) == 0);
    CHECK(dart_iap_queue_payload(&bridge.iap, payload, sizeof(payload)) == 0);
    report[3] = 0; report[4] = 4; report[5] = 1; report[1] = 2;
    CHECK(dart_iap_receive(&bridge.iap, report, 64) == -1); /* 1025-byte advertised payload */
    CHECK(control(0x21, 9, 0x205, 2, 64, report, 64) == DART_USB_STALL);
}

static void iap_fragment_restart(void)
{
    configured();
    uint8_t payload[100], frame[105], report[64] = {9, 2};
    memset(payload, 0x55, sizeof(payload));
    host_frame(payload, sizeof(payload), frame); memcpy(report + 2, frame, 62);
    CHECK(dart_iap_receive(&bridge.iap, report, 64) == 0);
    uint8_t changed_id[21] = {8, 1};
    CHECK(dart_iap_receive(&bridge.iap, changed_id, 21) == -1 && !bridge.iap.rx_active);
    CHECK(dart_iap_receive(&bridge.iap, report, 64) == 0);
    const uint8_t restart[] = {5, 0, 0x55, 4, 0, 0x38, 0x12, 0x34, 0x7e};
    CHECK(dart_iap_receive(&bridge.iap, restart, sizeof(restart)) == 1);
    uint8_t received[100]; CHECK(dart_iap_take_payload(&bridge.iap, received, sizeof(received)) == 4);
    CHECK(dart_iap_queue_payload(&bridge.iap, payload, sizeof(payload)) == 1);
    CHECK(control(0, 9, 0, 0, 0, NULL, 0) == DART_USB_ACK);
    CHECK(!bridge.iap.tx_length && !bridge.iap.rx_active && !bridge.iap.rx_ready);
}

static void hid_idle(void)
{
    configured();
    CHECK(control(0x21, 10, 0x0a00, 2, 0, NULL, 0) == DART_USB_ACK);
    for (uint8_t id = 1; id <= 4; ++id)
        CHECK(control(0xa1, 2, id, 2, 1, NULL, 0) == DART_USB_DATA && reply[0] == 10);
    CHECK(control(0x21, 10, 0x1402, 2, 0, NULL, 0) == DART_USB_ACK);
    CHECK(control(0xa1, 2, 2, 2, 1, NULL, 0) == DART_USB_DATA && reply[0] == 20);
    CHECK(control(0xa1, 2, 1, 2, 1, NULL, 0) == DART_USB_DATA && reply[0] == 10);
    CHECK(control(0x21, 10, 5, 2, 0, NULL, 0) == DART_USB_STALL);
}

static void metadata_replies(void)
{
    const dart_track_metadata track = {"Title", "Artist", "Album", 7, 180000, 12345, 1};
    uint8_t request[] = {4, 0, 0x20, 0, 0, 0, 7};
    uint8_t output[64]; size_t size;
    for (uint8_t command = 0x20; command <= 0x24; command += 2) {
        request[2] = command;
        CHECK(dart_iap_metadata_reply(&track, request, sizeof(request), 0, output, sizeof(output), &size) == 1);
        CHECK(output[0] == 4 && output[1] == 0 && output[2] == command + 1);
        const char *text = command == 0x20 ? track.title : command == 0x22 ? track.artist : track.album;
        CHECK(size == strlen(text) + 4 && strcmp((char *)output + 3, text) == 0);
    }
    request[2] = 0x1c;
    CHECK(dart_iap_metadata_reply(&track, request, 3, 0, output, sizeof(output), &size) == 1);
    const uint8_t status[] = {4, 0, 0x1d, 0, 2, 0xbf, 0x20, 0, 0, 0x30, 0x39, 1};
    CHECK(size == sizeof(status) && memcmp(output, status, size) == 0);
    request[2] = 0x1e;
    CHECK(dart_iap_metadata_reply(&track, request, 3, 0, output, sizeof(output), &size) == 1);
    CHECK(size == 7 && output[2] == 0x1f && output[6] == 7);
    request[2] = 0x20; request[6] = 8;
    CHECK(dart_iap_metadata_reply(&track, request, sizeof(request), 0, output, sizeof(output), &size) == -1 && size == 0);
    request[6] = 7; memset(output, 0xa5, sizeof(output));
    CHECK(dart_iap_metadata_reply(&track, request, sizeof(request), 0, output, 4, &size) == -1 && output[0] == 0xa5);
    request[2] = 0x29;
    CHECK(dart_iap_metadata_reply(&track, request, sizeof(request), 0, output, sizeof(output), &size) == 0);
}

static void metadata_transaction_ids(void)
{
    const dart_track_metadata track = {"\xc3\xa9 stereo", "Artist", "Album", 0, 4000, 0, 2};
    const uint8_t request[] = {4, 0, 0x20, 0x12, 0x34, 0, 0, 0, 0};
    uint8_t output[64]; size_t size;
    CHECK(dart_iap_metadata_reply(&track, request, sizeof(request), 1, output, sizeof(output), &size) == 1);
    CHECK(output[3] == 0x12 && output[4] == 0x34 && strcmp((char *)output + 5, track.title) == 0);
    CHECK(dart_iap_metadata_reply(&track, request, 7, 1, output, sizeof(output), &size) == -1);
    CHECK(dart_iap_metadata_reply(&track, request, sizeof(request), 0, output, sizeof(output), &size) == -1);
}

int main(int argc, char **argv)
{
    static const struct { const char *name; void (*run)(void); } cases[] = {
        {"descriptors", descriptors}, {"lifecycle", lifecycle},
        {"invalid_requests", invalid_requests}, {"sample_rates", sample_rates},
        {"audio_seconds", audio_seconds}, {"audio_buffering", audio_buffering},
        {"iap_known_vector", iap_known_vector}, {"iap_roundtrip", iap_roundtrip},
        {"iap_malformed", iap_malformed}, {"iap_fragment_restart", iap_fragment_restart},
        {"hid_idle", hid_idle}, {"metadata_replies", metadata_replies},
        {"metadata_transaction_ids", metadata_transaction_ids}
    };
    if (argc != 2) return 2;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        if (!strcmp(argv[1], cases[i].name)) { cases[i].run(); puts(cases[i].name); return 0; }
    }
    return 2;
}
