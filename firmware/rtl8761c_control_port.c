#include "rtl8761c_control_port.h"

static dart_rtl_control_port *active;
static int setup_callback(dart_rtl_gadget *, const uint8_t *);
static void disconnect_callback(dart_rtl_gadget *);

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }

static int profile(dart_rtl_control_port *p)
{
    if (!p || !p->audio || !p->audio->bridge || !p->audio->map_dma || !p->gadget || !p->gadget->ep0 ||
        !p->setup_slot || !p->disconnect_slot) return 0;
    const dart_rtl_endpoint *ep = p->gadget->ep0;
    if (!ep->ops || !ep->ops->queue || !ep->ops->dequeue || !ep->ops->set_halt ||
        ep->max_packet != 64) return 0;
#if UINTPTR_MAX == UINT32_MAX
    if ((uintptr_t)p->gadget != 0x0030cb6c || (uintptr_t)ep != 0x0030cbb4 ||
        (uintptr_t)ep->ops != 0x0030cf58 ||
        (uintptr_t)ep->ops->queue != 0x0020c7b1 ||
        (uintptr_t)ep->ops->dequeue != 0x020bd493 ||
        (uintptr_t)ep->ops->set_halt != 0x020bd4dd ||
        (uintptr_t)p->setup_slot != 0x0030d164 ||
        (uintptr_t)p->disconnect_slot != 0x0030d168) return 0;
#endif
    return 1;
}

static int fail(dart_rtl_control_port *p, int error)
{
    p->last_error = error ? error : -5;
    p->state = DART_RTL_CONTROL_FAULT;
    return p->last_error;
}

static void complete(dart_rtl_endpoint *endpoint, dart_rtl_request *request)
{
    dart_rtl_control_port *p = request->context;
    if (endpoint != p->gadget->ep0 || request != &p->request || !p->in_flight) {
        fail(p, -22); return;
    }
    p->in_flight = 0;
    if (p->resetting || p->closing || request->status == -108 || request->status == -104) {
        p->cancelled_count++; p->state = DART_RTL_CONTROL_IDLE; return;
    }
    if (request->status || request->actual != request->length) {
        fail(p, request->status ? request->status : -5); return;
    }
    p->completed_count++;
    p->state = p->state == DART_RTL_CONTROL_OUT ? DART_RTL_CONTROL_APPLY : DART_RTL_CONTROL_IDLE;
}

int dart_rtl_control_init(dart_rtl_control_port *p, dart_rtl_audio_port *audio,
                          dart_rtl_gadget *gadget, dart_rtl_setup_fn *setup,
                          dart_rtl_disconnect_fn *disconnect)
{
    if (!p) return -22;
    p->audio = audio; p->gadget = gadget; p->setup_slot = setup; p->disconnect_slot = disconnect;
    if (!profile(p)) return -22;
    p->state = DART_RTL_CONTROL_IDLE;
    p->bound = p->in_flight = p->cancel_requested = p->resetting = p->closing = p->stalled = p->reconcile_audio = 0;
    p->last_error = 0;
    p->setup_count = p->completed_count = p->cancelled_count = p->reset_count = 0;
    p->request.buffer = p->data; p->request.length = 0; p->request.dma_address = UINT32_MAX;
    p->request.complete = complete; p->request.context = p;
    p->request.next = p->request.previous = &p->request.next;
    p->request.status = 0; p->request.actual = p->request.reserved = 0; p->request.flags = 0;
    for (size_t i = 0; i < 3; ++i) p->request.padding[i] = 0;
    const uint8_t descriptor[] = {7, 5, 0, 0, 64, 0, 0};
    for (size_t i = 0; i < sizeof(descriptor); ++i) p->descriptor[i] = descriptor[i];
    return 0;
}

int dart_rtl_control_bind(dart_rtl_control_port *p)
{
    if (!profile(p) || active || p->bound || p->audio->bridge->configuration ||
        p->audio->enable_attempted || p->gadget->ep0->descriptor) return -22;
#if UINTPTR_MAX == UINT32_MAX
    if ((uintptr_t)*p->setup_slot != 0x020be8a1 ||
        (uintptr_t)*p->disconnect_slot != 0x020be7e3 ||
        (uintptr_t)p->gadget->driver_data != 0x0030d180 ||
        ((void **)p->gadget->driver_data)[2]) return -22;
#endif
    p->original_setup = *p->setup_slot;
    p->original_disconnect = *p->disconnect_slot;
    p->original_descriptor = p->gadget->ep0->descriptor;
    active = p; p->bound = 1;
    p->gadget->ep0->descriptor = p->descriptor;
    *p->setup_slot = setup_callback; *p->disconnect_slot = disconnect_callback;
    return 0;
}

static int queue(dart_rtl_control_port *p, size_t length, uint8_t state)
{
    uint32_t dma = p->audio->map_dma(p->audio->dma_context, p->data, sizeof(p->data));
    if (dma == UINT32_MAX || (dma & 3)) return fail(p, -22);
    p->request.length = (uint32_t)length; p->request.dma_address = dma;
    p->request.actual = 0; p->request.status = -115;
    p->request.flags = state == DART_RTL_CONTROL_IN && length < le16(p->setup + 6) &&
                       length % 64 == 0 ? 2 : 0;
    p->state = state; p->in_flight = 1; p->cancel_requested = 0;
    int result = p->gadget->ep0->ops->queue(p->gadget->ep0, &p->request);
    if (result) { p->in_flight = 0; return fail(p, result); }
    return 0;
}

static int process(dart_rtl_control_port *p, int received)
{
    size_t length;
    int result = dart_usb_control(p->audio->bridge, p->setup,
                                  received ? p->data : (const uint8_t *)0,
                                  received ? p->request.actual : 0,
                                  p->data, sizeof(p->data), &length);
    if (result < 0) return fail(p, -22);
    if (p->reconcile_audio && p->audio->bridge->alternate && !p->audio->enabled) {
        int started = dart_rtl_audio_start(p->audio);
        if (started) {
            const uint8_t idle[] = {1, 11, 0, 0, 1, 0, 0, 0};
            (void)dart_usb_control(p->audio->bridge, idle, 0, 0, p->data, sizeof(p->data), &length);
            return fail(p, started);
        }
    }
    return queue(p, result == DART_USB_DATA ? length : 0,
                  result == DART_USB_DATA ? DART_RTL_CONTROL_IN : DART_RTL_CONTROL_STATUS);
}

static int ready(dart_rtl_control_port *p)
{
    if (!(p->setup[0] & 0x80) && le16(p->setup + 6))
        return queue(p, le16(p->setup + 6), DART_RTL_CONTROL_OUT);
    return process(p, 0);
}

static int setup_callback(dart_rtl_gadget *gadget, const uint8_t *setup)
{
    dart_rtl_control_port *p = active;
    if (!p || gadget != p->gadget || !setup || p->resetting || p->closing || p->in_flight ||
        !profile(p) || gadget->ep0->descriptor != p->descriptor) return -22;
    uint16_t value = le16(setup + 2), index = le16(setup + 4), length = le16(setup + 6);
    int drain = 0;
    /* SET_ADDRESS is owned by the captured lower PCD dispatcher, before this
     * callback. Never program an address or queue a second status stage here. */
    if (setup[0] == 0 && setup[1] == 5) return -95;
    if (!(setup[0] & 0x80) && length) {
        int rate = setup[0] == 0x22 && setup[1] == 1 && value == 0x0100 &&
                   index == DART_USB_AUDIO_ENDPOINT && length == 3;
        int report = setup[0] == 0x21 && setup[1] == 9 && (value >> 8) == 2 &&
                     index == DART_USB_HID_INTERFACE &&
                     dart_iap_out_report_size((uint8_t)value) == length && length <= 64;
        if (!p->audio->bridge->configuration || (!rate && !report)) return -22;
        drain = rate;
    } else if (setup[0] == 0 && setup[1] == 9 && !index && !length &&
               (value == 0 || value == DART_USB_CONFIGURATION)) drain = 1;
    else if (setup[0] == 1 && setup[1] == 11 && index == DART_USB_AUDIO_INTERFACE &&
             !length && value <= 1 && p->audio->bridge->configuration) drain = 1;
    p->reconcile_audio = (uint8_t)drain;
    for (size_t i = 0; i < 8; ++i) p->setup[i] = setup[i];
    p->setup_count++; p->stalled = 0; p->last_error = 0;
    p->state = drain ? DART_RTL_CONTROL_DRAIN : DART_RTL_CONTROL_READY;
    if (drain) {
        int result = dart_rtl_audio_stop(p->audio);
        if (result < 0) return fail(p, result);
        /* The CU interprets delayed-status + a later OUT queue as status IN.
         * Arm OUT data before returning 1255; its application waits for audio
         * cancellation below, while the host's status stage remains delayed. */
        if (result && ((setup[0] & 0x80) || !length)) return DART_RTL_DELAYED_STATUS;
        p->state = DART_RTL_CONTROL_READY;
    }
    int result = ready(p);
    if (result) return result;
    /* The PCD's delayed-status flag lets the task validate OUT data before
     * queuing status. Its completion callback must return before requeueing. */
    return !(setup[0] & 0x80) && length ? DART_RTL_DELAYED_STATUS : 0;
}

static void disconnect_callback(dart_rtl_gadget *gadget)
{
    if (active && active->gadget == gadget) {
        active->resetting = 1;
        (void)dart_rtl_control_service(active);
    }
}

int dart_rtl_control_service(dart_rtl_control_port *p)
{
    if (!p || !p->bound || active != p) return -22;
    if (p->resetting || p->closing) {
        if (p->in_flight && !p->cancel_requested) {
            p->cancel_requested = 1;
            (void)p->gadget->ep0->ops->dequeue(p->gadget->ep0, &p->request);
        }
        int result = dart_rtl_audio_stop(p->audio);
        if (result < 0) return result;
        if (result || p->in_flight) return 1;
        dart_usb_init(p->audio->bridge);
        p->state = DART_RTL_CONTROL_IDLE; p->last_error = p->stalled = p->resetting = 0;
        p->reset_count++;
        return 0;
    }
    if (p->state == DART_RTL_CONTROL_DRAIN) {
        int result = dart_rtl_audio_stop(p->audio);
        if (result < 0) return fail(p, result);
        if (result) return 1;
        p->state = DART_RTL_CONTROL_READY;
    }
    /* A new SETUP can abort a pending control while audio cancellation is
     * still outstanding. Serve its read reply normally, then finish the old
     * drain and resume the unchanged alternate once the control pipe is idle. */
    if (p->state == DART_RTL_CONTROL_IDLE &&
        (p->audio->stopping || (p->audio->enable_attempted && !p->audio->enabled))) {
        int stopped = dart_rtl_audio_stop(p->audio);
        if (stopped) return stopped;
        if (p->audio->bridge->alternate && !p->audio->faulted)
            return dart_rtl_audio_start(p->audio);
    }
    int result = 0;
    if (p->state == DART_RTL_CONTROL_READY) result = ready(p);
    else if (p->state == DART_RTL_CONTROL_APPLY) {
        if (p->reconcile_audio) {
            result = dart_rtl_audio_stop(p->audio);
            if (result < 0) return fail(p, result);
            if (result) return 1;
        }
        result = process(p, 1);
    }
    if (p->state == DART_RTL_CONTROL_FAULT) {
        if (!p->stalled) { p->stalled = 1; (void)p->gadget->ep0->ops->set_halt(p->gadget->ep0, 1); }
        if (p->audio->enable_attempted) (void)dart_rtl_audio_stop(p->audio);
        return p->last_error;
    }
    return result;
}

int dart_rtl_control_tick(dart_rtl_control_port *p)
{
    int result = dart_rtl_control_service(p);
    if (result) return result;
    if (p->resetting || p->closing ||
        (p->reconcile_audio && p->state != DART_RTL_CONTROL_IDLE) ||
        !p->audio->bridge->configuration || !p->audio->bridge->alternate || !p->audio->enabled) return 0;
    return dart_rtl_audio_service(p->audio);
}

int dart_rtl_control_unbind(dart_rtl_control_port *p)
{
    if (!p || !p->bound || active != p) return -22;
    p->closing = 1;
    int result = dart_rtl_control_service(p);
    if (result) return result;
    if (*p->setup_slot != setup_callback || *p->disconnect_slot != disconnect_callback ||
        p->gadget->ep0->descriptor != p->descriptor) return -22;
    *p->setup_slot = p->original_setup; *p->disconnect_slot = p->original_disconnect;
    p->gadget->ep0->descriptor = p->original_descriptor;
    active = 0; p->bound = p->closing = 0;
    return 0;
}
