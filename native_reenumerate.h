/* Reopen all handles after IOUSBHostDevice terminates and re-enumerates them. */
static void native_reenumerate(IOUSBHostDevice *__strong *deviceRef,
    IOUSBHostInterface *__strong *interfaceRef, IOUSBHostPipe *__strong *pipeRef) {
    IOUSBHostDevice *device=*deviceRef; NSError *error=nil; uint64_t oldID=0;
    IORegistryEntryGetRegistryEntryID(device.ioService,&oldID);
    if(*pipeRef)require([*pipeRef abortWithOption:IOUSBHostAbortOptionSynchronous error:&error],@"Drain HCI before reset",error);
    *pipeRef=nil;
    if(*interfaceRef)[*interfaceRef destroy];*interfaceRef=nil;
    record[@"reenumeration"]=[@{@"old_registry_id":@(oldID),@"reset_requested":@YES} mutableCopy];
    checkpoint(@"before native device reenumeration");
    require([device resetWithError:&error],@"Native USB reenumeration",error);
    [device destroy];*deviceRef=nil;
    IOUSBHostDevice *replacement=nil; uint64_t newID=0;
    for(unsigned attempt=0;attempt<100 && !replacement;attempt++) {
        io_iterator_t iterator=0;
        CFMutableDictionaryRef matching=[IOUSBHostDevice createMatchingDictionaryWithVendorID:@0x0b05 productID:@0x1d70
            bcdDevice:nil deviceClass:nil deviceSubclass:nil deviceProtocol:nil speed:nil productIDArray:nil];
        require(IOServiceGetMatchingServices(kIOMainPortDefault,matching,&iterator)==KERN_SUCCESS,@"Find reenumerated BT600",nil);
        io_service_t service;
        while((service=IOIteratorNext(iterator))) {
            uint64_t identity=0;IORegistryEntryGetRegistryEntryID(service,&identity);
            if(identity!=oldID && !replacement) {
                replacement=[[IOUSBHostDevice alloc] initWithIOService:service options:IOUSBHostObjectInitOptionsNone
                    queue:nil error:&error interestHandler:nil];
                if(replacement)newID=identity;
            }
            IOObjectRelease(service);
        }
        IOObjectRelease(iterator);
        if(!replacement)usleep(50000);
    }
    require(replacement!=nil,@"Reopen reenumerated device within five seconds",error);
    *deviceRef=replacement;
    record[@"reenumeration"][@"new_registry_id"]=@(newID);
    uint8_t state=((const uint8_t *)control(replacement,0x80,8,0,0,[NSMutableData dataWithLength:1]).bytes)[0];
    require(state<=1,@"Expected stock configuration after reset",nil);
    record[@"reenumeration"][@"device_reported_configuration"]=@(state);
    require([replacement configureWithValue:0 matchInterfaces:YES error:&error],@"Clear configuration after bus reset",error);
    require([replacement configureWithValue:1 matchInterfaces:YES error:&error],@"Configure replacement device and publish interfaces",error);
    IOUSBHostInterface *interface=nil;
    for(unsigned attempt=0;attempt<60 && !interface;attempt++) {
        CFMutableDictionaryRef query=[IOUSBHostInterface createMatchingDictionaryWithVendorID:@0x0b05 productID:@0x1d70
            bcdDevice:nil interfaceNumber:@0 configurationValue:@1 interfaceClass:nil interfaceSubclass:nil
            interfaceProtocol:nil speed:nil productIDArray:nil];
        io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,query);
        if(service) {
            interface=[[IOUSBHostInterface alloc] initWithIOService:service options:IOUSBHostObjectInitOptionsNone
                queue:nil error:&error interestHandler:nil];
            IOObjectRelease(service);
        }
        if(!interface)usleep(50000);
    }
    require(interface!=nil,@"Reopen native HCI interface",error);*interfaceRef=interface;
    IOUSBHostPipe *pipe=[interface copyPipeWithAddress:0x81 error:&error];
    require(pipe!=nil,@"Reopen valid HCI pipe",error);*pipeRef=pipe;
    checkpoint(@"native device reenumerated and HCI reopened");
}
