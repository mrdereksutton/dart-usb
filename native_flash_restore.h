/* Fixed 32-byte program and restoration of a verified FF application-pad sector. */
static void flash_restore_trial(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, NSString *root, uint32_t allocation, BOOL statusOnly) {
    NSString *folder=[root stringByAppendingPathComponent:@"results/native-host-build/flash-restore"];
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:
        [folder stringByAppendingPathComponent:@"resident-flash-read.json"]] options:0 error:nil];
    NSData *image=[NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-flash-read.bin"]];
    require(manifest && [manifest[@"allows_flash_restore_trial"] boolValue] && image.length && image.length<=4096 && !(image.length&3) &&
        [manifest[@"base"] unsignedIntValue]==allocation && [manifest[@"image_hex"] isEqual:hex(image)] &&
        [manifest[@"trial_cpu_address"] unsignedIntValue]==0x020de000 && [manifest[@"trial_sector_bytes"] unsignedIntValue]==4096,
        @"Fixed-sector restoration image",nil);
    NSDictionary *symbols=manifest[@"symbols"];uint32_t entry=[symbols[@"dart_resident_setup"] unsignedIntValue];
    require((entry&1) && entry>=allocation && entry<allocation+4096,@"Restoration entry inside allocation",nil);
    for(NSString *name in symbols) {uint32_t address=[symbols[name] unsignedIntValue];require(address>=allocation && address<allocation+4096,@"Restoration symbols inside allocation",nil);}
    require(read_word(interface,pipe,0x00020190)==0xcc35 && read_word(interface,pipe,0x00020198)==0xcd83 &&
        read_word(interface,pipe,0x0028033c)==0x57b9 && read_word(interface,pipe,0x00280340)==0x58c1 &&
        read_word(interface,pipe,0x00280338)==0x55af && read_word(interface,pipe,0x0028031c)==0x4e59 &&
        !(read_word(interface,pipe,0x002803a0)&0x400) && (read_word(interface,pipe,0x00280740)&0x00ff0000)==0x00500000 &&
        read_word(interface,pipe,0x0030d164)==0x020be8a1 && read_word(interface,pipe,0x0030cbc8)==0 &&
        read_word(interface,pipe,0x0030cbcc)==64,@"Known native storage and idle EP0 profile",nil);
    NSData *backup=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"results/sprint-20261019/boot-analysis/original-app-partition.spi.bin"]];
    require(backup.length==0x48000,@"Verified raw application backup present",nil);
    NSData *original=[backup subdataWithRange:NSMakeRange(0x47000,4096)];
    uint8_t ff[4096];memset(ff,255,sizeof(ff));require([original isEqual:[NSData dataWithBytes:ff length:sizeof(ff)]],@"Backup padding sector is all FF",nil);
    uint8_t patternBytes[32];for(unsigned i=0;i<32;i++)patternBytes[i]=(uint8_t)(0x20+i);
    NSMutableData *programmed=[original mutableCopy];[programmed replaceBytesInRange:NSMakeRange(0,32) withBytes:patternBytes];
    uint32_t selector=read_word(interface,pipe,0x002c10d8);
    record[@"resident_profile"]=[@{@"base":@(allocation),@"sha256":manifest[@"sha256"],@"symbols":symbols,@"restored":@NO} mutableCopy];
    NSMutableDictionary *trial=[@{@"cpu_address":@0x020de000,@"spi_offset":@0xde000,@"sector_bytes":@4096,
        @"program_bytes":@32,@"pattern":hex([NSData dataWithBytes:patternBytes length:32]),@"erase_type":@1,
        @"program_attempted":@NO,@"flash_restored":@NO,@"status_only":@(statusOnly)} mutableCopy];record[@"flash_restore_trial"]=trial;
    NSData *(^readSector)(void)=^NSData * {
        NSMutableData *data=[NSMutableData data];
        for(uint16_t page=568;page<576;page++)[data appendData:control(interface,0x80,6,0x17b,page,[NSMutableData dataWithLength:512])];
        return data;
    };
    void (^save)(NSData *,NSString *)=^(NSData *data,NSString *stage) {
        NSString *path=[output.stringByDeletingPathExtension stringByAppendingFormat:@".%@.bin",stage];NSError *error=nil;
        require([data writeToFile:path options:NSDataWritingAtomic error:&error],@"Save restoration bytes",error);trial[[stage stringByAppendingString:@"_path"]]=path;
    };
    BOOL installationAttempted=NO, installed=NO;
    @try {
        const uint8_t *bytes=image.bytes;
        for(NSUInteger i=0;i<image.length;i+=4) {uint32_t word=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;write_word(interface,pipe,allocation+(uint32_t)i,word);}
        require(read_word(interface,pipe,[symbols[@"dart_trial_attempted"] unsignedIntValue])==0 &&
            read_word(interface,pipe,[symbols[@"dart_resident_busy"] unsignedIntValue])==0,
            @"Restoration state is initially idle",nil);
        installationAttempted=YES;
        write_word(interface,pipe,0x0030d164,entry);
        installed=YES;
        NSData *before=readSector();save(before,@"before");require([before isEqual:original],@"Live raw sector matches preserved FF original",nil);
        control(interface,0x80,6,0x17a,2,[NSMutableData dataWithLength:18]);
        for(NSString *name in @[@"sr1",@"sr2",@"bp_level",@"status_result"])
            trial[name]=@(read_word(interface,pipe,[symbols[[@"dart_trial_" stringByAppendingString:name]] unsignedIntValue]));
        require([trial[@"status_result"] unsignedIntValue]==0x18,@"Flash protection status read completed",nil);
        checkpoint(@"read-only flash protection status recorded");
        if(!statusOnly) {
            checkpoint(@"before fixed 32-byte padding program");
            control(interface,0x80,6,0x17a,0,[NSMutableData dataWithLength:18]);
            trial[@"program_attempted"]=@(read_word(interface,pipe,[symbols[@"dart_trial_attempted"] unsignedIntValue]));
            trial[@"program_status"]=@(read_word(interface,pipe,[symbols[@"dart_trial_program_status"] unsignedIntValue]));
            require([trial[@"program_attempted"] boolValue] && [trial[@"program_status"] unsignedIntValue]==0x18,@"Fixed padding program completed",nil);
            control(interface,0x80,6,0x17a,2,[NSMutableData dataWithLength:18]);
            require(read_word(interface,pipe,[symbols[@"dart_trial_sr1"] unsignedIntValue])==0x34 &&
                read_word(interface,pipe,[symbols[@"dart_trial_sr2"] unsignedIntValue])==2 &&
                read_word(interface,pipe,[symbols[@"dart_trial_reprotect_status"] unsignedIntValue])==0x18,
                @"Original flash protection restored after program",nil);
            trial[@"program_protection_restored"]=@YES;
            NSData *observed=readSector();save(observed,@"programmed");
            trial[@"program_readback_verified"]=@([observed isEqual:programmed]);checkpoint(@"padding program read back");
            require([observed isEqual:programmed],@"Only the fixed 32-byte pattern changed",nil);
        }
    } @finally {
        cleanupDepth++;
        @try {
            if(installed) {
                uint32_t attempted=read_word(interface,pipe,[symbols[@"dart_trial_attempted"] unsignedIntValue]);
                trial[@"program_attempted"]=@(attempted);
                if(attempted) {
                    checkpoint(@"before restoring padding with sector erase");
                    control(interface,0x80,6,0x17a,1,[NSMutableData dataWithLength:18]);
                    uint32_t status=read_word(interface,pipe,[symbols[@"dart_trial_erase_status"] unsignedIntValue]);trial[@"erase_status"]=@(status);
                    require(status==0x18,@"Fixed sector erase completed",nil);
                    control(interface,0x80,6,0x17a,2,[NSMutableData dataWithLength:18]);
                    require(read_word(interface,pipe,[symbols[@"dart_trial_sr1"] unsignedIntValue])==0x34 &&
                        read_word(interface,pipe,[symbols[@"dart_trial_sr2"] unsignedIntValue])==2 &&
                        read_word(interface,pipe,[symbols[@"dart_trial_reprotect_status"] unsignedIntValue])==0x18,
                        @"Original flash protection restored after erase",nil);
                    trial[@"erase_protection_restored"]=@YES;
                }
                NSData *after=readSector();save(after,@"after");
                require([after isEqual:original],@"Every original padding byte restored",nil);trial[@"flash_restored"]=@YES;
                for(NSString *name in @[@"ipsr",@"primask",@"basepri"])
                    trial[name]=@(read_word(interface,pipe,[symbols[[@"dart_trial_" stringByAppendingString:name]] unsignedIntValue]));
                trial[@"read_completions"]=@(read_word(interface,pipe,[symbols[@"dart_resident_completed"] unsignedIntValue]));
                trial[@"read_errors"]=@(read_word(interface,pipe,[symbols[@"dart_resident_errors"] unsignedIntValue]));
                require([trial[@"read_errors"] unsignedIntValue]==0,@"No native sector-read errors",nil);
                checkpoint(@"padding restored and verified");
            }
        } @finally {
            @try {
                if(installationAttempted)write_word(interface,pipe,0x0030d164,0x020be8a1);
                /* A partial upload has never queued a resident request. */
                require((!installed || read_word(interface,pipe,[symbols[@"dart_resident_busy"] unsignedIntValue])==0) &&
                    read_word(interface,pipe,0x0030d164)==0x020be8a1 &&
                    read_word(interface,pipe,0x0030cbc8)==0 && read_word(interface,pipe,0x002c10d8)==selector,
                    @"Restoration endpoint drained and callback returned",nil);
                record[@"resident_profile"][@"restored"]=@YES;checkpoint(@"flash trial RAM profile restored");
            } @finally { cleanupDepth--; }
        }
    }
}
