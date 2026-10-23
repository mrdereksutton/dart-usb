"""Build a bounded read-only native-SPI application export through EP0."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from arm_object_loader import load_arm_objects
ROOT=Path(__file__).resolve().parent

def build(directory,base=0x312280,restore_trial=False,receiver_window=False):
    if restore_trial and receiver_window:raise ValueError('Receiver-window export must be read-only')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    obj=directory/'resident_flash_read.o'
    source=ROOT/'firmware/resident_flash_read.c'
    subprocess.run(['xcrun','clang','-target','armv8m.main-none-eabi','-mcpu=cortex-m33+nodsp',
        '-mthumb','-mno-unaligned-access','-ffreestanding','-fno-builtin','-fno-stack-protector','-Os','-Wall','-Wextra','-Werror',
        *(['-DDART_FLASH_RESTORE_TRIAL=1'] if restore_trial else []),
        *(['-DDART_RECEIVER_WINDOW_READ=1'] if receiver_window else []),
        '-I',str(ROOT/'firmware'),'-c',str(source),'-o',str(obj)],check=True,capture_output=True)
    class Memory:
        def mem_map(self,address,size):
            if address!=base or size>4096:raise RuntimeError('SPI-export image exceeds checked allocation')
        def mem_write(self,address,data):self.data=data
    m=Memory();symbols,layout=load_arm_objects(m,[obj],base=base)
    for name in ('dart_resident_setup','dart_resident_request','dart_resident_busy','dart_resident_completed','dart_resident_errors'):
        if name not in symbols:raise RuntimeError('SPI-export symbol missing: '+name)
    size=(len(m.data.rstrip(b'\0'))+3)&~3;data=m.data[:size]
    manifest=dict(base=base,allocation_bytes=4096,upload_bytes=len(data),image_hex=data.hex(' '),
        sha256=hashlib.sha256(data).hexdigest(),symbols=symbols,arm_image=layout,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        compiler_target='ARMv8-M Mainline; no DSP; no unaligned accesses',source_address=0x02015000 if receiver_window else 0x02097000,
        partition_bytes=0x31000 if receiver_window else 0x48000,page_bytes=512,pages=392 if receiver_window else 576)
    manifest['allows_flash_restore_trial']=restore_trial
    if restore_trial:manifest.update(trial_cpu_address=0x020de000,trial_sector_bytes=4096,trial_pattern=bytes(range(0x20,0x40)).hex(' '))
    (directory/'resident-flash-read.bin').write_bytes(data)
    (directory/'resident-flash-read.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest,[obj]
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'results/native-host-build/flash-read')
    p.add_argument('--base',type=lambda s:int(s,0),default=0x312280);p.add_argument('--restore-trial',action='store_true');p.add_argument('--receiver-window',action='store_true');a=p.parse_args()
    if (a.restore_trial or a.receiver_window) and a.output==ROOT/'results/native-host-build/flash-read':p.error('Select a separate --output directory for this variant')
    m,_=build(a.output,a.base,a.restore_trial,a.receiver_window);print(json.dumps({k:m[k] for k in ('base','upload_bytes','sha256','symbols')},indent=2))
