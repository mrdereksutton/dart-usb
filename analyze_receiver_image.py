"""Check the SDK Bluetooth-stack image against the saved CU memory layout."""
import argparse,hashlib,json,struct
from pathlib import Path
from bt600_image_format import verify_image
ROOT=Path(__file__).resolve().parent
def analyze(path,flash_path):
    package=Path(path).read_bytes();image=package[512:];header=verify_image(image)
    if header['image_id']!=0x27a3 or not header['verified']:raise ValueError('Verified upper-stack image required')
    flash=Path(flash_path).read_bytes();start=header['image_base'];end=start+header['image_bytes']
    if hashlib.sha256(flash).hexdigest()!='6ceb104173c7d474b42d62d501087e7933131c43deef03c706022f12a8c633c7':
        raise ValueError('CU flash snapshot hash changed')
    if start<0x2000000 or end>0x2200000:raise ValueError('Stack image outside captured flash')
    reference_uuid=flash[0x9713c:0x9714c];uuid=image[0x13c:0x14c]
    code=image[0x400:];entry=header['execute']&~1
    if entry!=start+0x400 or code[:2]!=bytes.fromhex('10 b5'):raise ValueError('Unrecognized stack startup entry')
    # Pin the observed startup instruction sequence before interpreting literals.
    if code[0x32:0x36]!=bytes.fromhex('01 20 10 bd'):raise ValueError('Stack entry no longer matches the analyzed copy/clear routine')
    dest,source,length,bss,bss_length=struct.unpack_from('<5I',code,0x38)
    data_offset=source-start
    if data_offset<0 or data_offset+length>header['image_bytes']:raise ValueError('Stack initializer data outside image')
    return {'image':str(path),'image_sha256':hashlib.sha256(image[:header['image_bytes']]).hexdigest(),'header':header,
        'cpu_start':start,'cpu_end':end,'rom_uuid_match':uuid==reference_uuid,
        'fits_before_current_ota_header':end<=0x2046000,'bytes_before_ota_header':0x2046000-end,
        'captured_window_all_ff':all(value==255 for value in flash[start-0x2000000:end-0x2000000]),
        'startup':{'entry':entry|1,'data_source':source,'data_destination':dest,'data_bytes':length,
            'bss_destination':bss,'bss_bytes':bss_length,'ram_end':bss+bss_length},
        'loaded_on_device':False,'native_ram_ownership_verified':False,
        'remaining':['Verify RAM ownership and initialization','Bind GAP/AVDTP and SBC-to-PCM','Verify program/erase/restoration before persistent changes']}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image',type=Path)
    p.add_argument('--flash',type=Path,default=ROOT/'results/bt600-targets-20261017T101939.145845Z.bin');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=analyze(args.image,args.flash);args.output.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('rom_uuid_match','fits_before_current_ota_header','bytes_before_ota_header','startup')},indent=2))
