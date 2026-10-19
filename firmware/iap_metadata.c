#include "iap_metadata.h"

static uint32_t be32(const uint8_t *data)
{
    return ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16) |
           ((uint32_t)data[2] << 8) | data[3];
}

static void put32(uint8_t *output, uint32_t value)
{
    for (size_t i = 0; i < 4; ++i) output[i] = (uint8_t)(value >> (24 - i * 8));
}

int dart_iap_metadata_reply(const dart_track_metadata *track,
                            const uint8_t *request, size_t request_length,
                            int transaction_ids_active, uint8_t *reply,
                            size_t capacity, size_t *reply_length)
{
    if (reply_length) *reply_length = 0;
    if (!track || !request || !reply_length || !reply) return -1;
    if (!request_length || request[0] != 4) return 0;
    if (request_length < 3) return -1;
    uint16_t command = (uint16_t)(((uint16_t)request[1] << 8) | request[2]);
    const char *text = command == 0x20 ? track->title : command == 0x22 ? track->artist :
                       command == 0x24 ? track->album : (const char *)0;
    if (command != 0x1c && command != 0x1e && command != 0x20 && command != 0x22 && command != 0x24)
        return 0;
    size_t header = transaction_ids_active ? 5 : 3;
    int indexed = command == 0x20 || command == 0x22 || command == 0x24;
    if (request_length != header + (indexed ? 4u : 0u)) return -1;
    if (indexed && (be32(request + header) != track->track_index || !text)) return -1;
    size_t body = command == 0x1c ? 9 : command == 0x1e ? 4 : 0;
    if (indexed) {
        while (body < DART_IAP_MAX_PAYLOAD - header && text[body]) body++;
        if (body == DART_IAP_MAX_PAYLOAD - header) return -1;
        body++; /* UTF-8 terminator is part of the iAP payload */
    }
    if (header + body > capacity) return -1;
    reply[0] = 4; reply[1] = 0; reply[2] = (uint8_t)(command + 1);
    if (transaction_ids_active) { reply[3] = request[3]; reply[4] = request[4]; }
    if (indexed) {
        for (size_t i = 0; i < body; ++i) reply[header + i] = (uint8_t)text[i];
    } else if (command == 0x1e) {
        put32(reply + header, track->track_index);
    } else {
        put32(reply + header, track->duration_ms);
        put32(reply + header + 4, track->position_ms);
        reply[header + 8] = track->playback_status;
    }
    *reply_length = header + body;
    return 1;
}
