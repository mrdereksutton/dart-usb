"""Validate a physical ISO trial and save received PCM as WAV."""
import argparse, collections, hashlib, json, struct, wave
from pathlib import Path

def analyze(report_path, save=True):
    path=Path(report_path);report=json.loads(path.read_text());capture=report['iso_capture']
    raw=Path(capture['pcm_path']);payload=raw.read_bytes();size=capture['packet_bytes']
    if size not in (63,192):raise ValueError('Expected a tested 63/192-byte ISO format')
    frames=capture.get('frames')
    if frames is None:frames=json.loads(Path(capture['frame_path']).read_text())
    packets=[];offset=0
    for frame in frames:
        count=frame['bytes']
        if count:
            packets.append(payload[offset:offset+count]);offset+=count
    if offset!=len(payload):raise ValueError('Saved byte count differs from transfer counters')
    if not packets or any(len(p)!=size for p in packets):raise ValueError('Incomplete PCM packets')
    version=capture.get('format_version',1)
    sequence=[((struct.unpack_from('<h',packet)[0]+128)&255)|(((struct.unpack_from('<h',packet,2)[0]+128)&255)<<8) if version>=2 else struct.unpack_from('<H',packet)[0] for packet in packets]
    gaps=[{'packet':i+1,'previous':a,'current':b} for i,(a,b) in enumerate(zip(sequence,sequence[1:])) if (b-a)&65535!=1]
    expected=((1024,)*46+(-1024,)*48) if size==192 else (1024,)*(6 if version>=2 else 7)+(-1024,)*8
    end=192 if size==192 else 32
    bad=[i for i,p in enumerate(packets) if struct.unpack('<'+str(len(expected))+'h',p[4 if version>=2 else 2:end])!=expected]
    target=capture['target_counters']
    restored=bool(capture.get('restored') and report.get('resident_profile',{}).get('restored') and
        report.get('allocator_trial',{}).get('restored') and report.get('allocator_trial',{}).get('allocated_and_freed') and
        (report.get('original_configuration')==1 or report.get('configuration_restored')))
    irq_refill=capture.get('host_refill_required') is False
    valid=bool(report.get('success') and not gaps and not bad and restored and
        (not irq_refill or (capture.get('interrupt_restored') and capture.get('native_drain_verified'))) and
        capture.get('completion_status',0)==0 and capture.get('frame_count',len(frames))==len(frames) and
        target['errors']==0 and target['pending']==0 and target['running']==0 and
        target['queued']==target['completed']+target['cancelled'] and
        all(f['status']==0 and f['bytes']==size for f in frames))
    wav=path.with_suffix('.wav');pcm=b''.join(packet[:192 if size==192 else 32] for packet in packets)
    rate=capture.get('sample_rate',16000);channels=capture.get('channels',1)
    result={'passed':valid,'report':str(path.resolve()),'raw_sha256':hashlib.sha256(payload).hexdigest(),
        'packets':len(packets),'received_bytes':len(payload),'duration_seconds':len(pcm)/(rate*channels*2),
        'first_sequence':sequence[0],'last_sequence':sequence[-1],'sequence_gaps':gaps,'bad_payload_packets':bad,
        'frame_results':[{'status':s,'bytes':b,'count':n} for (s,b),n in collections.Counter((f['status'],f['bytes']) for f in frames).items()],
        'target_counters':target,'restoration_verified':restored,'wav_path':str(wav.resolve()),
        'format':f'{rate} Hz, {channels} channels, signed 16-bit LE; initial samples encode packet counter; '+('bytes 32..62 are padding' if size==63 else '192 PCM bytes per millisecond'),
        'source':'BT600 resident generated tone; '+('device USB interrupt refills the native queue' if irq_refill else 'host EP0 pump refills the native queue')}
    if save:
        with wave.open(str(wav),'wb') as w:w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm)
        path.with_suffix('.analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path);a=p.parse_args()
    r=analyze(a.report)
    summary={k:r[k] for k in ('passed','packets','received_bytes','duration_seconds','first_sequence','last_sequence','restoration_verified','wav_path')}
    summary.update(sequence_gap_count=len(r['sequence_gaps']),bad_payload_count=len(r['bad_payload_packets']))
    print(json.dumps(summary,indent=2));raise SystemExit(0 if r['passed'] else 1)
