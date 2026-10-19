/* Uses the same checked resident allocation and native request ABI as EP0. */
static void resident_stream(IOUSBHostDevice *device, IOUSBHostInterface *interface,
                            IOUSBHostPipe *pipe, NSString *root, uint32_t allocation) {
    NSString *folder=[root stringByAppendingPathComponent:@"results/native-host-build/stream"];
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:
        [NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-stream.json"]] options:0 error:nil];
    NSData *image=[NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-stream.bin"]];
    require(manifest && image.length && image.length<=4096 && !(image.length&3) &&
        [manifest[@"base"] unsignedIntValue]==allocation && [manifest[@"upload_bytes"] unsignedIntValue]==image.length &&
        [manifest[@"image_hex"] isEqual:hex(image)],@"Stream image matches checked allocation and manifest",nil);
    NSDictionary *symbols=manifest[@"symbols"];
    uint32_t entry=[symbols[@"dart_stream_setup"] unsignedIntValue];
    require((entry&1) && entry>=allocation && entry<allocation+4096,@"Stream entry inside allocation",nil);
    for(NSString *name in symbols) {
        uint32_t address=[symbols[name] unsignedIntValue];
        require(address>=allocation && address<allocation+4096,@"Stream symbols inside allocation",nil);
    }
    require(read_word(interface,pipe,0x0030cc10)==0x0030cf58 &&
        read_word(interface,pipe,0x0030cf70)==0x0020c7b1,
        @"Original idle native ISO endpoint",nil);
    uint32_t originalDescriptor=read_word(interface,pipe,0x0030cc1c);
    uint32_t originalMaxPacket=read_word(interface,pipe,0x0030cc20);
    uint8_t original=((const uint8_t *)control(device,0x81,10,0,1,[NSMutableData dataWithLength:1]).bytes)[0];
    require(original==0,@"Stream starts at alternate zero",nil);
    record[@"resident_profile"]=[@{@"mode":@"bounded PCM stream",@"base":@(allocation),
        @"sha256":manifest[@"sha256"],@"symbols":symbols,@"restored":@NO} mutableCopy];
    record[@"iso_capture"]=[@{@"original_alternate":@(original),@"selected_alternate":@6,
        @"format_version":@2,@"sample_rate":@16000,@"channels":@1,@"packet_bytes":@63,@"frames":[NSMutableArray array],
        @"original_endpoint_descriptor":@(originalDescriptor),@"original_endpoint_max_packet":@(originalMaxPacket),
        @"host_refill_required":@YES,@"restored":@NO} mutableCopy];
    IOUSBHostInterface *audio=nil; IOUSBHostPipe *iso=nil; BOOL changed=NO, installed=NO;
    @try {
        const uint8_t *bytes=image.bytes;
        for(NSUInteger i=0;i<image.length;i+=4) {
            uint32_t word=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;
            write_word(interface,pipe,allocation+(uint32_t)i,word);
        }
        require(read_word(interface,pipe,[symbols[@"dart_stream_pending"] unsignedIntValue])==0,@"Stream state starts clear",nil);
        audio=open_audio_interface(); NSError *error=nil;
        changed=YES;
        require([audio selectAlternateSetting:6 error:&error],@"Enable stock 63-byte ISO endpoint",error);
        require(read_word(interface,pipe,0x0030cc20)==63 && read_word(interface,pipe,0x0030cc1c)!=0,
            @"Live endpoint enabled with expected packet size",nil);
        iso=[audio copyPipeWithAddress:0x83 error:&error];
        require(iso!=nil,@"Open native ISO IN 0x83",error);
        NSMutableDictionary *nativeState=[NSMutableDictionary dictionary];
        for(uint32_t at=0x0030c55c;at<=0x0030c564;at+=4)
            nativeState[[NSString stringWithFormat:@"0x%08x",at]]=@(read_word(interface,pipe,at));
        for(uint32_t at=0x0030be1c;at<=0x0030be38;at+=4)
            nativeState[[NSString stringWithFormat:@"0x%08x",at]]=@(read_word(interface,pipe,at));
        record[@"iso_capture"][@"native_before"]=nativeState;
        installed=YES;write_word(interface,pipe,0x0030d164,entry);
        control(interface,0x80,6,0x17d,0,[NSMutableData dataWithLength:18]);
        checkpoint(@"resident PCM producer started");
        NSUInteger frameCount=2048;
        const char *requestedFrames=getenv("BT600_CAPTURE_FRAMES");
        if(requestedFrames) {
            char *end=NULL; unsigned long value=strtoul(requestedFrames,&end,10);
            require(end && !*end && value>=64 && value<=32000,@"Capture frame count is 64..32000",nil);
            frameCount=value;
        }
        capture_iso(audio,iso,frameCount,63,record[@"iso_capture"][@"frames"],^{
            control(interface,0x80,6,0x17d,0,[NSMutableData dataWithLength:18]);
        });
    } @finally {
        cleanupDepth++;
        checkpoint(@"stopping resident stream");
        if(installed)control(interface,0x80,6,0x17f,0,[NSMutableData dataWithLength:18]);
        NSError *error=nil;
        if(iso)require([iso abortWithOption:IOUSBHostAbortOptionSynchronous error:&error],@"Drain resident audio pipe",error);
        iso=nil;
        if(changed)require([audio selectAlternateSetting:original error:&error],@"Disable ISO and restore alternate",error);
        if(audio)[audio destroy];
        require(read_word(interface,pipe,0x0030d164)==0x020be8a1,@"Original setup restored",nil);
        NSMutableDictionary *counters=[NSMutableDictionary dictionary];
        for(NSString *name in @[@"running",@"pending",@"queued",@"completed",@"errors",@"cancelled",@"last_queue",@"last_status",@"last_actual"])
            counters[name]=@(read_word(interface,pipe,[symbols[[@"dart_stream_" stringByAppendingString:name]] unsignedIntValue]));
        record[@"iso_capture"][@"target_counters"]=counters;
        uint32_t busyAddress=[symbols[@"dart_stream_busy"] unsignedIntValue];
        require(busyAddress && !(busyAddress&3),@"Aligned request slot state",nil);
        for(uint32_t at=busyAddress;at<busyAddress+16;at+=4)
            require(read_word(interface,pipe,at)==0,@"Every resident request slot released",nil);
        require(read_word(interface,pipe,0x0030be20)==0x0030be20 &&
            read_word(interface,pipe,0x0030be24)==0x0030be20 && read_word(interface,pipe,0x0030be1c)==0,
            @"Native ISO queue empty and endpoint disabled",nil);
        uint32_t ring=read_word(interface,pipe,0x0030c560);
        require((ring&255)==((ring>>8)&255),@"Native ring completely drained",nil);
        record[@"iso_capture"][@"native_drain_verified"]=@YES;
        require([counters[@"pending"] unsignedIntValue]==0 && [counters[@"running"] unsignedIntValue]==0,
            @"Native ISO requests drained before freeing code",nil);
        record[@"iso_capture"][@"restored_endpoint_descriptor"]=@(read_word(interface,pipe,0x0030cc1c));
        record[@"iso_capture"][@"restored_endpoint_max_packet"]=@(read_word(interface,pipe,0x0030cc20));
        require([record[@"iso_capture"][@"restored_endpoint_max_packet"] unsignedIntValue]==originalMaxPacket &&
            [record[@"iso_capture"][@"restored_endpoint_descriptor"] unsignedIntValue]==originalDescriptor,
            @"ISO endpoint returned to original idle descriptor and packet size",nil);
        record[@"resident_profile"][@"restored"]=@YES;
        record[@"iso_capture"][@"restored"]=@YES;
        checkpoint(@"resident stream and alternate restored");
        cleanupDepth--;
    }
}
