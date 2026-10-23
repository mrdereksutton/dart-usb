/* Host-only demonstration of the same portable C firmware, with no USB backend. */
#include "usb_bridge.h"
#include "iap_metadata.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static dart_usb_bridge bridge;
static uint8_t reply[256];
static size_t reply_size;

static void fail(const char *message)
{
    fprintf(stderr, "Offline demo: %s\n", message);
    exit(1);
}

static void hex(const uint8_t *data, size_t length)
{
    for (size_t i = 0; i < length; ++i) printf("%02x", data[i]);
}

static FILE *output_file(const char *directory, const char *name)
{
    char path[4096];
    int length = snprintf(path, sizeof(path), "%s/%s", directory, name);
    if (length < 0 || (size_t)length >= sizeof(path)) fail("output path is too long");
    FILE *f = fopen(path, "wb");
    if (!f) fail("could not create output file");
    return f;
}

static void write_bytes(FILE *file, const uint8_t *data, size_t length)
{
    if (fwrite(data, 1, length, file) != length) fail("could not write output");
}

static void save_reply(const char *directory, const char *name)
{
    FILE *f = output_file(directory, name);
    write_bytes(f, reply, reply_size);
    if (fclose(f)) fail("could not close descriptor file");
}

static void request(const char *name, uint8_t kind, uint8_t command, uint16_t value,
                     uint16_t index, uint16_t length, const uint8_t *data)
{
    const uint8_t setup[] = {kind, command, (uint8_t)value, (uint8_t)(value >> 8),
        (uint8_t)index, (uint8_t)(index >> 8), (uint8_t)length, (uint8_t)(length >> 8)};
    int result = dart_usb_control(&bridge, setup, data, kind & 0x80 ? 0 : length,
                                  reply, sizeof(reply), &reply_size);
    if (result == DART_USB_STALL) fail(name);
    printf("{\"event\":\"control\",\"name\":\"%s\",\"setup_hex\":\"", name);
    hex(setup, sizeof(setup));
    printf("\",\"out_hex\":\""); if (!(kind & 0x80) && data) hex(data, length);
    printf("\",\"result\":%d,\"reply_hex\":\"", result); hex(reply, reply_size); puts("\"}");
}

static void audio_demo(const char *directory, uint32_t rate, unsigned seconds)
{
    char name[64]; snprintf(name, sizeof(name), "audio-%u.usb-packets.bin", rate);
    FILE *file = output_file(directory, name);
    uint8_t frequency[] = {(uint8_t)rate, (uint8_t)(rate >> 8), (uint8_t)(rate >> 16)};
    request("Select sample rate", 0x22, 1, 0x0100, 0x83, 3, frequency);
    request("Read sample rate", 0xa2, 0x81, 0x0100, 0x83, 3, NULL);
    request("Start audio", 1, 11, 1, 1, 0, NULL);
    uint32_t produced = 0, total = 0;
    const double notes[] = {440.0, 554.365, 659.255, 880.0, 783.991, 659.255, 554.365, 440.0};
    for (uint32_t ms = 0; ms < seconds * 1000; ++ms) {
        if (ms % 5 == 0) {
            uint32_t until = (ms + 5) * rate / 1000;
            size_t frames = until - produced;
            int16_t pcm[480];
            for (size_t i = 0; i < frames; ++i) {
                uint32_t frame = produced + (uint32_t)i;
                double time = (double)frame / rate;
                size_t note = (size_t)(frame * 2 / rate) % 8;
                double local = (double)(frame % (rate / 2)) / rate;
                double envelope = fmin(1.0, fmin(local / 0.015, (0.5 - local) / 0.015));
                double phase = 6.283185307179586 * notes[note] * time;
                pcm[i * 2] = (int16_t)(4200 * envelope * (sin(phase) + 0.15 * sin(phase * 2)));
                pcm[i * 2 + 1] = (int16_t)(4200 * envelope * (sin(phase) + 0.15 * sin(phase * 3)));
            }
            if (dart_usb_push_pcm(&bridge, pcm, frames) != frames) fail("PCM producer lost frames");
            produced = until;
        }
        uint8_t packet[192];
        size_t length = dart_usb_audio_packet(&bridge, packet, sizeof(packet));
        if (!length) fail("active stream did not produce a packet");
        const uint8_t prefix[] = {(uint8_t)length, (uint8_t)(length >> 8)};
        write_bytes(file, prefix, 2); write_bytes(file, packet, length);
        total += (uint32_t)(length / 4);
    }
    if (fclose(file)) fail("could not close packet file");
    if (total != rate * seconds || bridge.queued_frames || bridge.audio.missing_frames)
        fail("audio accounting failed");
    printf("{\"event\":\"audio\",\"sample_rate\":%u,\"seconds\":%u,"
           "\"frames\":%u,\"packets\":%u,\"missing_frames\":%u,\"rejected_frames\":%u,"
           "\"packet_file\":\"%s\"}\n", rate, seconds, total, seconds * 1000,
           bridge.audio.missing_frames, bridge.rejected_frames, name);
    request("Stop audio", 1, 11, 0, 1, 0, NULL);
}

static void metadata_demo(unsigned seconds)
{
    const dart_track_metadata track = {
        "Dart USB - offline stereo receiver demo with a complete title longer than one HID packet",
        "Dart USB", "Receiver firmware development", 0, seconds * 1000, 0, 1
    };
    /* Legacy Extended Interface title query; IDPS negotiation is outside this demo. */
    const uint8_t host_report[15] = {7, 0, 0x55, 7, 4, 0, 0x20, 0, 0, 0, 0, 0xd5, 0, 0, 0};
    request("Get track title over HID", 0x21, 9, 0x0207, 2, sizeof(host_report), host_report);
    uint8_t command[32], response[DART_IAP_MAX_PAYLOAD];
    size_t command_size = dart_iap_take_payload(&bridge.iap, command, sizeof(command));
    size_t response_size;
    if (dart_iap_metadata_reply(&track, command, command_size, 0, response,
                                sizeof(response), &response_size) != 1)
        fail("metadata reply was not produced");
    if (!dart_iap_queue_payload(&bridge.iap, response, response_size)) fail("metadata TX was busy");
    printf("{\"event\":\"metadata\",\"payload_hex\":\""); hex(response, response_size);
    printf("\",\"reports_hex\":[");
    unsigned count = 0;
    while (bridge.iap.tx_length) {
        uint8_t report[64]; size_t length = dart_iap_peek_report(&bridge.iap, report, sizeof(report));
        if (!length) fail("metadata report was empty");
        if (count++) putchar(',');
        putchar('"'); hex(report, length); putchar('"');
        dart_iap_report_sent(&bridge.iap);
    }
    printf("],\"report_count\":%u}\n", count);
}

int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    char *end; unsigned long seconds = strtoul(argv[2], &end, 10);
    if (*end || seconds < 1 || seconds > 30) return 2;
    dart_usb_init(&bridge);
    printf("{\"event\":\"build\",\"bridge_state_bytes\":%zu,\"hardware_access\":false}\n", sizeof(bridge));
    request("Device header", 0x80, 6, 0x0100, 0, 8, NULL);
    request("Device descriptor", 0x80, 6, 0x0100, 0, 18, NULL); save_reply(argv[1], "device.bin");
    request("Set address", 0, 5, 7, 0, 0, NULL);
    request("Configuration header", 0x80, 6, 0x0200, 0, 9, NULL);
    request("Configuration descriptor", 0x80, 6, 0x0200, 0, 255, NULL); save_reply(argv[1], "configuration.bin");
    request("Select audio and HID configuration", 0, 9, 2, 0, 0, NULL);
    request("HID report descriptor", 0x81, 6, 0x2200, 2, 255, NULL); save_reply(argv[1], "hid-report.bin");
    audio_demo(argv[1], 44100, (unsigned)seconds);
    audio_demo(argv[1], 48000, (unsigned)seconds);
    metadata_demo((unsigned)seconds);
    return 0;
}
