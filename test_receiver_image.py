"""Verify the candidate stack's signed format, placement and real startup writes."""
from pathlib import Path
import importlib.util,unittest
from analyze_receiver_image import analyze
ROOT=Path(__file__).resolve().parent
class ReceiverImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=ROOT/'results/receiver-references-20261020'
        cls.small=next(cls.folder.glob('upperstack_2M_*.bin'),None)
        cls.large=next(cls.folder.glob('upperstack_4M_*.bin'),None)
        cls.flash=ROOT/'results/bt600-targets-20261017T101939.145845Z.bin'
        if cls.small is None or cls.large is None or not cls.flash.is_file():raise unittest.SkipTest('Pinned SDK references and CU snapshot required')
    def test_small_signed_stack_matches_rom_uuid_and_fits_blank_window(self):
        r=analyze(self.small,self.flash)
        self.assertTrue(r['header']['verified']);self.assertTrue(r['rom_uuid_match'])
        self.assertTrue(r['captured_window_all_ff']);self.assertTrue(r['fits_before_current_ota_header'])
        self.assertEqual(r['bytes_before_ota_header'],1192)
        self.assertEqual(r['header']['rsa_pss_salt_bytes'],222)
    def test_large_signed_stack_overlaps_the_current_ota_header(self):
        r=analyze(self.large,self.flash)
        self.assertTrue(r['header']['verified']);self.assertFalse(r['fits_before_current_ota_header'])
        self.assertEqual(r['header']['rsa_pss_salt_bytes'],32)
    def test_actual_stack_entry_only_initializes_its_data_and_bss(self):
        if importlib.util.find_spec('unicorn') is None:self.skipTest('Unicorn required')
        import unicorn as uc
        from unicorn import arm_const as regs
        r=analyze(self.small,self.flash);startup=r['startup'];image=self.small.read_bytes()[512:]
        ram=(ROOT/'results/flash-backup/flash-20261017T023847Z.bin').read_bytes()
        m=uc.Uc(uc.UC_ARCH_ARM,uc.UC_MODE_THUMB|uc.UC_MODE_MCLASS)
        for address,data in ((0x200000,ram),(0x2000000,self.flash.read_bytes())):
            m.mem_map(address,len(data));m.mem_write(address,data)
        m.mem_write(r['cpu_start'],image);m.mem_map(0x500000,0x20000)
        m.reg_write(regs.UC_ARM_REG_SP,0x51f000);m.reg_write(regs.UC_ARM_REG_LR,0x500001)
        writes=[]
        def write(machine,access,address,size,value,unused):
            if 0x500000<=address<0x520000:return
            self.assertGreaterEqual(address,startup['data_destination']);self.assertLessEqual(address+size,startup['ram_end'])
            writes.append((address,size))
        m.hook_add(uc.UC_HOOK_MEM_WRITE,write);m.emu_start(startup['entry'],0x500000,count=10000)
        self.assertEqual(m.reg_read(regs.UC_ARM_REG_PC),0x500000);self.assertEqual(m.reg_read(regs.UC_ARM_REG_R0),1)
        offset=startup['data_source']-r['cpu_start'];length=startup['data_bytes']
        self.assertEqual(bytes(m.mem_read(startup['data_destination'],length)),image[offset:offset+length])
        self.assertEqual(bytes(m.mem_read(startup['bss_destination'],startup['bss_bytes'])),bytes(startup['bss_bytes']))
        self.assertEqual(sum(size for _,size in writes),length+startup['bss_bytes'])
if __name__=='__main__':unittest.main()
