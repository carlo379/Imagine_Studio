import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from studio_server import Studio
from agent_api import APIError
from image_studio import mock_png
import base64


class ProjectArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=Studio(mock=True,storage=Path(self.temp.name)/'source')
        self.p=self.app.productions
        outline=self.p.dispatch('POST',[],{'title':'Portable world','kind':'story'})[1]
        self.pid=outline['production']['id'];self.eid=outline['episodes'][0]['id']
        self.other=self.p.dispatch('POST',[],{'title':'Private unrelated work','kind':'quick'})[1]
        self.asset=self.app.upload({'data_url':'data:image/png;base64,'+base64.b64encode(mock_png()).decode(),'name':'Hero.png'})
        self.bible=self.app.filmmaking.series.save_bible(self.pid,dict(expected_revision=0,answers={'idea':'A robot explores.'},guide={'cast':[{'id':'hero','name':'Robot','description':'Golden shell','reference_ids':[self.asset['id']]}],'places':[{'id':'lab','name':'Lab','description':'Bright laboratory'}],'props':[{'id':'tool','name':'Wrench','description':'Silver tool'}]}))
        self.book=self.app.filmmaking.series.save_book(self.eid,dict(expected_revision=0,guide={'script':'The robot walks into the lab.'}))
        ep=self.app.stories.record('episodes',self.eid)
        saved=self.app.stories.episode_edit(ep,dict(expected_revision=ep['revision'],scenes=[{'title':'Lab','text':'Robot enters.'}]))
        scene_id=saved['scenes'][0]['id']
        self.shot=self.p.create_shot(self.p.get(self.pid,'production'),{'title':'Opening','episode_id':self.eid,'story_scene_id':scene_id})
        self.image=self.app.images.draft(self.shot['image_id'])
        self.image['settings']['prompt']='Golden robot in the bright lab.'
        self.app.images.db['jobs'].append(dict(id='image-job',mock=True,status='done',draft=copy.deepcopy(self.image),expanded_prompt='FULL IMAGE PROMPT',outputs=[self.asset],key='private-idempotency-key'))
        self.app.history.append(dict(id='video-job',mock=True,status='done',video='https://expired.invalid/video.mp4',settings={'_studio_video_id':self.shot['video_id'],'prompt':'FULL VIDEO PROMPT'},created_at=1))
        # Local video makes the test independent of provider/network/fixture rendering.
        video=self.app.storage/'videos'/'video-job.mp4';video.parent.mkdir();video.write_bytes(b'original video bytes')
        self.app.history[-1]['archive_local_video']=True
        with self.p.sql:
            self.timeline=self.p.new('timeline',production_id=self.pid,title='Cut',clips=[{'id':'clip-one','source':{'kind':'take','id':'video-job'}}],audio=[],captions=[{'id':'caption-one','text':'Hello'}])
        with self.p.sql:
            self.p.new('media-prompt-job',kind='image',media_id=self.image['id'],status='done',result={'prompt':'Saved generated prompt'},mock=True)
        self.app.archives.jobs['export-test']={}
    def tearDown(self):
        self.p.sql.close();self.temp.cleanup()
    def export(self):
        result=self.app.archives.export('export-test',self.pid)
        return self.app.archives.folder/'export-test.zip',result
    def destination(self):
        app=Studio(mock=True,storage=Path(self.temp.name)/'destination')
        self.addCleanup(app.productions.sql.close)
        app.archives.jobs['import-test']={}
        return app
    def test_roundtrip_scope_versions_prompts_media_and_repeated_import(self):
        path,result=self.export()
        self.assertTrue(result['report']['complete'])
        with zipfile.ZipFile(path) as z:
            m=json.loads(z.read('project.json'));raw=z.read('project.json').decode()
            self.assertNotIn('Private unrelated work',raw)
            self.assertNotIn('private-idempotency-key',raw)
            self.assertIn('FULL IMAGE PROMPT',raw);self.assertIn('FULL VIDEO PROMPT',raw)
            self.assertIn('Saved generated prompt',raw)
            self.assertIn('Golden shell',raw);self.assertIn('Silver tool',raw)
            self.assertTrue(any(n.startswith('documents/') for n in z.namelist()))
            self.assertEqual(z.read('media/videos/video-job.mp4'),b'original video bytes')
            self.assertTrue(any(e.get('versions') for e in m['records']))
        dest=self.destination()
        with patch('httpx.stream') as network:
            restored=dest.archives.restore('import-test',path)
            network.assert_not_called()
        pid=restored['project_id'];self.assertNotEqual(pid,self.pid)
        outline=dest.productions.outline(pid)
        self.assertTrue(outline['production']['title'].endswith('(imported)'))
        self.assertEqual(len(outline['episodes']),1)
        self.assertEqual(len(outline['shots']),1)
        bible=dest.filmmaking.series.bible(pid)
        self.assertEqual(bible['guide']['cast'][0]['description'],'Golden shell')
        imported_asset=dest.assets[0];self.assertNotEqual(imported_asset['id'],self.asset['id'])
        self.assertEqual(bible['guide']['cast'][0]['reference_ids'],[imported_asset['id']])
        self.assertEqual(dest.asset(imported_asset['id'])[1].read_bytes(),self.app.asset(self.asset['id'])[1].read_bytes())
        video=dest.history[0];self.assertEqual(dest.download(video['id']).read_bytes(),b'original video bytes')
        timeline=dest.productions.all('timeline')[0]
        self.assertEqual(timeline['clips'][0]['source']['id'],video['id'])
        self.assertNotEqual(timeline['clips'][0]['id'],'clip-one')
        self.assertEqual(dest.images.db['jobs'][0]['draft']['id'],outline['shots'][0]['image']['id'])
        book=dest.filmmaking.series.book(outline['episodes'][0]['id'])
        self.assertEqual(book['guide']['script'],'The robot walks into the lab.')
        second=dest.archives.restore('import-test',path)
        self.assertNotEqual(second['project_id'],pid)
        self.assertEqual(len(dest.productions.all('timeline')),2)
    def test_import_into_original_workspace_does_not_overwrite(self):
        path,_=self.export();self.app.archives.jobs['import-test']={}
        before=copy.deepcopy(self.app.assets[0]);result=self.app.archives.restore('import-test',path)
        self.assertNotEqual(result['project_id'],self.pid)
        self.assertEqual(self.app.assets[0],before)
        self.assertEqual(self.p.get(self.pid,'production')['title'],'Portable world')
    def test_import_preserves_list_valued_metadata_paths(self):
        expected={'path':['guide','cast',0],'sha256':'metadata-value',
                  'nested':[{'path':{'chapter':'cast'},'sha256':'dict-path'},
                            {'path':None,'sha256':'null-path'},
                            {'sha256':'no-path'},
                            {'path':42,'sha256':'numeric-path'}]}
        def change(manifest):
            record=next(e['record'] for e in manifest['records'] if e.get('kind')=='production' and e['record']['id']==self.pid)
            record['archive_metadata']=copy.deepcopy(expected)
        path=self.altered(change)
        dest=self.destination()
        result=dest.archives.restore('import-test',path)
        record=dest.productions.get(result['project_id'],'production')
        self.assertEqual(record['archive_metadata'],expected)
    def test_missing_files_and_remote_inputs_reported(self):
        self.app.asset(self.asset['id'])[1].unlink()
        self.image['settings']['base']={'src':'https://example.invalid/reference.png'}
        _,result=self.export()
        self.assertFalse(result['report']['complete'])
        self.assertIn('assets/'+self.asset['id']+'.png',result['report']['missing_files'])
        self.assertIn('https://example.invalid/reference.png',result['report']['remote_references'])
    def test_generation_in_progress_blocks_export(self):
        self.app.images.db['jobs'][0]['status']='pending'
        with self.assertRaisesRegex(APIError,'finish'):
            self.export()
    def altered(self,change,extra=None):
        path,_=self.export();target=Path(self.temp.name)/'altered.zip'
        with zipfile.ZipFile(path) as source,zipfile.ZipFile(target,'w') as out:
            for name in source.namelist():
                raw=source.read(name)
                if name=='project.json':
                    manifest=json.loads(raw);change(manifest);raw=json.dumps(manifest).encode()
                out.writestr(name,raw)
            if extra:out.writestr(extra,b'unsafe')
        return target
    def test_bad_checksum_does_not_publish_records_or_files(self):
        path=self.altered(lambda m:m['files'][0].update(sha256='0'*64));dest=self.destination()
        with self.assertRaisesRegex(APIError,'checksum'):dest.archives.restore('import-test',path)
        self.assertEqual(dest.productions.all('production'),[]);self.assertEqual(dest.assets,[])
        self.assertFalse((dest.storage/'assets').exists())
    def test_path_traversal_unknown_version_and_unknown_collection(self):
        for change,extra in [(lambda m:None,'../escape'),(lambda m:m.update(version=999),None),(lambda m:m['records'][0].update(store='credentials'),None)]:
            with self.subTest(extra=extra):
                path=self.altered(change,extra);dest=self.destination()
                with self.assertRaises(APIError):dest.archives.restore('import-test',path)
                self.assertEqual(dest.productions.all('production'),[])
    def test_failed_publish_rolls_back(self):
        path,_=self.export();dest=self.destination();save=dest.agent.save
        failed=False
        def fail_once(path,data):
            nonlocal failed
            if path==dest.references_path and not failed:
                failed=True;raise OSError('disk full')
            return save(path,data)
        with patch.object(dest.agent,'save',side_effect=fail_once):
            with self.assertRaises(OSError):dest.archives.restore('import-test',path)
        self.assertEqual(dest.assets,[]);self.assertEqual(dest.images.db['jobs'],[])
        self.assertEqual(dest.productions.all('production'),[])
        self.assertFalse(list((dest.storage/'assets').glob('*')))

    def test_request_evidence_audio_and_finished_edit_restore(self):
        folder=self.app.storage/'video-request-snapshots'/'video-job';folder.mkdir(parents=True)
        snapshot=folder/'request.json';snapshot.write_text(json.dumps({'scene_id':self.shot['video_id'],'request':{'prompt':'Exact expanded request'},'images':[{'id':'input-0','path':'video-request-snapshots/video-job/input-0.bin'}]}))
        (folder/'input-0.bin').write_bytes(b'original input pixels')
        self.app.history[0]['request_snapshot']={'path':'video-request-snapshots/video-job/request.json','sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest()}
        with self.p.sql:
            audio=self.p.new('edit-media',name='Voice.wav',ext='wav',mime='audio/wav')
            timeline=self.p.get(self.timeline['id'],'timeline');timeline['audio']=[{'id':'music-clip','source':{'kind':'upload','id':audio['id']}}];self.p.put('timeline',timeline)
            rendered=self.p.new('export',production_id=self.pid,timeline_id=timeline['id'],status='done',snapshot=copy.deepcopy(timeline))
        audio_file=self.app.storage/'edit-media'/(audio['id']+'.wav');audio_file.parent.mkdir();audio_file.write_bytes(b'audio bytes')
        output=self.app.storage/'exports'/rendered['id'];output.mkdir(parents=True);(output/'export.mp4').write_bytes(b'edited movie');(output/'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n');(output/'edit.json').write_text(json.dumps(timeline))
        path,_=self.export();dest=self.destination();result=dest.archives.restore('import-test',path)
        job=dest.history[0];evidence=dest.storage/job['request_snapshot']['path']
        self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(),job['request_snapshot']['sha256'])
        frozen=json.loads(evidence.read_text());self.assertEqual(frozen['scene_id'],job['settings']['_studio_video_id'])
        self.assertEqual((dest.storage/frozen['images'][0]['path']).read_bytes(),b'original input pixels')
        self.assertEqual(Path(frozen['images'][0]['path']).stem,frozen['images'][0]['id'])
        edited=dest.productions.all('export')[0];self.assertEqual(dest.editing.file(edited['id']).read_bytes(),b'edited movie')
        self.assertEqual(dest.editing.media_file(dest.productions.all('edit-media')[0]['id'])[1].read_bytes(),b'audio bytes')
        self.assertNotEqual(edited['snapshot']['audio'][0]['source']['id'],audio['id'])

    def test_browser_transfer_routes_and_agent_background_routes(self):
        import io
        from types import SimpleNamespace
        from uuid import uuid4
        with patch.object(self.app,'spawn',side_effect=lambda target,*args:target(*args)):
            code,task=self.app.agent.dispatch('POST','/agent/v1/productions/'+self.pid+'/export',{})
        self.assertEqual(code,202);self.assertEqual(task['status'],'done')
        self.assertEqual(self.app.agent.dispatch('GET','/agent/v1/project-archives/'+task['id'],{})[1]['status'],'done')
        reply=[]
        handler=SimpleNamespace(allowed_host=lambda:True,session_hash='session',server=SimpleNamespace(server_port=8765),headers={},path=task['download'],send=lambda status,data:reply.append((status,data)),media=lambda path,mime,name:reply.append((200,path.read_bytes())))
        self.app.archives.route(handler,'GET');self.assertTrue(reply[-1][1].startswith(b'PK'))
        raw=reply[-1][1];handler.path='/api/project-archives/import';handler.rfile=io.BytesIO(raw);handler.headers={'Content-Length':str(len(raw))}
        self.app.archives.route(handler,'POST');self.assertEqual(reply[-1][0],403)
        handler.headers.update({'Origin':'http://127.0.0.1:8765','X-Tester':'local'})
        with patch.object(self.app,'spawn',side_effect=lambda target,*args:target(*args)):
            self.app.archives.route(handler,'POST')
        self.assertEqual(reply[-1][0],202);self.assertEqual(reply[-1][1]['status'],'done')
        self.assertNotEqual(reply[-1][1]['project_id'],self.pid)
        # Completed export links survive a server/service restart.
        self.app.archives.jobs.pop(task['id']);self.assertEqual(self.app.archives.status(task['id'])['status'],'done')

    def test_group_children_and_archived_takes_are_included(self):
        child=self.other['production'];child['parent_production_id']=self.pid
        with self.p.sql:self.p.put('production',child)
        self.app.images.db['jobs'][0]['archived']=True
        path,_=self.export()
        with zipfile.ZipFile(path) as z:
            m=json.loads(z.read('project.json'))
        self.assertTrue(any(e['record'].get('id')==child['id'] for e in m['records']))
        self.assertTrue(any(e['record'].get('id')=='image-job' for e in m['records']))

    def test_reference_handle_collision_keeps_saved_prompt_snapshots(self):
        ref=self.app.save_reference({'title':'Robot','handle':'Robot','category':'Character','description':'Golden shell','images':[{'asset_id':self.asset['id']}]})
        series=self.app.stories.record('series',self.p.get(self.pid,'production')['series_id']);series['assets']=['Robot']
        book=self.app.filmmaking.series.book(self.eid)
        self.app.filmmaking.series.save_book(self.eid,{'expected_revision':book['revision'],'selected_asset_ids':['reference-'+ref['id']],'refresh_inheritance':True})
        self.image['settings']['bindings']=[{'snapshot':copy.deepcopy(ref)}]
        self.image['settings']['prompt']='Show @Robot in the lab.'
        self.app.images.db['jobs'][0]['request_id']='provider-request-123'
        path,_=self.export();self.app.archives.jobs['import-test']={}
        self.app.archives.restore('import-test',path)
        imported=self.app.references[-1]
        self.assertNotEqual(imported['handle'],'Robot')
        self.assertLessEqual(len(imported['handle']),40)
        self.assertEqual(self.app.images.db['drafts'][-1]['settings']['prompt'],'Show @Robot in the lab.')
        self.assertEqual(self.app.images.db['jobs'][-1]['request_id'],'provider-request-123')
        imported_ep=self.app.stories.db['episodes'][-1]
        imported_book=self.app.filmmaking.series.book(imported_ep['id'])
        choices=self.app.filmmaking.series.library(imported_book['production_id'])
        self.assertIn(imported_book['selected_asset_ids'][0],{a['id'] for a in choices})
        self.app.filmmaking.series.save_book(imported_ep['id'],{'expected_revision':imported_book['revision'],'refresh_inheritance':True})

    def test_imported_review_evidence_keeps_frame_slot_identifiers(self):
        import uuid
        rid=uuid.uuid4().hex;raw=b'review frame pixels'
        self.app.video_review.db['reviews'].append({'id':rid,'mock':True,'status':'done','video_job_id':'video-job','revision':1,'evidence':{'frames':[{'id':'frame-0','sha256':hashlib.sha256(raw).hexdigest()}]}})
        folder=self.app.storage/'video-review-evidence'/rid;folder.mkdir(parents=True);(folder/'frame-0.jpg').write_bytes(raw)
        path,_=self.export();dest=self.destination();dest.archives.restore('import-test',path)
        review=dest.video_review.db['reviews'][0]
        self.assertNotEqual(review['id'],rid)
        self.assertEqual(review['evidence']['frames'][0]['id'],'frame-0')
        self.assertEqual(dest.video_review.evidence_file(review['id'],'frame-0').read_bytes(),raw)

    def test_compact_compressed_history_avoids_pretty_print_limit(self):
        path,_=self.export()
        with zipfile.ZipFile(path) as z:
            metadata=json.loads(z.read('project.json'))
            compact=len(z.read('project.json'))
            pretty=len(json.dumps(metadata,ensure_ascii=False,indent=2).encode())
            self.assertLess(compact,pretty)
            self.assertEqual(z.getinfo('project.json').compress_type,zipfile.ZIP_DEFLATED)
        with patch('project_archives.MAX_JSON',(compact+pretty)//2):
            path,_=self.export()
        dest=self.destination();dest.archives.restore('import-test',path)
        with zipfile.ZipFile(path) as z:
            expected=sum(len(e.get('versions',[])) for e in json.loads(z.read('project.json'))['records'])
        actual=dest.productions.sql.execute('SELECT count(*) FROM versions').fetchone()[0]
        self.assertEqual(actual,expected)

if __name__=='__main__':unittest.main()
