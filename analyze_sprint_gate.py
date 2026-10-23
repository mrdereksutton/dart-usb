"""Save the sprint dependency decision against pinned local vendor evidence."""
import argparse, datetime, hashlib, json, re
from pathlib import Path
from analyze_asus_firmware import analyze
ROOT=Path(__file__).resolve().parent

def assess(folder):
    folder=Path(folder)
    firmware=next((folder/'vendor').rglob('rtl8761cu_mx_fw'))
    driver=next((folder/'vendor').rglob('rtk_misc.c'))
    sdk=folder/'bt_a2dp.h'
    layout, _ = analyze(firmware.read_bytes())
    source=driver.read_text()
    assert all(x in source for x in ('0xfdbb','UPG_SUBCMD_CODE','0xfc20','PATCH_SEG_MAX'))
    return {'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'started_utc':'2026-10-19T12:44:24+00:00','checkpoint_due_utc':'2026-10-19T13:04:24+00:00',
        'standalone_route_ready':False,'two_hour_standalone_target_feasible':False,
        'receiver':{'ready':False,'native_init_entry':None,'pairing_entry':None,'decoded_pcm_callback':None,
            'related_sdk_chip_family':'RTL87x3E',
            'reference_declarations':re.findall(r'bool (bt_a2dp_[a-z_]+)\(',sdk.read_text()),
            'reference_header_sha256':hashlib.sha256(sdk.read_bytes()).hexdigest(),
            'remaining':'Resolve callable RTL8761CU receiver, pairing and SBC-to-PCM entry points; the other-family header cannot supply addresses/ABI.'},
        'persistent_boot':{'ready':False,'firmware_sha256':layout['firmware_sha256'],
            'eco':layout['eco'],'container':'RTBTCore','images':layout['images'],
            'application_base':layout['application_base'],
            'vendor_driver_sha256':hashlib.sha256(driver.read_bytes()).hexdigest(),
            'vendor_upgrade_query':{'opcode':'0xfdbb','subopcode':1,'header_bytes':128,'executed':False},
            'vendor_download':{'opcode':'0xfc20','fragment_data_bytes':252,'end_bit':'0x80','executed':False},
            'image_validation_algorithm_verified':False,'physical_storage_offsets_verified':False,
            'raw_storage_restore_verified':False,
            'remaining':'Trace the CU boot/upgrade validator and physical image-bank mapping; obtain original bytes for a reversible application-sector install.'},
        'selected_branch':'physical USB PCM capture; resolve boot blocker; preserve build/results',
        'persistent_writes_performed':False}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args()
    report=assess(a.folder);target=a.folder/'dependency-gate.json';target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('checked_utc','standalone_route_ready','two_hour_standalone_target_feasible','selected_branch')},indent=2))
