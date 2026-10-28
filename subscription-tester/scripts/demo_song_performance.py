"""End-to-end offline HTTP/SDK demonstration. Synthetic fixtures; never uses production state.

Run with the app's Python from subscription-tester. The isolated mock server stays
open with --serve, otherwise output records/files remain available for inspection.
"""
import argparse
import array
import base64
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_client import StudioClient
from studio_server import Studio, StudioHandler


def wait(get,job):
    deadline=time.monotonic()+90
    while job['status'] in ('queued','running','rendering'):
        if time.monotonic()>deadline:raise RuntimeError('Local job timeout; inspect saved job before retrying.')
        time.sleep(.05);job=get(job['id'])
    if job['status']!='done':raise RuntimeError(job.get('error') or job['status'])
    return job


def run(client,folder,ffmpeg):
    def upload(path):
        m=client.request('editing/media','POST',dict(name=path.name,base64=base64.b64encode(path.read_bytes()).decode()))
        return dict(kind='upload',id=m['id'])
    master=folder/'fixture-master.wav';video=folder/'fixture-take.mp4';rate=16000
    samples=array.array('h',(int(12000*math.sin(2*math.pi*440*n/rate)*(.8 if (n/rate)%0.5<.12 else .05)) for n in range(2*rate)))
    with wave.open(str(master),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(samples.tobytes())
    subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=c=red:s=160x90:r=24:d=1.25',
        '-f','lavfi','-i','color=c=blue:s=160x90:r=24:d=1.25','-f','lavfi','-i','sine=frequency=1200:duration=2.5',
        '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-map','2:a','-c:v','libx264','-c:a','aac',str(video)],check=True,timeout=30)
    production=client.request('productions','POST',dict(kind='quick',title='Offline Song Performance demonstration'))['production']
    project=client.create_song_project('Original-clock fixture',production['id'],upload(master),lyrics='retry')
    analysis=wait(client.song_analysis_job,client.analyze_song(project,idempotency_key='demo-song-analysis'))
    project=client.apply_song_analysis(analysis,project)
    project=client.edit_song_project(project,cues=[*project['cues'],dict(id='literal-retry',kind='word',start=.5,end=.9,text='retry',source='human',method='manual',review_state='reviewed')])
    source=upload(video);selections=[];comparisons=[]
    for order,(start,end,mode) in enumerate(((0,1,'dance_only'),(1,2,'cutaway'))):
        shot=client.create_song_shot(project,title='Fixture '+mode,order=order,start=start,end=end,duration=2,
            mode=mode,leading_handle=.25,trailing_handle=.25,story_beat='A red view gives way to a blue view.',
            choreography='Step once and hold.' if order==0 else 'A close view of the blue prop.',camera='Locked camera.')
        project=client.song_project(project['id'])
        proposal=client.prepare_song_shot(shot,project)
        assert proposal['request']['generate_audio'] is False
        assert 'reference_audios' not in proposal['request']
        applied=client.apply_song_draft(shot,project,proposal);shot=applied['shot']
        review=client.create_song_take_review(shot,source)
        # Known synthetic fixture frames are inspected locally; never claim continuous human playback.
        review=client.edit_song_take_review(review,song_anchor=start,clip_anchor=start+.25,
            method='sampled_frames',reviewer='Offline synthetic fixture inspection',notes='Known color fixtures; not a singing or continuous playback assessment.',
            intervals=[dict(start=0,end=2.5,state='usable',note='Synthetic color coverage fixture')])
        assert not review['lip_sync_approved']
        if order==0:
            comparison=client.compare_song_take(shot,review,idempotency_key='demo-song-comparison')
            export=wait(lambda i:client.request('editing/exports/'+i),comparison['export'])
            comparisons.append(export['id'])
        selections.append(dict(review_id=review['id'],expected_review_revision=review['revision'],song_start=start,song_end=end))
    project=client.song_project(project['id'])
    coverage=client.assemble_song(project,selections,idempotency_key='demo-song-coverage')
    assert coverage['can_apply'] and not coverage['coverage']['missing_spans']
    assembly=client.assemble_song(project,selections,apply=True,idempotency_key='demo-song-assembly')
    export=client.request('editing/exports','POST',dict(timeline_id=assembly['timeline_id'],expected_revision=assembly['timeline_revision']),'demo-song-export')
    export=wait(lambda i:client.request('editing/exports/'+i),export)
    output=folder/'song-working-edit.mp4';output.write_bytes(client.request('editing/exports/'+export['id']+'/download'))
    comparison_output=folder/'song-comparison.mp4';comparison_output.write_bytes(client.request('editing/exports/'+comparisons[0]+'/download'))
    subprocess.run([ffmpeg,'-v','error','-i',str(output),'-f','null','-'],check=True,timeout=30)
    def pcm(path):
        raw=subprocess.run([ffmpeg,'-v','error','-i',str(path),'-ac','1','-ar',str(rate),'-f','f32le','-'],capture_output=True,check=True).stdout
        return array.array('f',raw)
    original=pcm(master);rendered=pcm(output);correlations=[]
    for at in (.1,.9,1.7):
        a=int(at*rate);b=a+1600;x=original[a:b];y=rendered[a:b]
        score=sum(v*w for v,w in zip(x,y))/math.sqrt(sum(v*v for v in x)*sum(w*w for w in y));assert score>.9
        correlations.append(round(score,6))
    def color(path,at):
        raw=subprocess.run([ffmpeg,'-v','error','-ss',str(at),'-i',str(path),'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
        return list(raw[:3])
    colors=[color(output,.9),color(output,1.1)]
    assert colors[0][0]>colors[0][2]*2 and colors[1][2]>colors[1][0]*2
    assert client.request('jobs')==[], 'This demonstration must never submit generations.'
    return dict(production_id=production['id'],project_id=project['id'],assembly_id=assembly['id'],timeline_id=assembly['timeline_id'],
        export_id=export['id'],comparison_ids=comparisons,output=str(output),comparison=str(comparison_output),
        master_audio_correlations=correlations,boundary_colors=colors,paid_generation_requests=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path);parser.add_argument('--serve',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args();folder=args.state_dir or Path(tempfile.mkdtemp(prefix='imagine-song-demo-'))
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'state').exists():parser.error('Use a new empty demonstration directory.')
    app=Studio(mock=True,storage=folder/'state');server=ThreadingHTTPServer(('127.0.0.1',args.port),StudioHandler);server.tester=app
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}';client=StudioClient(url,app.agent.token_path)
    try:
        report={**run(client,folder,app.editing.ffmpeg),'url':url,'state_dir':str(folder/'state')}
        (folder/'demonstration.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)
        if args.serve:
            print('Isolated mock Studio remains available; Ctrl+C to stop.',flush=True)
            while True:time.sleep(1)
    except KeyboardInterrupt:pass
    finally:
        server.shutdown();server.server_close();thread.join();app.productions.sql.close()

if __name__=='__main__':main()
