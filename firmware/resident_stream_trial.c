/* Bounded PCM producer for the stock 63-byte ISO endpoint. No persistent writes. */
#include "rtl8761c_control_port.h"
#ifndef STREAM_SLOTS
#define STREAM_SLOTS 14
#define STREAM_BYTES 63
#define STREAM_SAMPLES 32
#define STREAM_SETUP_NAME dart_stream_setup
#endif
#ifndef STREAM_LIMIT
#define STREAM_LIMIT 32768
#endif
volatile uint32_t dart_stream_running, dart_stream_pending, dart_stream_queued;
volatile uint32_t dart_stream_completed, dart_stream_errors, dart_stream_cancelled;
volatile int32_t dart_stream_last_queue, dart_stream_last_status;
volatile uint32_t dart_stream_last_actual;
volatile uint32_t dart_stream_limit = STREAM_LIMIT;
static dart_rtl_request requests[STREAM_SLOTS];
static _Alignas(4) int16_t packets[STREAM_SLOTS][STREAM_SAMPLES];
_Alignas(4) volatile uint8_t dart_stream_busy[STREAM_SLOTS];
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
    for(unsigned i=0;i<STREAM_SAMPLES;i++)
        packets[slot][i]=STREAM_BYTES==192 ? (i<48?1024:-1024) : ((i&8)?-1024:1024);
    packets[slot][0]=(int16_t)(sequence&255)-128;
    packets[slot][1]=(int16_t)((sequence>>8)&255)-128;
    if(STREAM_BYTES==63)((uint8_t *)packets[slot])[62]=0;
    r->buffer=(uint8_t *)packets[slot]; r->length=STREAM_BYTES;
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
    if(ep!=EP || slot>=STREAM_SLOTS || request!=&requests[slot] || !dart_stream_busy[slot] || !dart_stream_pending) {
        dart_stream_errors++; dart_stream_running=0; unlock(saved); return;
    }
    dart_stream_busy[slot]=0; dart_stream_pending--;
    if(request->status || request->actual!=STREAM_BYTES) {
        if(dart_stream_running)dart_stream_errors++;
        else dart_stream_cancelled++;
        dart_stream_running=0;
        unlock(saved); return;
    }
    dart_stream_completed++;
    if(dart_stream_queued>=dart_stream_limit && !dart_stream_pending)dart_stream_running=0;
    unlock(saved);
}
int STREAM_SETUP_NAME(dart_rtl_gadget *gadget,const uint8_t *setup) {
    if((uintptr_t)gadget!=0x0030cb6c || !setup)return -22;
    if(setup[0]==0x80 && setup[1]==6 && setup[3]==1 && !setup[4] && !setup[5] &&
       setup[6]==18 && !setup[7]) {
        if(setup[2]==0x7d) {
            if((dart_stream_queued && !dart_stream_running) ||
               (uintptr_t)EP->ops!=0x0030cf58 || (uintptr_t)EP->ops->queue!=0x0020c7b1 ||
               !EP->descriptor || EP->descriptor[2]!=0x83 || (EP->descriptor[3]&3)!=1 ||
               EP->max_packet!=STREAM_BYTES || dart_stream_limit>STREAM_LIMIT)return -22;
            dart_stream_running=1;
            for(unsigned slot=0;slot<STREAM_SLOTS && dart_stream_running && dart_stream_queued<dart_stream_limit;slot++)
                if(!dart_stream_busy[slot])queue(slot);
        } else if(setup[2]==0x7f) {
            dart_stream_running=0; SLOT=ORIGINAL;
        }
    }
    return ORIGINAL(gadget,setup);
}
