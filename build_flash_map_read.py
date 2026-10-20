"""Build a bounded read-only SPI-header helper; never accesses USB."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from native_flash_read import elf_text
ROOT=Path(__file__).resolve().parent
def build_helper():
    source=ROOT/'firmware/flash_map_read_helper.S'
    with tempfile.TemporaryDirectory(prefix='bt600-flash-map-') as folder:
        obj=Path(folder)/'helper.o'
        subprocess.run(['xcrun','clang','-target','armv8m.main-none-eabi','-mcpu=cortex-m33+nodsp','-mthumb',
            '-c',str(source),'-o',str(obj)],check=True,capture_output=True)
        data=elf_text(obj.read_bytes())
    if not data or len(data)>144 or len(data)&3:raise ValueError('Read helper overlaps result buffer')
    return data
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'results/native-host-build/flash-map-read.bin')
    a=p.parse_args();data=build_helper();a.output.parent.mkdir(exist_ok=True,parents=True);a.output.write_bytes(data)
    print(json.dumps(dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())))
