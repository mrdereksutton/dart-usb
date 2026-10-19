"""Replay the compiled PCM producer through captured ISO queue/completion code."""
import importlib.util, struct, tempfile, unittest
from pathlib import Path
from arm_object_loader import load_arm_objects
from build_resident_stream import build
from native_control_offline import NativeControlEmulator, PCD_COMPLETE
import native_usb_offline as native

class ResidentStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec('unicorn') is None:raise unittest.SkipTest('Unicorn required')
        cls.folder=tempfile.TemporaryDirectory(prefix='dart-stream-');cls.addClassCleanup(cls.folder.cleanup)
        cls.manifest,cls.objects=build(cls.folder.name)
    def model(self):
        m=NativeControlEmulator()
        rom=(Path(__file__).parent/'results/flash-backup/rom_dump_0x00001000-0x0009f000.bin').read_bytes()
        m.machine.mem_map(0x7000,0x1000);m.machine.mem_write(0x7000,rom[0x6000:0x7000])
        s,_=load_arm_objects(m.machine,self.objects)
        def aligned_access(cpu,access,address,size,value,unused):
            pc=cpu.reg_read(m.regs.UC_ARM_REG_PC)
            protected={s['dart_stream_'+name] for name in ('pending','queued','completed','errors','cancelled')}
            if access==m.uc.UC_MEM_WRITE and address in protected and not cpu.reg_read(m.regs.UC_ARM_REG_PRIMASK):
                raise RuntimeError('Counter update without interrupt serialization')
            if 0x700000<=pc<0x701000 and size in (2,4,8) and address&(size-1):
                raise RuntimeError(f'Unaligned resident access at PC {pc:#x}: {address:#x}/{size}')
        m.machine.hook_add(m.uc.UC_HOOK_MEM_READ|m.uc.UC_HOOK_MEM_WRITE,aligned_access)
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
        decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
        def base_isa(cpu,address,size,unused):
            if 0x700000<=address<0x701000:
                ins=next(decoder.disasm(bytes(cpu.mem_read(address,size)),address),None)
                if ins and ins.mnemonic in ("uxtab","uxtah","sxtab","sxtah","qadd","qsub","smlad","smlsd"):
                    raise RuntimeError(f"Optional DSP instruction in resident code: {ins.mnemonic}")
        m.machine.hook_add(m.uc.UC_HOOK_CODE,base_isa)
        self.assertEqual(m.enable(63),0)
        m.put_word(0x30d164,s['dart_stream_setup'])
        return m,s
    def pump(self,m,index=125):
        self.assertEqual(m.setup(struct.pack('<BBHHH',0x80,6,0x100+index,0,18)),0)
        m.finish_control()
        self.assertEqual(m.machine.reg_read(m.regs.UC_ARM_REG_PRIMASK),0)
    def finish_one(self,m,status=0):
        entry=m.word(m.ep3_state+4)
        self.assertNotEqual(entry,m.ep3_state+4)
        request=m.word(entry)
        pcm=bytes(m.machine.mem_read(m.word(request),63))
        m.put_word(entry+0x10,63 if not status else 0)
        m.call(PCD_COMPLETE,m.ep3_state,entry,status)
        self.assertEqual(m.machine.reg_read(m.regs.UC_ARM_REG_PRIMASK),0)
        return pcm
    def test_real_queue_ring_wraps_with_contiguous_pcm_and_native_completions(self):
        m,s=self.model();m.put_word(s['dart_stream_limit'],320)
        self.pump(m)
        self.assertEqual(m.word(s['dart_stream_pending']),14)
        for sequence in range(320):
            pcm=self.finish_one(m)
            self.assertEqual(struct.unpack('<16h',pcm[:32]),((sequence&255)-128,((sequence>>8)&255)-128)+(1024,)*6+(-1024,)*8)
            if sequence%7==6 and sequence<319:self.pump(m)
        self.assertEqual(m.word(s['dart_stream_completed']),320)
        self.assertEqual(m.word(s['dart_stream_pending']),0)
        self.assertEqual(m.word(s['dart_stream_errors']),0)
        self.assertEqual(m.word(s['dart_stream_running']),0)
    def test_stop_drains_without_refill_before_callback_code_can_be_freed(self):
        m,s=self.model();self.pump(m);self.finish_one(m)
        self.pump(m,127)
        self.assertEqual(m.word(0x30d164),0x20be8a1)
        while m.word(s['dart_stream_pending']):self.finish_one(m,-108)
        self.assertEqual(m.word(s['dart_stream_cancelled']),13)
        self.assertEqual(m.word(s['dart_stream_errors']),0)
    def test_transfer_error_stops_submissions(self):
        m,s=self.model();self.pump(m);self.finish_one(m,-5)
        self.assertEqual(m.word(s['dart_stream_running']),0)
        self.assertEqual(m.word(s['dart_stream_errors']),1)
        self.assertEqual(m.word(s['dart_stream_queued']),14)
    def test_native_queue_failure_stops_without_phantom_pending(self):
        m,s=self.model();m.iso_result=-11;self.pump(m)
        self.assertEqual(m.word(s['dart_stream_pending']),0)
        self.assertEqual(m.word(s['dart_stream_errors']),1)

if __name__=='__main__':unittest.main()
