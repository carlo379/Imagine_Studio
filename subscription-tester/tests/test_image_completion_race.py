import tempfile
import threading
import unittest
from unittest.mock import patch
from studio_server import Studio


class ImageCompletionRaceTests(unittest.TestCase):
    def test_done_job_releases_gate_before_next_submission_can_observe_it(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Studio(mock=True,storage=folder)
            self.addCleanup(app.productions.sql.close)
            first=app.images.create({'settings':{'model':'gpt-image-2','prompt':'Synthetic first image'}})
            second=app.images.create({'settings':{'model':'gpt-image-2','prompt':'Synthetic second image'}})
            published=threading.Event();release=threading.Event();finished=threading.Event()
            original=app.images.persist;results=[];errors=[];workers=[]
            def persist():
                original()
                if any(j['key']=='race-first' and j['status']=='done' for j in app.images.db['jobs']) and not published.is_set():
                    published.set();release.wait(5)
            def spawn(target,*args):
                if workers:return  # Keep the second request pending to detect a late old-worker reset.
                thread=threading.Thread(target=target,args=args);workers.append(thread);thread.start()
            def submit():
                try:results.append(app.images.generate(second['id'],{'expected_revision':second['revision'],'approved':True},'race-second'))
                except Exception as error:errors.append(error)
                finally:finished.set()
            with patch.object(app.images,'persist',side_effect=persist),patch.object(app,'spawn',side_effect=spawn),patch('httpx.Client',side_effect=AssertionError('No provider calls')):
                app.images.generate(first['id'],{'expected_revision':first['revision'],'approved':True},'race-first')
                self.assertTrue(published.wait(5))
                thread=threading.Thread(target=submit);thread.start()
                try:self.assertFalse(finished.wait(.05),'A submission must wait for completion publication to finish')
                finally:release.set();thread.join(5);workers[0].join(5)
                self.assertFalse(errors,errors)
                self.assertEqual(results[0]['status'],'pending')
                self.assertEqual(app.state['phase'],'generating','The old worker must not reset the next job state')
