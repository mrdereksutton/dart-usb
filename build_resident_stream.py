"""Build the bounded stock-ISO PCM producer at the verified pool-5 base."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from arm_object_loader import load_arm_objects
ROOT=Path(__file__).resolve().parent

def build(directory,base=0x312280):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    obj=directory/'resident_stream_trial.o'
    source=ROOT/'firmware/resident_stream_trial.c'
    subprocess.run(['xcrun','clang','-target','armv8m.main-none-eabi','-mcpu=cortex-m33+nodsp',
        '-mthumb','-mno-unaligned-access','-ffreestanding','-fno-builtin','-fno-stack-protector','-Os','-Wall','-Wextra','-Werror',
        '-I',str(ROOT/'firmware'),'-c',str(source),'-o',str(obj)],check=True,capture_output=True)
    class Memory:
        def mem_map(self,address,size):
            if address!=base or size>4096:raise RuntimeError('Stream image exceeds checked allocation')
        def mem_write(self,address,data):self.data=data
    m=Memory();symbols,layout=load_arm_objects(m,[obj],base=base)
    size=(len(m.data.rstrip(b'\0'))+3)&~3;data=m.data[:size]
    manifest=dict(base=base,allocation_bytes=4096,upload_bytes=len(data),image_hex=data.hex(' '),
        sha256=hashlib.sha256(data).hexdigest(),symbols=symbols,arm_image=layout,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        compiler_target='ARMv8-M Mainline; no DSP; no unaligned accesses',sample_rate=16000,channels=1,packet_bytes=63,max_packets=32768,format_version=2)
    (directory/'resident-stream.bin').write_bytes(data)
    (directory/'resident-stream.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest,[obj]
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'results/native-host-build/stream')
    p.add_argument('--base',type=lambda s:int(s,0),default=0x312280);a=p.parse_args()
    m,_=build(a.output,a.base);print(json.dumps({k:m[k] for k in ('base','upload_bytes','sha256','symbols')},indent=2))
