#include "iap_hid.h"

static const uint8_t in_sizes[] = {12, 14, 20, 63};
static const uint8_t out_sizes[] = {8, 10, 14, 20, 63};

void dart_iap_init(dart_iap_hid *link)
{
    if (!link) return;
    link->rx_used = link->rx_expected = link->rx_header = link->rx_payload = 0;
    link->tx_length = link->tx_offset = 0;
    link->rx_id = link->rx_active = link->rx_ready = 0;
    link->tx_id = link->tx_data_size = 0;
}

size_t dart_iap_report_descriptor(uint8_t *output, size_t capacity)
{
    static const uint8_t prefix[] = {
        0x06, 0x00, 0xff, /* vendor usage page */
        0x09, 0x01, 0xa1, 0x01, /* application collection */
        0x75, 0x08, 0x15, 0x00, 0x26, 0xff, 0x00
    };
    if (!output || capacity < DART_IAP_REPORT_DESCRIPTOR_SIZE) return 0;
    size_t n = 0;
    for (size_t i = 0; i < sizeof(prefix); ++i) output[n++] = prefix[i];
    for (uint8_t id = 1; id <= 9; ++id) {
        output[n++] = 0x85; output[n++] = id;
        output[n++] = 0x95;
        output[n++] = id <= 4 ? in_sizes[id - 1] : out_sizes[id - 5];
        output[n++] = 0x09; output[n++] = 1;
        output[n++] = id <= 4 ? 0x82 : 0x92;
        output[n++] = 0x02; output[n++] = 0x01; /* variable buffered bytes */
    }
    output[n++] = 0xc0;
    return n;
}

size_t dart_iap_out_report_size(uint8_t id)
{
    return id >= 5 && id <= 9 ? (size_t)out_sizes[id - 5] + 1 : 0;
}

static int reject_rx(dart_iap_hid *link)
{
    link->rx_used = link->rx_expected = link->rx_header = link->rx_payload = 0;
    link->rx_id = link->rx_active = 0;
    return -1;
}

int dart_iap_receive(dart_iap_hid *link, const uint8_t *report, size_t length)
{
    if (!link || link->rx_ready) return -1;
    if (!report || length < 3 || length != dart_iap_out_report_size(report[0]))
        return reject_rx(link);
    uint8_t control = report[1];
    size_t chunk = length - 2;
    if (control == 0 || control == 2) {
        reject_rx(link);
        if (report[2] != 0x55) return -1;
        size_t header = report[3] ? 2 : 4;
        size_t payload = report[3] ? report[3] :
                         ((size_t)report[4] << 8) | report[5];
        if (!payload || payload > DART_IAP_MAX_PAYLOAD) return -1;
        size_t expected = header + payload + 1;
        if ((control == 0 && expected > chunk) ||
            (control == 2 && expected <= chunk)) return -1;
        link->rx_header = (uint16_t)header;
        link->rx_payload = (uint16_t)payload;
        link->rx_expected = (uint16_t)expected;
        link->rx_id = report[0];
        link->rx_active = 1;
    } else if (control == 1 || control == 3) {
        if (!link->rx_active || link->rx_id != report[0]) return reject_rx(link);
        size_t remaining = link->rx_expected - link->rx_used;
        if ((control == 1 && remaining > chunk) ||
            (control == 3 && remaining <= chunk)) return reject_rx(link);
    } else {
        return reject_rx(link);
    }
    size_t remaining = link->rx_expected - link->rx_used;
    if (chunk > remaining) chunk = remaining; /* final report padding */
    for (size_t i = 0; i < chunk; ++i) link->rx[link->rx_used++] = report[i + 2];
    if (control == 2 || control == 3) return 0;
    uint8_t sum = 0;
    for (size_t i = 1; i < link->rx_expected; ++i) sum = (uint8_t)(sum + link->rx[i]);
    if (sum || link->rx_used != link->rx_expected) return reject_rx(link);
    link->rx_active = 0;
    link->rx_ready = 1;
    return 1;
}

size_t dart_iap_take_payload(dart_iap_hid *link, uint8_t *output, size_t capacity)
{
    if (!link || !link->rx_ready || !output || capacity < link->rx_payload) return 0;
    size_t length = link->rx_payload;
    for (size_t i = 0; i < length; ++i) output[i] = link->rx[link->rx_header + i];
    link->rx_ready = 0;
    reject_rx(link);
    return length;
}

int dart_iap_queue_payload(dart_iap_hid *link, const uint8_t *payload, size_t length)
{
    if (!link || link->tx_length || !payload || !length || length > DART_IAP_MAX_PAYLOAD)
        return 0;
    size_t n = 0;
    link->tx[n++] = 0x55;
    if (length <= 255) {
        link->tx[n++] = (uint8_t)length;
    } else {
        link->tx[n++] = 0;
        link->tx[n++] = (uint8_t)(length >> 8);
        link->tx[n++] = (uint8_t)length;
    }
    uint8_t sum = 0;
    for (size_t i = 1; i < n; ++i) sum = (uint8_t)(sum + link->tx[i]);
    for (size_t i = 0; i < length; ++i) {
        link->tx[n++] = payload[i];
        sum = (uint8_t)(sum + payload[i]);
    }
    link->tx[n++] = (uint8_t)(0u - sum);
    link->tx_length = (uint16_t)n;
    link->tx_offset = 0;
    link->tx_id = 4;
    for (size_t i = 0; i < sizeof(in_sizes); ++i) {
        if (n + 1 <= in_sizes[i]) { link->tx_id = (uint8_t)(i + 1); break; }
    }
    link->tx_data_size = in_sizes[link->tx_id - 1];
    return 1;
}

size_t dart_iap_peek_report(const dart_iap_hid *link, uint8_t *output, size_t capacity)
{
    if (!link || !link->tx_length || !output || capacity < (size_t)link->tx_data_size + 1)
        return 0;
    size_t chunk = link->tx_length - link->tx_offset;
    size_t room = link->tx_data_size - 1;
    if (chunk > room) chunk = room;
    output[0] = link->tx_id;
    output[1] = link->tx_offset ?
                (link->tx_offset + chunk == link->tx_length ? 1 : 3) :
                (chunk == link->tx_length ? 0 : 2);
    for (size_t i = 0; i < room; ++i)
        output[i + 2] = i < chunk ? link->tx[link->tx_offset + i] : 0;
    return (size_t)link->tx_data_size + 1;
}

void dart_iap_report_sent(dart_iap_hid *link)
{
    if (!link || !link->tx_length) return;
    size_t room = link->tx_data_size - 1;
    size_t remaining = link->tx_length - link->tx_offset;
    if (remaining <= room) link->tx_length = link->tx_offset = 0;
    else link->tx_offset += (uint16_t)room;
}
