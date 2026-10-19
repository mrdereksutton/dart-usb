"""Validate a physical ISO trial and save its received 16 kHz mono PCM as WAV."""
import argparse, collections, hashlib, json, struct, wave
from pathlib import Path

def analyze(report_path, save=True):
    path=Path(report_path);report=json.loads(path.read_text());capture=report['iso_capture']
    raw=Path(capture['pcm_path']);payload=raw.read_bytes();size=capture['packet_bytes']
    if size!=63:raise ValueError('Expected the tested stock 63-byte ISO format')
    frames=capture['frames'];packets=[];offset=0
    for frame in frames:
        count=frame['bytes']
        if count:
            packets.append(payload[offset:offset+count]);offset+=count
    if offset!=len(payload):raise ValueError('Saved byte count differs from transfer counters')
    if not packets or any(len(p)!=63 for p in packets):raise ValueError('Incomplete PCM packets')
    version=capture.get('format_version',1)
    sequence=[((struct.unpack_from('<h',packet)[0]+128)&255)|(((struct.unpack_from('<h',packet,2)[0]+128)&255)<<8) if version==2 else struct.unpack_from('<H',packet)[0] for packet in packets]
    gaps=[{'packet':i+1,'previous':a,'current':b} for i,(a,b) in enumerate(zip(sequence,sequence[1:])) if (b-a)&65535!=1]
    expected=(1024,)*(6 if version==2 else 7)+(-1024,)*8
    bad=[i for i,p in enumerate(packets) if struct.unpack('<'+str(14 if version==2 else 15)+'h',p[4 if version==2 else 2:32])!=expected]
    target=capture['target_counters']
    restored=bool(capture.get('restored') and report.get('resident_profile',{}).get('restored') and
        report.get('allocator_trial',{}).get('restored') and report.get('allocator_trial',{}).get('allocated_and_freed') and
        (report.get('original_configuration')==1 or report.get('configuration_restored')))
    valid=bool(report.get('success') and not gaps and not bad and restored and
        target['errors']==0 and target['pending']==0 and target['running']==0 and
        target['queued']==target['completed']+target['cancelled'] and
        all(f['status']==0 and f['bytes']==63 for f in frames))
    wav=path.with_suffix('.wav');pcm=b''.join(packet[:32] for packet in packets)
    result={'passed':valid,'report':str(path.resolve()),'raw_sha256':hashlib.sha256(payload).hexdigest(),
        'packets':len(packets),'received_bytes':len(payload),'duration_seconds':len(pcm)/32000,
        'first_sequence':sequence[0],'last_sequence':sequence[-1],'sequence_gaps':gaps,'bad_payload_packets':bad,
        'frame_results':[{'status':s,'bytes':b,'count':n} for (s,b),n in collections.Counter((f['status'],f['bytes']) for f in frames).items()],
        'target_counters':target,'restoration_verified':restored,'wav_path':str(wav.resolve()),
        'format':'16 kHz mono signed 16-bit LE; initial sample(s) of each millisecond encode the packet counter; bytes 32..62 are transport padding',
        'source':'BT600 resident generated tone; host EP0 pump refills the native queue'}
    if save:
        with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
        path.with_suffix('.analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);a=p.parse_args()
    r=analyze(a.report);print(json.dumps(r,indent=2));raise SystemExit(0 if r['passed'] else 1)
