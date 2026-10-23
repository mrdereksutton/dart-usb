#ifndef DART_IAP_METADATA_H
#define DART_IAP_METADATA_H

#include "iap_hid.h"

typedef struct {
    const char *title, *artist, *album; /* stable, NUL-terminated UTF-8 */
    uint32_t track_index, duration_ms, position_ms;
    uint8_t playback_status; /* iAP: 0 stopped, 1 playing, 2 paused */
} dart_track_metadata;

/* Extended Interface read replies: status, track index, title, artist and album.
 * Returns 1 for a reply, 0 for another command/lingo, -1 for bad arguments.
 * The session owner supplies whether transaction IDs are active; replies echo
 * the request ID. IDPS, authentication, playback/AVRCP actions and notifications
 * belong to the session/application layer, not to this function. */
int dart_iap_metadata_reply(const dart_track_metadata *track,
                            const uint8_t *request, size_t request_length,
                            int transaction_ids_active, uint8_t *reply,
                            size_t capacity, size_t *reply_length);

#endif
