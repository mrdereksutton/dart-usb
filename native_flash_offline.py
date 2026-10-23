"""Execute captured NOR wrappers against a bounded simulated SPI flash backend."""
from pathlib import Path
import hashlib,struct
from native_usb_offline import RAM_SHA256,FLASH_SHA256
ROOT=Path(__file__).resolve().parent
class FlashReplay:
    def __init__(self,protected=False):
        import unicorn as uc
        from unicorn import arm_const as regs
        self.uc,self.regs=uc,regs
        rom=(ROOT/'results/flash-backup/rom_dump_0x00001000-0x0009f000.bin').read_bytes()
        ram=(ROOT/'results/flash-backup/flash-20261017T023847Z.bin').read_bytes()
        flash=(ROOT/'results/bt600-targets-20261017T101939.145845Z.bin').read_bytes()
        if hashlib.sha256(ram).hexdigest()!=RAM_SHA256 or hashlib.sha256(flash).hexdigest()!=FLASH_SHA256:raise ValueError('Pinned flash replay inputs changed')
        self.flash=bytearray(flash);self.commands=[];self.writes=[];self.enabled=False
        self.sr1=0x34 if protected else 0x20;self.sr2=2;self.status_changes=[];self.status_enabled=False
        self.machine=uc.Uc(uc.UC_ARCH_ARM,uc.UC_MODE_THUMB|uc.UC_MODE_MCLASS)
        for base,data in ((0x1000,rom),(0x200000,ram)):
            self.machine.mem_map(base,len(data));self.machine.mem_write(base,data)
        self.machine.mem_map(0x500000,0x20000);self.machine.hook_add(uc.UC_HOOK_CODE,self.instruction)
    def word(self,address):return struct.unpack('<I',bytes(self.machine.mem_read(address,4)))[0]
    def result(self,value=0x18):
        self.machine.reg_write(self.regs.UC_ARM_REG_R0,value)
        self.machine.reg_write(self.regs.UC_ARM_REG_PC,self.machine.reg_read(self.regs.UC_ARM_REG_LR))
    def instruction(self,m,address,size,unused):
        args=[m.reg_read(getattr(self.regs,f'UC_ARM_REG_R{i}')) for i in range(4)]
        if address==0xc3de:
            if args[0] not in (1,2,4) or args[1] not in (0x020de000,0x020de020):raise RuntimeError('Unexpected flash lock')
            m.mem_write(args[3],struct.pack('<I',0x500800));self.result(0)
        elif address==0x202798:self.result(0)
        elif address==0xc094:
            if args[0]!=0x500800:raise RuntimeError('Wrong flash completion node')
            self.result()
        elif address==0x201a8a:self.result()
        elif address in (0x202ce2,0x202c6e):
            bank,descriptor,buffer,count=args
            command,offset,flags=struct.unpack('<III',bytes(m.mem_read(descriptor,12)));opcode=command&255
            self.commands.append(dict(opcode=opcode,offset=offset,bytes=count,flags=flags))
            if bank!=0:raise RuntimeError('Unexpected flash bank')
            if opcode==6 and address==0x202ce2:
                if count or buffer:raise RuntimeError('Invalid write enable')
                self.enabled=True
            elif opcode==0x50 and address==0x202ce2:
                if count or buffer:raise RuntimeError('Invalid volatile-status enable')
                self.status_enabled=True
            elif opcode in (5,0x35) and address==0x202c6e:
                if count!=1 or flags:raise RuntimeError('Invalid protection status read')
                m.mem_write(buffer,bytes([self.sr1 if opcode==5 else self.sr2]))
            elif opcode in (1,0x31) and address==0x202ce2:
                data=bytes(m.mem_read(buffer,count))
                if not self.status_enabled or offset or flags or opcode!=1 or data not in (b'\x20',b'\x34',b'\x20\x02',b'\x34\x02'):
                    raise RuntimeError(f'Unexpected protection change: opcode={opcode:x}, bytes={data.hex()}, flags={flags:x}')
                self.sr1=data[0]
                if count==2:self.sr2=data[1]
                self.status_changes.append((self.sr1,self.sr2));self.status_enabled=False
            elif opcode==0x32 and address==0x202ce2:
                if not self.enabled or offset!=0xde000 or count!=32 or flags&7!=3:raise RuntimeError('Program exceeds bounded trial')
                data=bytes(m.mem_read(buffer,count))
                if not self.sr1&0x1c:
                    self.flash[offset:offset+count]=bytes(a&b for a,b in zip(self.flash[offset:offset+count],data))
                    self.writes.append(dict(operation='program',offset=offset,bytes=count))
                self.enabled=False
            elif opcode==0x20 and address==0x202ce2:
                if not self.enabled or offset!=0xde000 or count or buffer or flags&7!=3:raise RuntimeError('Erase exceeds bounded trial')
                if not self.sr1&0x1c:
                    self.flash[offset:offset+4096]=b'\xff'*4096
                    self.writes.append(dict(operation='sector erase',offset=offset,bytes=4096))
                self.enabled=False
            elif opcode==0xeb and address==0x202c6e:
                if not 0xde000<=offset or offset+count>0xdf000:raise RuntimeError('Read outside trial sector')
                m.mem_write(buffer,bytes(self.flash[offset:offset+count]))
            else:raise RuntimeError(f'Unexpected SPI opcode {opcode:02x}')
            self.result()
    def call(self,entry,*args):
        r=self.regs;m=self.machine
        for i,value in enumerate(args):m.reg_write(getattr(r,f'UC_ARM_REG_R{i}'),value)
        m.reg_write(r.UC_ARM_REG_SP,0x51f000);m.reg_write(r.UC_ARM_REG_LR,0x500001)
        m.emu_start(entry,0x500000,count=10000)
        if m.reg_read(r.UC_ARM_REG_PC)!=0x500000:raise RuntimeError('Flash replay did not return')
        return m.reg_read(r.UC_ARM_REG_R0)
