/* HCI personality with an advertised 192-byte ISO alternate, kept RAM-only. */
#define STREAM_LIMIT 300768
#define STREAM_SLOTS 14
#define STREAM_BYTES 192
#define STREAM_SAMPLES 96
#define STREAM_SETUP_NAME dart_stream_body
#include "resident_stream_trial.c"
#include "resident_stock_configuration.h"
volatile uint32_t dart_stream_config_busy, dart_stream_config_completed, dart_stream_config_errors;
static dart_rtl_request config_request;
static const uint8_t ep0_descriptor[]={7,5,0,0,64,0,0};
static const uint8_t audio_descriptor[]={7,5,0x83,1,192,0,1};
static const uint8_t *saved_audio_descriptor;
static uint32_t saved_audio_max;
static void config_complete(dart_rtl_endpoint *ep,dart_rtl_request *request) {
    if(ep!=(dart_rtl_endpoint *)(uintptr_t)0x30cbb4 || request!=&config_request ||
       request->status || request->actual!=request->length)dart_stream_config_errors++;
    else dart_stream_config_completed++;
    if(ep->descriptor==ep0_descriptor)ep->descriptor=0;
    dart_stream_config_busy=0;
}
static int configuration(dart_rtl_gadget *gadget,const uint8_t *setup) {
    dart_rtl_endpoint *ep=gadget->ep0;
    if(dart_stream_config_busy || ep->descriptor || (uintptr_t)ep->ops!=0x30cf58)return -16;
    unsigned length=(unsigned)setup[6]|(unsigned)setup[7]<<8;
    if(length>sizeof(stock_configuration))length=sizeof(stock_configuration);
    dart_rtl_request *r=&config_request;
    r->buffer=(uint8_t *)stock_configuration;r->dma_address=(uint32_t)(uintptr_t)stock_configuration;
    r->length=length;r->complete=config_complete;r->context=0;
    r->next=r->previous=&r->next;r->actual=r->reserved=0;r->status=-115;
    r->flags=0;r->padding[0]=r->padding[1]=r->padding[2]=0;
    ep->descriptor=ep0_descriptor;dart_stream_config_busy=1;
    uint32_t held=lock();volatile uint8_t *selector=(volatile uint8_t *)(uintptr_t)0x2c10d9;
    uint8_t original=*selector;*selector=5;int result=ep->ops->queue(ep,r);*selector=original;unlock(held);
    if(result) {ep->descriptor=0;dart_stream_config_busy=0;dart_stream_config_errors++;}
    return result;
}
int dart_stream_setup(dart_rtl_gadget *gadget,const uint8_t *setup) {
    if((uintptr_t)gadget!=0x30cb6c || !setup)return -22;
    if(setup[0]==0x80 && setup[1]==6 && setup[2]==0 && setup[3]==2 && !setup[4] && !setup[5])
        return configuration(gadget,setup);
    if(setup[0]==0x80 && setup[1]==6 && setup[3]==1 && setup[6]==18 && !setup[7]) {
        if(setup[2]==127) {dart_stream_running=0;return ORIGINAL(gadget,setup);}
        if(setup[2]==124) {
            if(dart_stream_pending || dart_stream_config_busy || saved_audio_descriptor)return -16;
            SLOT=ORIGINAL;return ORIGINAL(gadget,setup);
        }
    }
    if(setup[0]==1 && setup[1]==11 && setup[4]==1 && !setup[5] && !setup[6] && !setup[7]) {
        unsigned alternate=(unsigned)setup[2]|(unsigned)setup[3]<<8;
        int result=ORIGINAL(gadget,setup);if(result)return result;
        if(alternate==6) {
            if(dart_stream_pending || saved_audio_descriptor || !EP->descriptor || EP->max_packet!=63)return -22;
            saved_audio_descriptor=EP->descriptor;saved_audio_max=EP->max_packet;
            uint32_t held=lock();volatile uint8_t *selector=(volatile uint8_t *)(uintptr_t)0x2c10d9;
            uint8_t original=*selector;*selector=5;
            result=EP->ops->disable(EP);
            if(!result) {EP->descriptor=audio_descriptor;result=EP->ops->enable(EP,audio_descriptor);}
            *selector=original;unlock(held);
            if(result)dart_stream_config_errors++;
            return result;
        }
        if(alternate==0 && saved_audio_descriptor) {
            if(dart_stream_pending)return -16;
            EP->descriptor=saved_audio_descriptor;EP->max_packet=saved_audio_max;
            saved_audio_descriptor=0;
        }
        return result;
    }
    return dart_stream_body(gadget,setup);
}

/* The stock IRQ-48 entry returns normally after processing endpoint events.
 * Refill only after it releases the native completion's stopped flag. */
volatile uint32_t dart_stream_irq_calls;
uint32_t dart_stream_irq(void) {
    uint32_t result=((uint32_t (*)(void))(uintptr_t)0x0020d083)();
    dart_stream_irq_calls++;
    if(dart_stream_running && EP->max_packet==STREAM_BYTES &&
       !(*(volatile uint32_t *)(uintptr_t)0x0030be28&1)) {
        for(unsigned slot=0;slot<STREAM_SLOTS && dart_stream_running && dart_stream_queued<dart_stream_limit;slot++)
            if(!dart_stream_busy[slot])queue(slot);
    }
    return result;
}
