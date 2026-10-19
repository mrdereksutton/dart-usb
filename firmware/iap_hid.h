#ifndef DART_IAP_HID_H
#define DART_IAP_HID_H

#include <stddef.h>
#include <stdint.h>

#define DART_IAP_MAX_PAYLOAD 1024
#define DART_IAP_FRAME_CAPACITY (DART_IAP_MAX_PAYLOAD + 5)
#define DART_IAP_REPORT_DESCRIPTOR_SIZE 96

/* Allocation-free iAP framing. The application owns lingo commands and session
 * transaction IDs; payloads are opaque to this transport. Serialize all calls. */
typedef struct {
    uint8_t rx[DART_IAP_FRAME_CAPACITY];
    uint8_t tx[DART_IAP_FRAME_CAPACITY];
    uint16_t rx_used, rx_expected, rx_header, rx_payload;
    uint16_t tx_length, tx_offset;
    uint8_t rx_id, rx_active, rx_ready, tx_id, tx_data_size;
} dart_iap_hid;

void dart_iap_init(dart_iap_hid *link);
size_t dart_iap_report_descriptor(uint8_t *output, size_t capacity);
size_t dart_iap_out_report_size(uint8_t id);

/* Accept one full host SET_REPORT, including report ID. Returns 1 for a complete
 * checked frame, 0 for a fragment, -1 for malformed input or an unread frame.
 * A new SINGLE/FIRST flushes an incomplete frame, but never an unread one. */
int dart_iap_receive(dart_iap_hid *link, const uint8_t *report, size_t length);
/* A short destination leaves the complete received payload available. */
size_t dart_iap_take_payload(dart_iap_hid *link, uint8_t *output, size_t capacity);

/* Queue a complete device-to-host payload; returns 0 while a prior TX is busy.
 * Peek is repeatable and consumes nothing. Call report_sent only after that
 * report completes successfully. On disconnect, cancel DMA before reinitializing
 * this state. Never interleave fragments from separate payloads. */
int dart_iap_queue_payload(dart_iap_hid *link, const uint8_t *payload, size_t length);
size_t dart_iap_peek_report(const dart_iap_hid *link, uint8_t *output, size_t capacity);
void dart_iap_report_sent(dart_iap_hid *link);

#endif
