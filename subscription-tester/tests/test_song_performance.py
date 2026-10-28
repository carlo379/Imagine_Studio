"""Behavioral song workflow using private synthetic media; no provider submissions."""
import array
import base64
import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import wave
from unittest.mock import Mock, patch

from agent_api import APIError
from studio_server import Studio
from song_performance import frame,song_time

class SongTests(unittest.TestCase):
    def test_recognition_skips_invalid_word_times_and_applies_valid_cues(self):
        self.app.editing.transcriber_available=lambda:True
        self.app.editing.transcriber=lambda path:[dict(words=[
            dict(start=.1,end=.4,word='Two',probability=.9),
            dict(start=.4,end=.4,word='small'),
            dict(start=.5,end=.9,word='hands',probability=.9)])]
        result=dict(cues=[],notes=[])
        self.s.recognize(result,self.root/'unused.wav',lambda:False)
        self.assertEqual([w['text'] for w in result['cues']],['Two','hands'])
        self.assertTrue(any('Skipped 1' in n for n in result['notes']))
        p=self.call('PATCH','projects/'+self.project['id'],dict(
            expected_revision=self.project['revision'],cues=result['cues']))
        self.assertEqual(len(p['cues']),2)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.app=Studio(mock=True,storage=self.root/'state')
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.app.productions.sql.close)
        self.s=self.app.song_performance
        self.production=self.app.productions.dispatch('POST',[],dict(kind='quick',title='Song fixture'))[1]['production']
        self.app.generate=Mock(side_effect=AssertionError('No provider generation allowed'))
        self.app.begin=Mock(side_effect=AssertionError('No provider action allowed'))
        self.master=self.wav('master',2)
        self.project=self.call('POST','projects',dict(title='Clock fixture',production_id=self.production['id'],master=self.master,lyrics='retry'))

    def call(self,method,path,data=None,key=None):
        return self.app.agent.dispatch(method,'/agent/v1/song-performance/'+path,data or {},key)[1]

    def wav(self,name,duration=2,shift=0,different=False):
        rate=16000;values=[]
        for n in range(round(duration*rate)):
            t=n/rate-shift
            pulse=(t%0.5)<.12 and t>=.25
            frequency=440 if not different else 731
            amplitude=.6 if pulse else .01
            values.append(int(amplitude*32767*math.sin(2*math.pi*frequency*t)))
        path=self.root/(name+'.wav')
        with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(array.array('h',values).tobytes())
        m=self.app.editing.upload(dict(name=path.name,base64=base64.b64encode(path.read_bytes()).decode()))
        return dict(kind='upload',id=m['id'])

    def video(self,duration=2.25):
        path=self.root/'take.mp4'
        subprocess.run([self.app.editing.ffmpeg,'-v','error','-y','-f','lavfi','-i',f"color=c=red:s=160x90:r=24:d={duration/2}",
            '-f','lavfi','-i',f"color=c=blue:s=160x90:r=24:d={duration/2}",'-f','lavfi','-i',f'sine=frequency=1200:duration={duration}',
            '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-map','2:a','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],check=True,timeout=30)
        m=self.app.editing.upload(dict(name=path.name,base64=base64.b64encode(path.read_bytes()).decode()))
        return dict(kind='upload',id=m['id'])

    def plan(self,**changes):
        p=self.call('GET','projects/'+self.project['id'])
        s=self.call('POST','projects/'+p['id']+'/shots',dict(expected_revision=p['revision'],shot=dict(start=0,end=2,duration=3,mode='dance_only',choreography='Step left and right.',**changes)))
        self.project=self.call('GET','projects/'+p['id']);return s

    def wait_analysis(self,j):
        for _ in range(300):
            j=self.call('GET','analysis-jobs/'+j['id'])
            if j['status'] not in ('queued','running'):return j
            time.sleep(.02)
        self.fail('Analysis timeout')

    def wait_export(self,identity):
        for _ in range(1000):
            j=self.app.agent.dispatch('GET','/agent/v1/editing/exports/'+identity,{})[1]
            if j['status'] not in ('queued','rendering'):
                self.assertEqual(j['status'],'done',j.get('error'));return j
            time.sleep(.02)
        self.fail('Export timeout')

    def reviewed(self,shot,source=None,**changes):
        r=self.call('POST','shots/'+shot['id']+'/take-reviews',dict(expected_revision=shot['revision'],source=source or self.video()))
        return self.call('PATCH','shots/'+shot['id']+'/take-reviews/'+r['id'],dict(expected_revision=r['revision'],
            method='human_continuous_playback',reviewer='Fixture operator',intervals=[dict(start=0,end=r['source_metadata']['duration'],state='usable')],**changes))

    def test_capabilities_honest_sources_scope_and_revisions(self):
        cap=self.call('GET','schema');self.assertFalse(cap['recording_generation']['enabled']);self.assertEqual(cap['recording_generation']['http_status'],403)
        self.assertTrue(cap['local_analysis']['manual_cues']);self.assertFalse(cap['local_analysis']['forced_alignment'])
        p=self.project
        with self.assertRaises(APIError) as stale:self.call('PATCH','projects/'+p['id'],dict(expected_revision=999,lyrics='lost'))
        self.assertEqual(stale.exception.status,409)
        for source in ({'kind':'upload','id':'missing'},{'path':'/tmp/song.wav'},{'url':'https://example.com/song.wav'}):
            with self.assertRaises(APIError):self.call('POST','projects',dict(title='Bad',production_id=self.production['id'],master=source))
        other=Studio(mock=True,storage=self.root/'other')
        try:
            with self.assertRaises(APIError):other.agent.dispatch('GET','/agent/v1/song-performance/projects/'+p['id'],{})
            with self.assertRaises(APIError):other.song_performance.metadata(self.master,audio=True)
        finally:other.productions.sql.close()
        self.assertEqual(self.app.agent.dispatch('GET','/agent/v1/schema',{})[1]['song_performance']['defaults']['resolution'],'480p')

    def test_analysis_cache_merge_cancellation_and_missing_transcriber(self):
        self.app.editing.transcriber_available=lambda:False
        p=self.project
        with self.assertRaises(APIError):self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']))
        j=self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']),key='analyze-0001')
        same=self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']),key='analyze-0001');self.assertEqual(j['id'],same['id'])
        with self.assertRaises(APIError) as conflict:self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=999),key='analyze-0001')
        self.assertEqual(conflict.exception.code,'idempotency_conflict')
        j=self.wait_analysis(j);self.assertEqual(j['status'],'done',j)
        p=self.call('POST','analysis-jobs/'+j['id']+'/apply',dict(expected_revision=j['revision'],expected_project_revision=p['revision']))
        self.assertTrue(p['analysis']['result']['waveform']['values']);self.assertTrue(any(c['kind']=='beat' for c in p['cues']))
        self.assertFalse(any(c['kind']=='word' for c in p['cues']))
        manual=dict(id='literal-retry',kind='word',start=.5,end=.9,text='retry',source='human',method='manual',review_state='reviewed')
        p=self.call('PATCH','projects/'+p['id'],dict(expected_revision=p['revision'],cues=p['cues']+[manual]))
        j=self.wait_analysis(self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']),key='analyze-0002'))
        p=self.call('POST','analysis-jobs/'+j['id']+'/apply',dict(expected_revision=j['revision'],expected_project_revision=p['revision']))
        self.assertEqual(next(c for c in p['cues'] if c['id']=='literal-retry'),manual)
        self.assertEqual(p['lyrics'],'retry');self.app.generate.assert_not_called()
        with patch.object(self.app,'spawn'):
            j=self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']),key='analyze-0003')
        j=self.call('POST','analysis-jobs/'+j['id']+'/cancel',dict(expected_revision=j['revision']));self.assertEqual(j['status'],'cancelled')
        with self.assertRaises(APIError):self.call('POST','analysis-jobs/'+j['id']+'/apply',dict(expected_revision=j['revision'],expected_project_revision=p['revision']))

    def test_stems_equal_duration_need_review_and_verified_offsets(self):
        p=self.project;stem=self.wav('different',different=True)
        p=self.call('PATCH','projects/'+p['id'],dict(expected_revision=p['revision'],stems={'lead_vocal':stem}))
        j=self.wait_analysis(self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']),key='stem-0001'))
        p=self.call('POST','analysis-jobs/'+j['id']+'/apply',dict(expected_revision=j['revision'],expected_project_revision=p['revision']))
        self.assertEqual(p['stem_alignment']['lead_vocal']['status'],'needs_review')
        self.assertFalse(any(c['kind']=='vocal_activity' for c in p['cues']))
        p=self.call('PATCH','projects/'+p['id'],dict(expected_revision=p['revision'],stem_alignment={'lead_vocal':dict(status='verified',human_correction_s=.1)}))
        j=self.wait_analysis(self.call('POST','projects/'+p['id']+'/analyze',dict(expected_revision=p['revision']),key='stem-0002'))
        p=self.call('POST','analysis-jobs/'+j['id']+'/apply',dict(expected_revision=j['revision'],expected_project_revision=p['revision']))
        self.assertTrue(any(c['kind']=='vocal_activity' for c in p['cues']))

    def test_prepare_apply_modes_idempotent_no_generation_and_voice_preservation(self):
        s=self.plan();p=self.project
        proposal=self.call('POST','shots/'+s['id']+'/prepare',dict(expected_revision=s['revision'],expected_project_revision=p['revision']))
        self.assertFalse(proposal['request']['generate_audio']);self.assertNotIn('reference_audios',proposal['request']);self.assertIn('mouth closed',proposal['scene']['prompt'])
        result=self.call('POST','shots/'+s['id']+'/apply-draft',dict(expected_revision=s['revision'],expected_project_revision=p['revision'],preparation=proposal))
        self.assertEqual(result['draft']['scene']['resolution'],'480p');self.assertEqual(result['draft']['scene']['model'],'grok-imagine-video-1.5');self.app.generate.assert_not_called()
        s=result['shot'];p=self.call('GET','projects/'+p['id'])
        s=self.call('PATCH','shots/'+s['id'],dict(expected_revision=s['revision'],expected_project_revision=p['revision'],changes=dict(mode='singing',lyric_text='retry',prompt='')))
        p=self.call('GET','projects/'+p['id']);draft=self.app.agent.record(s['draft_id'])
        proposal=self.call('POST','shots/'+s['id']+'/prepare',dict(expected_revision=s['revision'],expected_project_revision=p['revision'],expected_draft_revision=draft['revision']))
        self.assertEqual(proposal['request']['reference_audios'],[{'voice_id':'ursa'}]);self.assertIn('"retry"',proposal['scene']['prompt'])
        result=self.call('POST','shots/'+s['id']+'/apply-draft',dict(expected_revision=s['revision'],expected_project_revision=p['revision'],expected_draft_revision=draft['revision'],preparation=proposal))
        s=result['shot'];p=self.call('GET','projects/'+p['id'])
        s=self.call('PATCH','shots/'+s['id'],dict(expected_revision=s['revision'],expected_project_revision=p['revision'],changes=dict(mode='dance_only')))
        p=self.call('GET','projects/'+p['id']);draft=self.app.agent.record(s['draft_id'])
        proposal=self.call('POST','shots/'+s['id']+'/prepare',dict(expected_revision=s['revision'],expected_project_revision=p['revision'],expected_draft_revision=draft['revision']))
        self.assertTrue(proposal['scene']['voices']);self.assertNotIn('reference_audios',proposal['request'])
        self.assertIsNone(proposal['scene']['recording']);self.app.generate.assert_not_called()

    def test_master_replacement_keeps_history_stales_reviews(self):
        s=self.plan();r=self.reviewed(s);p=self.project
        replacement=self.wav('replacement',different=True)
        p=self.call('PATCH','projects/'+p['id'],dict(expected_revision=p['revision'],master=replacement))
        self.assertEqual(p['master_version'],2);self.assertTrue(p['shots'][0]['stale']);self.assertTrue(p['shots'][0]['reviews'][0]['stale'])
        self.assertEqual(p['shots'][0]['reviews'][0]['master_sha256'],r['master_sha256'])
        with self.assertRaises(APIError):self.call('POST','shots/'+s['id']+'/prepare',dict(expected_revision=s['revision'],expected_project_revision=p['revision']))

    def test_anchor_signs_multiple_windows_unassessed_and_conflicts(self):
        self.assertEqual(song_time(dict(song_anchor=3,clip_anchor=1),2),4)
        self.assertEqual(song_time(dict(song_anchor=1,clip_anchor=3),2),0)
        s=self.plan();r=self.call('POST','shots/'+s['id']+'/take-reviews',dict(expected_revision=s['revision'],source=self.video()))
        self.assertEqual(r['method'],'unassessed');self.assertFalse(r['lip_sync_approved']);self.assertGreater(r['source_metadata']['duration'],2)
        with self.assertRaises(APIError):self.call('PATCH','shots/'+s['id']+'/take-reviews/'+r['id'],dict(expected_revision=r['revision'],intervals=[dict(start=0,end=1,state='usable')]))
        updated=self.call('PATCH','shots/'+s['id']+'/take-reviews/'+r['id'],dict(expected_revision=r['revision'],method='sampled_frames',song_anchor=.25,clip_anchor=.5,
            intervals=[dict(start=0,end=.5,state='rejected',reason='timing'),dict(start=.5,end=1.5,state='usable'),dict(start=1.5,end=2,state='unassessed')]))
        self.assertEqual(len(updated['intervals']),3);self.assertEqual(updated['method'],'sampled_frames');self.assertFalse(updated['lip_sync_approved'])
        with self.assertRaises(APIError):self.call('PATCH','shots/'+s['id']+'/take-reviews/'+r['id'],dict(expected_revision=r['revision'],notes='stale'))

    def test_pose_collision_and_full_expanded_validation(self):
        from image_studio import mock_png
        asset=self.app.upload(dict(name='pose',data_url='data:image/png;base64,'+base64.b64encode(mock_png()).decode()))
        p=self.project
        for times in ((.4,.45),(.01,), (2.99,)):
            with self.subTest(times=times),self.assertRaises(APIError):self.call('POST','projects/'+p['id']+'/shots',dict(expected_revision=p['revision'],shot=dict(start=0,end=2,duration=3,poses=[dict(song_time=t,asset_id=asset['id'],purpose='body accent') for t in times])))
        s=self.plan(poses=[dict(song_time=.4,asset_id=asset['id'],purpose='body accent')])
        preparation=self.call('POST','shots/'+s['id']+'/prepare',dict(expected_revision=s['revision'],expected_project_revision=self.project['revision']))
        self.assertEqual(preparation['anchors'][0]['snapped_clip_time'],1/3)
        self.assertEqual(preparation['request']['keyframes'][0]['timestamp_s'],1/3)
        p=self.project;s=self.call('PATCH','shots/'+s['id'],dict(expected_revision=s['revision'],expected_project_revision=p['revision'],changes=dict(prompt='猫'*2000)))
        p=self.call('GET','projects/'+p['id'])
        with self.assertRaises(ValueError):self.call('POST','shots/'+s['id']+'/prepare',dict(expected_revision=s['revision'],expected_project_revision=p['revision']))

    def test_comparison_assembly_render_audio_clock_and_restart(self):
        s=self.plan();r=self.reviewed(s);p=self.project
        primary=self.app.editing.timeline(self.production['id']);original=copy.deepcopy(primary)
        c=self.call('POST','shots/'+s['id']+'/comparisons',dict(expected_revision=s['revision'],review_id=r['id'],expected_review_revision=r['revision']),key='compare-0001')
        self.wait_export(c['export_id'])
        same=self.call('POST','shots/'+s['id']+'/comparisons',dict(expected_revision=s['revision'],review_id=r['id'],expected_review_revision=r['revision']),key='compare-0001');self.assertEqual(c['id'],same['id'])
        selection=[dict(review_id=r['id'],expected_review_revision=r['revision'],song_start=0,song_end=2)]
        proposal=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=selection,apply=False),key='assemble-proposal')
        self.assertTrue(proposal['can_apply']);self.assertEqual(proposal['coverage']['missing_spans'],[])
        shortage=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=[],apply=False),key='missing-coverage')
        self.assertFalse(shortage['can_apply']);self.assertEqual(shortage['coverage']['missing_spans'],[dict(start=0,end=2)])
        with self.assertRaises(APIError):self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=[],apply=True),key='missing-apply')
        a=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=selection,apply=True),key='assemble-0001')
        same=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=selection,apply=True),key='assemble-0001');self.assertEqual(a['id'],same['id'])
        timeline=self.app.productions.get(a['timeline_id'],'timeline');self.assertFalse(timeline['primary']);self.assertEqual(timeline['audio'][0]['out'],2);self.assertEqual(timeline['clips'][0]['volume'],0);self.assertEqual(timeline['clips'][0]['speed'],1)
        self.assertEqual(self.app.productions.get(primary['id'],'timeline'),original)
        j=self.app.agent.dispatch('POST','/agent/v1/editing/exports',dict(timeline_id=timeline['id'],expected_revision=timeline['revision']),'render-song-0001')[1]
        j=self.wait_export(j['id']);path=self.app.storage/'exports'/j['id']/'export.mp4'
        subprocess.run([self.app.editing.ffmpeg,'-v','error','-i',str(path),'-f','null','-'],check=True,timeout=30)
        def pcm(path):
            raw=subprocess.run([self.app.editing.ffmpeg,'-v','error','-i',str(path),'-ac','1','-ar','16000','-f','f32le','-'],capture_output=True,check=True).stdout
            return array.array('f',raw)
        _,masterpath=self.app.editing.source(self.master);original_audio=pcm(masterpath);rendered=pcm(path)
        for at in (.1,.9,1.7):
            lo=int(at*16000);hi=lo+1600;x=original_audio[lo:hi];y=rendered[lo:hi]
            correlation=sum(a*b for a,b in zip(x,y))/math.sqrt(sum(a*a for a in x)*sum(b*b for b in y))
            self.assertGreater(correlation,.9,'Master clock or audio mix changed')
        restored=Studio(mock=True,storage=self.app.storage)
        try:
            value=restored.song_performance.project(p['id']);self.assertEqual(value['working_timeline_id'],a['timeline_id']);self.assertEqual(value['shots'][0]['reviews'][0]['intervals'],r['intervals'])
        finally:restored.productions.sql.close()
        self.app.generate.assert_not_called()

    def test_archive_restores_song_sources_versions_reviews_and_working_edit(self):
        s=self.plan();r=self.reviewed(s);p=self.project
        selections=[dict(review_id=r['id'],expected_review_revision=r['revision'],song_start=0,song_end=2)]
        a=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=selections,apply=True),key='archive-assembly')
        self.app.archives.jobs['song-export']={}
        self.app.archives.export('song-export',self.production['id'])
        archive=self.app.archives.folder/'song-export.zip'
        dest=Studio(mock=True,storage=self.root/'restored-archive')
        try:
            dest.archives.jobs['song-import']={}
            dest.archives.restore('song-import',archive)
            projects=dest.productions.all('song-project');self.assertEqual(len(projects),1)
            restored=dest.song_performance.project(projects[0]['id'])
            self.assertNotEqual(restored['id'],p['id']);self.assertNotEqual(restored['master']['source']['id'],self.master['id'])
            self.assertFalse(restored['shots'][0]['stale']);self.assertFalse(restored['shots'][0]['reviews'][0]['stale'])
            self.assertEqual(restored['shots'][0]['reviews'][0]['intervals'],r['intervals'])
            self.assertFalse(dest.productions.get(restored['working_timeline_id'],'timeline')['primary'])
            self.assertEqual(dest.song_performance.metadata(restored['master']['source'],audio=True)[0]['sha256'],p['master']['sha256'])
        finally:dest.productions.sql.close()

    def test_only_affected_cues_stale_and_reanalysis_is_revision_safe(self):
        p=self.project
        first=self.call('POST','projects/'+p['id']+'/shots',dict(expected_revision=p['revision'],shot=dict(start=0,end=.75,duration=1)))
        p=self.call('GET','projects/'+p['id'])
        second=self.call('POST','projects/'+p['id']+'/shots',dict(expected_revision=p['revision'],shot=dict(start=1,end=2,duration=1)))
        p=self.call('GET','projects/'+p['id'])
        p=self.call('PATCH','projects/'+p['id'],dict(expected_revision=p['revision'],cues=[dict(id='first-phrase',kind='phrase',start=.1,end=.5,text='retry')]))
        self.assertTrue(next(s for s in p['shots'] if s['id']==first['id'])['stale'])
        self.assertFalse(next(s for s in p['shots'] if s['id']==second['id'])['stale'])
        with self.assertRaises(APIError):self.call('PATCH','projects/'+p['id'],dict(expected_revision=True,lyrics='invalid revision'))

    def test_audio_sample_boundary_survives_editor_round_trip(self):
        source=self.wav('sample-clock',duration=32001/16000)
        p=self.call('PATCH','projects/'+self.project['id'],dict(expected_revision=self.project['revision'],master=source))
        self.assertEqual(p['master']['samples'],32001)
        s=self.call('POST','projects/'+p['id']+'/shots',dict(expected_revision=p['revision'],shot=dict(start=0,end=p['master']['duration'],duration=3)))
        r=self.reviewed(s);p=self.call('GET','projects/'+p['id'])
        selected=[dict(review_id=r['id'],expected_review_revision=r['revision'],song_start=0,song_end=p['master']['duration'])]
        assembly=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=selected,apply=True),key='sample-clock-assemble')
        t=self.app.productions.get(assembly['timeline_id'],'timeline')
        self.assertAlmostEqual(t['audio'][0]['out'],32001/16000,places=9)
        saved=self.app.editing.save(t['id'],dict(expected_revision=t['revision'],title='Reviewed sample clock'))
        self.assertAlmostEqual(saved['audio'][0]['out'],32001/16000,places=9)
        self.assertEqual(assembly['coverage']['placements'][0]['end_frame'],49)

    def test_working_edit_guards_song_clock_and_compensated_dissolve(self):
        s=self.plan();r=self.reviewed(s);p=self.project
        selections=[dict(review_id=r['id'],expected_review_revision=r['revision'],song_start=a,song_end=b) for a,b in ((0,1),(1,2))]
        assembly=self.call('POST','projects/'+p['id']+'/assemble',dict(expected_revision=p['revision'],selections=selections,apply=True),key='guard-clock-assembly')
        t=self.app.productions.get(assembly['timeline_id'],'timeline')
        for changes in (dict(audio=[]),dict(audio=[{**t['audio'][0],'in':.1}]),dict(clips=[{**t['clips'][0],'volume':1},t['clips'][1]]),dict(output={**t['output'],'loudness_target_lufs':-16})):
            with self.subTest(changes=list(changes)),self.assertRaises(APIError) as error:self.app.editing.save(t['id'],dict(expected_revision=t['revision'],**changes))
            self.assertEqual(error.exception.code,'song_clock_conflict')
        # An ordinary incoming overlap would shift the second clip and truncate the song.
        second={**t['clips'][1],'transition':dict(type='dissolve',duration=.5)}
        with self.assertRaises(APIError) as error:self.app.editing.save(t['id'],dict(expected_revision=t['revision'],clips=[t['clips'][0],second]))
        self.assertEqual(error.exception.code,'song_clock_conflict')
        # Real reviewed source handles compensate for the overlap; the downstream clock remains 1s.
        first={**t['clips'][0],'out':1.5}
        changed=self.app.editing.save(t['id'],dict(expected_revision=t['revision'],clips=[first,second]))
        from editing_tools import starts
        self.assertEqual(starts(changed['clips']),[0,1]);self.assertEqual(changed['audio'][0],t['audio'][0])
        export=self.app.editing.export(changed['id'],dict(expected_revision=changed['revision']),'guard-clock-export')
        export=self.wait_export(export['id']);self.assertAlmostEqual(export['media']['duration'],2,places=2)
        path=self.app.storage/'exports'/export['id']/'export.mp4'
        subprocess.run([self.app.editing.ffmpeg,'-v','error','-i',str(path),'-f','null','-'],check=True,timeout=30)

    def test_http_sdk_complete_offline_demo_without_provider(self):
        from http.server import ThreadingHTTPServer
        import threading
        from studio_server import StudioHandler
        from agent_client import StudioClient
        from scripts.demo_song_performance import run
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);server.tester=self.app
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=StudioClient('http://127.0.0.1:'+str(server.server_port),self.app.agent.token_path)
            report=run(client,self.root,self.app.editing.ffmpeg)
            self.assertEqual(report['paid_generation_requests'],0)
            self.assertTrue(all(c>.999 for c in report['master_audio_correlations']))
            self.assertTrue(Path(report['comparison']).is_file())
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
