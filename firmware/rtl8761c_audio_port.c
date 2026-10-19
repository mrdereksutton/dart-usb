#include "rtl8761c_audio_port.h"

enum { SLOT_FREE, SLOT_PREPARED, SLOT_QUEUED };

static int matching_profile(const dart_rtl_endpoint *ep)
{
    if (!ep || !ep->name || !ep->ops || !ep->ops->enable || !ep->ops->disable ||
        !ep->ops->queue || !ep->ops->dequeue) return 0;
    const char expected[] = "ep3in";
    for (size_t i = 0; i < sizeof(expected); ++i)
        if (ep->name[i] != expected[i]) return 0;
#if UINTPTR_MAX == UINT32_MAX
    if ((uintptr_t)ep != 0x0030cc08 || (uintptr_t)ep->ops != 0x0030cf58 ||
        (uintptr_t)ep->ops->enable != 0x020bd30d ||
        (uintptr_t)ep->ops->disable != 0x020bd3b3 ||
        (uintptr_t)ep->ops->queue != 0x0020c7b1 ||
        (uintptr_t)ep->ops->dequeue != 0x020bd493) return 0;
#endif
    return 1;
}

static void completed(dart_rtl_endpoint *endpoint, dart_rtl_request *request)
{
    dart_rtl_audio_slot *slot = request->context;
    dart_rtl_audio_port *port = slot->owner;
    if (endpoint != port->endpoint || slot->state != SLOT_QUEUED) {
        port->last_error = -22;
        port->faulted = 1;
        return;
    }
    if (!port->stopping) {
        if (request->status || request->actual != request->length) {
            port->last_error = request->status ? request->status : -5;
            port->faulted = 1;
            port->transfer_failures++;
        } else port->completed_packets++;
    }
    slot->state = SLOT_FREE;
}

int dart_rtl_audio_init(dart_rtl_audio_port *port, dart_usb_bridge *bridge,
                        dart_rtl_endpoint *endpoint,
                        uint32_t (*map_dma)(void *, const uint8_t *, size_t), void *context)
{
    if (!port || !bridge || !matching_profile(endpoint) || !map_dma ||
        endpoint->descriptor || endpoint->max_packet < DART_USB_AUDIO_MAX_PACKET) return -22;
    port->bridge = bridge; port->endpoint = endpoint;
    port->map_dma = map_dma; port->dma_context = context;
    port->original_descriptor = endpoint->descriptor;
    port->original_max_packet = endpoint->max_packet;
    port->enabled = port->enable_attempted = port->stopping = port->disable_complete = port->faulted = 0;
    port->last_error = 0;
    port->queued_packets = port->completed_packets = port->queue_failures = port->transfer_failures = 0;
    port->discarded_packets = 0;
    for (size_t i = 0; i < 2; ++i) {
        dart_rtl_audio_slot *slot = &port->slots[i];
        slot->owner = port; slot->state = SLOT_FREE; slot->cancellation_requested = 0;
        slot->request.buffer = slot->packet;
        slot->request.length = 0; slot->request.dma_address = UINT32_MAX;
        slot->request.complete = completed; slot->request.context = slot;
        slot->request.next = slot->request.previous = &slot->request.next;
        slot->request.status = 0; slot->request.actual = slot->request.reserved = 0;
        slot->request.flags = 0;
        for (size_t j = 0; j < 3; ++j) slot->request.padding[j] = 0;
    }
    const uint8_t descriptor[] = {9, 5, 0x83, 1, 192, 0, 1, 0, 0};
    for (size_t i = 0; i < sizeof(descriptor); ++i) port->descriptor[i] = descriptor[i];
    return 0;
}

int dart_rtl_audio_start(dart_rtl_audio_port *port)
{
    if (!port || !port->bridge || port->enabled || port->enable_attempted || port->stopping ||
        port->bridge->configuration != DART_USB_CONFIGURATION || !port->bridge->alternate ||
        !matching_profile(port->endpoint) || port->endpoint->descriptor != port->original_descriptor ||
        port->endpoint->max_packet != port->original_max_packet) return -22;
    port->faulted = 0; port->last_error = 0; port->disable_complete = 0;
    port->endpoint->descriptor = port->descriptor;
    port->enable_attempted = 1;
    int result = port->endpoint->ops->enable(port->endpoint, port->descriptor);
    if (!result && port->endpoint->max_packet != DART_USB_AUDIO_MAX_PACKET) result = -22;
    if (result) {
        port->faulted = 1; port->last_error = result;
        return result; /* stop must clean up any partial native enable */
    }
    port->enabled = 1;
    return 0;
}

int dart_rtl_audio_service(dart_rtl_audio_port *port)
{
    if (!port || !port->enabled || port->stopping) return -22;
    if (port->faulted) return port->last_error ? port->last_error : -5;
    if (!port->bridge->configuration || !port->bridge->alternate ||
        port->endpoint->descriptor != port->descriptor ||
        port->endpoint->max_packet != DART_USB_AUDIO_MAX_PACKET) {
        port->faulted = 1; port->last_error = -22; return -22;
    }
    dart_rtl_audio_slot *slot = (dart_rtl_audio_slot *)0;
    for (size_t i = 0; i < 2; ++i)
        if (port->slots[i].state == SLOT_FREE) { slot = &port->slots[i]; break; }
    if (!slot) return 0;
    uint32_t dma = port->map_dma(port->dma_context, slot->packet, sizeof(slot->packet));
    if (dma == UINT32_MAX || (dma & 3)) {
        port->faulted = 1; port->last_error = -22; return -22;
    }
    size_t length = dart_usb_audio_packet(port->bridge, slot->packet, sizeof(slot->packet));
    if (!length) { port->faulted = 1; port->last_error = -22; return -22; }
    slot->state = SLOT_PREPARED;
    slot->request.length = (uint32_t)length;
    slot->request.dma_address = dma;
    slot->request.actual = 0; slot->request.status = -115;
    slot->cancellation_requested = 0;
    slot->state = SLOT_QUEUED; /* completion may run before queue returns */
    int result = port->endpoint->ops->queue(port->endpoint, &slot->request);
    if (result) {
        if (slot->state == SLOT_QUEUED) slot->state = SLOT_PREPARED;
        port->queue_failures++; port->faulted = 1; port->last_error = result;
        return result;
    }
    port->queued_packets++;
    return 1;
}

int dart_rtl_audio_stop(dart_rtl_audio_port *port)
{
    if (!port || !port->bridge) return -22;
    port->stopping = 1;
    for (size_t i = 0; i < 2; ++i) {
        dart_rtl_audio_slot *slot = &port->slots[i];
        if (slot->state == SLOT_QUEUED && !slot->cancellation_requested) {
            slot->cancellation_requested = 1;
            int result = port->endpoint->ops->dequeue(port->endpoint, &slot->request);
            if (result) port->last_error = result;
        }
    }
    if (port->enable_attempted && !port->disable_complete) {
        int result = port->endpoint->ops->disable(port->endpoint);
        if (result) { port->last_error = result; return result; }
        port->disable_complete = 1; port->enabled = 0;
    }
    for (size_t i = 0; i < 2; ++i)
        if (port->slots[i].state == SLOT_QUEUED) return 1;
    for (size_t i = 0; i < 2; ++i) {
        if (port->slots[i].state == SLOT_PREPARED) port->discarded_packets++;
        port->slots[i].state = SLOT_FREE;
    }
    port->endpoint->descriptor = port->original_descriptor;
    port->endpoint->max_packet = port->original_max_packet;
    port->enable_attempted = port->stopping = 0;
    return 0;
}
