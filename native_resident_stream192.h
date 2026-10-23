/* Uses the same checked resident allocation and native request ABI as EP0. */
static void resident_stream192(IOUSBHostDevice *__strong *deviceRef, IOUSBHostInterface *__strong *interfaceRef,
                            IOUSBHostPipe *__strong *pipeRef, NSString *root, uint32_t allocation, BOOL useIRQ) {
    NSString *folder=[root stringByAppendingPathComponent:@"results/native-host-build/stream192"];
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:
        [NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-stream192.json"]] options:0 error:nil];
    NSData *image=[NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-stream192.bin"]];
    require(manifest && image.length && image.length<=6144 && !(image.length&3) &&
        [manifest[@"base"] unsignedIntValue]==allocation && [manifest[@"upload_bytes"] unsignedIntValue]==image.length &&
        [manifest[@"image_hex"] isEqual:hex(image)],@"Stream image matches checked allocation and manifest",nil);
    NSDictionary *symbols=manifest[@"symbols"];
    uint32_t entry=[symbols[@"dart_stream_setup"] unsignedIntValue];
    require((entry&1) && entry>=allocation && entry<allocation+6144,@"Stream entry inside allocation",nil);
    for(NSString *name in symbols) {
        uint32_t address=[symbols[name] unsignedIntValue];
        require(address>=allocation && address<allocation+6144,@"Stream symbols inside allocation",nil);
    }
    require(read_word(*interfaceRef,*pipeRef,0x0030cc10)==0x0030cf58 &&
        read_word(*interfaceRef,*pipeRef,0x0030cf70)==0x0020c7b1,
        @"Original idle native ISO endpoint",nil);
    uint32_t originalDescriptor=read_word(*interfaceRef,*pipeRef,0x0030cc1c);
    uint32_t originalMaxPacket=read_word(*interfaceRef,*pipeRef,0x0030cc20);
    uint8_t original=((const uint8_t *)control(*deviceRef,0x81,10,0,1,[NSMutableData dataWithLength:1]).bytes)[0];
    require(original==0,@"Stream starts at alternate zero",nil);
    record[@"resident_profile"]=[@{@"mode":@"bounded PCM stream",@"base":@(allocation),
        @"sha256":manifest[@"sha256"],@"symbols":symbols,@"restored":@NO} mutableCopy];
    record[@"iso_capture"]=[@{@"original_alternate":@(original),@"selected_alternate":@6,
        @"format_version":@3,@"sample_rate":@48000,@"channels":@2,@"packet_bytes":@192,@"frames":[NSMutableArray array],
        @"original_endpoint_descriptor":@(originalDescriptor),@"original_endpoint_max_packet":@(originalMaxPacket),
        @"host_refill_required":@YES,@"restored":@NO} mutableCopy];
    uint32_t irqEntry=[symbols[@"dart_stream_irq"] unsignedIntValue];
    if(useIRQ) {
        require((irqEntry&1) && irqEntry>=allocation && irqEntry<allocation+6144 &&
            read_word(*interfaceRef,*pipeRef,0xe000ed08)==0x00280000 &&
            read_word(*interfaceRef,*pipeRef,0x00280100)==0x0020d083,@"Verified RAM USB interrupt vector",nil);
        record[@"resident_profile"][@"irq_entry"]=@(irqEntry);
        record[@"resident_profile"][@"original_irq"]=@0x0020d083;
        record[@"iso_capture"][@"host_refill_required"]=@NO;
    }
    BOOL irqAttempted=NO;
    IOUSBHostInterface *audio=nil; IOUSBHostPipe *iso=nil; BOOL changed=NO, installed=NO;
    @try {
        const uint8_t *bytes=image.bytes;
        for(NSUInteger i=0;i<image.length;i+=4) {
            uint32_t word=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;
            write_word(*interfaceRef,*pipeRef,allocation+(uint32_t)i,word);
        }
        require(read_word(*interfaceRef,*pipeRef,[symbols[@"dart_stream_pending"] unsignedIntValue])==0,@"Stream state starts clear",nil);
        installed=YES;write_word(*interfaceRef,*pipeRef,0x0030d164,entry);
        cleanupDepth++;
        native_reenumerate(deviceRef,interfaceRef,pipeRef);
        cleanupDepth--;
        record[@"iso_capture"][@"full_rate_reenumeration"]=[record[@"reenumeration"] copy];
        require(read_word(*interfaceRef,*pipeRef,0x0030d164)==entry,@"Resident setup survived bus reset",nil);
        NSData *advertised=control(*deviceRef,0x80,6,0x200,0,[NSMutableData dataWithLength:200]);
        record[@"iso_capture"][@"advertised_configuration"]=hex(advertised);
        require([hex(advertised) isEqual:manifest[@"configuration"]],@"Reenumerated host sees 192-byte ISO descriptor",nil);
        if(useIRQ) {
            require(read_word(*interfaceRef,*pipeRef,0x00280100)==0x0020d083,@"USB IRQ still stock after reenumeration",nil);
            irqAttempted=YES;write_word(*interfaceRef,*pipeRef,0x00280100,irqEntry);
            checkpoint(@"device interrupt refill installed");
        }
        audio=open_audio_interface(); NSError *error=nil;
        changed=YES;
        require([audio selectAlternateSetting:6 error:&error],@"Enable RAM 192-byte ISO endpoint",error);
        require(read_word(*interfaceRef,*pipeRef,0x0030cc20)==192 && read_word(*interfaceRef,*pipeRef,0x0030cc1c)!=0,
            @"Live endpoint enabled with expected packet size",nil);
        record[@"iso_capture"][@"active_heap_free_bytes"]=@(read_word(*interfaceRef,*pipeRef,0x0028199c));
        iso=[audio copyPipeWithAddress:0x83 error:&error];
        require(iso!=nil,@"Open native ISO IN 0x83",error);
        require(iso.descriptors->descriptor.wMaxPacketSize==192,@"Host pipe uses 192 bytes per frame",nil);
        NSMutableDictionary *nativeState=[NSMutableDictionary dictionary];
        for(uint32_t at=0x0030c55c;at<=0x0030c564;at+=4)
            nativeState[[NSString stringWithFormat:@"0x%08x",at]]=@(read_word(*interfaceRef,*pipeRef,at));
        for(uint32_t at=0x0030be1c;at<=0x0030be38;at+=4)
            nativeState[[NSString stringWithFormat:@"0x%08x",at]]=@(read_word(*interfaceRef,*pipeRef,at));
        record[@"iso_capture"][@"native_before"]=nativeState;
        installed=YES;write_word(*interfaceRef,*pipeRef,0x0030d164,entry);
        control(*interfaceRef,0x80,6,0x17d,0,[NSMutableData dataWithLength:18]);
        checkpoint(@"resident PCM producer started");
        NSUInteger frameCount=2048;
        const char *requestedFrames=getenv("BT600_CAPTURE_FRAMES");
        if(requestedFrames) {
            char *end=NULL; unsigned long value=strtoul(requestedFrames,&end,10);
            require(end && !*end && value>=64 && value<=300000,@"Capture frame count is 64..300000",nil);
            frameCount=value;
        }
        void (^refill)(void)=nil;
        if(!useIRQ)refill=^{control(*interfaceRef,0x80,6,0x17d,0,[NSMutableData dataWithLength:18]);};
        capture_iso(audio,iso,frameCount,192,record[@"iso_capture"][@"frames"],refill);
    } @finally {
        cleanupDepth++;
        checkpoint(@"stopping resident stream");
        if(installed)control(*interfaceRef,0x80,6,0x17f,0,[NSMutableData dataWithLength:18]);
        NSError *error=nil;
        if(iso)require([iso abortWithOption:IOUSBHostAbortOptionSynchronous error:&error],@"Drain resident audio pipe",error);
        iso=nil;
        if(changed)require([audio selectAlternateSetting:original error:&error],@"Disable ISO and restore alternate",error);
        if(audio)[audio destroy];
        if(irqAttempted) {
            uint32_t observed=read_word(*interfaceRef,*pipeRef,0x00280100);
            require(observed==irqEntry || observed==0x0020d083,@"Owned USB interrupt vector before restore",nil);
            write_word(*interfaceRef,*pipeRef,0x00280100,0x0020d083);
            record[@"iso_capture"][@"interrupt_restored"]=@YES;
            record[@"iso_capture"][@"target_irq_calls"]=@(read_word(*interfaceRef,*pipeRef,[symbols[@"dart_stream_irq_calls"] unsignedIntValue]));
        }
        if(installed)control(*interfaceRef,0x80,6,0x17c,0,[NSMutableData dataWithLength:18]);
        require(read_word(*interfaceRef,*pipeRef,0x0030d164)==0x020be8a1,@"Original setup restored",nil);
        NSMutableDictionary *counters=[NSMutableDictionary dictionary];
        for(NSString *name in @[@"running",@"pending",@"queued",@"completed",@"errors",@"cancelled",@"last_queue",@"last_status",@"last_actual"])
            counters[name]=@(read_word(*interfaceRef,*pipeRef,[symbols[[@"dart_stream_" stringByAppendingString:name]] unsignedIntValue]));
        record[@"iso_capture"][@"target_counters"]=counters;
        uint32_t busyAddress=[symbols[@"dart_stream_busy"] unsignedIntValue];
        require(busyAddress && !(busyAddress&3),@"Aligned request slot state",nil);
        for(uint32_t at=busyAddress;at<busyAddress+16;at+=4)
            require(read_word(*interfaceRef,*pipeRef,at)==0,@"Every resident request slot released",nil);
        require(read_word(*interfaceRef,*pipeRef,0x0030be20)==0x0030be20 &&
            read_word(*interfaceRef,*pipeRef,0x0030be24)==0x0030be20 && read_word(*interfaceRef,*pipeRef,0x0030be1c)==0,
            @"Native ISO queue empty and endpoint disabled",nil);
        uint32_t ring=read_word(*interfaceRef,*pipeRef,0x0030c560);
        require((ring&255)==((ring>>8)&255),@"Native ring completely drained",nil);
        record[@"iso_capture"][@"native_drain_verified"]=@YES;
        require([counters[@"pending"] unsignedIntValue]==0 && [counters[@"running"] unsignedIntValue]==0,
            @"Native ISO requests drained before freeing code",nil);
        record[@"iso_capture"][@"restored_endpoint_descriptor"]=@(read_word(*interfaceRef,*pipeRef,0x0030cc1c));
        record[@"iso_capture"][@"restored_endpoint_max_packet"]=@(read_word(*interfaceRef,*pipeRef,0x0030cc20));
        require([record[@"iso_capture"][@"restored_endpoint_max_packet"] unsignedIntValue]==originalMaxPacket &&
            [record[@"iso_capture"][@"restored_endpoint_descriptor"] unsignedIntValue]==originalDescriptor,
            @"ISO endpoint returned to original idle descriptor and packet size",nil);
        for(NSString *name in @[@"config_busy",@"config_completed",@"config_errors"])
            counters[name]=@(read_word(*interfaceRef,*pipeRef,[symbols[[@"dart_stream_" stringByAppendingString:name]] unsignedIntValue]));
        require([counters[@"config_busy"] unsignedIntValue]==0,@"Descriptor request drained",nil);
        if(installed) {
            native_reenumerate(deviceRef,interfaceRef,pipeRef);
            record[@"iso_capture"][@"stock_reenumeration"]=[record[@"reenumeration"] copy];
            NSData *restored=control(*deviceRef,0x80,6,0x200,0,[NSMutableData dataWithLength:200]);
            require([hex(restored) isEqual:manifest[@"stock_configuration"]],@"Stock host configuration descriptor restored",nil);
        }
        record[@"resident_profile"][@"restored"]=@YES;
        record[@"iso_capture"][@"restored"]=@YES;
        checkpoint(@"resident stream and alternate restored");
        cleanupDepth--;
    }
}
