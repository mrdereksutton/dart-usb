/* Two 16-byte SPI reads. No erase/program API is reachable from this helper. */
static void flash_mapping_read(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, NSString *root) {
    require(read_word(interface,pipe,0x0002018c)==0x0000cbb5 &&
        read_word(interface,pipe,0x00280348)==0x000056ab &&
        read_word(interface,pipe,0x002802ec)==0x00202c6f &&
        read_word(interface,pipe,0x0030d164)==0x020be8a1,@"Known native SPI read path and setup callback",nil);
    NSData *helper=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"results/native-host-build/flash-map-read.bin"]];
    require(helper.length && helper.length<=144 && !(helper.length&3),@"Bound SPI-read helper",nil);
    NSMutableDictionary *original=[NSMutableDictionary dictionary];
    for(uint32_t at=0x00211e30;at<0x00211f08;at+=4) {
        uint32_t value=read_word(interface,pipe,at);
        require(value==0,@"SPI-read scratch is unused",nil);original[@(at).stringValue]=@(value);
    }
    NSMutableArray *checks=[NSMutableArray array];
    record[@"flash_mapping"]=[@{@"checks":checks,@"original_words":original,@"helper_hex":hex(helper),
        @"read_only":@YES,@"restored":@NO,@"program_erase_restore_verified":@NO} mutableCopy];
    NSData *baseline=control(interface,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
    @try {
        const uint8_t *bytes=helper.bytes;
        for(NSUInteger i=0;i<helper.length;i+=4) {
            uint32_t value=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;
            write_word(interface,pipe,0x00211e30+(uint32_t)i,value);
        }
        const uint32_t sources[]={0x02046110,0x02097110};
        for(unsigned index=0;index<2;index++) {
            uint32_t source=sources[index];NSMutableData *expected=[NSMutableData data];
            for(uint32_t at=source;at<source+16;at+=4) {uint32_t value=read_word(interface,pipe,at);[expected appendBytes:&value length:4];}
            write_word(interface,pipe,0x00211efc,source);write_word(interface,pipe,0x00211f00,0);
            write_word(interface,pipe,0x00211f04,0);write_word(interface,pipe,0x0030d164,0x00211e31);
            require([control(interface,0x80,6,0x101,0,[NSMutableData dataWithLength:18]) isEqual:baseline],@"Stock descriptor through SPI-read helper",nil);
            require(read_word(interface,pipe,0x0030d164)==0x020be8a1 &&
                read_word(interface,pipe,0x00211f00)==0xd47a6001,@"SPI-read helper completed and unhooked",nil);
            uint32_t status=read_word(interface,pipe,0x00211f04);NSMutableData *received=[NSMutableData data];
            for(uint32_t at=0x00211ec0;at<0x00211ed0;at+=4) {uint32_t value=read_word(interface,pipe,at);[received appendBytes:&value length:4];}
            [checks addObject:@{@"cpu_address":@(source),@"spi_offset":@(source-0x02000000),@"status":@(status),
                @"expected":hex(expected),@"received":hex(received),@"matches":@([expected isEqual:received])}];
            checkpoint(@"native SPI header compared");
            require(status==0x18 && [expected isEqual:received],@"Native SPI bytes match CPU header",nil);
        }
    } @finally {
        cleanupDepth++;
        write_word(interface,pipe,0x0030d164,0x020be8a1);
        for(NSString *key in original)write_word(interface,pipe,key.intValue,[original[key] unsignedIntValue]);
        require([control(interface,0x80,6,0x101,0,[NSMutableData dataWithLength:18]) isEqual:baseline],@"Descriptor after SPI-read restoration",nil);
        record[@"flash_mapping"][@"restored"]=@YES;checkpoint(@"SPI-read helper restored");
        cleanupDepth--;
    }
}
