"""Concurrent production reads, video validation and job polling stay isolated."""
import concurrent.futures
import copy
import tempfile
import threading
import unittest
from studio_server import Studio

class ProductionConcurrencyTests(unittest.TestCase):
    def test_parallel_validation_dependencies_and_polling_return_exact_records(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Studio(mock=True,storage=folder)
            self.addCleanup(app.productions.sql.close)
            p=app.productions
            outline=p.dispatch('POST',[],{'kind':'story','title':'Concurrency test'})[1]
            pid=outline['production']['id'];episode=outline['episodes'][0]
            app.filmmaking.series.save_book(episode['id'],{'expected_revision':0,'answers':{'idea':'A robot waits.'}})
            episode=p.dispatch('POST',[pid,'scenes'],{'episode_id':episode['id'],'expected_revision':episode['revision'],'title':'The room','text':'A robot waits.'})[1]
            shot=p.dispatch('POST',[pid,'shots'],{'title':'Hold','episode_id':episode['id'],'story_scene_id':episode['scenes'][0]['id']})[1]
            video=app.agent.record(shot['video_id'])
            app.agent.edit(video['id'],{'expected_revision':video['revision'],'scene':{**video['scene'],'prompt':'A robot waits quietly.'}})
            video=app.agent.record(video['id'])
            context=app.prompting.context('video',video,{})
            app.prompting.mark('video',video,context,'review-fixture','codex')
            request=app.resolve(app.agent.compile(video['scene']))
            expected_status=app.prompting.request_status(request,video['id'])
            expected_dependencies=app.prompting.dependencies('video',video)
            kinds=['concurrency-record-'+str(i) for i in range(4)]
            expected={}
            with p.sql:
                for kind in kinds:
                    for i in range(32):p.new(kind,marker=kind,index=i,payload={'label':'record '+str(i)})
                    expected[kind]=p.all(kind)
            baseline=copy.deepcopy(video)
            gate=threading.Barrier(8)
            def read(worker):
                gate.wait(timeout=15)
                kind=kinds[worker%len(kinds)]
                for turn in range(120):
                    # Same SQL with different bindings and interleaved cursor/get
                    # operations reproduces the former shared statement-cache race.
                    self.assertEqual(p.all(kind),expected[kind])
                    record=expected[kind][turn%32]
                    self.assertEqual(p.get(record['id'],kind),record)
                    if worker%2:
                        self.assertEqual(app.prompting.request_status(request,video['id']),expected_status)
                    else:
                        self.assertEqual(app.prompting.dependencies('video',video),expected_dependencies)
                        self.assertEqual(p.get(shot['id'],'shot'),shot)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures=[pool.submit(read,i) for i in range(8)]
                for future in futures:future.result(timeout=60)
            self.assertEqual(video,baseline)
            self.assertEqual(p.sql.execute('PRAGMA quick_check').fetchone()[0],'ok')

if __name__=='__main__':unittest.main()
