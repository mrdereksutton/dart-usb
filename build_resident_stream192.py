"""Build a RAM-only full-rate ISO descriptor handoff with a native PCM producer."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from arm_object_loader import load_arm_objects
from native_flash_read import elf_text
ROOT=Path(__file__).resolve().parent

def build(directory,base=0x312280):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    stock=bytes.fromhex((ROOT/'tests/fixtures/bt600_stock_configuration.hex').read_text())
    if len(stock)!=200 or stock[186:193]!=bytes.fromhex('07 05 83 01 3f 00 01'):raise ValueError('Pinned stock alternate descriptor changed')
    changed=bytearray(stock);changed[190]=192
    (directory/'resident_stock_configuration.h').write_text('_Alignas(4) static const uint8_t stock_configuration[]={'+','.join(str(b) for b in changed)+'};\n')
    source=ROOT/'firmware/resident_stream192_trial.c';obj=directory/'resident_stream192_trial.o'
    subprocess.run(['xcrun','clang','-target','armv8m.main-none-eabi','-mcpu=cortex-m33+nodsp','-mthumb','-mno-unaligned-access',
        '-ffreestanding','-fno-builtin','-fno-stack-protector','-Os','-Wall','-Wextra','-Werror',
        '-I',str(ROOT/'firmware'),'-I',str(directory),'-c',str(source),'-o',str(obj)],check=True,capture_output=True)
    class Memory:
        def mem_map(self,address,size):
            if address!=base or size>8192:raise RuntimeError('Full-rate stream exceeds checked 6144-byte allocation')
        def mem_write(self,address,data):self.data=data
    m=Memory();symbols,layout=load_arm_objects(m,[obj],base=base)
    used=(len(m.data.rstrip(b'\0'))+3)&~3;data=m.data[:used]
    if len(data)>6144:raise RuntimeError('Full-rate upload exceeds allocated bytes')
    helper=directory/'resident_heap_helper.o'
    subprocess.run(['xcrun','clang','-target','armv8m.main-none-eabi','-mcpu=cortex-m33+nodsp','-mthumb',
        '-DRESIDENT_ALLOC_BYTES=6144','-c',str(ROOT/'firmware/resident_heap_helper.S'),'-o',str(helper)],check=True,capture_output=True)
    (directory/'resident-heap-helper192.bin').write_bytes(elf_text(helper.read_bytes()))
    manifest=dict(base=base,allocation_bytes=6144,upload_bytes=len(data),image_hex=data.hex(' '),sha256=hashlib.sha256(data).hexdigest(),
        symbols=symbols,arm_image=layout,sample_rate=48000,channels=2,packet_bytes=192,max_packets=300768,format_version=3,slots=14,
        stock_configuration=stock.hex(' '),configuration=bytes(changed).hex(' '),
        source_sha256={name:hashlib.sha256((ROOT/'firmware'/name).read_bytes()).hexdigest() for name in ('resident_stream_trial.c','resident_stream192_trial.c')})
    (directory/'resident-stream192.bin').write_bytes(data);(directory/'resident-stream192.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest,[obj]
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'results/native-host-build/stream192')
    p.add_argument('--base',type=lambda x:int(x,0),default=0x312280);a=p.parse_args();m,_=build(a.output,a.base)
    print(json.dumps({k:m[k] for k in ('base','upload_bytes','sha256','symbols')},indent=2))
