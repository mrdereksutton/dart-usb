"""Validate saved CU firmware images and preserve an original application capsule."""
import argparse,hashlib,json
from pathlib import Path
from bt600_image_format import HEADER_SIZE,FLASH_BASE,verify_image,partitions
from analyze_asus_firmware import analyze
ROOT=Path(__file__).resolve().parent
PIN='6ceb104173c7d474b42d62d501087e7933131c43deef03c706022f12a8c633c7'

def validate_spi_backup(report_path,expected):
    path=Path(report_path);report=json.loads(path.read_text());read=report['application_spi_read']
    if not (report.get('success') and read.get('restored') and
        report.get('resident_profile',{}).get('restored') and report.get('allocator_trial',{}).get('restored') and
        report.get('allocator_trial',{}).get('allocated_and_freed') and not report.get('persistent_writes',True)):
        raise ValueError('SPI backup or restoration incomplete')
    if read.get('cpu_address')!=0x02097000 or read.get('spi_offset')!=0x97000 or len(read.get('passes',[]))!=2:
        raise ValueError('Expected two reads of the application partition')
    copies=[]
    for item in read['passes']:
        data=Path(item['path']).read_bytes()
        if len(data)!=0x48000 or data!=expected:raise ValueError('SPI application copy differs from original CPU partition')
        copies.append({'path':item['path'],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    return {'report':str(path),'matching_reads':True,'copies':copies,'restoration_verified':True}

def analyze_boot(flash_path,vendor_path,output,live_report=None,spi_report=None):
    flash=Path(flash_path).read_bytes()
    if hashlib.sha256(flash).hexdigest()!=PIN:raise ValueError('Saved CPU flash capture hash changed')
    live_match=None
    if live_report is not None:
        live=json.loads(Path(live_report).read_text())
        if not live.get('success'):raise ValueError('Live boot header probe failed')
        selected=[r for r in live['reads'] if 0x02046000<=int(r['address'],16)<0x02046400 or 0x02097000<=int(r['address'],16)<0x02097400]
        if len(selected)<58:raise ValueError('Live header probe is incomplete')
        for r in selected:
            offset=int(r['address'],16)-FLASH_BASE
            if int.from_bytes(flash[offset:offset+4],'little')!=int(r['value'],16):raise ValueError('Live boot header differs from saved capture')
        live_match=True
    found=[]
    for offset in range(0,len(flash)-HEADER_SIZE,0x1000):
        try:r=verify_image(flash[offset:])
        except ValueError:continue
        if not r['verified']:continue
        found.append(dict(r,cpu_address=FLASH_BASE+offset,cpu_view_offset=offset))
    ota=next(x for x in found if x['image_id']==0x2790);app=next(x for x in found if x['image_id']==0x2793)
    layout=partitions(flash[ota['cpu_view_offset']:])
    partition=next(x for x in layout if x['image_id']==0x2793)
    if partition['cpu_address']!=app['cpu_address'] or app['image_bytes']>partition['size']:raise ValueError('Application image/partition mismatch')
    vendor=Path(vendor_path).read_bytes();package,_=analyze(vendor)
    vendor_checks=[verify_image(vendor[i['file_offset']:i['file_offset']+i['size']]) for i in package['images']]
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    original=flash[partition['cpu_view_offset']:partition['cpu_view_offset']+partition['size']]
    (output/'original-app-partition.cpu-view.bin').write_bytes(original)
    (output/'original-app-image.bin').write_bytes(original[:app['image_bytes']])
    spi=validate_spi_backup(spi_report,original) if spi_report else None
    if spi:(output/'original-app-partition.spi.bin').write_bytes(original)
    result={'capture_sha256':PIN,'live_header_match':live_match,'live_header_report':str(live_report) if live_report else None,'current_images':found,'vendor_images':vendor_checks,'partitions':layout,
        'all_current_images_verified':len(found)==7,'all_vendor_images_verified':all(x['verified'] for x in vendor_checks),
        'application_partition':dict(partition,sha256=hashlib.sha256(original).hexdigest()),
        'verified_algorithms':{'crc16':'CRC16/IBM, poly A001 reflected, init 0, bytes 0x132..image end',
            'image_hash':'SHA-256, bytes 0x130..image end, stored 0x110..0x12f',
            'signature':'RSA-2048 PSS, SHA-256, salt 32; message bytes 0x110..image end; signature/key big endian'},
        'installation_ready':False,'physical_spi_mapping_verified':bool(spi),
        'physical_spi_mapping_scope':'application partition only' if spi else None,
        'application_spi_backup':spi,'program_erase_restore_verified':False,
        'boot_trust_policy_verified':False,'boot_entry_integration_verified':False,
        'persistent_writes_performed':False,
        'next_blocker':'Verify native storage program/erase/restore and boot-entry integration using the existing signed application; receiver entry points also remain unresolved.'}
    (output/'boot-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--vendor',type=Path,required=True)
    p.add_argument('--flash',type=Path,default=ROOT/'results/bt600-targets-20261017T101939.145845Z.bin')
    p.add_argument('--live-report',type=Path);p.add_argument('--spi-report',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'results/sprint-20261019/boot-analysis');a=p.parse_args()
    r=analyze_boot(a.flash,a.vendor,a.output,a.live_report,a.spi_report)
    print(json.dumps({k:r[k] for k in ('all_current_images_verified','all_vendor_images_verified','application_partition','installation_ready','next_blocker')},indent=2))
