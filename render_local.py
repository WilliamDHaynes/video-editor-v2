"""CPU-limited offline assembly renderer. Reads original; writes only new trial outputs."""
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
from settings import FFMPEG, FFPROBE, SOURCE, source_duration
OUT=ROOT/'outputs'
TMP=ROOT/'render-parts'

def run(args,log):
    if shutil.disk_usage(ROOT).free < 3*1024**3:
        raise RuntimeError('Less than 3 GiB free; stopped before next media command')
    with log.open('ab') as f:
        subprocess.run(args,stdout=f,stderr=f,check=True,creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)

def probe(path):
    return json.loads(subprocess.check_output([FFPROBE,'-v','error','-show_format','-show_streams','-of','json',str(path)],text=True))

def base():
    return [FFMPEG,'-nostdin','-hide_banner','-loglevel','warning','-n','-hwaccel','none','-threads','2']

def video_options():
    return ['-c:v','libx264','-preset','veryfast','-crf','24','-maxrate','3M','-bufsize','6M','-pix_fmt','yuv420p','-threads','2','-c:a','aac','-b:a','160k','-ar','48000','-ac','2','-movflags','+faststart']

def validate(edl):
    if Path(edl.get('source','')).resolve()!=SOURCE.resolve():
        raise ValueError('Only the approved recording is supported')
    segs=edl.get('segments',[])
    if not 1<=len(segs)<=12:
        raise ValueError('Choose 1-12 segments')
    previous=0
    for s in segs:
        a,b=s['start'],s['end']
        if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or not 0<=a<b<=source_duration() or a<previous or b-a>180:
            raise ValueError('Invalid, overlapping, unordered or overlong source range')
        previous=b
    if sum(s['end']-s['start'] for s in segs)>660:
        raise ValueError('Draft exceeds eleven-minute bound')
    if edl.get('audio_source_index') not in (0,1,2):
        raise ValueError('Invalid audio track')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--edl',default='offline_edl.json');ap.add_argument('--prefix',default='OFFLINE_REVIEW');opts=ap.parse_args()
    if opts.edl not in ('offline_edl.json','ai_edl.json') or opts.prefix not in ('OFFLINE_REVIEW','AI_SAMPLE_REVIEW'):
        raise ValueError('Unsupported render target')
    edl=json.loads((ROOT/opts.edl).read_text(encoding='utf-8'));validate(edl)
    before=SOURCE.stat();OUT.mkdir(exist_ok=True);TMP.mkdir(exist_ok=True)
    progress=ROOT/'render-status.json';log=ROOT/f'{opts.prefix}_render.log'
    def status(stage,**extra):
        data={'stage':stage,'prefix':opts.prefix,**extra};progress.write_text(json.dumps(data,indent=2),encoding='utf-8');print(stage,flush=True)
    parts=[];cut_times=[];elapsed=0
    try:
        for i,s in enumerate(edl['segments']):
            status(f'Rendering scene {i+1}/{len(edl["segments"])}',scene=i+1,total=len(edl['segments']))
            d=s['end']-s['start'];p=TMP/f'{opts.prefix}_scene_{i+1:02}.mp4'
            # Source ranges are deliberately fixed and labels are trusted local text.
            label=''.join(c for c in s['label'] if c.isalnum() or c in ' -')[:50]
            vf=f"fps=30,scale=1280:720,drawtext=text='{label}':fontsize=28:fontcolor=white:box=1:boxcolor=black@0.55:x=28:y=28:enable='lt(t,3)'"
            af=f'afade=t=in:d=0.03,afade=t=out:st={max(0,d-0.03)}:d=0.03,alimiter=limit=0.95:level=false'
            run(base()+['-ss',str(s['start']),'-i',str(SOURCE),'-t',str(d),'-map','0:v:0','-map',f'0:a:{edl["audio_source_index"]}','-vf',vf,'-filter_threads','1','-af',af]+video_options()+[str(p)],log)
            parts.append(p);elapsed+=d;cut_times.append(elapsed)
        listing=TMP/f'{opts.prefix}_concat.txt';listing.write_text(''.join(f"file '{p.name}'\n" for p in parts),encoding='utf-8')
        final=OUT/f'{opts.prefix}_video_16x9.mp4';status('Joining scenes and normalizing audio')
        run([FFMPEG,'-nostdin','-hide_banner','-loglevel','warning','-n','-threads','2','-f','concat','-safe','1','-i',str(listing),'-map','0:v:0','-map','0:a:0','-c:v','copy','-af','loudnorm=I=-16:TP=-1.5:LRA=11','-filter_threads','1','-c:a','aac','-b:a','160k','-ar','48000','-ac','2','-threads','2','-movflags','+faststart',str(final)],log)
        results=[{'file':str(final.relative_to(ROOT)),'kind':'landscape','source_ranges':edl['segments'],'expected_seconds':elapsed,'cut_times_seconds':cut_times[:-1]}]
        if opts.edl=='offline_edl.json':
            for i,s in enumerate(edl.get('shorts',[])):
                status(f'Rendering vertical context short {i+1}')
                target=OUT/f'OFFLINE_REVIEW_short_{i+1:02}_9x16.mp4';d=s['end']-s['start'];label=''.join(c for c in s['label'] if c.isalnum() or c in ' -')[:50]
                vf=f"fps=30,scale=720:405,pad=720:1280:0:438:color=0x111a26,drawtext=text='VIDEO REVIEW':fontsize=38:fontcolor=white:x=(w-tw)/2:y=230,drawtext=text='{label}':fontsize=28:fontcolor=white:x=(w-tw)/2:y=300,drawtext=text='LOCAL REVIEW - FULL FRAME':fontsize=20:fontcolor=0xa9bacb:x=(w-tw)/2:y=930"
                run(base()+['-ss',str(s['start']),'-i',str(SOURCE),'-t',str(d),'-map','0:v:0','-map',f'0:a:{edl["audio_source_index"]}','-vf',vf,'-filter_threads','1','-af',f'loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.05,afade=t=out:st={d-0.1}:d=0.1']+video_options()+[str(target)],log)
                results.append({'file':str(target.relative_to(ROOT)),'kind':'vertical_full_frame_context','source_ranges':[s],'expected_seconds':d})
        status('Checking output decode and metadata')
        for r in results:
            path=ROOT/r['file'];meta=probe(path);r.update(bytes=path.stat().st_size,duration_seconds=float(meta['format']['duration']),streams=[{k:s.get(k) for k in ('codec_type','codec_name','width','height','start_time','duration','avg_frame_rate')} for s in meta['streams']])
            decode_log=ROOT/(path.stem+'_decode-check.log')
            run([FFMPEG,'-nostdin','-hide_banner','-v','error','-xerror','-hwaccel','none','-threads','2','-i',str(path),'-map','0:v:0','-map','0:a:0','-f','null','NUL'],decode_log)
            r['decode_check']='passed';r['decode_log_bytes']=decode_log.stat().st_size
        after=SOURCE.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
            raise RuntimeError('Original metadata changed')
        result={'kind':edl['kind'],'original_size_mtime_unchanged':True,'audio_track_role_verified':False,'audio_track_used':edl['audio_source_index'],'no_dialogue_or_event_claims_added':True,'outputs':results}
        (ROOT/f'{opts.prefix}_render-manifest.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        status('Complete',outputs=results)
    except Exception as exc:
        status('Stopped',error=type(exc).__name__+'; see local render log')
        raise

if __name__=='__main__':main()
