"""Replay the full-rate descriptor and producer; stock setup is a driver boundary."""
import struct,tempfile,unittest,importlib.util
from pathlib import Path
from arm_object_loader import load_arm_objects
from build_resident_stream192 import build
from native_control_offline import NativeControlEmulator,PCD_COMPLETE,SETUP
import native_usb_offline as native
class FullRateStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('unicorn') is None:raise unittest.SkipTest('Unicorn required')
        cls.folder=tempfile.TemporaryDirectory(prefix='dart-stream192-');cls.addClassCleanup(cls.folder.cleanup)
        cls.manifest,cls.objects=build(cls.folder.name)
    def model(self,descriptor_dma=False):
        m=NativeControlEmulator()
        rom=(Path(__file__).parent/'results/flash-backup/rom_dump_0x00001000-0x0009f000.bin').read_bytes()
        m.machine.mem_map(0x7000,0x1000);m.machine.mem_write(0x7000,rom[0x6000:0x7000])
        s,_=load_arm_objects(m.machine,self.objects)
        if descriptor_dma:m.machine.mem_write(m.core+0x43,b'\x01')
        m.put_word(0x30d164,s['dart_stream_setup'])
        m.result_overrides[0x020be8a0]=0
        return m,s
    def direct(self,m,s,kind,request,value,index=0,length=0):
        m.machine.mem_write(SETUP,struct.pack('<BBHHH',kind,request,value,index,length))
        return m.call(s['dart_stream_setup'],0x30cb6c,SETUP)
    def test_normal_config_descriptor_reaches_real_native_ep0_queue(self):
        m,s=self.model()
        for length in (9,200):
            self.assertEqual(m.setup(struct.pack('<BBHHH',0x80,6,0x200,0,length)),0)
            entry=m.word(m.ep0_state+4);request=m.word(entry)
            data=bytes(m.machine.mem_read(m.word(request),length))
            self.assertEqual(data,bytes.fromhex(self.manifest['configuration'])[:length])
            m.finish_control()
        self.assertEqual(m.word(s['dart_stream_config_completed']),2)
        self.assertEqual(m.word(s['dart_stream_config_errors']),0)
    def test_alt_selection_enables_192_then_streams_and_restores(self):
        m,s=self.model();self.assertEqual(m.enable(63),0)
        old_descriptor=m.word(native.EP3+20)
        self.assertEqual(self.direct(m,s,1,11,6,1),0)
        self.assertEqual(m.word(native.EP3+24),192)
        self.assertEqual(self.direct(m,s,0x80,6,0x17d,0,18),0)
        self.assertEqual(m.word(s['dart_stream_pending']),14)
        for sequence in range(40):
            entry=m.word(m.ep3_state+4);request=m.word(entry)
            pcm=bytes(m.machine.mem_read(m.word(request),192))
            values=struct.unpack('<96h',pcm)
            self.assertEqual(values,((sequence&255)-128,((sequence>>8)&255)-128)+(1024,)*46+(-1024,)*48)
            m.put_word(entry+16,192);m.call(PCD_COMPLETE,m.ep3_state,entry,0)
            if sequence%4==3:self.assertEqual(self.direct(m,s,0x80,6,0x17d,0,18),0)
        self.assertEqual(self.direct(m,s,0x80,6,0x17f,0,18),0)
        self.assertEqual(m.word(0x30d164),s['dart_stream_setup'])
        while m.word(s['dart_stream_pending']):
            entry=m.word(m.ep3_state+4);m.put_word(entry+16,0);m.call(PCD_COMPLETE,m.ep3_state,entry,-108)
        self.assertEqual(self.direct(m,s,1,11,0,1),0)
        self.assertEqual(m.word(native.EP3+20),old_descriptor)
        self.assertEqual(m.word(native.EP3+24),63)
        self.assertEqual(self.direct(m,s,0x80,6,0x17c,0,18),0)
        self.assertEqual(m.word(0x30d164),0x020be8a1)
        self.assertEqual(m.word(s['dart_stream_errors']),0)
    def test_descriptor_dma_mode_enables_and_queues_full_rate(self):
        m,s=self.model(True);self.assertEqual(m.enable(63),0)
        self.assertEqual(self.direct(m,s,1,11,6,1),0)
        self.assertEqual(m.word(native.EP3+24),192)
        self.assertEqual(self.direct(m,s,0x80,6,0x17d,0,18),0)
        self.assertEqual(m.word(s['dart_stream_pending']),14)
    def test_device_irq_refills_without_host_control_requests(self):
        m,s=self.model();m.enable(63);self.direct(m,s,1,11,6,1)
        m.put_word(s['dart_stream_limit'],200);m.result_overrides[0x20d082]=1
        self.assertEqual(self.direct(m,s,0x80,6,0x17d,0,18),0)
        for sequence in range(200):
            entry=m.word(m.ep3_state+4);self.assertNotEqual(entry,m.ep3_state+4)
            request=m.word(entry);pcm=bytes(m.machine.mem_read(m.word(request),192))
            lo,hi=struct.unpack_from('<hh',pcm);self.assertEqual((lo+128)|((hi+128)<<8),sequence)
            m.put_word(entry+16,192);m.call(PCD_COMPLETE,m.ep3_state,entry,0)
            self.assertEqual(m.call(s['dart_stream_irq']),1)
        self.assertEqual(m.word(s['dart_stream_completed']),200)
        self.assertEqual(m.word(s['dart_stream_pending']),0)
        self.assertEqual(m.word(s['dart_stream_errors']),0)
        self.assertEqual(m.word(s['dart_stream_irq_calls']),200)
    def test_device_irq_counter_wraps_during_long_stream(self):
        m,s=self.model();m.enable(63);self.direct(m,s,1,11,6,1);m.result_overrides[0x20d082]=1
        self.direct(m,s,0x80,6,0x17d,0,18)
        while m.word(s['dart_stream_pending']):
            entry=m.word(m.ep3_state+4);m.put_word(entry+16,192);m.call(PCD_COMPLETE,m.ep3_state,entry,0)
        m.put_word(s['dart_stream_queued'],65530);m.put_word(s['dart_stream_completed'],65530)
        m.call(s['dart_stream_irq'])
        for sequence in range(65530,65570):
            entry=m.word(m.ep3_state+4);request=m.word(entry)
            low,high=struct.unpack('<hh',bytes(m.machine.mem_read(m.word(request),4)))
            self.assertEqual((low+128)|((high+128)<<8),sequence&65535)
            m.put_word(entry+16,192);m.call(PCD_COMPLETE,m.ep3_state,entry,0);m.call(s['dart_stream_irq'])
        self.assertEqual(m.word(s['dart_stream_errors']),0)
    def test_unhook_is_rejected_while_audio_endpoint_is_owned(self):
        m,s=self.model();m.enable(63);self.direct(m,s,1,11,6,1)
        self.assertEqual(self.direct(m,s,0x80,6,0x17c,0,18),-16)
        self.assertEqual(m.word(0x30d164),s['dart_stream_setup'])
if __name__=='__main__':unittest.main()
