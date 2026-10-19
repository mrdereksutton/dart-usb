/* Bounded PCM producer for the stock 63-byte ISO endpoint. No persistent writes. */
#include "rtl8761c_control_port.h"
volatile uint32_t dart_stream_running, dart_stream_pending, dart_stream_queued;
volatile uint32_t dart_stream_completed, dart_stream_errors, dart_stream_cancelled;
volatile int32_t dart_stream_last_queue, dart_stream_last_status;
volatile uint32_t dart_stream_last_actual;
volatile uint32_t dart_stream_limit = 32768;
static dart_rtl_request requests[14];
static _Alignas(4) int16_t packets[14][32];
_Alignas(4) volatile uint8_t dart_stream_busy[14];
#define EP ((dart_rtl_endpoint *)(uintptr_t)0x0030cc08)
#define ORIGINAL ((dart_rtl_setup_fn)(uintptr_t)0x020be8a1)
#define SLOT (*(dart_rtl_setup_fn *)(uintptr_t)0x0030d164)
static void completed(dart_rtl_endpoint *, dart_rtl_request *);
static uint32_t lock(void) {
    uint32_t saved;
    __asm volatile("mrs %0, primask\n cpsid i" : "=r"(saved) :: "memory");
    return saved;
}
static void unlock(uint32_t saved) { __asm volatile("msr primask, %0" :: "r"(saved) : "memory"); }
static int queue(unsigned slot) {
    dart_rtl_request *r=&requests[slot];
    uint32_t sequence=dart_stream_queued;
    for(unsigned i=0;i<32;i++)packets[slot][i]=(i&8)?-1024:1024;
    packets[slot][0]=(int16_t)(sequence&255)-128;
    packets[slot][1]=(int16_t)((sequence>>8)&255)-128;
    ((uint8_t *)packets[slot])[62]=0;
    r->buffer=(uint8_t *)packets[slot]; r->length=63;
    r->dma_address=(uint32_t)(uintptr_t)packets[slot];
    r->complete=completed; r->context=(void *)(uintptr_t)slot;
    r->next=r->previous=&r->next; r->status=-115; r->actual=r->reserved=0;
    r->flags=0; r->padding[0]=r->padding[1]=r->padding[2]=0;
    uint32_t saved=lock();
    dart_stream_busy[slot]=1; dart_stream_pending++;
    int result=EP->ops->queue(EP,r);
    dart_stream_last_queue=result;
    if(result) { dart_stream_busy[slot]=0; dart_stream_pending--; dart_stream_errors++; dart_stream_running=0; }
    else dart_stream_queued++;
    unlock(saved);
    return result;
}
static void completed(dart_rtl_endpoint *ep, dart_rtl_request *request) {
    uint32_t saved=lock();
    dart_stream_last_status=request->status; dart_stream_last_actual=request->actual;
    unsigned slot=(unsigned)(uintptr_t)request->context;
    if(ep!=EP || slot>=14 || request!=&requests[slot] || !dart_stream_busy[slot] || !dart_stream_pending) {
        dart_stream_errors++; dart_stream_running=0; unlock(saved); return;
    }
    dart_stream_busy[slot]=0; dart_stream_pending--;
    if(request->status || request->actual!=63) {
        if(dart_stream_running)dart_stream_errors++;
        else dart_stream_cancelled++;
        dart_stream_running=0;
        unlock(saved); return;
    }
    dart_stream_completed++;
    if(dart_stream_queued>=dart_stream_limit && !dart_stream_pending)dart_stream_running=0;
    unlock(saved);
}
int dart_stream_setup(dart_rtl_gadget *gadget,const uint8_t *setup) {
    if((uintptr_t)gadget!=0x0030cb6c || !setup)return -22;
    if(setup[0]==0x80 && setup[1]==6 && setup[3]==1 && !setup[4] && !setup[5] &&
       setup[6]==18 && !setup[7]) {
        if(setup[2]==0x7d) {
            if((dart_stream_queued && !dart_stream_running) ||
               (uintptr_t)EP->ops!=0x0030cf58 || (uintptr_t)EP->ops->queue!=0x0020c7b1 ||
               !EP->descriptor || EP->descriptor[2]!=0x83 || (EP->descriptor[3]&3)!=1 ||
               EP->max_packet!=63 || dart_stream_limit>32768)return -22;
            dart_stream_running=1;
            for(unsigned slot=0;slot<14 && dart_stream_running && dart_stream_queued<dart_stream_limit;slot++)
                if(!dart_stream_busy[slot])queue(slot);
        } else if(setup[2]==0x7f) {
            dart_stream_running=0; SLOT=ORIGINAL;
        }
    }
    return ORIGINAL(gadget,setup);
}
