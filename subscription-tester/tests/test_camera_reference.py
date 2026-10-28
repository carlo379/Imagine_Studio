"""Isolated HTTP + real Canvas parity. Never calls a media provider or live Studio."""
import base64
import copy
import html
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from agent_client import AgentError, StudioClient
import camera_renderer
from studio_server import Studio, StudioHandler
from workspace_accounts import WorkspaceAccounts


class CameraReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='imagine-agent-fix-',dir='/tmp');cls.addClassCleanup(cls.temp.cleanup)
        cls.app=Studio(mock=True,storage=cls.temp.name);cls.addClassCleanup(cls.app.productions.sql.close)
        cls.manager=WorkspaceAccounts(cls.app,mock_identity=True);cls.addClassCleanup(cls.manager.sql.close)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),StudioHandler);cls.addClassCleanup(cls.server.server_close)
        if cls.server.server_port==8766:raise RuntimeError('Refusing the live Studio port.')
        cls.server.tester=cls.app;cls.server.accounts=cls.manager
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.addClassCleanup(cls.thread.join,5);cls.addClassCleanup(cls.server.shutdown)
        cls.client=StudioClient(f'http://127.0.0.1:{cls.server.server_port}',cls.app.storage/'agent-token')

    def shot(self):
        production=self.client.create_production('Local Camera Control')['production']
        shot=self.client.create_shot(production['id'],'Reference export')
        return shot,self.client.shot_staging(shot['id'])

    def state(self):
        return (list(self.app.productions.sql.execute('SELECT * FROM records')),
            list(self.app.productions.sql.execute('SELECT * FROM versions')),
            copy.deepcopy(self.app.images.db),copy.deepcopy(self.app.agent.db),
            copy.deepcopy(self.app.assets),copy.deepcopy(self.app.references))

    def reference_browser(self):
        local=Path(__file__).resolve().parents[1]/'.validation/parity-browser/chrome-headless-shell-mac-arm64/chrome-headless-shell'
        executable=os.environ.get('IMAGINE_CAMERA_REFERENCE_BROWSER') or (str(local) if local.is_file() else None)
        if not executable:
            self.skipTest('Browser pixel parity requires a test-only browser. On macOS arm64 run scripts/install_parity_browser.py; on Linux set IMAGINE_CAMERA_REFERENCE_BROWSER to a separately pinned headless shell. Other camera API tests still run.')
        executable_path=Path(executable).resolve()
        self.assertTrue(executable_path.is_file() and os.access(executable_path,os.X_OK))
        self.assertNotIn('/Applications/',str(executable_path))
        self.assertNotIn(str(Path.home()/'Library'),str(executable_path))
        return executable_path

    def browser_png(self,stage):
        """Compare against a separately pinned project-local headless shell."""
        executable_path=self.reference_browser()
        root=Path(__file__).resolve().parents[1]
        # Fresh source bundle, not the server's checked-in headless artifact.
        script="const e=require('esbuild');process.stdout.write(e.buildSync({entryPoints:['ui/filmmaking-model.ts'],bundle:true,write:false,format:'iife',globalName:'BrowserCamera',target:'es2022',logLevel:'silent'}).outputFiles[0].text);"
        bundle=subprocess.run(['node','-e',script],cwd=root,check=True,capture_output=True,text=True).stdout
        payload=json.dumps(stage,ensure_ascii=True).replace('<','\\u003c')
        invocation='''const stage=STAGING;const size=BrowserCamera.frameSize(stage.ratio);
            const canvas=document.createElement('canvas');canvas.width=size.width;canvas.height=size.height;
            canvas.getContext('2d',{willReadFrequently:true});BrowserCamera.drawStage(canvas,stage,false);
            document.getElementById('browser-result').textContent=canvas.toDataURL('image/png');'''.replace('STAGING',payload)
        with tempfile.TemporaryDirectory(prefix='imagine-camera-browser-test-',dir='/tmp') as temporary:
            directory=Path(temporary);page=directory/'browser.html'
            page.write_text('<!doctype html><meta charset="utf-8"><pre id="browser-result"></pre><script>'+bundle.replace('</script','<\\/script')+'</script><script>'+invocation+'</script>')
            # Offline, unique profile. Only this owned process group is cleaned up.
            environment={k:os.environ[k] for k in ('PATH','LANG','LC_ALL') if k in os.environ}
            command=[str(executable_path),'--headless','--disable-gpu','--dump-dom',
                '--virtual-time-budget=250','--user-data-dir='+str(directory/'profile'),
                '--no-first-run','--no-default-browser-check','--disable-extensions',
                '--disable-background-networking','--disable-component-update','--disable-sync',
                '--disable-default-apps','--disable-breakpad','--disable-crash-reporter',
                '--no-crash-upload','--metrics-recording-only','--host-resolver-rules=MAP * ~NOTFOUND',
                '--proxy-server=http://127.0.0.1:9','--proxy-bypass-list=<-loopback>',page.as_uri()]
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True,env=environment,cwd=directory)
            try:output,_=process.communicate(timeout=15)
            finally:camera_renderer._terminate_owned_group(process)
            self.assertEqual(process.returncode,0)
        match=re.search(r'<pre id="browser-result">(.*?)</pre>',output.decode(),re.S)
        self.assertIsNotNone(match,'Browser Canvas must export an actual PNG.')
        return base64.b64decode(html.unescape(match.group(1)).split(',',1)[1],validate=True)

    def test_three_presets_match_browser_pixels_and_all_frame_sizes(self):
        self.reference_browser()
        catalog=self.client.camera_presets()
        self.assertTrue(catalog['renderer']['available'],'Install Node Skia Canvas and build the local worker.')
        shot,direction=self.shot();histograms=[]
        for identity,ratio,pose in [('wide','16:9','walk'),('close-up','9:16','reach'),('birds-eye','1:1','sit')]:
            with self.subTest(preset=identity,ratio=ratio):
                stage=copy.deepcopy(catalog['defaults']);stage['ratio']=ratio
                stage['camera']=next(p['camera'] for p in catalog['camera'] if p['id']==identity)
                stage['subjects'][0].update(name='Subject </script> & café',pose=pose,arms=25,head=15)
                direction=self.client.save_shot_staging(direction,stage);before=self.state()
                raw=self.client.camera_reference(direction);expected=self.browser_png(direction['staging'])
                self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'));self.assertEqual(self.state(),before)
                with Image.open(io.BytesIO(raw)) as server,Image.open(io.BytesIO(expected)) as browser:
                    dimensions=catalog['frame_sizes'][ratio]
                    self.assertEqual(server.size,(dimensions['width'],dimensions['height']));self.assertEqual(server.size,browser.size)
                    diff=ImageChops.difference(server.convert('RGBA'),browser.convert('RGBA'))
                    maximum=max(hi for lo,hi in diff.getextrema())
                    differing=sum(1 for pixel in diff.getdata() if any(channel > 1 for channel in pixel))
                    differing_percent=100*differing/(server.width*server.height)
                    print(f'PIXEL_DIFF preset={identity} maximum={maximum} differing_percent={differing_percent:.4f}',flush=True)
                    histograms.append(server.histogram())
                    self.assertLessEqual(maximum,4,'Canvas pixel diff exceeds four channel values.')
                    # 2026-10-08 baseline: Wide 3 / 0.5192%, Close-up 2 / 0.2754%,
                    # Bird's eye 3 / 0.3127%. These are Skia anti-aliasing differences,
                    # not layout errors.
                    self.assertLessEqual(differing_percent,1.0,'More than 1.0% of Canvas pixels differ by more than one channel value.')
                    self.assertGreater(len(server.convert('RGB').getcolors(server.width*server.height)),20)
        self.assertNotEqual(histograms[0],histograms[1]);self.assertNotEqual(histograms[1],histograms[2])

    def test_revision_body_missing_workspace_and_unavailable_runtime_guards(self):
        shot,direction=self.shot()
        with self.assertRaises(AgentError) as e:self.client.camera_reference(direction)
        self.assertEqual((e.exception.status,e.exception.code),(400,'missing_staging'))
        catalog=self.client.camera_presets();direction=self.client.save_shot_staging(direction,catalog['defaults']);before=self.state()
        with patch('camera_renderer.render_reference') as renderer:
            for payload in ({'expected_revision':0},{'expected_revision':True},
                    {'expected_revision':direction['revision'],'staging':catalog['defaults']},
                    {'expected_revision':direction['revision'],'workspace_id':'other'},
                    {'expected_revision':direction['revision'],'url':'https://provider.invalid'},
                    {'expected_revision':direction['revision'],'path':'/private/file'}):
                with self.assertRaises(AgentError):self.client.request('filmmaking/shots/'+shot['id']+'/reference.png','POST',payload)
            renderer.assert_not_called()
        with patch('camera_renderer.runtime_settings',side_effect=camera_renderer._unavailable('missing')):
            with self.assertRaises(AgentError) as e:self.client.camera_reference(direction)
            self.assertEqual((e.exception.status,e.exception.code),(503,'camera_renderer_unavailable'))
            self.assertFalse(self.client.camera_presets()['renderer']['available'])
        other=self.manager.new_guest();foreign_app=self.manager.app(other);self.addCleanup(foreign_app.productions.sql.close)
        foreign=StudioClient(self.client.base.removesuffix('/agent/v1'),foreign_app.storage/'agent-token')
        with self.assertRaises(AgentError) as e:foreign.camera_reference(direction)
        self.assertEqual(e.exception.status,404);self.assertEqual(self.state(),before)

    def test_local_export_transfers_through_existing_revision_checked_compose(self):
        shot,direction=self.shot();stage=self.client.camera_presets()['defaults']
        direction=self.client.save_shot_staging(direction,stage)
        png=self.client.camera_reference(direction)
        image=self.client.request('productions/shots/'+shot['id'])['image'];before=copy.deepcopy(image)
        result=self.client.compose_shot(direction,image['revision'],'Use this local composition.',png)
        self.assertEqual(result['draft']['settings']['model'],before['settings']['model'])
        self.assertEqual(len(result['draft']['settings']['extras']),1)
        self.assertEqual(self.app.images.db['jobs'],[]);self.assertEqual(self.app.records(),[])
        with self.assertRaises(AgentError) as e:self.client.compose_shot(direction,image['revision'],'Stale composition.',png)
        self.assertEqual(e.exception.status,409)

    def test_catalog_matches_shared_source_and_exposes_no_runtime_paths(self):
        catalog=self.client.camera_presets();source=json.loads(camera_renderer.CATALOG.read_text())
        for key in ('defaults','movements','frame_sizes'):self.assertEqual(catalog[key],source[key])
        self.assertEqual(len(catalog['camera']),7);self.assertEqual(len(catalog['movements']),14)
        for server,shared in zip(catalog['camera'],source['camera']):
            self.assertEqual(server['patch'],shared['patch']);self.assertEqual(server['camera'],{**source['defaults']['camera'],**shared['patch']})
        self.assertEqual(set(catalog['renderer']),{'engine','available','local_only','saved_only','guides','timeout_seconds','reference_route'})
        self.assertEqual(catalog['renderer']['engine'],'Node Skia Canvas 2D')
        self.assertNotIn('/Applications/',json.dumps(catalog));self.assertFalse(catalog['renderer']['guides'])
        self.assertIn('presets',self.client.request('filmmaking/schema')['camera_routes'])

    def test_export_reads_saved_geometry_without_loading_character_media(self):
        shot,direction=self.shot();stage=self.client.camera_presets()['defaults']
        direction=self.client.save_shot_staging(direction,stage)
        # A previously saved reference can later be archived/missing. Canvas only
        # uses its saved mannequin name and pose; new saves/compose retain checks.
        saved=self.app.filmmaking.direction(shot['id']);saved['staging']['subjects'][0]['asset_id']='historical-character'
        with self.app.productions.sql:self.app.productions.put('direction',saved)
        before=self.state()
        with patch.object(self.app.asset_studio,'get',side_effect=AssertionError('A local Canvas export must not load character media')),patch('camera_renderer.render_reference',return_value=b'local-png') as render:
            self.assertEqual(self.client.camera_reference(direction),b'local-png')
            self.assertEqual(render.call_args.args[0]['subjects'][0]['asset_id'],'historical-character')
        self.assertEqual(self.state(),before)


if __name__=='__main__':unittest.main()
