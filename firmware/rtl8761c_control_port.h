#ifndef DART_RTL8761C_CONTROL_PORT_H
#define DART_RTL8761C_CONTROL_PORT_H

#include "rtl8761c_audio_port.h"

#define DART_RTL_DELAYED_STATUS 1255
#define DART_RTL_CONTROL_CAPACITY 128

typedef struct {
    void *ops;
    dart_rtl_endpoint *ep0;
    void *reserved[13];
    void *driver_data;
} dart_rtl_gadget;

typedef int (*dart_rtl_setup_fn)(dart_rtl_gadget *, const uint8_t *);
typedef void (*dart_rtl_disconnect_fn)(dart_rtl_gadget *);

enum dart_rtl_control_state {
    DART_RTL_CONTROL_IDLE, DART_RTL_CONTROL_DRAIN, DART_RTL_CONTROL_READY,
    DART_RTL_CONTROL_IN, DART_RTL_CONTROL_OUT, DART_RTL_CONTROL_APPLY,
    DART_RTL_CONTROL_STATUS, DART_RTL_CONTROL_FAULT
};

typedef struct {
    dart_rtl_audio_port *audio;
    dart_rtl_gadget *gadget;
    dart_rtl_setup_fn *setup_slot, original_setup;
    dart_rtl_disconnect_fn *disconnect_slot, original_disconnect;
    const uint8_t *original_descriptor;
    dart_rtl_request request;
    _Alignas(4) uint8_t data[DART_RTL_CONTROL_CAPACITY];
    uint8_t setup[8], descriptor[7];
    uint8_t state, bound, in_flight, cancel_requested, resetting, closing, stalled, reconcile_audio;
    int last_error;
    uint32_t setup_count, completed_count, cancelled_count, reset_count;
} dart_rtl_control_port;

#if UINTPTR_MAX == UINT32_MAX
_Static_assert(offsetof(dart_rtl_gadget, ep0) == 4, "CU gadget EP0 offset");
_Static_assert(offsetof(dart_rtl_gadget, driver_data) == 0x3c, "CU gadget data offset");
#endif

/* Target-side APIs; no host USB code. Initialize fresh/stopped storage, with
 * an initialized audio adapter and unconfigured native composite. Bind verifies
 * the pinned gadget/callbacks, then owns EP0's descriptor and setup/disconnect
 * slots until unbind completes. One bound instance is supported. */
int dart_rtl_control_init(dart_rtl_control_port *, dart_rtl_audio_port *, dart_rtl_gadget *,
                          dart_rtl_setup_fn *, dart_rtl_disconnect_fn *);
int dart_rtl_control_bind(dart_rtl_control_port *);

/* Service from the serialized native task after completions, and before audio
 * service. It drains old audio, processes received OUT data, and queues delayed
 * status. Never service recursively from a native completion callback. */
int dart_rtl_control_service(dart_rtl_control_port *);
/* Combined one-millisecond task entry. It services controls even while audio is
 * idle, and queues audio only after a format/alternate change's status completes.
 * Use this entry instead of calling the audio adapter directly when bound. */
int dart_rtl_control_tick(dart_rtl_control_port *);
int dart_rtl_control_unbind(dart_rtl_control_port *);

#endif
