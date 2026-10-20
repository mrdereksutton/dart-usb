"""Execute the SPI helper and actual captured ROM address translation offline."""
import hashlib,struct,unittest
from pathlib import Path
from build_flash_map_read import build_helper
from native_usb_offline import RAM_SHA256
try:
    import unicorn as uc
    from unicorn import arm_const as regs
except ImportError:
    uc=None
ROOT=Path(__file__).resolve().parent
CALLBACK=0x020be8a0
@unittest.skipIf(uc is None,'Unicorn required')
class FlashMapReadTests(unittest.TestCase):
    def machine(self):
        m=uc.Uc(uc.UC_ARCH_ARM,uc.UC_MODE_THUMB|uc.UC_MODE_MCLASS)
        rom=(ROOT/'results/flash-backup/rom_dump_0x00001000-0x0009f000.bin').read_bytes()
        ram=(ROOT/'results/flash-backup/flash-20261017T023847Z.bin').read_bytes()
        self.assertEqual(hashlib.sha256(ram).hexdigest(),RAM_SHA256)
        for base,data in ((0x1000,rom),(0x200000,ram)):
            m.mem_map(base,len(data));m.mem_write(base,data)
        m.mem_map(0x500000,0x20000);m.mem_map(CALLBACK&~0xfff,0x1000)
        m.reg_write(regs.UC_ARM_REG_SP,0x51f000);m.reg_write(regs.UC_ARM_REG_LR,0x500001)
        return m
    def test_header_read_preserves_context_and_restores_callback_before_call(self):
        for source in (0x02046110,0x02097110):
            with self.subTest(source=hex(source)):
                m=self.machine();code=build_helper();self.assertLessEqual(len(code),144)
                m.mem_write(0x211e30,code);m.mem_write(0x211efc,struct.pack('<I',source))
                m.mem_write(0x500100,bytes.fromhex('80 06 01 01 00 00 12 00'))
                m.mem_write(0x30d164,struct.pack('<I',0x211e31));calls=[]
                def read(machine,address,size,unused):
                    if address==0xcbb4:
                        args=[machine.reg_read(getattr(regs,f'UC_ARM_REG_R{i}')) for i in range(3)]
                        self.assertEqual(bytes(machine.mem_read(0x30d164,4)),struct.pack('<I',CALLBACK|1))
                        calls.append(args);machine.mem_write(args[1],bytes(range(16)))
                        machine.reg_write(regs.UC_ARM_REG_R0,0x18)
                        machine.reg_write(regs.UC_ARM_REG_PC,machine.reg_read(regs.UC_ARM_REG_LR))
                m.hook_add(uc.UC_HOOK_CODE,read)
                before=[0x30cb6c,0x500100]+list(range(2,13))
                for i,value in enumerate(before):m.reg_write(getattr(regs,f'UC_ARM_REG_R{i}'),value)
                m.emu_start(0x211e31,CALLBACK,count=200)
                self.assertEqual([m.reg_read(getattr(regs,f'UC_ARM_REG_R{i}')) for i in range(13)],before)
                self.assertEqual(calls,[[source,0x211ec0,16]])
                self.assertEqual(bytes(m.mem_read(0x211f00,8)),struct.pack('<II',0xd47a6001,0x18))
    def test_other_requests_and_unlisted_sources_cannot_call_flash(self):
        for setup,source in ((bytes.fromhex('20 00 00 00 00 00 00 00'),0x2097110),
                             (bytes.fromhex('80 06 01 01 00 00 12 00'),0x2000000)):
            m=self.machine();m.mem_write(0x211e30,build_helper());m.mem_write(0x211efc,struct.pack('<I',source))
            m.mem_write(0x500100,setup);m.reg_write(regs.UC_ARM_REG_R1,0x500100)
            def no_flash(machine,address,size,unused):
                if address==0xcbb4:self.fail('Unexpected native flash call')
            m.hook_add(uc.UC_HOOK_CODE,no_flash);m.emu_start(0x211e31,CALLBACK,count=200)
            self.assertEqual(m.reg_read(regs.UC_ARM_REG_PC),CALLBACK)
    def test_actual_rom_builds_quad_read_at_the_expected_physical_offsets(self):
        for source in (0x02046110,0x02097110):
            m=self.machine();calls=[]
            def spi(machine,address,size,unused):
                if address==0x202c6e:
                    args=[machine.reg_read(getattr(regs,f'UC_ARM_REG_R{i}')) for i in range(4)]
                    transaction=struct.unpack('<III',bytes(machine.mem_read(args[1],12)))
                    calls.append((args[0],transaction[0]&255,transaction[1],args[2],args[3]))
                    machine.reg_write(regs.UC_ARM_REG_R0,0x18)
                    machine.reg_write(regs.UC_ARM_REG_PC,machine.reg_read(regs.UC_ARM_REG_LR))
            m.hook_add(uc.UC_HOOK_CODE,spi)
            for i,value in enumerate((source,0x500200,16)):m.reg_write(getattr(regs,f'UC_ARM_REG_R{i}'),value)
            m.emu_start(0x56ab,0x500000,count=1000)
            self.assertEqual(calls,[(0,0xeb,source-0x02000000,0x500200,16)])
            self.assertEqual(m.reg_read(regs.UC_ARM_REG_R0),0x18)
if __name__=='__main__':unittest.main()
