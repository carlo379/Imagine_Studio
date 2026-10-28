"""Offline performance regressions. Never invoke providers or live writers."""
import copy
import gzip
import io
import json
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from agent_api import APIError
from studio_server import Studio
from studio_performance import workspace_status
from media_inspection import MediaInspection
from media_previews import MediaPreviews
from static_assets import StaticAssets


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Studio(mock=True,storage=self.temp.name)
        self.p=self.app.productions
        self.outline=self.p.dispatch('POST',[],{'kind':'quick','title':'Performance fixture'})[1]
        self.pid=self.outline['production']['id'];self.shot=self.outline['shots'][0]

    def tearDown(self):
        self.app.editing.inspection.pool.shutdown(wait=True)
        if hasattr(self.app,'previews'):self.app.previews.pool.shutdown(wait=True)
        self.p.sql.close();self.temp.cleanup()

    def test_compact_outline_retains_status_but_leaves_archives_in_detail(self):
        shot=self.p.get(self.shot['id'],'shot')
        shot['series_context']={'bible':{'notes':'archive '*40000}}
        with self.p.sql:self.p.put('shot',shot)
        with patch.object(self.p,'view_shot',side_effect=AssertionError('Expanded a list row')):
            status,summary=self.app.agent.dispatch('GET','/agent/v1/productions/'+self.pid+'/summary',{})
        self.assertEqual(status,200);self.assertTrue(summary['summary'])
        row=summary['shots'][0]
        self.assertNotIn('series_context',row);self.assertEqual(row['id'],shot['id'])
        self.assertEqual(row['video']['id'],shot['video_id']);self.assertIn('status',row)
        self.assertLess(len(json.dumps(summary)),10000)
        self.assertEqual(self.p.outline(self.pid)['shots'][0]['series_context'],shot['series_context'])

    def test_status_reads_are_stable_and_revision_changes_are_visible(self):
        first=workspace_status(self.app);self.assertEqual(first,workspace_status(self.app))
        shot=self.p.get(self.shot['id'],'shot');shot.update(title='Changed elsewhere',revision=shot['revision']+1)
        with self.p.sql:self.p.put('shot',shot)
        changed=workspace_status(self.app)
        self.assertNotEqual(first['areas']['productions'],changed['areas']['productions'])
        self.assertEqual(first['areas']['image'],changed['areas']['image'])
        self.assertEqual(set(changed),{'revision','areas'})

    def test_legacy_discovery_only_repeats_for_relationship_changes(self):
        with patch.object(self.p,'discover',wraps=self.p.discover) as discover:
            self.p.summary(self.pid);self.p.summary(self.pid)
            self.assertEqual(discover.call_count,0)
            self.app.agent.db['scenes'][0]['scene']['prompt']='An ordinary prompt edit.'
            self.p.summary(self.pid);self.assertEqual(discover.call_count,0)
            self.app.agent.create({'title':'A newly attached video'})
            self.p.summary(self.pid);self.assertEqual(discover.call_count,1)
            self.p.summary(self.pid);self.assertEqual(discover.call_count,1)

    def test_slow_inspection_does_not_hold_workspace_api_lock(self):
        entered=threading.Event();release=threading.Event()
        def slow_source(_):
            entered.set();release.wait(3)
            return dict(duration=1,video=True,audio=False),None
        with ThreadPoolExecutor(max_workers=2) as pool,patch.object(self.app.editing,'source',side_effect=slow_source):
            pending=pool.submit(self.app.agent.dispatch,'POST','/agent/v1/editing/inspect',{'source':{'kind':'upload','id':'fixture'}})
            try:
                self.assertTrue(entered.wait(1))
                lightweight=pool.submit(self.app.agent.dispatch,'GET','/agent/v1/productions/workspace',{})
                self.assertEqual(lightweight.result(timeout=1)[0],200)
            finally:release.set()
            self.assertEqual(pending.result(timeout=1)[1]['duration'],1)

    def test_cache_survives_restart_and_invalidates_a_changed_source(self):
        path=Path(self.temp.name)/'fixture.wav';path.write_bytes(b'fixture')
        cache=self.app.editing.inspection;cache.put(path,{'metadata':{'duration':2},'loudness_lufs':-19})
        other=MediaInspection(self.temp.name)
        try:
            self.assertEqual(other.get(path)['loudness_lufs'],-19)
            path.write_bytes(b'changed file version')
            self.assertEqual(other.get(path),{})
        finally:other.pool.shutdown(wait=True)

    def test_background_inspection_of_uncached_take_never_downloads(self):
        self.app.history.append(dict(id='uncached',status='done',video='https://example.invalid/result',mock=False,settings={'duration':5},created_at=1))
        with patch.object(self.app,'download',side_effect=AssertionError('Unexpected download')):
            result=self.app.agent.dispatch('POST','/agent/v1/editing/inspect',{'source':{'kind':'take','id':'uncached'},'background':True})[1]
        self.assertEqual(result['inspection_status'],'uncached');self.assertEqual(result['duration'],5)

    def test_image_thumbnail_is_small_cached_and_owner_scoped(self):
        asset_id='a'*32;path=Path(self.temp.name)/'assets'/(asset_id+'.png');path.parent.mkdir(exist_ok=True)
        Image.new('RGB',(960,540),'navy').save(path)
        original=path.read_bytes()
        self.app.assets.append(dict(id=asset_id,name='Fixture.png',ext='png',mime='image/png',src='/api/assets/'+asset_id))
        previews=MediaPreviews(self.app)
        try:
            raw,mime,state=previews.get('image',asset_id,160)
            self.assertEqual((mime,state),('image/jpeg','ready'))
            self.assertEqual(Image.open(io.BytesIO(raw)).size,(160,90));self.assertEqual(path.read_bytes(),original)
            with patch('media_previews.Image.open',side_effect=AssertionError('Decoded twice')):
                self.assertEqual(previews.get('image',asset_id,160)[0],raw)
            foreign=SimpleNamespace(asset=lambda _:(_ for _ in ()).throw(ValueError('missing')))
            other=MediaPreviews(foreign)
            try:
                with self.assertRaises(APIError):other.get('image',asset_id,160)
            finally:other.pool.shutdown(wait=True)
        finally:previews.pool.shutdown(wait=True)

    def test_library_pages_do_not_expand_archives_or_lose_results(self):
        draft=self.app.images.create({'title':'Library base','settings':{}})
        for index in range(3):
            record=copy.deepcopy(draft);record.update(id='library'+str(index),title='Searchable '+str(index),story_context={'scene_text':'large '*40000})
            self.app.images.db['drafts'].append(record)
        request={'collection':'images','query':'Searchable','offset':0,'limit':2}
        first=self.app.agent.dispatch('POST','/agent/v1/library/page',request)[1]
        second=self.app.agent.dispatch('POST','/agent/v1/library/page',{**request,'offset':2})[1]
        self.assertEqual(first['total'],3);self.assertTrue(first['has_more']);self.assertFalse(second['has_more'])
        self.assertEqual(len({i['id'] for i in first['items']+second['items']}),3)
        self.assertNotIn('scene_text',json.dumps(first));self.assertLess(len(json.dumps(first)),5000)

    def test_export_summaries_keep_delivery_fields_without_track_snapshots(self):
        timeline=self.app.editing.timeline(self.pid)
        snapshot={**timeline,'captions':[{'text':'archive '*10000}],'clips':[{'large':'archive '*10000}]}
        with self.p.sql:job=self.p.new('export',timeline_id=timeline['id'],snapshot=snapshot,status='done',progress=1,error=None,quality='full')
        items=self.app.agent.dispatch('GET','/agent/v1/editing/export-summaries',{})[1]
        self.assertTrue(items[0]['latest_delivery']);self.assertEqual(items[0]['snapshot']['title'],timeline['title'])
        self.assertNotIn('clips',items[0]['snapshot']);self.assertNotIn('captions',items[0]['snapshot'])
        self.assertEqual(self.p.get(job['id'],'export')['snapshot'],snapshot)


class StaticAssetTests(unittest.TestCase):
    def test_versioned_css_is_compressed_and_revalidated_without_caching_api(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'static'/'screen.css';path.parent.mkdir();path.write_text('.screen{color:green}'*300)
            assets=StaticAssets(root);digest=assets.content(path)[2]
            class Response:
                def __init__(self,url,headers):self.path=url;self.headers=headers;self.wfile=io.BytesIO();self.sent={}
                def send_response(self,status):self.status=status
                def send_header(self,key,value):self.sent[key]=value
                def end_headers(self):pass
            response=Response('/static/screen.css?v='+digest,{'Accept-Encoding':'gzip'})
            self.assertTrue(assets.serve(response));self.assertEqual(response.status,200)
            self.assertIn('immutable',response.sent['Cache-Control']);self.assertEqual(gzip.decompress(response.wfile.getvalue()),path.read_bytes())
            cached=Response(response.path,{'Accept-Encoding':'gzip','If-None-Match':response.sent['ETag']})
            assets.serve(cached);self.assertEqual(cached.status,304);self.assertEqual(cached.wfile.getvalue(),b'')
            path.write_text('changed stylesheet')
            changed=Response(response.path,{})
            assets.serve(changed);self.assertNotIn('immutable',changed.sent['Cache-Control'])
            self.assertFalse(assets.serve(Response('/api/state',{})))
            self.assertFalse(assets.serve(Response('/static/workspace.js',{})))
