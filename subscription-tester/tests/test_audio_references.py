"""Local FFmpeg fixtures and mocked submission guards; no provider acceptance claims."""
import base64
import copy
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import Mock, patch

from agent_api import APIError
from audio_references import AudioReferences
from studio_server import Studio
from test_studio import PNG


class RecordingFixture:

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.tmp.name)
        self.api=self.app.agent;self.service=AudioReferences(self.app)
        output=io.BytesIO()
        with wave.open(output,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
            # Leading and trailing silence are intentional; must remain intact.
            w.writeframes(b'\0\0'*8000+b'\x10\x10'*16000+b'\0\0'*8000)
        self.raw=output.getvalue();self.data=dict(name='vocal.wav',base64=base64.b64encode(self.raw).decode())
    def tearDown(self):
        self.app.productions.sql.close();self.tmp.cleanup()
    def call(self,method,path,data=None,key=None):
        return self.api.dispatch(method,'/agent/v1/'+path,data or {},key)[1]
    def recording(self):return self.call('POST','audio-references',self.data,'recording-upload-1')
    def attached(self,**changes):
        r=self.recording();e=self.call('POST',f"audio-references/{r['id']}/excerpts",dict(start_s=0,end_s=2))
        return self.api.create(dict(scene=dict(prompt='The character sings and sways.',duration=2,
            recording=dict(reference_id=r['id'],excerpt_id=e['id']),**changes)))

class RecordingTests(RecordingFixture,unittest.TestCase):
    def test_upload_is_probed_private_and_idempotent(self):
        r=self.recording();self.assertEqual(r,self.recording());self.assertEqual(r['duration'],2)
        _,path=self.service.file(r['id']);self.assertEqual(path.read_bytes(),self.raw)
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertIsNone(r['provider_upload_id']);self.assertEqual(len(self.call('GET','audio-references')),1)
        self.assertEqual(self.call('GET',f"audio-references/{r['id']}/download")[0],self.raw)
        with self.assertRaisesRegex(APIError,'different recording'):
            self.call('POST','audio-references',{**self.data,'name':'other.wav'},'recording-upload-1')
    def test_rejects_invalid_content_formats_bounds_and_unknown_fields(self):
        for data in ({**self.data,'name':'vocal.mp3'},{**self.data,'base64':'!'},{**self.data,'name':'vocal.ogg'},
                {**self.data,'path':'/tmp/audio.wav'},{**self.data,'base64':base64.b64encode(b'not audio').decode()}):
            with self.subTest(data=list(data)):
                with self.assertRaises(APIError):self.call('POST','audio-references',data,'invalid-upload-1')
        with self.assertRaises(APIError):self.call('POST','audio-references',self.data)
        r=self.recording()
        for start,end in ((-1,1),(0,3),(1,1),(True,1),(0,float('nan')),(0,float('inf'))):
            with self.subTest(start=start,end=end):
                with self.assertRaises(APIError):self.service.excerpt(r['id'],dict(start_s=start,end_s=end))
    def test_full_excerpt_retains_exact_bytes_and_trim_is_repeatable(self):
        r=self.recording();full=self.service.excerpt(r['id'],dict(start_s=0,end_s=2))
        self.assertEqual(self.service.file(full['id'],'audio-excerpt')[1].read_bytes(),self.raw)
        trim=self.service.excerpt(r['id'],dict(start_s=.25,end_s=1.75))
        self.assertEqual(trim,self.service.excerpt(r['id'],dict(start_s=.25,end_s=1.75)))
        self.assertEqual(full,self.service.excerpt(r['id'],dict(start_s=0.0,end_s=2.0)))
        self.assertEqual(trim['duration'],1.5)
        with wave.open(str(self.service.file(trim['id'],'audio-excerpt')[1])) as w:
            self.assertEqual(w.readframes(100),b'\0'*100*w.getsampwidth())
    def test_image_plus_recording_compiles_without_network_during_validation(self):
        image=self.app.upload(dict(name='frame.png',data_url=PNG))
        record=self.attached(first=dict(asset_id=image['id']),refs=[dict(source=dict(asset_id=image['id']))])
        with patch('httpx.Client') as network:
            result=self.api.validation(record)
            self.assertTrue(result['valid']);self.assertTrue(result['warnings'])
            self.assertEqual(result['effective_audio_reference']['excerpt']['duration'],2)
            request=result['request']
            self.assertTrue(request['reference_audios'][0]['url'].startswith('data:audio/wav;base64,'))
            self.assertIn('<AUDIO_0>',request['prompt'])
            self.assertNotIn('_studio_scene',request)
            self.assertNotIn('_studio_audio_reference',request)
            network.assert_not_called();self.assertEqual(self.app.records(),[])
    def test_model_resolution_audio_and_preset_conflicts_are_explicit(self):
        for fields,message in ((dict(model='grok-imagine-video-1.5-lite'),'full Video'),
                (dict(resolution='1080p'),'480p'),(dict(audio=False),'Enable audio'),
                (dict(voices=[dict(voice='rex')]),'preset voice')):
            r=self.attached(**fields)
            with self.subTest(fields=fields):
                with self.assertRaisesRegex(APIError,message):self.api.compile(r['scene'])
    def test_request_snapshot_preserves_recording_bytes_without_inline_blob(self):
        record=self.attached();body=self.api.validation(record)['request']
        folder=self.app.storage/'snapshot';folder.mkdir()
        frozen=self.app.video_review._freeze_request(body,folder)
        audio=frozen['request']['reference_audios'][0]
        self.assertEqual(audio['prompt_tag'],'<AUDIO_0>')
        self.assertEqual((self.app.storage/audio['path']).read_bytes(),self.raw)
        self.assertNotIn('url',audio)
    def test_revision_remove_mismatch_and_restart(self):
        r=self.attached();r=self.api.patch(r['id'],dict(expected_revision=1,changes=dict(duration=3)))
        result=self.api.validation(r);self.assertTrue(result['effective_audio_reference']['duration_mismatch'])
        with self.assertRaises(APIError) as caught:self.api.patch(r['id'],dict(expected_revision=1,changes=dict(recording=None)))
        self.assertEqual(caught.exception.status,409)
        restarted=Studio(mock=True,storage=self.tmp.name)
        try:
            self.assertEqual(restarted.agent.record(r['id']),r)
            self.assertEqual(len(restarted.productions.all('audio-reference')),1)
            self.assertTrue(restarted.agent.validation(r)['valid'])
        finally:restarted.productions.sql.close()
        r=self.api.patch(r['id'],dict(expected_revision=r['revision'],changes=dict(recording=None)))
        self.assertTrue(self.api.validation(r)['valid'])
    def test_workspace_isolation_tampering_and_editing_uploads(self):
        r=self.attached();foreign=r['scene']['recording'];e=self.app.editing.upload(self.data)
        with self.assertRaises(APIError):self.service.attachment(dict(reference_id=e['id'],excerpt_id=foreign['excerpt_id']))
        with tempfile.TemporaryDirectory() as folder:
            other=Studio(mock=True,storage=folder)
            try:
                with self.assertRaises(APIError):other.agent.create(dict(scene=dict(recording=foreign)))
                with self.assertRaises(APIError):AudioReferences(other).file(foreign['reference_id'])
            finally:other.productions.sql.close()
        _,path=self.service.file(foreign['reference_id']);path.write_bytes(b'changed')
        with self.assertRaisesRegex(APIError,'changed'):self.api.normalize(r['scene'])
    def test_preset_and_image_only_payloads_remain_supported(self):
        record=self.api.create(dict(scene=dict(prompt='Hello <AUDIO_0>',voices=[dict(voice='rex')])))
        self.assertEqual(self.api.validation(record)['request']['reference_audios'],[dict(voice_id='rex')])
        asset=self.app.upload(dict(name='frame.png',data_url=PNG))
        record=self.api.create(dict(scene=dict(first=dict(asset_id=asset['id']))))
        request=self.api.validation(record)['request'];self.assertIn('image',request)
        self.assertNotIn('reference_audios',request);self.assertNotIn('recording',request)
    def test_character_association_and_excerpt_ownership(self):
        record=self.attached();value=record['scene']['recording']
        character=self.app.save_reference(dict(title='Test character',handle='TestCharacter',category='Character',
            description='Fixture only.',images=[],voice='rex'))
        valid=self.api.normalize({**record['scene'],'recording':{**value,'character_id':character['id']}})
        self.assertEqual(valid['recording']['character_id'],character['id'])
        with self.assertRaises(APIError):self.api.normalize({**record['scene'],'recording':{**value,'character_id':'foreign'}})
        other=self.call('POST','audio-references',self.data,'another-recording-key')
        with self.assertRaisesRegex(APIError,'different recording'):
            self.service.attachment({**value,'reference_id':other['id']})

    def test_schema_exposes_disabled_capability_and_typed_private_routes(self):
        schema=self.call('GET','schema');self.assertTrue(schema['uploaded_audio']['generation_enabled'])
        self.assertEqual(schema['uploaded_audio']['access'],'unverified')
        self.assertIsNone(schema['uploaded_audio']['provider_limits'])
        spec=self.call('GET','openapi.json');routes=spec['paths']
        headers=routes['/audio-references']['post']['parameters']
        self.assertTrue(any(p['name']=='Idempotency-Key' and p['required'] for p in headers))
        self.assertIn('AudioExcerpt',spec['components']['schemas'])
        self.assertIn('audio/wav',routes['/audio-excerpts/{id}/download']['get']['responses']['200']['content'])

    def test_mp3_content_supported_locally(self):
        r=self.recording();_,source=self.service.file(r['id'])
        target=Path(self.tmp.name)/'fixture.mp3'
        subprocess.run([self.app.editing.ffmpeg,'-v','error','-nostdin','-i',str(source),str(target)],check=True)
        r=self.call('POST','audio-references',dict(name='fixture.mp3',base64=base64.b64encode(target.read_bytes()).decode()),'recording-mp3-1')
        self.assertEqual(r['format'],'mp3');self.assertGreater(r['duration'],1.9)

class RecordingHTTPTests(RecordingFixture,unittest.TestCase):
    def test_sdk_http_workflow_and_unauthorized_preview(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
        from agent_client import StudioClient, AgentError
        from studio_server import StudioHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);server.tester=self.app
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        client=StudioClient(base,self.api.token_path)
        source=Path(self.tmp.name)/'local.wav';source.write_bytes(self.raw)
        try:
            recording=client.upload_audio_reference(source,idempotency_key='http-audio-upload')
            excerpt=client.prepare_audio_excerpt(recording,0,2)
            record=client.create_scene('HTTP recording fixture',dict(duration=2,prompt='Sings and sways.'))
            record=client.attach_audio_reference(record,recording,excerpt)
            self.assertTrue(client.audio_reference_capabilities()['generation_enabled'])
            self.assertTrue(client.validate(record)['valid'])
            self.assertEqual(client.request('audio-excerpts/'+excerpt['id']+'/download'),self.raw)
            for route in ('/agent/v1/audio-references/'+recording['id']+'/download',
                          '/api/agent/audio-references/'+recording['id']+'/download'):
                headers={'Origin':'https://malicious.invalid'}
                with self.assertRaises(HTTPError) as error:urlopen(Request(base+route,headers=headers))
                self.assertEqual(error.exception.code,403);error.exception.close()
            with self.assertRaises(AgentError) as error:
                client.generate(record,approved=False,idempotency_key='http-audio-unapproved')
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base+'/api/agent/audio-references/'+recording['id']+'/download',headers={'Sec-Fetch-Site':'cross-site'}))
            self.assertEqual(error.exception.code,403);error.exception.close()
            self.assertEqual(self.app.records(),[])
            record=client.remove_audio_reference(record);self.assertTrue(client.validate(record)['valid'])
        finally:
            server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
