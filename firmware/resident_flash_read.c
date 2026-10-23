/* Bounded raw SPI application read through native EP0; RAM-only and read-only. */
#include "rtl8761c_control_port.h"

volatile uint32_t dart_resident_busy, dart_resident_completed, dart_resident_errors;
dart_rtl_request dart_resident_request;
static _Alignas(4) uint8_t data[512];
static const uint8_t ep0_descriptor[] = {7, 5, 0, 0, 64, 0, 0};

#define ORIGINAL ((dart_rtl_setup_fn)(uintptr_t)0x020be8a1)
#define SLOT (*(dart_rtl_setup_fn *)(uintptr_t)0x0030d164)
#ifdef DART_RECEIVER_WINDOW_READ
#define READ_BASE 0x02015000u
#define READ_PAGES 392u
#else
#define READ_BASE 0x02097000u
#define READ_PAGES 576u
#endif

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }

#ifdef DART_FLASH_RESTORE_TRIAL
/* One fixed pattern in the backed-up, unsigned padding sector. No chip/block
 * erase path or arbitrary address is exposed by this diagnostic. */
volatile uint32_t dart_trial_attempted, dart_trial_program_status, dart_trial_erase_status;
volatile uint32_t dart_trial_ipsr, dart_trial_primask, dart_trial_basepri;
volatile uint32_t dart_trial_sr1, dart_trial_sr2, dart_trial_bp_level, dart_trial_status_result;
volatile uint32_t dart_trial_unprotect_status, dart_trial_reprotect_status;
static _Alignas(4) const uint8_t trial_pattern[32]={
    0x20,0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x29,0x2a,0x2b,0x2c,0x2d,0x2e,0x2f,
    0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,0x3a,0x3b,0x3c,0x3d,0x3e,0x3f};
static int restore_trial(dart_rtl_gadget *gadget,const uint8_t *setup) {
    uint16_t mode=le16(setup+4);
    if(setup[0]!=0x80 || setup[3]!=1 || le16(setup+6)!=18 || mode>2 || dart_resident_busy)return -22;
    __asm volatile("mrs %0, ipsr" : "=r"(dart_trial_ipsr));
    __asm volatile("mrs %0, primask" : "=r"(dart_trial_primask));
    __asm volatile("mrs %0, basepri" : "=r"(dart_trial_basepri));
    if(dart_trial_ipsr || dart_trial_primask || dart_trial_basepri)return -16;
    if(mode==2) {
        /* Status reads never send write-enable or alter protection bits. */
        uint32_t command[3]={0x00010005,0,0}; uint8_t status=0,level=0;
        int result=((int (*)(uint32_t,const void *,void *,uint32_t))(uintptr_t)0x202c6f)(0,command,&status,1);
        dart_trial_sr1=status; dart_trial_status_result=(uint32_t)result;
        if(result!=0x18)return -5;
        command[0]=0x00010035; status=0;
        result=((int (*)(uint32_t,const void *,void *,uint32_t))(uintptr_t)0x202c6f)(0,command,&status,1);
        dart_trial_sr2=status; dart_trial_status_result=(uint32_t)result;
        if(result!=0x18)return -5;
        result=((int (*)(uint32_t,void *))(uintptr_t)0x554d)(0,&level);
        dart_trial_bp_level=level; dart_trial_status_result=(uint32_t)result;
        if(result!=0x18)return -5;
        return ORIGINAL(gadget,setup);
    }
    if((*(volatile uint8_t *)(uintptr_t)0x002803a1 & 4) ||
       *(volatile uint8_t *)(uintptr_t)0x00280742!=0x50 ||
       dart_trial_sr1!=0x34 || dart_trial_sr2!=2 || dart_trial_bp_level!=5)return -22;
    if(!mode) {
        if(dart_trial_attempted)return -16;
        for(unsigned offset=0;offset<4096;offset+=512) {
            int status=((int (*)(uint32_t,void *,uint32_t))(uintptr_t)0xcbb5)(0x020de000+offset,data,512);
            if(status!=0x18)return -5;
            for(unsigned i=0;i<512;i++)if(data[i]!=255)return -22;
        }
        dart_trial_attempted=1;
    } else {
        if(!dart_trial_attempted)return -16;
    }
    /* The stock BP-level setter selects volatile-status enable 0x50 under
     * the checked boot flag and geometry above. Keep the existing native
     * locked program/erase wrappers; restore BP=5 before returning to USB. */
    dart_trial_unprotect_status=((int (*)(uint32_t,uint32_t))(uintptr_t)0x55af)(0,0);
    int result=-5;
    if(dart_trial_unprotect_status==0x18) {
        if(!mode) {
            result=((int (*)(uint32_t,const void *,uint32_t,uint32_t))(uintptr_t)0xcc35)(0x020de000,trial_pattern,32,32);
            dart_trial_program_status=(uint32_t)result;
        } else {
            result=((int (*)(uint32_t,uint32_t))(uintptr_t)0xcd83)(0x020de000,1);
            dart_trial_erase_status=(uint32_t)result;
        }
    }
    dart_trial_reprotect_status=((int (*)(uint32_t,uint32_t))(uintptr_t)0x55af)(0,5);
    if(result!=0x18 || dart_trial_reprotect_status!=0x18)return -5;
    return ORIGINAL(gadget,setup);
}
#endif

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
#ifdef DART_FLASH_RESTORE_TRIAL
    if(setup[1]==6 && setup[2]==0x7a)return restore_trial(gadget,setup);
#endif
    if (setup[0] == 0x80 && setup[1] == 6 && le16(setup + 2) == 0x017f &&
        !le16(setup + 4) && le16(setup + 6) == 18) {
        if (dart_resident_busy) return -16;
        SLOT = ORIGINAL;
        return ORIGINAL(gadget, setup);
    }
    if (setup[1] != 6 || setup[2] != 0x7b) return ORIGINAL(gadget, setup);
    uint16_t page=le16(setup+4), requested=le16(setup+6);
    if (setup[0]!=0x80 || setup[3]!=1 || page>=READ_PAGES || !requested || requested>512 || dart_resident_busy) return -22;
    size_t length=requested;
    dart_rtl_endpoint *endpoint = gadget->ep0;
    if ((uintptr_t)endpoint != 0x0030cbb4 || endpoint->descriptor ||
        (uintptr_t)endpoint->ops != 0x0030cf58 ||
        (uintptr_t)endpoint->ops->queue != 0x0020c7b1 || endpoint->max_packet != 64) return -22;
    int status=((int (*)(uint32_t,void *,uint32_t))(uintptr_t)0x0000cbb5)(READ_BASE+(uint32_t)page*512u,data,(uint32_t)length);
    if(status!=0x18) {dart_resident_errors++;return -5;}
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
