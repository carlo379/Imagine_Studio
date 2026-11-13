"""Real HTTP ZIP uploads using only temporary workspaces."""
import copy
import io
from pathlib import Path
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import unittest

from agent_client import StudioClient, AgentError
from agent_api import APIError
from studio_server import StudioHandler
try:
    import test_project_archives as fixtures      # the tests folder is on the path (unittest discover -s tests)
except ImportError:
    from tests import test_project_archives as fixtures


class AgentArchiveImportTests(unittest.TestCase):
    export = fixtures.ProjectArchiveTests.export
    destination = fixtures.ProjectArchiveTests.destination
    altered = fixtures.ProjectArchiveTests.altered

    def setUp(self):
        fixtures.ProjectArchiveTests.setUp(self)
        self.dest = self.destination()
        self.dest.productions.dispatch('POST', [], {'title': 'Keep me', 'kind': 'quick'})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), StudioHandler)
        self.server.tester = self.dest
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.client = StudioClient(self.base, self.dest.agent.token_path)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        fixtures.ProjectArchiveTests.tearDown(self)

    def poll(self, task):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = self.client.request('project-archives/' + task['id'])
            if task['status'] in ('done', 'error'):
                while self.dest.archives.operation.locked() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(self.dest.archives.operation.locked())
                self.assertEqual(list(self.dest.archives.folder.glob('upload-*')), [])
                self.assertEqual(list(self.dest.archives.folder.glob('import-*')), [])
                return task
            time.sleep(.01)
        self.fail('Archive task did not finish')

    def test_roundtrip(self):
        child = self.other['production']
        child['parent_production_id'] = self.pid
        with self.p.sql:
            self.p.put('production', child)
        ref = self.app.save_reference({'title':'Robot', 'handle':'Robot', 'category':'Character',
                                      'description':'Golden shell', 'images':[{'asset_id':self.asset['id']}]})
        self.image['settings']['bindings'] = [{'snapshot': copy.deepcopy(ref)}]
        self.image['archive_metadata'] = {'path': ['guide', 'cast', 0], 'sha256': 'metadata'}
        self.app.images.dispatch('POST', ['jobs', 'image-job', 'approve'],
                                 {'asset_id': self.asset['id'], 'approved': True}, None)
        def interrupted(m):
            next(e['record'] for e in m['records'] if e['store'] == 'history').update(status='pending', recoverable=True)
        path = self.altered(interrupted)
        before = self.dest.archives.inventory()
        with patch('httpx.stream') as stream, patch('httpx.Client') as network, \
             patch.object(self.dest, 'start_video', side_effect=AssertionError('generation')), \
             patch.object(self.dest, 'resume', side_effect=AssertionError('resume')), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError('buffered ZIP upload')):
            task = self.poll(self.client.import_project(path))
            stream.assert_not_called()
            network.assert_not_called()
        self.assertEqual(task['status'], 'done', task)
        pid = task['project_id']
        self.assertNotEqual(pid, self.pid)
        outline = self.dest.productions.outline(pid)
        self.assertEqual(len(outline['episodes']), 1)
        self.assertEqual(len(outline['shots']), 1)
        children = [p for p in self.dest.productions.all('production') if p.get('parent_production_id') == pid]
        self.assertEqual(len(children), 1)
        self.assertNotEqual(children[0]['id'], child['id'])
        self.assertEqual(self.dest.filmmaking.series.book(outline['episodes'][0]['id'])['guide']['script'],
                         'The robot walks into the lab.')
        image = self.dest.images.draft(outline['shots'][0]['image']['id'])
        self.assertTrue(self.dest.assets[0]['approved'])
        self.assertEqual(self.dest.assets[0]['review_state'], 'approved')
        output = self.dest.images.db['jobs'][0]['outputs'][0]
        self.assertTrue(output['approved'])
        self.assertEqual(output['id'], self.dest.assets[0]['id'])
        self.assertEqual(image['archive_metadata']['path'], ['guide', 'cast', 0])
        self.assertNotEqual(self.dest.references[0]['id'], ref['id'])
        self.assertEqual(self.dest.asset(self.dest.assets[0]['id'])[1].read_bytes(), self.app.asset(self.asset['id'])[1].read_bytes())
        self.assertEqual(self.dest.history[0]['status'], 'error')
        self.assertFalse(self.dest.history[0]['recoverable'])
        self.assertEqual((self.dest.storage / 'videos' / (self.dest.history[0]['id'] + '.mp4')).read_bytes(), b'original video bytes')
        for entry in before:
            self.assertIn(entry, self.dest.archives.inventory())
        contract = self.client.request('openapi.json')
        op = contract['paths']['/project-archives/import']['post']
        self.assertIn('application/zip', op['requestBody']['content'])
        self.assertIn('202', op['responses'])
        schema = self.client.request('schema')
        self.assertIn('project-archives/import', schema['routes'])
        self.assertEqual(schema['project_archives'], op['x-archive-limits'])

    def test_auth_limits_and_media_type(self):
        for token in (None, 'invalid'):
            headers = {'Content-Type': 'application/zip'}
            if token: headers['Authorization'] = 'Bearer ' + token
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + '/agent/v1/project-archives/import', data=b'bad', headers=headers))
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        path = Path(self.temp.name) / 'bad.zip'
        path.write_bytes(b'bad')
        with patch('project_archives.MAX_ARCHIVE', 2):
            with self.assertRaises(AgentError) as error:
                self.client.import_project(path)
            self.assertEqual((error.exception.status, error.exception.code), (413, 'archive_limit'))
        with self.assertRaises(AgentError) as error:
            self.client.request('project-archives/import', 'POST', {})
        self.assertEqual(error.exception.status, 415)
        self.assertEqual(list(self.dest.archives.folder.glob('upload-*')), [])

    def test_unsafe_archive_tasks(self):
        bad = Path(self.temp.name) / 'bad.zip'
        bad.write_bytes(b'not a zip')
        for mutate, extra, code in [(None, None, 'invalid_archive'),
                (lambda m: None, '../escape', 'invalid_archive'),
                (lambda m: m['files'][0].update(sha256='0'*64), None, 'invalid_archive'),
                (lambda m: m.update(version=999), None, 'archive_version')]:
            path = bad if mutate is None else self.altered(mutate, extra)
            before = self.dest.archives.inventory()
            task = self.poll(self.client.import_project(path))
            self.assertEqual(task['status'], 'error')
            self.assertEqual(task['error']['code'], code)
            self.assertEqual(self.dest.archives.inventory(), before)
            self.assertFalse((self.dest.storage / 'assets').exists())

    def test_busy_and_publish_failure(self):
        path, _ = self.export()
        self.dest.archives.operation.acquire()
        try:
            with self.assertRaises(AgentError) as error:
                self.client.import_project(path)
            self.assertEqual((error.exception.status, error.exception.code), (409, 'archive_busy'))
            self.assertEqual(list(self.dest.archives.folder.glob('upload-*')), [])
        finally:
            self.dest.archives.operation.release()
        before = self.dest.archives.inventory()
        with patch.object(self.dest.archives, 'publish', side_effect=OSError('disk full')):
            task = self.poll(self.client.import_project(path))
        self.assertEqual(task['error']['code'], 'archive_failed')
        self.assertEqual(self.dest.archives.inventory(), before)
        self.assertEqual(self.poll(self.client.import_project(path))['status'], 'done')

    def test_bounded_stream_and_202_response(self):
        # Exercise AgentAPI.serve directly to inspect reads and HTTP status.
        class BoundedInput(io.BytesIO):
            def read(inner, size=-1):
                self.assertGreater(size, 0)
                self.assertLessEqual(size, 1024 * 1024)
                return super().read(size)
        raw = b'not-a-zip' * 300000
        replies = []
        handler = SimpleNamespace(
            allowed_host=lambda: True, server=SimpleNamespace(server_port=8766),
            path='/agent/v1/project-archives/import',
            headers={'Authorization': 'Bearer ' + self.dest.agent.token,
                     'Content-Type': 'application/zip', 'Content-Length': str(len(raw))},
            rfile=BoundedInput(raw), send=lambda status, body: replies.append((status, body)))
        self.dest.agent.serve(handler, 'POST')
        self.assertEqual(replies[0][0], 202)
        self.assertEqual(self.poll(replies[0][1])['error']['code'], 'invalid_archive')
        # A competing start after receipt also deletes the now-complete upload.
        handler.rfile = BoundedInput(raw)
        with patch.object(self.dest.archives, 'start', side_effect=APIError('archive_busy', 'Busy', 409)):
            self.dest.agent.serve(handler, 'POST')
        self.assertEqual(replies[-1][0], 409)
        self.assertEqual(list(self.dest.archives.folder.glob('upload-*')), [])

    def test_interruption_and_spawn_failure(self):
        headers = {'Content-Length':'10', 'Content-Type':'application/zip'}
        handler = SimpleNamespace(headers=headers, rfile=io.BytesIO(b'short'))
        with self.assertRaisesRegex(APIError, 'interrupted'):
            self.dest.archives.receive_upload(handler)
        handler.rfile = io.BytesIO(b'0123456789')
        before = copy.deepcopy(self.dest.archives.jobs)
        with patch.object(self.dest, 'spawn', side_effect=RuntimeError('thread failed')):
            with self.assertRaises(RuntimeError):
                self.dest.archives.receive_upload(handler)
        self.assertEqual(self.dest.archives.jobs, before)
        self.assertFalse(self.dest.archives.operation.locked())
        self.assertEqual(list(self.dest.archives.folder.glob('upload-*')), [])
        for changes, status in [({'Transfer-Encoding':'chunked'}, 400), ({'Content-Length':'bogus'}, 400),
                                ({'Content-Length':'0'}, 413)]:
            handler.headers = {**headers, **changes}
            with self.assertRaises(APIError) as error:
                self.dest.archives.receive_upload(handler)
            self.assertEqual(error.exception.status, status)
