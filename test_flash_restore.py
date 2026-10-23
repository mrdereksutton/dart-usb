"""Verify fixed-sector operations through both the trial and real ROM code."""
import importlib.util,struct,tempfile,unittest
from pathlib import Path
from native_flash_offline import FlashReplay
from build_resident_flash_read import build
from arm_object_loader import load_arm_objects
from native_control_offline import NativeControlEmulator,SETUP
@unittest.skipIf(importlib.util.find_spec('unicorn') is None,'Unicorn required')
class RomFlashRestoreTests(unittest.TestCase):
    def test_actual_program_readback_and_sector_erase_restore_original(self):
        m=FlashReplay();original=bytes(m.flash);pattern=bytes(range(0x20,0x40));m.machine.mem_write(0x500200,pattern)
        self.assertEqual(m.call(0xcc35,0x20de000,0x500200,32,32),0x18)
        self.assertEqual(bytes(m.flash[0xde000:0xde020]),pattern)
        self.assertEqual(m.call(0xcbb5,0x20de000,0x500300,32),0x18)
        self.assertEqual(bytes(m.machine.mem_read(0x500300,32)),pattern)
        self.assertEqual(m.call(0xcd83,0x20de000,1),0x18)
        self.assertEqual(bytes(m.flash),original)
        self.assertEqual(m.writes,[dict(operation='program',offset=0xde000,bytes=32),dict(operation='sector erase',offset=0xde000,bytes=4096)])
        self.assertEqual([c['opcode'] for c in m.commands],[6,0x32,0xeb,6,0x20])
    def test_protected_program_ignores_write_and_volatile_unlock_restores_status(self):
        m=FlashReplay(protected=True);original=bytes(m.flash);pattern=bytes(range(0x20,0x40));m.machine.mem_write(0x500200,pattern)
        self.assertEqual(m.call(0xcc35,0x20de000,0x500200,32,32),0x18)
        self.assertEqual(bytes(m.flash),original)
        for operation,args in [(0xcc35,(0x20de000,0x500200,32,32)),(0xcd83,(0x20de000,1))]:
            self.assertEqual(m.call(0x55af,0,0),0x18)
            self.assertEqual(m.call(operation,*args),0x18)
            self.assertEqual(m.call(0x55af,0,5),0x18)
            self.assertEqual((m.sr1,m.sr2),(0x34,2))
            if operation==0xcc35:self.assertEqual(bytes(m.flash[0xde000:0xde020]),pattern)
        self.assertEqual(bytes(m.flash),original)
        self.assertEqual(m.status_changes,[(0x20,2),(0x34,2)]*2)
        self.assertEqual([x['operation'] for x in m.writes],['program','sector erase'])

@unittest.skipIf(importlib.util.find_spec('unicorn') is None,'Unicorn required')
class ResidentRestoreTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory(prefix='bt600-restore-');cls.addClassCleanup(cls.folder.cleanup)
        cls.manifest,cls.objects=build(cls.folder.name,restore_trial=True)
    def model(self):
        m=NativeControlEmulator();m.machine.mem_map(0xc000,0x1000);m.machine.mem_map(0x5000,0x1000)
        rom=(Path(__file__).parent/'results/flash-backup/rom_dump_0x00001000-0x0009f000.bin').read_bytes()
        m.machine.mem_map(0x7000,0x1000);m.machine.mem_write(0x7000,rom[0x6000:0x7000])
        s,_=load_arm_objects(m.machine,self.objects);m.put_word(0x30d164,s['dart_resident_setup']);m.storage_calls=[]
        m.sr1=0x34;m.status_changes=[];m.program_result=0x18
        def flash(machine,address,size,unused):
            args=[machine.reg_read(getattr(m.regs,f'UC_ARM_REG_R{i}')) for i in range(4)]
            if address==0x202c6e:
                command=struct.unpack('<III',bytes(machine.mem_read(args[1],12)))
                self.assertIn(command,[(0x10005,0,0),(0x10035,0,0)])
                self.assertEqual((args[0],args[3]),(0,1));machine.mem_write(args[2],bytes([m.sr1 if command[0]==0x10005 else 2]));m._return(0x18)
            elif address==0x554c:
                self.assertEqual(args[0],0);machine.mem_write(args[1],bytes([(m.sr1>>2)&7]));m._return(0x18)
            elif address==0x55ae:
                self.assertEqual(args[0],0);self.assertIn(args[1],(0,5));m.sr1=(m.sr1&~0x1c)|(args[1]<<2)
                m.status_changes.append(m.sr1);m._return(0x18)
            elif address==0xcbb4:
                machine.mem_write(args[1],bytes(machine.mem_read(args[0],args[2])));m._return(0x18)
            elif address==0xcc34:
                self.assertEqual((args[0],args[2],args[3]),(0x20de000,32,32));m.storage_calls.append(('program',args))
                self.assertEqual(m.sr1,0x20)
                if m.program_result==0x18:machine.mem_write(args[0],bytes(machine.mem_read(args[1],32)))
                m._return(m.program_result)
            elif address==0xcd82:
                self.assertEqual(args[:2],[0x20de000,1]);m.storage_calls.append(('sector erase',args))
                self.assertEqual(m.sr1,0x20)
                machine.mem_write(0x20de000,b'\xff'*4096);m._return(0x18)
        m.machine.hook_add(m.uc.UC_HOOK_CODE,flash);return m,s
    def trigger(self,m,s,mode):
        m.machine.mem_write(SETUP,struct.pack('<BBHHH',0x80,6,0x17a,mode,18))
        return m.call(s['dart_resident_setup'],0x30cb6c,SETUP)
    def test_program_is_once_and_erase_restores_the_sector(self):
        m,s=self.model();self.assertEqual(self.trigger(m,s,2),0);m.finish_control()
        self.assertEqual(self.trigger(m,s,1),-16)
        self.assertEqual(self.trigger(m,s,0),0);m.finish_control()
        self.assertEqual(bytes(m.machine.mem_read(0x20de000,32)),bytes(range(0x20,0x40)))
        self.assertEqual(self.trigger(m,s,0),-16)
        self.assertEqual(self.trigger(m,s,1),0);m.finish_control()
        self.assertEqual(bytes(m.machine.mem_read(0x20de000,4096)),b'\xff'*4096)
        self.assertEqual([name for name,_ in m.storage_calls],['program','sector erase'])
        self.assertEqual(m.status_changes,[0x20,0x34,0x20,0x34]);self.assertEqual(m.sr1,0x34)
    def test_other_modes_and_masked_context_reject_before_flash(self):
        m,s=self.model();self.assertEqual(self.trigger(m,s,3),-22)
        m.machine.reg_write(m.regs.UC_ARM_REG_PRIMASK,1);self.assertEqual(self.trigger(m,s,0),-16)
        self.assertEqual(m.storage_calls,[])
    def test_status_query_reads_only_and_leaves_pattern_unattempted(self):
        m,s=self.model();self.assertEqual(self.trigger(m,s,2),0);m.finish_control()
        for name,value in [('sr1',0x34),('sr2',2),('bp_level',5),('status_result',0x18),('attempted',0)]:
            self.assertEqual(m.word(s['dart_trial_'+name]),value)
        self.assertEqual(m.storage_calls,[])
    def test_nonblank_pattern_area_is_left_untouched(self):
        for offset in (0,4095):
            m,s=self.model();self.assertEqual(self.trigger(m,s,2),0);m.finish_control();m.machine.mem_write(0x20de000+offset,b'\x01')
            self.assertEqual(self.trigger(m,s,0),-22);self.assertEqual(m.storage_calls,[])
    def test_program_error_still_restores_original_protection(self):
        m,s=self.model();self.assertEqual(self.trigger(m,s,2),0);m.finish_control();m.program_result=5
        self.assertEqual(self.trigger(m,s,0),-5);self.assertEqual(m.sr1,0x34)
        self.assertEqual(m.status_changes,[0x20,0x34]);self.assertEqual(m.word(s['dart_trial_reprotect_status']),0x18)
    def test_nonvolatile_enable_configuration_rejects_before_change(self):
        m,s=self.model();self.assertEqual(self.trigger(m,s,2),0);m.finish_control();m.machine.mem_write(0x2803a1,b'\x04')
        self.assertEqual(self.trigger(m,s,0),-22);self.assertEqual(m.storage_calls,[]);self.assertEqual(m.status_changes,[])
if __name__=='__main__':unittest.main()
