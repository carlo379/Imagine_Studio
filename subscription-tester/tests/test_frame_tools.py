import base64
import copy
import shutil
import tempfile
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from studio_server import Studio, StudioHandler
from agent_api import APIError
from test_studio import PNG

class FrameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.temp.name)
        self.api=self.app.agent;self.asset=self.app.upload({'data_url':PNG,'name':'Test image'})
        self.app.history.append({'id':'mock-frame-job','mock':True,'status':'done','video':'/static/mock-video.mp4','settings':{'duration':5}})
    def tearDown(self):self.temp.cleanup()
    def call(self,path,data):return self.api.dispatch('POST','/agent/v1/'+path,data)[1]
    def place(self,**kw):return self.call('assets/'+self.asset['id']+'/place',kw)
    def test_capture_browser_and_provenance_persists(self):
        image=self.call('jobs/mock-frame-job/capture-frame',{'timestamp_s':1,'data_url':PNG})
        self.assertEqual(image['frame_seconds'],1);self.assertEqual(image['capture_method'],'browser')
        self.assertEqual(Studio(mock=True,storage=self.temp.name).asset(image['id'])[0],image)
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'optional ffmpeg unavailable')
    def test_agent_capture_decodes_local_video_including_end(self):
        for timestamp in (0,1,3):
            image=self.call('jobs/mock-frame-job/capture-frame',{'timestamp_s':timestamp})
            self.assertEqual(image['capture_method'],'ffmpeg');self.assertTrue(self.app.asset(image['id'])[1].read_bytes().startswith(b'\x89PNG'))
    def test_capture_invalid_inputs_do_not_save_assets(self):
        count=len(self.app.assets)
        for timestamp in (-1,float('nan'),float('inf'),True,999,'1'):
            with self.assertRaises(APIError):self.call('jobs/mock-frame-job/capture-frame',{'timestamp_s':timestamp,'data_url':PNG})
        with self.assertRaises(APIError):self.call('jobs/mock-frame-job/capture-frame',{'timestamp_s':1,'url':'https://example.com'})
        self.app.history[0]['status']='pending'
        with self.assertRaises(APIError):self.call('jobs/mock-frame-job/capture-frame',{'timestamp_s':1,'data_url':PNG})
        self.assertEqual(len(self.app.assets),count)
    def test_agent_missing_dependencies(self):
        with patch('frame_tools.shutil.which',return_value=None):
            with self.assertRaises(APIError) as e:self.call('jobs/mock-frame-job/capture-frame',{'timestamp_s':1})
            self.assertEqual(e.exception.code,'capture_dependency')
    def test_first_insertion_retags_and_conflict_prevents_loss(self):
        record=self.place(new_scene=True,target='reference')
        record=self.api.edit(record['id'],{'expected_revision':1,'scene':{**record['scene'],'prompt':'Move <IMAGE_0>.'}})
        placed=self.place(scene_id=record['id'],expected_revision=2,target='first')
        self.assertEqual(placed['scene']['prompt'],'Move <IMAGE_1>.')
        with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=2,target='last')
        self.assertIsNone(self.api.record(record['id'])['scene']['last'])
        with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=3,target='first')
        self.assertEqual(self.place(scene_id=record['id'],expected_revision=3,target='first',replace=True)['revision'],4)
    def test_invalid_new_scene_not_created_and_keyframe_bounds(self):
        for slot in (0,15,1.5,True,None):
            with self.assertRaises(APIError):self.place(new_scene=True,target='keyframe',slot=slot)
        self.assertEqual(len(self.api.db['scenes']),0)
        record=self.place(new_scene=True,target='keyframe',slot=1)
        with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=1,target='keyframe',slot=1)
        for slot in (2,3,4):record=self.place(scene_id=record['id'],expected_revision=record['revision'],target='keyframe',slot=slot)
        with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=4,target='keyframe',slot=5)
    def test_lite_rejections_and_reference_limit(self):
        record=self.api.create({'scene':{'model':'grok-imagine-video-1.5-lite'}})
        for target in ('last','keyframe'):
            with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=1,target=target,slot=1)
        record=self.place(scene_id=record['id'],expected_revision=1,target='first')
        with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=2,target='reference')
        record=self.place(new_scene=True,target='reference')
        for _ in range(13):record=self.place(scene_id=record['id'],expected_revision=record['revision'],target='reference')
        with self.assertRaises(APIError):self.place(scene_id=record['id'],expected_revision=14,target='reference')
    def test_video_media_supports_seek_ranges(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);server.tester=self.app
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/api/video-media/mock-frame-job'
            with urlopen(Request(url,headers={'Range':'bytes=10-99'})) as response:
                self.assertEqual(response.status,206);self.assertEqual(len(response.read()),90);self.assertTrue(response.headers['Content-Range'].startswith('bytes 10-99/'))
            with self.assertRaises(HTTPError) as error:urlopen(Request(url,headers={'Range':'bytes=999999999-'}))
            self.assertEqual(error.exception.code,416);error.exception.close()
        finally:server.shutdown();server.server_close()
