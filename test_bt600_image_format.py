"""Actual CU signed-image checks, including tampering that preserves CRC/SHA."""
from pathlib import Path
import hashlib,json,struct,tempfile,unittest
from bt600_image_format import verify_image,crc16_ibm,partitions
from analyze_bt600_boot import validate_spi_backup
ROOT=Path(__file__).resolve().parent
class CuImageFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'results/bt600-targets-20261017T101939.145845Z.bin'
        if not path.is_file():raise unittest.SkipTest('Pinned CU CPU flash capture required')
        cls.flash=path.read_bytes();n=struct.unpack_from('<I',cls.flash,0x97000+0x138)[0]
        cls.app=cls.flash[0x97000:0x97400+n];cls.ota=cls.flash[0x46000:0x46400]
    def test_crc_known_check(self):self.assertEqual(crc16_ibm(b'123456789'),0xbb3d)
    def test_current_application_passes_all_checks(self):
        r=verify_image(self.app);self.assertTrue(r['verified']);self.assertTrue(r['known_key']);self.assertEqual(r['execute'],0x2097400)
    def test_all_seven_current_images_verify(self):
        for offset in (0x46000,0x48000,0x85000,0x97000,0xdf000,0xec000,0x114000):
            with self.subTest(offset=hex(offset)):self.assertTrue(verify_image(self.flash[offset:])['verified'])
    def test_ota_table_matches_current_application_partition(self):
        app=next(p for p in partitions(self.ota) if p['image_id']==0x2793)
        self.assertEqual((app['cpu_address'],app['size']),(0x2097000,0x48000))
    def test_changed_payload_rejects_crc_hash_and_signature(self):
        image=bytearray(self.app);image[0x420]^=1;r=verify_image(image)
        self.assertFalse(r['crc16_valid']);self.assertFalse(r['sha256_valid']);self.assertFalse(r['rsa_pss_valid'])
    def test_changed_signature_rejects_even_with_valid_crc_and_hash(self):
        image=bytearray(self.app);image[0x10]^=1;r=verify_image(image)
        self.assertTrue(r['crc16_valid']);self.assertTrue(r['sha256_valid']);self.assertFalse(r['rsa_pss_valid']);self.assertFalse(r['verified'])
    def test_recomputed_crc_and_hash_cannot_replace_signature(self):
        image=bytearray(self.app);image[0x420]^=1
        struct.pack_into('<H',image,0x130,crc16_ibm(image[0x132:]))
        image[0x110:0x130]=hashlib.sha256(image[0x130:]).digest();r=verify_image(image)
        self.assertTrue(r['crc16_valid']);self.assertTrue(r['sha256_valid']);self.assertFalse(r['rsa_pss_valid'])
    def test_truncated_image_is_rejected(self):
        with self.assertRaises(ValueError):verify_image(self.app[:-1])

class SpiBackupValidationTests(unittest.TestCase):
    def fixture(self,folder):
        folder=Path(folder);data=bytes(range(256))*1152
        copies=[]
        for n in (1,2):
            path=folder/f'pass{n}.bin';path.write_bytes(data);copies.append({'path':str(path)})
        report={'success':True,'persistent_writes':False,'resident_profile':{'restored':True},
            'allocator_trial':{'restored':True,'allocated_and_freed':True},
            'application_spi_read':{'restored':True,'cpu_address':0x2097000,'spi_offset':0x97000,'passes':copies}}
        path=folder/'report.json';path.write_text(json.dumps(report));return path,report,data
    def test_two_matching_copies_are_verified_from_their_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_,data=self.fixture(folder);result=validate_spi_backup(path,data)
            self.assertTrue(result['matching_reads']);self.assertEqual(len(result['copies']),2)
    def test_corrupt_second_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path,report,data=self.fixture(folder);Path(report['application_spi_read']['passes'][1]['path']).write_bytes(data[:-1]+b'\0')
            with self.assertRaisesRegex(ValueError,'differs'):validate_spi_backup(path,data)
    def test_unrestored_heap_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path,report,data=self.fixture(folder);report['allocator_trial']['restored']=False;path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'restoration'):validate_spi_backup(path,data)
    def test_single_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path,report,data=self.fixture(folder);report['application_spi_read']['passes'].pop();path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'two reads'):validate_spi_backup(path,data)
if __name__=='__main__':unittest.main()
