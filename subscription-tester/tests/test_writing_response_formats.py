"""Writing transport regressions. No provider requests or live app data."""
import copy
import json
import threading
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import story_studio
from script_production import ScriptProduction, SCHEMA as PRODUCTION_SCHEMA, POLICY
from script_upload_ai import SCHEMA as DUPLICATE_SCHEMA


class WritingResponseTests(unittest.TestCase):
    def transport(self, result, schema, events=None):
        calls=[]
        class FakeRPC:
            def __init__(self, **kwargs):
                self.events=iter(events if events is not None else [
                    dict(method='item/completed',params={'item':{'type':'agentMessage','text':json.dumps(result)}}),
                    dict(method='turn/completed',params={'turn':{'status':'completed'}})])
            def account(self):return {'signed_in':True}
            def rpc(self, method, data):
                calls.append((method,data))
                return {'thread':{'id':'fake-thread'}} if method=='thread/start' else {}
            def receive(self):return next(self.events)
            def close(self):pass
        with patch.object(story_studio.openai_images,'CodexRPC',FakeRPC):
            try:return story_studio.writing_reply({},schema,POLICY)
            finally:self.calls=calls

    def test_reconnect_notification_keeps_same_turn_until_completed(self):
        result=dict(reply='Finished.',scenes=[])
        reply=self.transport(None,None,events=[
            dict(method='error',params=dict(error=dict(message='Reconnecting... 2/5',
                codexErrorInfo={'responseStreamDisconnected':{'httpStatusCode':None}}),willRetry=True)),
            dict(method='item/completed',params={'item':{'type':'agentMessage','text':json.dumps(result)}}),
            dict(method='turn/completed',params={'turn':{'status':'completed'}})])
        self.assertEqual(reply,result)
        self.assertEqual(sum(method=='turn/start' for method,_ in self.calls),1)

    def test_writing_uses_http_with_managed_auth_and_no_resubmission(self):
        self.transport(dict(reply='Finished.',scenes=[]),None)
        config=next(data['config'] for method,data in self.calls if method=='thread/start')
        self.assertEqual(config['model_provider'],'imagine_studio_writing')
        provider=config['model_providers.imagine_studio_writing']
        self.assertTrue(provider['requires_openai_auth'])
        self.assertFalse(provider['supports_websockets'])
        self.assertEqual(provider['request_max_retries'],0)
        self.assertEqual(provider['stream_max_retries'],0)
        self.assertNotIn('base_url',provider)
        self.assertNotIn('env_key',provider)

    def test_terminal_error_has_safe_diagnostic_without_retry(self):
        error=dict(message='Request failed Bearer sk-private-test',additionalDetails='data:image/png;base64,private-pixels',
                   codexErrorInfo={'httpConnectionFailed':{'httpStatusCode':400}})
        with self.assertRaises(story_studio.WritingError) as failure:
            self.transport(None,None,events=[dict(method='error',params=dict(error=error,willRetry=False,
                threadId='writing-thread',turnId='writing-turn'))])
        diagnostic=failure.exception.diagnostic
        self.assertEqual(diagnostic['code'],'httpConnectionFailed')
        self.assertEqual(diagnostic['http_status'],400)
        self.assertEqual(diagnostic['turn_id'],'writing-turn')
        self.assertNotIn('sk-private-test',str(diagnostic))
        self.assertNotIn('private-pixels',str(diagnostic))
        self.assertEqual(sum(method=='turn/start' for method,_ in self.calls),1)

    def test_failed_completion_uses_embedded_error(self):
        with self.assertRaisesRegex(story_studio.WritingError,'usage or rate limit') as failure:
            self.transport(None,None,events=[dict(method='turn/completed',params={'turn':dict(
                id='failed-turn',status='failed',error=dict(message='Quota reached',codexErrorInfo='usageLimitExceeded'))})])
        self.assertEqual(failure.exception.diagnostic['turn_id'],'failed-turn')

    def test_interrupted_completion_is_not_a_success(self):
        with self.assertRaises(story_studio.WritingError):
            self.transport(None,None,events=[dict(method='turn/completed',params={'turn':{'status':'interrupted'}})])

    def production_result(self):
        return dict(logline='A discovery.',synopsis='A light blinks in the workshop.',visual_style='Illustrated.',mentions=[],dialogue_changes=[],scenes=[dict(scene_index=0,shots=[dict(title='Discovery',image_prompt='Show the light.',video_prompt='The light blinks.',asset_mentions=[])])])

    def test_production_response_without_reply(self):
        result=self.production_result()
        self.assertEqual(self.transport(result,PRODUCTION_SCHEMA),result)

    def test_duplicate_response_without_reply(self):
        result=dict(matches=[],summary='No duplicated production details found.')
        self.assertEqual(self.transport(result,DUPLICATE_SCHEMA),result)

    def test_ordinary_script_reply_still_validated(self):
        result=dict(reply='A script suggestion.',scenes=[])
        self.assertEqual(self.transport(result,None),result)
        with self.assertRaises(ValueError):self.transport(dict(reply=42,scenes=[]),None)

    def test_missing_required_field_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'expected format'):
            self.transport(dict(matches=[]),DUPLICATE_SCHEMA)

    def planner(self):
        saved=[];p=SimpleNamespace(sql=nullcontext(),put=lambda kind,job:saved.append(copy.deepcopy(job)))
        app=SimpleNamespace(agent=SimpleNamespace(lock=threading.RLock()))
        f=SimpleNamespace(app=app,p=p,request_plan=lambda provider,context,schema,policy:self.transport(self.production_result(),schema))
        planner=ScriptProduction(SimpleNamespace(f=f,app=app,p=p))
        source='INT. WORKSHOP — DAY\n\nA light blinks.'
        context=dict(production={'title':'Sample'},episode={'title':'Sample'},series_bible={'answers':{},'guide':{'acts':[]}},questionnaire={},guide={'acts':[]},source_script=source,source_scenes=[dict(title='Workshop',text='A light blinks.')],allow_dialogue_polish=False,dialogue_units=[],asset_catalog=[])
        job=dict(id='sample-job',revision=1,status='pending',mock=False,provider='codex',context=context,catalog=[],source_script=source,allow_dialogue_polish=False)
        return planner,job,saved

    def test_completion_worker_saves_reviewable_result_and_preserves_source(self):
        planner,job,saved=self.planner();before=copy.deepcopy(job['context']['source_scenes'])
        planner.worker(job)
        self.assertEqual(saved[-1]['status'],'done')
        self.assertEqual(saved[-1]['result']['scenes'][0]['text'],before[0]['text'])
        self.assertEqual(saved[-1]['source_script'],job['source_script'])
        self.assertFalse(saved[-1]['completion']['reviewed'])

    def test_unexpected_failure_has_safe_stage_and_type(self):
        planner,job,saved=self.planner()
        def fail(*args):raise KeyError('private response contents')
        planner.f.request_plan=fail;planner.worker(job)
        self.assertEqual(saved[-1]['status'],'error')
        self.assertEqual(saved[-1]['error_stage'],'requesting production details')
        self.assertEqual(saved[-1]['error_type'],'KeyError')
        self.assertNotIn('private response contents',saved[-1]['error'])

    def test_validation_failure_identifies_stage(self):
        planner,job,saved=self.planner();planner.f.request_plan=lambda *args:{}
        planner.worker(job)
        self.assertEqual(saved[-1]['error_stage'],'validating production details')
        self.assertIn('unexpected shape',saved[-1]['error'])


if __name__=='__main__':unittest.main()
