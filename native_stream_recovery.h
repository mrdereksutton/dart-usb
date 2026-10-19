/* Release only the identified stopped trial after checking actual DMA ownership.
 * This covers the pre-critical-section build's lost pending-counter update. */
static void recover_stream(IOUSBHostInterface *interface, IOUSBHostPipe *pipe,
                            NSString *root, NSString *priorPath) {
    NSDictionary *prior=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:priorPath] options:0 error:nil];
    NSDictionary *old=prior[@"resident_profile"], *allocator=prior[@"allocator_trial"];
    require([old[@"sha256"] isEqual:@"00e0a7c9ae0a2384ba858eff2f1c3e036f6ca004d9061d17c23b3dc80cb1f376"] &&
        [old[@"base"] unsignedIntValue]==0x312280 && [allocator[@"allocation"] unsignedIntValue]==0x312280 &&
        [allocator[@"pool"] unsignedIntValue]==5 && [allocator[@"restore_required"] boolValue],
        @"Identify the retained pre-critical-section stream allocation",nil);
    require(read_word(interface,pipe,0x0030d164)==0x020be8a1 &&
        read_word(interface,pipe,0x0030be1c)==0 && read_word(interface,pipe,0x0030be20)==0x0030be20 &&
        read_word(interface,pipe,0x0030be24)==0x0030be20 && (read_word(interface,pipe,0x0030be28)&1),
        @"Native endpoint disabled with empty DMA request list",nil);
    uint32_t ring=read_word(interface,pipe,0x0030c560);
    require((ring&255)==((ring>>8)&255),@"Native ISO ring head equals tail",nil);
    for(uint32_t at=0x312598;at<0x3125a8;at+=4)
        require(read_word(interface,pipe,at)==0,@"All fourteen retained request slots are free",nil);
    NSDictionary *symbols=old[@"symbols"];
    require(read_word(interface,pipe,[symbols[@"dart_stream_running"] unsignedIntValue])==0,@"Retained stream stopped",nil);
    uint32_t queued=read_word(interface,pipe,[symbols[@"dart_stream_queued"] unsignedIntValue]);
    uint32_t completed=read_word(interface,pipe,[symbols[@"dart_stream_completed"] unsignedIntValue]);
    uint32_t cancelledCount=read_word(interface,pipe,[symbols[@"dart_stream_cancelled"] unsignedIntValue]);
    require(queued==completed+cancelledCount,@"Every queued request completed or cancelled",nil);
    uint32_t freeBytes=read_word(interface,pipe,0x0028199c), expected=[allocator[@"free_bytes_before"] unsignedIntValue];
    require(read_word(interface,pipe,0x0031227c)==0xdaa01008 && freeBytes+4104==expected,
        @"Owned 4096-byte pool-5 allocation and exact free-byte deficit",nil);
    NSData *helper=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"results/native-host-build/resident/resident-heap-helper.bin"]];
    require(helper.length && helper.length<=192 && !(helper.length&3),@"Verified resident release helper",nil);
    NSMutableDictionary *original=[NSMutableDictionary dictionary];
    for(uint32_t at=0x211e30;at<0x211e30+helper.length;at+=4) {
        uint32_t value=read_word(interface,pipe,at);require(!value,@"Recovery scratch unused",nil);original[@(at).stringValue]=@(value);
    }
    for(uint32_t at=0x211f00;at<=0x211f04;at+=4) {
        uint32_t value=read_word(interface,pipe,at);require(!value,@"Recovery result scratch unused",nil);original[@(at).stringValue]=@(value);
    }
    record[@"recovery"]=@{@"prior_report":priorPath,@"native_queue_empty":@YES,@"ring_empty":@YES,
        @"all_request_slots_free":@YES,@"queued":@(queued),@"completed":@(completed),@"cancelled":@(cancelledCount),
        @"stale_pending_counter":@(read_word(interface,pipe,[symbols[@"dart_stream_pending"] unsignedIntValue]))};
    record[@"allocator_trial"]=[@{@"allocation":@0x312280,@"free_bytes_before":@(freeBytes),
        @"expected_free_bytes":@(expected),@"restore_required":@YES} mutableCopy];
    @try {
        const uint8_t *bytes=helper.bytes;
        for(NSUInteger i=0;i<helper.length;i+=4)write_word(interface,pipe,0x211e30+(uint32_t)i,
            bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24);
        write_word(interface,pipe,0x211f00,1);write_word(interface,pipe,0x211f04,0x312280);
        write_word(interface,pipe,0x30d164,0x211e31);
        control(interface,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
        require(read_word(interface,pipe,0x211f00)==0xd47a5212 &&
            read_word(interface,pipe,0x28199c)==expected,@"Retained block freed with exact heap restoration",nil);
        record[@"allocator_trial"][@"allocated_and_freed"]=@YES;
    } @finally {
        cleanupDepth++;
        write_word(interface,pipe,0x30d164,0x020be8a1);
        for(NSString *key in original)write_word(interface,pipe,key.intValue,[original[key] unsignedIntValue]);
        record[@"allocator_trial"][@"restore_required"]=@(![record[@"allocator_trial"][@"allocated_and_freed"] boolValue]);
        record[@"allocator_trial"][@"restored"]=record[@"allocator_trial"][@"allocated_and_freed"] ?: @NO;
        checkpoint(@"retained stream recovery complete");cleanupDepth--;
    }
}
