#ifndef DART_RTL8761C_AUDIO_PORT_H
#define DART_RTL8761C_AUDIO_PORT_H

#include "usb_bridge.h"

typedef struct dart_rtl_endpoint dart_rtl_endpoint;
typedef struct dart_rtl_request dart_rtl_request;

/* Layout reconstructed from the saved CU code, not the related 87x3E HAL.
 * The on-device ABI has 32-bit pointers and a 44-byte request. Host tests use
 * native pointers; the ARM replay checks the actual 32-bit layout separately. */
struct dart_rtl_request {
    uint8_t *buffer;
    uint32_t length, dma_address;
    void (*complete)(dart_rtl_endpoint *, dart_rtl_request *);
    void *context;
    void *next, *previous;
    int32_t status;
    uint32_t actual, reserved;
    uint8_t flags, padding[3];
};

typedef struct {
    int (*enable)(dart_rtl_endpoint *, const uint8_t *descriptor);
    int (*disable)(dart_rtl_endpoint *);
    void *allocate_request, *free_request, *allocate_buffer, *free_buffer;
    int (*queue)(dart_rtl_endpoint *, dart_rtl_request *);
    int (*dequeue)(dart_rtl_endpoint *, dart_rtl_request *);
    void *set_halt;
} dart_rtl_endpoint_ops;

struct dart_rtl_endpoint {
    void *driver_data;
    const char *name;
    const dart_rtl_endpoint_ops *ops;
    void *next, *previous;
    const uint8_t *descriptor;
    uint32_t max_packet;
};

#if UINTPTR_MAX == UINT32_MAX
_Static_assert(sizeof(dart_rtl_request) == 44, "CU request size");
_Static_assert(offsetof(dart_rtl_request, complete) == 0x0c, "CU completion offset");
_Static_assert(offsetof(dart_rtl_request, context) == 0x10, "CU context offset");
_Static_assert(offsetof(dart_rtl_request, status) == 0x1c, "CU status offset");
_Static_assert(offsetof(dart_rtl_request, actual) == 0x20, "CU actual offset");
_Static_assert(offsetof(dart_rtl_request, flags) == 0x28, "CU flags offset");
_Static_assert(offsetof(dart_rtl_endpoint, descriptor) == 0x14, "CU descriptor offset");
_Static_assert(offsetof(dart_rtl_endpoint_ops, queue) == 0x18, "CU queue slot");
#endif

typedef struct dart_rtl_audio_port dart_rtl_audio_port;
typedef struct {
    dart_rtl_request request;
    _Alignas(4) uint8_t packet[DART_USB_AUDIO_MAX_PACKET];
    dart_rtl_audio_port *owner;
    uint8_t state, cancellation_requested;
} dart_rtl_audio_slot;

struct dart_rtl_audio_port {
    dart_usb_bridge *bridge;
    dart_rtl_endpoint *endpoint;
    uint32_t (*map_dma)(void *context, const uint8_t *buffer, size_t capacity);
    void *dma_context;
    const uint8_t *original_descriptor;
    uint32_t original_max_packet;
    dart_rtl_audio_slot slots[2];
    uint8_t descriptor[9];
    uint8_t enabled, enable_attempted, stopping, disable_complete, faulted;
    int last_error;
    uint32_t queued_packets, completed_packets, queue_failures, transfer_failures;
    uint32_t discarded_packets;
};

/* Initialize only fresh/stopped storage and an idle ep3in. No operation is called
 * here. On ARM the endpoint/vtable/function addresses must match the pinned CU
 * profile. map_dma is required: CPU/DMA address equivalence is never assumed. */
int dart_rtl_audio_init(dart_rtl_audio_port *port, dart_usb_bridge *bridge,
                        dart_rtl_endpoint *endpoint,
                        uint32_t (*map_dma)(void *, const uint8_t *, size_t), void *context);
int dart_rtl_audio_start(dart_rtl_audio_port *port);

/* One service opportunity per millisecond. Returns 1 queued, 0 if both owned
 * buffers are busy, or a negative error. A rejected packet is retained; further
 * submissions stop until stop/start. Calls and completion callbacks must be
 * serialized by the native port's interrupt/critical-section policy. */
int dart_rtl_audio_service(dart_rtl_audio_port *port);

/* Stop before reset/rate/alternate/configuration changes. Returns 0 only once
 * disable succeeds and every in-flight request completes/cancels, 1 while waiting,
 * or a native error. Keep this object/buffers alive until it returns 0. */
int dart_rtl_audio_stop(dart_rtl_audio_port *port);

#endif
