/* Export one of two fixed known flash windows, twice, using native SPI reads. */
static void application_spi_read(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, NSString *root, uint32_t allocation, BOOL receiverWindow) {
    uint32_t source=receiverWindow ? 0x02015000 : 0x02097000, bytesPerPass=receiverWindow ? 0x31000 : 0x48000;
    uint16_t pages=(uint16_t)(bytesPerPass/512);
    NSString *reportKey=receiverWindow ? @"receiver_window_spi_read" : @"application_spi_read";
    NSString *folder=[root stringByAppendingPathComponent:receiverWindow ? @"results/native-host-build/receiver-window" : @"results/native-host-build/flash-read"];
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:
        [folder stringByAppendingPathComponent:@"resident-flash-read.json"]] options:0 error:nil];
    NSData *image=[NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-flash-read.bin"]];
    require(manifest && image.length && image.length<=4096 && !(image.length&3) &&
        ![manifest[@"allows_flash_restore_trial"] boolValue] &&
        [manifest[@"source_address"] unsignedIntValue]==source && [manifest[@"partition_bytes"] unsignedIntValue]==bytesPerPass &&
        [manifest[@"pages"] unsignedIntValue]==pages && [manifest[@"base"] unsignedIntValue]==allocation &&
        [manifest[@"image_hex"] isEqual:hex(image)],@"Checked read-only SPI-export image",nil);
    NSDictionary *symbols=manifest[@"symbols"];
    uint32_t entry=[symbols[@"dart_resident_setup"] unsignedIntValue],busy=[symbols[@"dart_resident_busy"] unsignedIntValue];
    require((entry&1) && entry>=allocation && entry<allocation+4096,@"SPI-export entry in allocation",nil);
    for(NSString *name in symbols) {uint32_t address=[symbols[name] unsignedIntValue];require(address>=allocation && address<allocation+4096,@"SPI-export symbols in allocation",nil);}
    require(read_word(interface,pipe,0x0002018c)==0x0000cbb5 && read_word(interface,pipe,0x00280348)==0x000056ab &&
        read_word(interface,pipe,0x002802ec)==0x00202c6f && read_word(interface,pipe,0x0030d164)==0x020be8a1 &&
        read_word(interface,pipe,0x0030cbc8)==0 && read_word(interface,pipe,0x0030cbcc)==64,@"Native SPI/EP0 profile",nil);
    uint32_t selector=read_word(interface,pipe,0x002c10d8);
    NSData *expected;
    if(receiverWindow) {
        NSData *capture=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"results/bt600-targets-20261017T101939.145845Z.bin"]];
        require(capture.length==0x200000,@"Preserved complete CPU flash view",nil);
        expected=[capture subdataWithRange:NSMakeRange(0x15000,bytesPerPass)];
        const uint8_t *saved=expected.bytes;
        for(NSUInteger i=0;i<expected.length;i++)require(saved[i]==255,@"Receiver window was blank in original capture",nil);
    } else expected=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"results/sprint-20261019/boot-analysis/original-app-partition.cpu-view.bin"]];
    require(expected.length==bytesPerPass,@"Preserved original flash window",nil);
    record[@"resident_profile"]=[@{@"base":@(allocation),@"sha256":manifest[@"sha256"],@"symbols":symbols,@"restored":@NO} mutableCopy];
    NSMutableArray *passes=[NSMutableArray array];
    record[reportKey]=[@{@"cpu_address":@(source),@"spi_offset":@(source-0x02000000),@"bytes_per_pass":@(bytesPerPass),
        @"page_bytes":@512,@"pages_per_pass":@(pages),@"passes":passes,@"read_only":@YES,@"restored":@NO} mutableCopy];
    @try {
        const uint8_t *bytes=image.bytes;
        for(NSUInteger i=0;i<image.length;i+=4) {uint32_t word=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;write_word(interface,pipe,allocation+(uint32_t)i,word);}
        write_word(interface,pipe,0x0030d164,entry);
        for(unsigned pass=0;pass<2;pass++) {
            NSMutableData *received=[NSMutableData data];
            for(uint16_t page=0;page<pages;page++) {
                NSData *data=control(interface,0x80,6,0x017b,page,[NSMutableData dataWithLength:512]);
                [received appendData:data];
                require([data isEqual:[expected subdataWithRange:NSMakeRange((NSUInteger)page*512,512)]],@"SPI page matches original CPU view",nil);
                if(!(page%32)) {record[reportKey][@"completed_pages"]=@((unsigned)page+pass*pages+1);checkpoint(@"native SPI window pages received");}
            }
            NSString *path=[output.stringByDeletingPathExtension stringByAppendingFormat:@".pass%u.bin",pass+1];NSError *error=nil;
            require([received writeToFile:path options:NSDataWritingAtomic error:&error],@"Save native SPI application copy",error);
            [passes addObject:@{@"path":path,@"bytes":@(received.length),@"matches_cpu_capture":@([received isEqual:expected])}];
            record[reportKey][@"completed_pages"]=@((pass+1)*pages);
            checkpoint(@"native SPI application copy saved");
        }
        uint32_t completed=read_word(interface,pipe,[symbols[@"dart_resident_completed"] unsignedIntValue]);
        uint32_t errors=read_word(interface,pipe,[symbols[@"dart_resident_errors"] unsignedIntValue]);
        record[reportKey][@"native_completions"]=@(completed);
        record[reportKey][@"native_errors"]=@(errors);
        require(completed==2u*pages && errors==0,@"Both SPI copies completed without errors",nil);
    } @finally {
        cleanupDepth++;
        write_word(interface,pipe,0x0030d164,0x020be8a1);
        require(read_word(interface,pipe,busy)==0 && read_word(interface,pipe,0x0030cbc8)==0 &&
            read_word(interface,pipe,0x002c10d8)==selector,@"SPI-export endpoint drained and restored",nil);
        record[@"resident_profile"][@"restored"]=@YES;record[reportKey][@"restored"]=@YES;
        checkpoint(@"SPI-export callback and endpoint restored");cleanupDepth--;
    }
}
