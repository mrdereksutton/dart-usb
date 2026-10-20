"""Replay SPI export through the captured native EP0 queue and completion."""
import importlib.util,struct,tempfile,unittest
from pathlib import Path
from arm_object_loader import load_arm_objects
from build_resident_flash_read import build
from native_control_offline import NativeControlEmulator,SETUP
class ResidentFlashReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('unicorn') is None:raise unittest.SkipTest('Unicorn required')
        cls.folder=tempfile.TemporaryDirectory(prefix='bt600-spi-export-');cls.addClassCleanup(cls.folder.cleanup)
        cls.manifest,cls.objects=build(cls.folder.name)
    def model(self):
        m=NativeControlEmulator();m.machine.mem_map(0xc000,0x1000)
        s,_=load_arm_objects(m.machine,self.objects);m.put_word(0x30d164,s['dart_resident_setup'])
        m.spi_calls=[];m.spi_status=0x18
        def spi(machine,address,size,unused):
            if address==0xcbb4:
                arguments=[machine.reg_read(getattr(m.regs,f'UC_ARM_REG_R{i}')) for i in range(3)]
                source,destination,count=arguments;m.spi_calls.append(arguments)
                if m.spi_status==0x18:machine.mem_write(destination,bytes(machine.mem_read(source,count)))
                m._return(m.spi_status)
        m.machine.hook_add(m.uc.UC_HOOK_CODE,spi)
        return m,s
    def request(self,m,s,page=0,length=512):
        setup=struct.pack('<BBHHH',0x80,6,0x17b,page,length)
        m.machine.mem_write(SETUP,setup)
        return m.call(s['dart_resident_setup'],0x30cb6c,SETUP)
    def test_first_and_last_partition_pages_use_native_ep0(self):
        for descriptor_dma in (False,True):
            m,s=self.model()
            if descriptor_dma:m.machine.mem_write(m.core+0x43,b'\x01')
            for page in (0,1,575):
                self.assertEqual(self.request(m,s,page),0)
                request=s['dart_resident_request'];source=0x2097000+page*512
                self.assertEqual(bytes(m.machine.mem_read(m.word(request),512)),bytes(m.machine.mem_read(source,512)))
                self.assertEqual(m.spi_calls[-1],[source,m.word(request),512])
                m.finish_control();self.assertEqual(m.word(s['dart_resident_busy']),0)
                self.assertEqual(m.word(0x30cbc8),0)
            self.assertEqual(m.word(s['dart_resident_completed']),3)
            self.assertEqual(m.word(s['dart_resident_errors']),0)
    def test_partition_and_transfer_limits_reject_before_spi(self):
        m,s=self.model()
        for page,length in ((576,512),(65535,16),(0,0),(0,513)):
            self.assertEqual(self.request(m,s,page,length),-22)
        self.assertEqual(m.spi_calls,[])
    def test_spi_failure_never_queues_ep0(self):
        m,s=self.model();m.spi_status=0x10
        self.assertEqual(self.request(m,s),-5)
        self.assertEqual(m.word(s['dart_resident_busy']),0)
        self.assertEqual(m.word(s['dart_resident_errors']),1)
        self.assertEqual(m.word(0x30cbc8),0)
if __name__=='__main__':unittest.main()
