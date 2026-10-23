"""Verify capture acceptance rejects data loss and incomplete restoration."""
import json,struct,tempfile,unittest
from pathlib import Path
from analyze_stream_capture import analyze
class CaptureAnalysisTests(unittest.TestCase):
    def fixture(self,folder):
        folder=Path(folder);raw=folder/'capture.pcm';path=folder/'capture.json'
        packets=[]
        for sequence in range(3):
            packets.append(struct.pack('<16h',sequence,*((1024,)*7+(-1024,)*8))+bytes(31))
        raw.write_bytes(b''.join(packets))
        report={'success':True,'original_configuration':0,'configuration_restored':True,
            'resident_profile':{'restored':True},'allocator_trial':{'restored':True,'allocated_and_freed':True},
            'iso_capture':{'pcm_path':str(raw),'packet_bytes':63,'restored':True,
                'frames':[{'status':0,'bytes':63} for _ in range(3)],
                'target_counters':dict(errors=0,pending=0,running=0,queued=5,completed=3,cancelled=2)}}
        path.write_text(json.dumps(report));return path,raw,report
    def test_complete_received_tone_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            p,_,_=self.fixture(folder);r=analyze(p)
            self.assertTrue(r['passed']);self.assertEqual(r['packets'],3);self.assertTrue(p.with_suffix('.wav').is_file())
    def test_missing_packet_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p,raw,_=self.fixture(folder);data=bytearray(raw.read_bytes());struct.pack_into('<H',data,63,4);raw.write_bytes(data)
            self.assertFalse(analyze(p,False)['passed'])
    def test_bad_pcm_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p,raw,_=self.fixture(folder);data=bytearray(raw.read_bytes());data[3]^=1;raw.write_bytes(data)
            self.assertFalse(analyze(p,False)['passed'])
    def test_unrestored_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p,_,r=self.fixture(folder);r['allocator_trial']['restored']=False;p.write_text(json.dumps(r))
            self.assertFalse(analyze(p,False)['passed'])
    def test_separate_frame_counters_are_loaded_and_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            p,_,r=self.fixture(folder);capture=r['iso_capture']
            frames=p.with_suffix('.frames.json');frames.write_text(json.dumps(capture.pop('frames')))
            capture.update(frame_path=str(frames),frame_count=3);p.write_text(json.dumps(r))
            self.assertTrue(analyze(p,False)['passed'])
            capture['frame_count']=4;p.write_text(json.dumps(r))
            self.assertFalse(analyze(p,False)['passed'])
    def test_irq_capture_requires_interrupt_and_native_queue_restoration(self):
        with tempfile.TemporaryDirectory() as folder:
            p,_,r=self.fixture(folder);capture=r['iso_capture'];capture['host_refill_required']=False
            for interrupt,drained in ((False,True),(True,False),(True,True)):
                capture.update(interrupt_restored=interrupt,native_drain_verified=drained);p.write_text(json.dumps(r))
                analysis=analyze(p,False)
                self.assertEqual(analysis['passed'],interrupt and drained)
                self.assertIn('device USB interrupt',analysis['source'])
    def test_transfer_completion_error_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p,_,r=self.fixture(folder);r['iso_capture']['completion_status']=-1;p.write_text(json.dumps(r))
            self.assertFalse(analyze(p,False)['passed'])
    def test_low_amplitude_counter_version_is_decoded(self):
        with tempfile.TemporaryDirectory() as folder:
            p,raw,r=self.fixture(folder);r['iso_capture']['format_version']=2
            raw.write_bytes(b''.join(struct.pack('<16h',s-128,-128,*((1024,)*6+(-1024,)*8))+bytes(31) for s in range(3)))
            p.write_text(json.dumps(r));self.assertTrue(analyze(p,False)['passed'])
    def test_stereo_full_rate_pcm_is_checked_through_the_last_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            p,raw,r=self.fixture(folder);a=r['iso_capture'];a.update(format_version=3,packet_bytes=192,sample_rate=48000,channels=2)
            a['frames']=[{'status':0,'bytes':192} for _ in range(3)]
            raw.write_bytes(b''.join(struct.pack('<96h',s-128,-128,*((1024,)*46+(-1024,)*48)) for s in range(3)))
            p.write_text(json.dumps(r));self.assertTrue(analyze(p,False)['passed'])
            damaged=bytearray(raw.read_bytes());damaged[191]^=1;raw.write_bytes(damaged)
            self.assertFalse(analyze(p,False)['passed'])
if __name__=='__main__':unittest.main()
