/* Bounded descriptor transport check; normal enumeration remains stock. */
#include "rtl8761c_control_port.h"
#include "resident_profile_descriptors.h"

volatile uint32_t dart_resident_busy, dart_resident_completed, dart_resident_errors;
dart_rtl_request dart_resident_request;
static _Alignas(4) uint8_t data[128];
static const uint8_t ep0_descriptor[] = {7, 5, 0, 0, 64, 0, 0};

#define ORIGINAL ((dart_rtl_setup_fn)(uintptr_t)0x020be8a1)
#define SLOT (*(dart_rtl_setup_fn *)(uintptr_t)0x0030d164)

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }

static void complete(dart_rtl_endpoint *endpoint, dart_rtl_request *request)
{
    if ((uintptr_t)endpoint != 0x0030cbb4 || request != &dart_resident_request ||
        request->status || request->actual != request->length) dart_resident_errors++;
    else dart_resident_completed++;
    if (endpoint->descriptor == ep0_descriptor) endpoint->descriptor = 0;
    dart_resident_busy = 0;
}

int dart_resident_setup(dart_rtl_gadget *gadget, const uint8_t *setup)
{
    if (!gadget || (uintptr_t)gadget != 0x0030cb6c || !setup) return -22;
    if (setup[0] == 0x80 && setup[1] == 6 && le16(setup + 2) == 0x017f &&
        !le16(setup + 4) && le16(setup + 6) == 18) {
        if (dart_resident_busy) return -16;
        SLOT = ORIGINAL;
        return ORIGINAL(gadget, setup);
    }
    if (setup[1] != 6 || setup[2] != 0x7e) return ORIGINAL(gadget, setup);
    const uint8_t *source = 0;
    size_t length = 0;
    if (setup[0] == 0x80 && !le16(setup + 4)) {
        if (setup[3] == 1) { source = resident_device; length = sizeof(resident_device); }
        if (setup[3] == 2) { source = resident_configuration; length = sizeof(resident_configuration); }
    } else if (setup[0] == 0x81 && setup[3] == 0x22 && le16(setup + 4) == 2) {
        source = resident_report; length = sizeof(resident_report);
    }
    if (!source || dart_resident_busy) return -22;
    dart_rtl_endpoint *endpoint = gadget->ep0;
    if ((uintptr_t)endpoint != 0x0030cbb4 || endpoint->descriptor ||
        (uintptr_t)endpoint->ops != 0x0030cf58 ||
        (uintptr_t)endpoint->ops->queue != 0x0020c7b1 || endpoint->max_packet != 64) return -22;
    uint16_t requested = le16(setup + 6);
    if (length > requested) length = requested;
    for (size_t i = 0; i < length; ++i) data[i] = source[i];
    dart_rtl_request *request = &dart_resident_request;
    request->buffer = data; request->length = (uint32_t)length;
    request->dma_address = (uint32_t)(uintptr_t)data;
    request->complete = complete; request->context = 0;
    request->next = request->previous = &request->next;
    request->status = -115; request->actual = request->reserved = 0;
    request->flags = length < requested && length % 64 == 0 ? 2 : 0;
    for (size_t i = 0; i < 3; ++i) request->padding[i] = 0;
    endpoint->descriptor = ep0_descriptor;
    dart_resident_busy = 1;
    /* Live stock EP0 requests use identical CPU/DMA SRAM addresses. Keep this
     * trial's native queue bookkeeping in the verified active heap, rather
     * than the stale region-6 alias. Restore the selector before returning. */
    volatile uint8_t *selector = (volatile uint8_t *)(uintptr_t)0x002c10d9;
    uint8_t saved_selector = *selector;
    *selector = 5;
    int result = endpoint->ops->queue(endpoint, request);
    *selector = saved_selector;
    if (result) { dart_resident_busy = 0; endpoint->descriptor = 0; dart_resident_errors++; }
    return result;
}
