// Native IOUSBHost HCI transport and restored RAM profile trials.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <IOUSBHost/IOUSBHost.h>
#include <unistd.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/file.h>
static volatile sig_atomic_t cancelled;
static unsigned cleanupDepth;

static NSMutableDictionary *record;
static NSString *output;
static BOOL quiet;

static void checkpoint(NSString *stage) {
    record[@"stage"] = stage;
    NSData *data = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingPrettyPrinted error:nil];
    if (![data writeToFile:output options:NSDataWritingAtomic error:nil])
        @throw [NSException exceptionWithName:@"Report" reason:@"Cannot save hardware checkpoint" userInfo:nil];
    if (!quiet) { printf("%s\n", stage.UTF8String); fflush(stdout); }
}

static void require(BOOL condition, NSString *operation, NSError *error) {
    if (!condition) @throw [NSException exceptionWithName:@"USB" reason:
        [NSString stringWithFormat:@"%@: %@", operation, error ?: @"Unexpected response"] userInfo:nil];
}

static NSString *hex(NSData *data) {
    NSMutableString *text = [NSMutableString string];
    const uint8_t *bytes = data.bytes;
    for (NSUInteger i = 0; i < data.length; ++i) [text appendFormat:i ? @" %02x" : @"%02x", bytes[i]];
    return text;
}

static NSData *control(IOUSBHostObject *device, uint8_t type, uint8_t request,
                       uint16_t value, uint16_t index, NSMutableData *data) {
    require(!cancelled || cleanupDepth,@"Cancelled before USB request",nil);
    IOUSBDeviceRequest setup = {.bmRequestType=type, .bRequest=request,
        .wValue=value, .wIndex=index, .wLength=(uint16_t)data.length};
    NSError *error = nil; NSUInteger transferred = 0;
    require([device sendDeviceRequest:setup data:data bytesTransferred:&transferred
                   completionTimeout:1.5 error:&error], @"EP0 transfer", error);
    require(transferred == data.length, @"EP0 length", nil);
    return [data copy];
}

static NSData *hci(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, uint16_t opcode, NSData *parameters) {
    require(!cancelled || cleanupDepth,@"Cancelled before HCI command",nil);
    NSError *error = nil;
    NSMutableData *rx = [interface ioDataWithCapacity:260 error:&error];
    require(rx != nil, @"Allocate event buffer", error);
    dispatch_semaphore_t ready = dispatch_semaphore_create(0);
    __block IOReturn status = kIOReturnError;
    __block NSUInteger received = 0;
    require([pipe enqueueIORequestWithData:rx completionTimeout:0 error:&error
        completionHandler:^(IOReturn result, NSUInteger count) {
            status = result; received = count; dispatch_semaphore_signal(ready);
        }], @"Queue interrupt IN", error);
    @try {
        uint8_t header[] = {(uint8_t)opcode, (uint8_t)(opcode >> 8), (uint8_t)parameters.length};
        NSMutableData *command = [NSMutableData dataWithBytes:header length:3];
        [command appendData:parameters];
        control(interface, 0x20, 0, 0, 0, command);
        require(dispatch_semaphore_wait(ready, dispatch_time(DISPATCH_TIME_NOW, 2*NSEC_PER_SEC)) == 0,
                @"Wait for HCI completion", nil);
        require(status == kIOReturnSuccess && received <= rx.length, @"HCI interrupt completion", nil);
    } @finally {
        require([pipe abortWithOption:IOUSBHostAbortOptionSynchronous error:&error], @"Drain interrupt IN", error);
    }
    NSData *event = [rx subdataWithRange:NSMakeRange(0, received)];
    const uint8_t *p = event.bytes;
    require(event.length >= 6 && p[0] == 0x0e && p[1]+2 == event.length &&
            p[3] == (uint8_t)opcode && p[4] == opcode >> 8 && p[5] == 0,
            [@"HCI reply: " stringByAppendingString:hex(event)], nil);
    [record[@"commands"] addObject:@{@"opcode": @(opcode), @"parameters":hex(parameters), @"event":hex(event)}];
    checkpoint(@"HCI command completed");
    return [event subdataWithRange:NSMakeRange(5, event.length-5)];
}

static uint32_t read_word(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, uint32_t address) {
    require(!(address & 3) && ((address >= 0x00200000 && address <= 0x00313ffc) ||
            (address >= 0x020b9000 && address <= 0x020b9500) ||
            (address >= 0x02046000 && address <= 0x020463fc) ||
            (address >= 0x02097000 && address <= 0x020973fc) ||
            address==0x0002018c || address==0x00020190 || address==0x00020198 ||
            address==0xe000ed00 || address==0xe000ed08 || address==0xe000ed14 || address==0x400c0818), @"Bound known memory address", nil);
    uint8_t parameters[] = {0x20, (uint8_t)address, (uint8_t)(address>>8), (uint8_t)(address>>16), (uint8_t)(address>>24)};
    NSData *reply = hci(interface, pipe, 0xfc61, [NSData dataWithBytes:parameters length:5]);
    require(reply.length == 5, @"Memory reply length", nil);
    const uint8_t *p = reply.bytes;
    uint32_t value = p[1] | (uint32_t)p[2]<<8 | (uint32_t)p[3]<<16 | (uint32_t)p[4]<<24;
    [record[@"reads"] addObject:@{@"address":[NSString stringWithFormat:@"0x%08x",address],
                                  @"value":[NSString stringWithFormat:@"0x%08x",value]}];
    checkpoint(@"RAM word read");
    return value;
}

static void write_word(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, uint32_t address, uint32_t value) {
    uint32_t allocation=[record[@"allocator_trial"][@"allocation"] unsignedIntValue];
    BOOL resident=record[@"resident_profile"]!=nil;
    uint32_t allocationBytes=[record[@"allocator_trial"][@"requested_bytes"] unsignedIntValue] ?: 4096;
    require(!(address & 3) && ((address >= 0x00211e30 && address < 0x00211f08) || address == 0x0030d164 ||
            (resident && ((allocation && address>=allocation && address<allocation+allocationBytes) ||
                          address==0x002c10d8 || address==0x0030cbc8 ||
                          (address==0x00280100 && record[@"resident_profile"][@"irq_entry"])))),
            @"Bound helper RAM write", nil);
    uint8_t parameters[] = {0x20, (uint8_t)address, (uint8_t)(address>>8), (uint8_t)(address>>16), (uint8_t)(address>>24),
        (uint8_t)value, (uint8_t)(value>>8), (uint8_t)(value>>16), (uint8_t)(value>>24)};
    [record[@"writes"] addObject:@{@"address":@(address),@"value":@(value)}];
    checkpoint(@"before RAM word write");
    NSData *reply=hci(interface,pipe,0xfc62,[NSData dataWithBytes:parameters length:sizeof(parameters)]);
    require(reply.length==1,@"RAM write acknowledgement",nil);
    require(read_word(interface,pipe,address)==value,@"RAM write readback",nil);
}

#include "native_iso_capture.h"
#include "native_reenumerate.h"
#include "native_flash_mapping.h"

static void resident_profile(IOUSBHostInterface *interface, IOUSBHostPipe *pipe, NSString *root, uint32_t allocation) {
    NSString *folder=[root stringByAppendingPathComponent:@"results/native-host-build/resident"];
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:
        [NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-profile.json"]] options:0 error:nil];
    NSData *image=[NSData dataWithContentsOfFile:[folder stringByAppendingPathComponent:@"resident-profile.bin"]];
    require(manifest && image.length && image.length<=4096 && !(image.length&3) &&
        [manifest[@"base"] unsignedIntValue]==allocation && [manifest[@"upload_bytes"] unsignedIntValue]==image.length &&
        [manifest[@"image_hex"] isEqual:hex(image)],@"Resident image matches its allocated base and manifest",nil);
    NSDictionary *symbols=manifest[@"symbols"];
    uint32_t entry=[symbols[@"dart_resident_setup"] unsignedIntValue];
    uint32_t busy=[symbols[@"dart_resident_busy"] unsignedIntValue];
    uint32_t completed=[symbols[@"dart_resident_completed"] unsignedIntValue];
    uint32_t errors=[symbols[@"dart_resident_errors"] unsignedIntValue];
    require((entry&1) && entry>=allocation && entry<allocation+4096 &&
        !(busy&3) && busy>=allocation && busy<=allocation+4092 &&
        !(completed&3) && completed>=allocation && completed<=allocation+4092 &&
        !(errors&3) && errors>=allocation && errors<=allocation+4092,@"Resident entry/state bounds",nil);
    require(read_word(interface,pipe,0x0030cbbc)==0x0030cf58 &&
        read_word(interface,pipe,0x0030cf70)==0x0020c7b1 &&
        read_word(interface,pipe,0x0030cbc8)==0 && read_word(interface,pipe,0x0030cbcc)==64,
        @"Live EP0 profile",nil);
    require(read_word(interface,pipe,0x0030d184)==0x002c1354 &&
        read_word(interface,pipe,0x002c1354)==0x0030d1c0 &&
        read_word(interface,pipe,0x002c135c)==0x0030d1c0 &&
        read_word(interface,pipe,0x0030b888)==0x01010020,@"Stock EP0 identity DMA and descriptor-ring mode",nil);
    uint32_t selector=read_word(interface,pipe,0x002c10d8);
    require(selector==0x00050600,@"Original queue allocator selector",nil);
    NSData *baseline=control(interface,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
    record[@"resident_profile"]=[@{@"base":@(allocation),@"upload_bytes":@(image.length),
        @"sha256":manifest[@"sha256"],@"symbols":symbols,@"original_selector":@(selector),
        @"responses":[NSMutableArray array],@"restored":@NO} mutableCopy];
    @try {
        const uint8_t *bytes=image.bytes;
        for(NSUInteger i=0;i<image.length;i+=4) {
            uint32_t word=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;
            write_word(interface,pipe,allocation+(uint32_t)i,word);
        }
        require(read_word(interface,pipe,busy)==0 && read_word(interface,pipe,completed)==0 &&
            read_word(interface,pipe,errors)==0,@"Resident state starts clear",nil);
        write_word(interface,pipe,0x0030d164,entry);
        checkpoint(@"resident profile installed");
        const uint8_t kinds[]={0x80,0x80,0x80,0x81};
        const uint16_t values[]={0x017e,0x027e,0x027e,0x227e}, indices[]={0,0,0,2}, lengths[]={18,9,128,96};
        NSArray *names=@[@"resident_device",@"resident_configuration",@"resident_configuration",@"resident_report"];
        for(unsigned i=0;i<4;i++) {
            NSData *reply=control(interface,kinds[i],6,values[i],indices[i],[NSMutableData dataWithLength:lengths[i]]);
            NSString *expected=manifest[@"descriptors"][names[i]];
            NSString *prefix=[expected substringToIndex:lengths[i]*3-1];
            [record[@"resident_profile"][@"responses"] addObject:@{@"value":@(values[i]),@"index":@(indices[i]),
                @"length":@(lengths[i]),@"reply":hex(reply)}];
            checkpoint(@"resident descriptor received");
            require([hex(reply) isEqual:prefix],@"Live descriptor matches the portable core",nil);
            require(read_word(interface,pipe,busy)==0,@"Native completion released the resident request",nil);
        }
        require(read_word(interface,pipe,completed)==4 && read_word(interface,pipe,errors)==0,
            @"Four native descriptor completions without errors",nil);
        require([control(interface,0x80,6,0x101,0,[NSMutableData dataWithLength:18]) isEqual:baseline],
            @"Stock descriptor path still works",nil);
        require([control(interface,0x80,6,0x17f,0,[NSMutableData dataWithLength:18]) isEqual:baseline],
            @"Resident cleanup returns the stock descriptor",nil);
        record[@"resident_profile"][@"verified"]=@YES;
    } @finally {
        cleanupDepth++;
        write_word(interface,pipe,0x0030d164,0x020be8a1);
        /* A subsequent HCI setup drains any older EP0 request before this read.
         * Keep the allocated callback storage alive unless that is confirmed. */
        require(read_word(interface,pipe,busy)==0,@"Resident EP0 request drained before freeing code",nil);
        uint32_t descriptor=read_word(interface,pipe,0x0030cbc8);
        if(descriptor) {
            require(descriptor>=allocation && descriptor<allocation+4096,@"Owned EP0 descriptor",nil);
            write_word(interface,pipe,0x0030cbc8,0);
        }
        if(read_word(interface,pipe,0x002c10d8)!=selector)write_word(interface,pipe,0x002c10d8,selector);
        record[@"resident_profile"][@"restored"]=@YES;
        checkpoint(@"resident callback and endpoint restored");
        cleanupDepth--;
    }
}

#include "native_resident_stream.h"
#include "native_stream_recovery.h"
#include "native_resident_stream192.h"
#include "native_application_read.h"
#include "native_flash_restore.h"

static void allocator_trial(IOUSBHostInterface *__strong *interfaceRef, IOUSBHostPipe *__strong *pipeRef, NSString *root, uint32_t allocationBytes, BOOL resident, void (^runResident)(uint32_t)) {
    require(read_word(*interfaceRef,*pipeRef,0x00281308)==0x00018c9b &&
            read_word(*interfaceRef,*pipeRef,0x00281310)==0x00018d25 &&
            (read_word(*interfaceRef,*pipeRef,0x00280eb8)&255)==5,@"Active native allocator profile",nil);
    uint32_t freeBytes=read_word(*interfaceRef,*pipeRef,0x0028199c);
    require(freeBytes>=allocationBytes+8,@"Active heap free bytes",nil);
    uint32_t block=read_word(*interfaceRef,*pipeRef,0x0028195c), eligible=0;
    for (unsigned count=0;count<32 && block;count++) {
        require(!(block&7) && block>=0x00280000 && block<=0x00313ff8,@"Active heap block bounds",nil);
        uint32_t next=read_word(*interfaceRef,*pipeRef,block), header=read_word(*interfaceRef,*pipeRef,block+4);
        require(!(header&0x80000000),@"Active heap block must be free",nil);
        if ((header&0xfffff)>=allocationBytes+8) { eligible=block+8; break; }
        require(next!=block,@"Active heap list progresses",nil);
        block=next;
    }
    require(eligible!=0,@"Contiguous active heap block",nil);
    NSData *helper=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:allocationBytes==6144 ? @"results/native-host-build/stream192/resident-heap-helper192.bin" : resident ?
        @"results/native-host-build/resident/resident-heap-helper.bin" : @"results/native-host-build/heap-trial-helper.bin"]];
    require(helper.length && helper.length<=192 && !(helper.length&3),@"Helper image size",nil);
    uint32_t callback=read_word(*interfaceRef,*pipeRef,0x0030d164);
    require(callback==0x020be8a1,@"Original setup callback",nil);
    NSMutableDictionary *original=[NSMutableDictionary dictionary];
    for (uint32_t at=0x00211e30; at<0x00211e30+helper.length; at+=4) {
        uint32_t value=read_word(*interfaceRef,*pipeRef,at);
        require(value==0,@"Helper scratch is unused",nil);
        original[@(at).stringValue]=@(value);
    }
    for (uint32_t at=0x00211f00; at<=0x00211f04; at+=4) {
        uint32_t value=read_word(*interfaceRef,*pipeRef,at);
        require(value==0,@"Result scratch is unused",nil);
        original[@(at).stringValue]=@(value);
    }
    record[@"allocator_trial"]=[@{@"pool":@5,@"requested_bytes":@(allocationBytes),@"free_bytes_before":@(freeBytes),
        @"eligible_allocation":@(eligible),@"original_words":original,
        @"original_callback":@(callback),@"helper_hex":hex(helper),@"restore_required":@YES} mutableCopy];
    NSData *baseline=control(*interfaceRef,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
    BOOL attempted=NO;
    @try {
        const uint8_t *bytes=helper.bytes;
        for (NSUInteger i=0;i<helper.length;i+=4) {
            uint32_t word=bytes[i]|(uint32_t)bytes[i+1]<<8|(uint32_t)bytes[i+2]<<16|(uint32_t)bytes[i+3]<<24;
            write_word(*interfaceRef,*pipeRef,0x00211e30+(uint32_t)i,word);
        }
        require(read_word(*interfaceRef,*pipeRef,0x0030d164)==callback,@"Callback still original before installation",nil);
        require(!cancelled,@"Cancelled before allocator execution",nil);
        cleanupDepth++; /* Finish recording ownership once allocation starts. */
        attempted=YES;
        write_word(*interfaceRef,*pipeRef,0x0030d164,0x00211e31);
        checkpoint(@"before allocator helper execution");
        NSData *observed=control(*interfaceRef,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
        require([observed isEqual:baseline],@"Stock descriptor through RAM helper",nil);
        uint32_t marker=read_word(*interfaceRef,*pipeRef,0x00211f00);
        uint32_t allocation=read_word(*interfaceRef,*pipeRef,0x00211f04);
        record[@"allocator_trial"][@"marker"]=@(marker);
        record[@"allocator_trial"][@"allocation"]=@(allocation);
        require(marker==(resident ? 0xd47a5211 : 0xd47a5011),@"Allocator helper completed",nil);
        require(allocation==eligible,@"Allocation from the verified free block",nil);
        require(read_word(*interfaceRef,*pipeRef,0x0030d164)==callback,@"Helper restored the callback itself",nil);
        cleanupDepth--;
        if(resident) {
            @try { runResident(allocation); }
            @finally {
                cleanupDepth++;
                if(!record[@"resident_profile"] || [record[@"resident_profile"][@"restored"] boolValue]) {
                    write_word(*interfaceRef,*pipeRef,0x00211f00,1);
                    write_word(*interfaceRef,*pipeRef,0x0030d164,0x00211e31);
                    control(*interfaceRef,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
                    require(read_word(*interfaceRef,*pipeRef,0x00211f00)==0xd47a5212 &&
                        read_word(*interfaceRef,*pipeRef,0x0030d164)==callback &&
                        read_word(*interfaceRef,*pipeRef,0x0028199c)==freeBytes,@"Resident allocation freed and heap restored",nil);
                    record[@"allocator_trial"][@"allocated_and_freed"]=@YES;
                }
                cleanupDepth--;
            }
        }
        require(read_word(*interfaceRef,*pipeRef,0x0028199c)==freeBytes,@"Allocated bytes returned to the active heap",nil);
        record[@"allocator_trial"][@"allocated_and_freed"]=@YES;
    } @finally {
        cleanupDepth++;
        checkpoint(@"restoring original callback before scratch");
        if (attempted) write_word(*interfaceRef,*pipeRef,0x0030d164,callback);
        for (NSString *key in original) write_word(*interfaceRef,*pipeRef,key.intValue,[original[key] unsignedIntValue]);
        NSData *restored=control(*interfaceRef,0x80,6,0x101,0,[NSMutableData dataWithLength:18]);
        require([restored isEqual:baseline],@"Original descriptor after restoration",nil);
        require(!resident || [record[@"allocator_trial"][@"allocated_and_freed"] boolValue],@"Resident allocation fully released",nil);
        record[@"allocator_trial"][@"restore_required"]=@NO;
        record[@"allocator_trial"][@"restored"]=@YES;
        checkpoint(@"allocator trial restored");
        cleanupDepth--;
    }
}

int main(int argc, const char **argv) { @autoreleasepool {
    BOOL flashMapRead=argc==4 && strcmp(argv[3],"--flash-map-read")==0;
    BOOL appRead=argc==4 && strcmp(argv[3],"--application-spi-read")==0;
    BOOL receiverRead=argc==4 && strcmp(argv[3],"--receiver-window-read")==0;
    BOOL restoreTrial=argc==4 && strcmp(argv[3],"--flash-restore-trial")==0;
    BOOL flashStatus=argc==4 && strcmp(argv[3],"--flash-status")==0;
    BOOL bootContext=argc==4 && strcmp(argv[3],"--boot-context")==0;
    BOOL cpuContext=argc==4 && strcmp(argv[3],"--cpu-context")==0;
    BOOL resetContext=argc==4 && strcmp(argv[3],"--reset-context")==0;
    BOOL recovering=argc==5 && strcmp(argv[3],"--recover-stream")==0;
    BOOL irqStream=argc==4 && strcmp(argv[3],"--stream-irq")==0;
    BOOL fullRate=irqStream || (argc==4 && strcmp(argv[3],"--stream-192")==0);
    BOOL streamTrial=fullRate || (argc==4 && strcmp(argv[3],"--stream-trial")==0);
    BOOL resident=restoreTrial || flashStatus || appRead || receiverRead || streamTrial || (argc==4 && strcmp(argv[3],"--resident-profile")==0);
    testIsoPolicy=argc==4 && strcmp(argv[3],"--iso-policy")==0;
    BOOL isoIdle=testIsoPolicy || (argc==4 && strcmp(argv[3],"--iso-idle")==0);
    signal(SIGINT,cancel_capture); signal(SIGTERM,cancel_capture);
    BOOL trial=resident || (argc==4 && strcmp(argv[3],"--allocator-trial")==0);
    BOOL receiverContext=argc==4 && strcmp(argv[3],"--receiver-context")==0;
    BOOL heapContext=receiverContext || (argc==4 && strcmp(argv[3],"--heap-context")==0);
    BOOL profileContext=argc==4 && strcmp(argv[3],"--profile-context")==0;
    if (argc != 3 && !trial && !heapContext && !profileContext && !isoIdle && !recovering && !resetContext && !cpuContext && !bootContext && !flashMapRead) { fprintf(stderr,"Usage: bt600-native-hci REPOSITORY REPORT.json [--allocator-trial|--resident-profile|--stream-trial|--stream-192|--stream-irq|--iso-idle|--iso-policy|--heap-context|--receiver-context|--profile-context|--reset-context|--cpu-context|--boot-context|--flash-map-read|--application-spi-read|--receiver-window-read|--flash-status|--flash-restore-trial|--recover-stream PRIOR.json]\n"); return 2; }
    NSString *root = [NSString stringWithUTF8String:argv[1]];
    output = [NSString stringWithUTF8String:argv[2]];
    NSDictionary *approval = [NSJSONSerialization JSONObjectWithData:
        [NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:@"results/hardware-resume.json"]]
        options:0 error:nil];
    if (![approval[@"user_authorized_hardware"] boolValue] ||
        ![approval[@"operations"] containsObject:(restoreTrial ? @"native_flash_restore_trial" : (bootContext || flashMapRead || flashStatus || appRead || receiverRead) ? @"native_boot_read" : resetContext ? @"native_reenumeration" : recovering ? @"native_resident_stream" : streamTrial ? @"native_resident_stream" : isoIdle ? @"native_iso_capture" : resident ? @"native_resident_profile" :
            trial ? @"native_allocator_trial" : @"native_hci_read")]) return 3;
    if(fullRate && ![approval[@"operations"] containsObject:@"native_reenumeration"])return 3;
    if(irqStream && ![approval[@"operations"] containsObject:@"native_irq_stream"])return 3;
    int lease=open("/private/tmp/fauxpod-bt600-native.lock",O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);
    if(lease<0 || flock(lease,LOCK_EX|LOCK_NB)) {
        if(lease>=0)close(lease);
        fprintf(stderr,"Another native BT600 worker owns the device lease, or the lease is unavailable.\n");
        return 4;
    }
    ftruncate(lease,0); dprintf(lease,"%d\n",getpid());
    record = [@{@"pid": @(getpid()), @"transport": @"IOUSBHost direct interrupt pipe 0x81",
        @"persistent_writes": @(restoreTrial), @"ram_writes": @(trial || recovering || flashMapRead),
        @"commands": [NSMutableArray array], @"reads": [NSMutableArray array],@"writes":[NSMutableArray array]} mutableCopy];
    __block IOUSBHostDevice *device = nil; __block IOUSBHostInterface *interface = nil; __block IOUSBHostPipe *pipe = nil;
    int original = -1; BOOL changed = NO, success = NO;
    io_service_t service = 0; io_iterator_t iterator = 0;
    @try {
        checkpoint(@"before native device open");
        CFMutableDictionaryRef matching = [IOUSBHostDevice createMatchingDictionaryWithVendorID:@0x0b05 productID:@0x1d70
            bcdDevice:nil deviceClass:nil deviceSubclass:nil deviceProtocol:nil speed:nil productIDArray:nil];
        require(IOServiceGetMatchingServices(kIOMainPortDefault, matching, &iterator) == KERN_SUCCESS,
                @"Match BT600", nil);
        service = IOIteratorNext(iterator);
        io_service_t extra = IOIteratorNext(iterator);
        if (extra) IOObjectRelease(extra);
        require(service && !extra, @"Exactly one BT600", nil);
        NSError *error = nil;
        device = [[IOUSBHostDevice alloc] initWithIOService:service options:IOUSBHostObjectInitOptionsNone
            queue:nil error:&error interestHandler:nil];
        require(device != nil, @"Native device open", error);
        NSData *state = control(device, 0x80, 8, 0, 0, [NSMutableData dataWithLength:1]);
        original = ((const uint8_t *)state.bytes)[0]; record[@"original_configuration"] = @(original);
        require(original == 0 || original == 1, @"Expected configuration 0 or 1", nil);
        NSData *header = control(device,0x80,6,0x200,0,[NSMutableData dataWithLength:9]);
        const uint8_t *h = header.bytes; NSUInteger total = h[2] | (NSUInteger)h[3]<<8;
        require(total >= 9 && total <= 1024, @"Configuration length", nil);
        NSData *configuration = control(device,0x80,6,0x200,0,[NSMutableData dataWithLength:total]);
        record[@"configuration_descriptor"] = hex(configuration);
        const uint8_t *b = configuration.bytes; BOOL hciInterface = NO, eventPipe = NO;
        for (NSUInteger i=0; i+2<=total;) {
            require(b[i]>=2 && i+b[i]<=total, @"Descriptor bounds", nil);
            if (b[i+1]==4) { require(b[i]>=9,@"Interface descriptor",nil); hciInterface=b[i+2]==0 && b[i+3]==0; }
            if (b[i+1]==5 && hciInterface) { require(b[i]>=7,@"Endpoint descriptor",nil);
                if (b[i+2]==0x81 && (b[i+3]&3)==3 && (b[i+4]|(uint16_t)b[i+5]<<8)>0) eventPipe=YES; }
            i+=b[i];
        }
        require(eventPipe, @"Interface 0 alternate 0 interrupt endpoint 0x81", nil);
        checkpoint(@"configuration and interrupt descriptor validated");
        if (original==0 || !device.configurationDescriptor) { changed=YES;
            if(original==1)require([device configureWithValue:0 matchInterfaces:YES error:&error],@"Clear stale device configuration before publishing interfaces",error);
            require([device configureWithValue:1 matchInterfaces:YES error:&error], @"Select configuration 1", error); }
        checkpoint(@"configuration selected");
        io_service_t interfaceService = 0;
        for (int attempt=0; attempt<10 && !interfaceService; ++attempt) {
            CFMutableDictionaryRef query=[IOUSBHostInterface createMatchingDictionaryWithVendorID:@0x0b05 productID:@0x1d70
                bcdDevice:nil interfaceNumber:@0 configurationValue:@1 interfaceClass:nil interfaceSubclass:nil
                interfaceProtocol:nil speed:nil productIDArray:nil];
            interfaceService=IOServiceGetMatchingService(kIOMainPortDefault,query);
            if (!interfaceService) usleep(50000);
        }
        require(interfaceService != 0,@"Find HCI interface 0",nil);
        interface=[[IOUSBHostInterface alloc] initWithIOService:interfaceService options:IOUSBHostObjectInitOptionsNone
            queue:nil error:&error interestHandler:nil];
        IOObjectRelease(interfaceService);
        require(interface != nil,@"Native interface open",error);
        checkpoint(@"native HCI interface opened");
        pipe=[interface copyPipeWithAddress:0x81 error:&error];
        require(pipe != nil,@"Open interrupt pipe 0x81",error);
        checkpoint(@"interrupt pipe opened");
        NSData *rom=hci(interface,pipe,0xfc6d,[NSData data]);
        require(rom.length==2 && ((const uint8_t *)rom.bytes)[1]==1,@"CU ROM version 1",nil);
        record[@"rom_version"]=@1;
        uint32_t runtime=read_word(interface,pipe,0x002c12cc);
        require(runtime>=0x00300000 && runtime<=0x00313f00,@"Runtime pointer bounds",nil);
        uint32_t composite=read_word(interface,pipe,runtime+0x40);
        require(composite>=0x00300000 && composite<=0x00313f00,@"Composite pointer bounds",nil);
        uint32_t driver=read_word(interface,pipe,composite+0x30);
        require(driver>=0x00300000 && driver<=0x00313f00,@"Driver pointer bounds",nil);
        uint32_t callback=read_word(interface,pipe,driver+0x34);
        require((callback&1) && callback>=0x02000000 && callback<0x02200000,@"Setup entry bounds",nil);
        record[@"runtime"]=@(runtime); record[@"composite"]=@(composite);
        record[@"driver"]=@(driver); record[@"setup_callback"]=@(callback);
        if(flashMapRead) {quiet=YES;flash_mapping_read(interface,pipe,root);quiet=NO;}
        if(bootContext) {
            quiet=YES;
            for(uint32_t base=0x02046000;base<=0x02097000;base+=0x51000) {
                for(uint32_t at=base+0x110;at<base+0x180;at+=4)read_word(interface,pipe,at);
                read_word(interface,pipe,base+0x2a0);
            }
            quiet=NO;checkpoint(@"live boot headers read");
        }
        if(cpuContext) {
            for(uint32_t i=0;i<4;i++) {
                const uint32_t addresses[]={0xe000ed00,0xe000ed08,0xe000ed14,0x400c0818};
                read_word(interface,pipe,addresses[i]);
            }
        }
        if (profileContext) {
            quiet=YES;
            const uint32_t words[]={0x00281308,0x002812b0,0x002812b4,0x002c10d8,
                0x0030b888,0x0030b88c,0x0030d184,0x0030cbbc,0x0030cbc8,0x0030cbcc,
                0x0030cf70,0x0020f19c,0x0020f1a0,0x0020f1a4,0x0020c7b0,0x0020c7b4,
                0x020b937c,0x020b9380,0x020b911c,0x020b9120,0x020b9124,0x020b9128};
            for(unsigned i=0;i<sizeof(words)/sizeof(words[0]);i++)read_word(interface,pipe,words[i]);
            uint32_t req=read_word(interface,pipe,0x0030d184);
            for(uint32_t at=req;at<req+44;at+=4)read_word(interface,pipe,at);
            uint32_t pcd=read_word(interface,pipe,runtime);
            for(uint32_t at=pcd+0x2c;at<pcd+0x2c+0xb8;at+=4)read_word(interface,pipe,at);
            quiet=NO;
        }
        if(profileContext) {
            for(uint32_t at=0x0030be1c;at<=0x0030be38;at+=4)read_word(interface,pipe,at);
            read_word(interface,pipe,0x0030c55c);read_word(interface,pipe,0x0030c560);
            for(uint32_t at=0x00312580;at<0x003125d0;at+=4)read_word(interface,pipe,at);
        }
        if (heapContext) {
            quiet=YES;
            for (uint32_t at=0x00281934;at<=0x002819d4;at+=4) read_word(interface,pipe,at);
            for (uint32_t at=0x002c10d8;at<=0x002c10dc;at+=4) read_word(interface,pipe,at);
            for (uint32_t at=0x00211e30;at<0x00211e94;at+=4) require(read_word(interface,pipe,at)==0,@"Recovered helper scratch",nil);
            require(read_word(interface,pipe,0x00211f00)==0 && read_word(interface,pipe,0x00211f04)==0,@"Recovered result scratch",nil);
            uint32_t head=read_word(interface,pipe,0x0028195c);
            require(head>=0x00280000 && head<=0x00313ff8,@"Active heap free-list head",nil);
            for (unsigned block=0;block<32 && head;block++) {
                uint32_t next=read_word(interface,pipe,head);
                read_word(interface,pipe,head+4);
                if (!next || next==0x0040b7f8) break;
                require(next>=0x00280000 && next<=0x00313ff8 && next!=head,@"Active heap free-list link",nil);
                head=next;
            }
            quiet=NO;
        }
        if(receiverContext) {
            quiet=YES;
            NSMutableArray *passes=[NSMutableArray array];
            record[@"receiver_ram_context"]=@{@"start":@0x00287400,@"bytes":@0xcb0,@"passes":passes,@"read_only":@YES};
            for(unsigned pass=0;pass<2;pass++) {
                NSMutableData *data=[NSMutableData data];
                for(uint32_t at=0x00287400;at<0x002880b0;at+=4) {
                    uint32_t word=read_word(interface,pipe,at);
                    const uint8_t bytes[]={(uint8_t)word,(uint8_t)(word>>8),(uint8_t)(word>>16),(uint8_t)(word>>24)};
                    [data appendBytes:bytes length:4];
                }
                NSString *path=[output.stringByDeletingPathExtension stringByAppendingFormat:@".pass%u.bin",pass+1];NSError *error=nil;
                require([data writeToFile:path options:NSDataWritingAtomic error:&error],@"Save receiver RAM context",error);
                [passes addObject:@{@"path":path,@"bytes":@(data.length)}];
            }
            quiet=NO;checkpoint(@"receiver RAM context saved twice");
        }
        if(streamTrial) {
            iso_idle(device,configuration); record[@"iso_warmup"]=record[@"iso_capture"];
            [record removeObjectForKey:@"iso_capture"];
        }
        if (trial) { quiet=YES; allocator_trial(&interface,&pipe,root,fullRate ? 6144 : 4096,resident,^(uint32_t allocation) {
            if(restoreTrial || flashStatus)flash_restore_trial(interface,pipe,root,allocation,flashStatus);
            else if(appRead || receiverRead)application_spi_read(interface,pipe,root,allocation,receiverRead);
            else if(fullRate)resident_stream192(&device,&interface,&pipe,root,allocation,irqStream);
            else if(streamTrial)resident_stream(device,interface,pipe,root,allocation);
            else resident_profile(interface,pipe,root,allocation);
        }); quiet=NO; }
        if(resetContext) {
            uint32_t heapBefore=read_word(interface,pipe,0x0028199c);
            native_reenumerate(&device,&interface,&pipe);
            record[@"reenumeration"][@"heap_before"]=@(heapBefore);
            record[@"reenumeration"][@"heap_after"]=@(read_word(interface,pipe,0x0028199c));
            require(read_word(interface,pipe,0x002c12cc)==runtime && read_word(interface,pipe,driver+0x34)==callback,
                @"RAM USB context and setup callback survived reenumeration",nil);
            record[@"reenumeration"][@"ram_context_preserved"]=@YES;
        }
        if(recovering) { quiet=YES; recover_stream(interface,pipe,root,[NSString stringWithUTF8String:argv[4]]); quiet=NO; }
        if(isoIdle)iso_idle(device,configuration);
        success=YES;
    } @catch (NSException *exception) {
        record[@"error"]=exception.reason ?: exception.name;
    } @finally {
        cleanupDepth++;
        if (pipe) { NSError *error=nil; [pipe abortWithOption:IOUSBHostAbortOptionSynchronous error:&error]; pipe=nil; }
        if (interface) [interface destroy];
        if (changed && device) { NSError *error=nil;
            BOOL restored=[device configureWithValue:(NSUInteger)original matchInterfaces:YES error:&error];
            record[@"configuration_restored"]=@(restored);
            if (!restored) { success=NO; record[@"restore_error"]=error.description ?: @"Restore failed"; }
        }
        if (device) [device destroy];
        if (service) IOObjectRelease(service);
        if (iterator) IOObjectRelease(iterator);
        record[@"cancelled"]=@(cancelled!=0); record[@"success"]=@(success); checkpoint(success ? @"complete" : @"failed");
    }
    printf("Report: %s\n",output.UTF8String);
    if (!success) fprintf(stderr,"%s\n",[record[@"error"] UTF8String]);
    flock(lease,LOCK_UN);close(lease);
    return cancelled ? 130 : success ? 0 : 1;
}}
