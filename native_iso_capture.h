/* Native ISO capture. Open the pipe only after selecting its valid alternate. */
#include <signal.h>
static BOOL testIsoPolicy;
static void cancel_capture(int number) { (void)number; cancelled=1; }
static IOUSBHostInterface *open_audio_interface(void) {
    CFMutableDictionaryRef query=[IOUSBHostInterface createMatchingDictionaryWithVendorID:@0x0b05 productID:@0x1d70
        bcdDevice:nil interfaceNumber:@1 configurationValue:@1 interfaceClass:nil interfaceSubclass:nil
        interfaceProtocol:nil speed:nil productIDArray:nil];
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,query);
    require(service!=0,@"Find audio interface 1",nil);
    NSError *error=nil;
    IOUSBHostInterface *result=[[IOUSBHostInterface alloc] initWithIOService:service
        options:IOUSBHostObjectInitOptionsNone queue:nil error:&error interestHandler:nil];
    IOObjectRelease(service);
    require(result!=nil,@"Open native audio interface",error);
    return result;
}
static NSData *capture_iso(IOUSBHostInterface *audio, IOUSBHostPipe *iso, NSUInteger count,
                          NSUInteger packetBytes, NSMutableArray *frames, void (^pump)(void)) {
    require(count && count<=32000 && packetBytes && packetBytes<=192,@"Bound capture allocation",nil);
    NSError *error=nil;
    NSMutableData *data=[audio ioDataWithCapacity:count*packetBytes error:&error];
    require(data!=nil,@"Allocate ISO data",error);
    IOUSBHostIsochronousTransaction *transactions=calloc(count,sizeof(*transactions));
    require(transactions!=NULL,@"Allocate ISO transactions",nil);
    for(NSUInteger i=0;i<count;i++) {
        transactions[i].requestCount=(uint32_t)packetBytes;
        transactions[i].offset=(uint32_t)(i*packetBytes);
    }
    dispatch_semaphore_t ready=dispatch_semaphore_create(0);
    __block IOReturn completion=kIOReturnInvalid;
    NSMutableData *pcm=[NSMutableData data]; BOOL submitted=NO;
    @try {
        submitted=[iso enqueueIORequestWithData:data transactionList:transactions transactionListCount:count
            firstFrameNumber:0 options:IOUSBHostIsochronousTransferOptionsNone error:&error
            completionHandler:^(IOReturn status, IOUSBHostIsochronousTransaction *list) {
                (void)list; completion=status; dispatch_semaphore_signal(ready);
            }];
        require(submitted,@"Submit bounded ISO capture",error);
        checkpoint(@"isochronous capture submitted");
        NSTimeInterval began=NSDate.timeIntervalSinceReferenceDate;
        const char *cancelSetting=getenv("BT600_CANCEL_AFTER_MS");
        unsigned long cancelAfter=cancelSetting?strtoul(cancelSetting,NULL,10):0;
        require(!cancelSetting || (cancelAfter>=50 && cancelAfter<=30000),@"Bound cancellation injection",nil);
        NSTimeInterval deadline=NSDate.timeIntervalSinceReferenceDate+count/1000.0+2;
        BOOL done=NO;
        while(!done && !cancelled && NSDate.timeIntervalSinceReferenceDate<deadline) {
            done=dispatch_semaphore_wait(ready,dispatch_time(DISPATCH_TIME_NOW,4*NSEC_PER_MSEC))==0;
            if(!done && !cancelled && pump)pump();
            if(cancelAfter && (NSDate.timeIntervalSinceReferenceDate-began)*1000>=cancelAfter)raise(SIGINT);
        }
        record[@"iso_capture"][@"completion_status"]=@(completion);
        record[@"iso_capture"][@"cancelled"]=@(cancelled!=0);
        require(done,cancelled ? @"Capture cancelled" : @"Complete bounded ISO capture",nil);
    } @finally {
        cleanupDepth++;
        if(submitted)require([iso abortWithOption:IOUSBHostAbortOptionSynchronous error:&error],@"Drain ISO capture",error);
        for(NSUInteger i=0;i<count;i++) {
            IOUSBHostIsochronousTransaction t=transactions[i];
            [frames addObject:@{@"frame":@(i),@"status":@(t.status),@"bytes":@(t.completeCount),@"timestamp":@(t.timeStamp)}];
            if(t.completeCount<=packetBytes && t.completeCount)
                [pcm appendBytes:(const uint8_t *)data.bytes+i*packetBytes length:t.completeCount];
        }
        free(transactions);
        record[@"iso_capture"][@"received_bytes"]=@(pcm.length);
        NSString *raw=[output.stringByDeletingPathExtension stringByAppendingString:@".pcm"];
        require([pcm writeToFile:raw options:NSDataWritingAtomic error:&error],@"Save received ISO data",error);
        record[@"iso_capture"][@"pcm_path"]=raw;
        record[@"iso_capture"][@"completion_status"]=@(completion);
        checkpoint(@"isochronous capture saved and drained");
        cleanupDepth--;
    }
    return pcm;
}
static void iso_idle(IOUSBHostDevice *device, NSData *configuration) {
    const uint8_t *bytes=configuration.bytes; BOOL selected=NO, valid=NO;
    for(NSUInteger i=0;i+2<=configuration.length;i+=bytes[i]) {
        require(bytes[i]>=2 && i+bytes[i]<=configuration.length,@"ISO descriptor bounds",nil);
        if(bytes[i+1]==4)selected=bytes[i]>=9 && bytes[i+2]==1 && bytes[i+3]==6;
        if(selected && bytes[i+1]==5 && bytes[i]>=7 && bytes[i+2]==0x83 &&
           (bytes[i+3]&3)==1 && bytes[i+4]==63 && bytes[i+5]==0)valid=YES;
    }
    require(valid,@"Stock alternate 6 valid ISO IN 0x83 descriptor",nil);
    uint8_t original=((const uint8_t *)control(device,0x81,10,0,1,[NSMutableData dataWithLength:1]).bytes)[0];
    require(original==0,@"Audio interface initially idle",nil);
    IOUSBHostInterface *audio=nil; IOUSBHostPipe *iso=nil; BOOL changed=NO;
    record[@"iso_capture"]=[@{@"original_alternate":@(original),@"selected_alternate":@6,
        @"packet_bytes":@32,@"frames":[NSMutableArray array],@"restored":@NO} mutableCopy];
    @try {
        audio=open_audio_interface(); NSError *error=nil;
        changed=YES;
        require([audio selectAlternateSetting:6 error:&error],@"Select valid audio alternate 6",error);
        checkpoint(@"valid audio alternate selected before pipe open");
        iso=[audio copyPipeWithAddress:0x83 error:&error];
        require(iso!=nil,@"Open native ISO pipe 0x83",error);
        if(testIsoPolicy) {
            IOUSBHostIOSourceDescriptors descriptors=*iso.originalDescriptors;
            record[@"iso_capture"][@"original_host_max_packet"]=@(descriptors.descriptor.wMaxPacketSize);
            descriptors.descriptor.wMaxPacketSize=192;
            BOOL adjusted=[iso adjustPipeWithDescriptors:&descriptors error:&error];
            record[@"iso_capture"][@"host_policy_adjusted"]=@(adjusted);
            record[@"iso_capture"][@"host_policy_error"]=error.description ?: @"";
            if(adjusted)record[@"iso_capture"][@"adjusted_host_max_packet"]=@(iso.descriptors->descriptor.wMaxPacketSize);
            checkpoint(@"host ISO bandwidth policy tested");
            require(adjusted,@"Adjust native ISO host packet policy to 192",error);
        }
        capture_iso(audio,iso,64,32,record[@"iso_capture"][@"frames"],nil);
    } @finally {
        cleanupDepth++;
        NSError *error=nil;
        if(iso)require([iso abortWithOption:IOUSBHostAbortOptionSynchronous error:&error],@"Drain audio pipe",error);
        iso=nil;
        if(changed)require([audio selectAlternateSetting:original error:&error],@"Restore audio alternate",error);
        if(audio)[audio destroy];
        uint8_t restored=((const uint8_t *)control(device,0x81,10,0,1,[NSMutableData dataWithLength:1]).bytes)[0];
        require(restored==original,@"Verify original audio alternate",nil);
        record[@"iso_capture"][@"restored"]=@YES;
        checkpoint(@"audio alternate restored");
        cleanupDepth--;
    }
}
