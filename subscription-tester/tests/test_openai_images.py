import base64
import copy
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import openai_images as provider
import studio_server as studio
from agent_api import APIError
from test_studio import PNG
from prompt_fixtures import reviewed_prompt


class OpenAIImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = studio.Studio(mock=True, storage=self.temp.name)
        self.asset = self.app.upload({'name': 'character.png', 'data_url': PNG})

    def tearDown(self):
        for _ in range(100):
            if all(j['status'] != 'pending' for j in self.app.images.db['jobs']):
                break
            time.sleep(.02)
        self.temp.cleanup()

    def draft(self, model, **settings):
        return self.app.images.create({'settings': {'model': model, 'prompt': 'A robot at a desk.', **settings}})

    def generate(self, draft, key='openai-test-once'):
        if not self.app.mock:reviewed_prompt(self.app,'image',draft)
        job = self.app.images.generate(draft['id'], {'expected_revision': draft['revision'], 'approved': True}, key)
        for _ in range(100):
            result = self.app.images.job(job['id'])
            if result['status'] != 'pending':
                return result
            time.sleep(.02)
        self.fail('Worker timed out')

    def test_models_defaults_and_billing(self):
        native = self.draft('gpt-image-2')
        self.assertEqual(native['settings']['resolution'], 'auto')
        self.assertEqual(native['settings']['quality'], 'auto')
        validation = self.app.images.validate(native)
        self.assertTrue(validation['valid'])
        self.assertEqual(validation['endpoint'], 'codex://native-image-generation')
        self.assertNotIn('quality', validation['request'])
        self.assertIn('Codex', validation['billing'])
        api = self.draft('gpt-image-2.5-flare', resolution='1536x864', quality='xhigh')
        request = self.app.images.validate(api)['request']
        self.assertEqual(request['size'], '1536x864')
        self.assertNotIn('response_format', request)
        self.assertNotIn('aspect_ratio', request)
        for bad in ({'model': 'gpt-image-2.5'}, {'model': 'gpt-image-2', 'quality': 'high'},
                    {'model': 'gpt-image-2.5-flare', 'resolution': '17x17'}):
            with self.assertRaises(APIError):
                self.app.images.create({'settings': {'prompt': 'test', **bad}})

    def test_provider_switch_keeps_immutable_asset_snapshots(self):
        reference = self.app.save_reference({'title': 'Robot', 'handle': 'Robot', 'description': 'Gold robot',
            'category': 'Character', 'images': [{'asset_id': self.asset['id']}]})
        draft = self.app.images.create({'named_references': ['Robot'], 'settings': {'prompt': '@Robot sits.'}})
        settings = copy.deepcopy(draft['settings'])
        settings.update(model='gpt-image-2.5-sunburst', resolution='auto', quality='low')
        edited = self.app.images.edit(draft['id'], {'expected_revision': 1, 'settings': settings})
        self.assertEqual(edited['settings']['bindings'], draft['settings']['bindings'])
        _, body, count = self.app.images.compile(edited)
        self.assertEqual(count, 1)
        self.assertEqual(body['images'][0]['url'], PNG)
        self.assertIn('Gold robot', body['prompt'])

    def test_api_mock_never_contacts_provider(self):
        with patch('httpx.Client') as http, patch.object(provider, 'CodexRPC') as rpc:
            job = self.generate(self.draft('gpt-image-2.5-flare'))
            http.assert_not_called()
            rpc.assert_not_called()
        self.assertEqual(job['status'], 'done')
        self.assertEqual(job['billing'], 'OpenAI API billing')
        self.assertTrue(job['outputs'][0]['mock'])

    def test_api_does_not_require_grok_sign_in_and_preserves_idempotency(self):
        draft = self.draft('gpt-image-2.5-flare')
        self.app.mock = False
        self.app.update(signed_in=False)
        with patch.object(provider, 'api_key', return_value='fake-key'), patch.object(provider, 'generate_api',
            return_value=(base64.b64decode(PNG.split(',')[1]), {'requested_model': 'gpt-image-2.5-flare'})) as generate:
            job = self.generate(draft)
            self.assertEqual(job['status'], 'done')
            self.assertEqual(self.generate(draft)['id'], job['id'])
            self.assertEqual(generate.call_count, 1)
        self.assertNotIn('fake-key', str(job))

    def test_missing_api_key_blocks_without_subscription_fallback(self):
        self.app.mock = False
        draft = self.draft('gpt-image-2.5-flare')
        with patch.object(provider, 'api_key', return_value=''), patch.object(provider, 'generate_subscription') as native:
            with self.assertRaises(APIError):
                self.generate(draft)
            native.assert_not_called()
        self.assertFalse(self.app.images.db['jobs'])

    def test_api_generation_and_edit_transport(self):
        response = Mock(status_code=200, headers={'x-request-id': 'request-test'})
        response.json.return_value = {'data': [{'b64_json': PNG.split(',')[1]}]}
        for extras in ([], [{'asset_id': self.asset['id']} ]):
            endpoint, body, _ = self.app.images.compile(self.draft('gpt-image-2.5-sunburst', extras=extras))
            with patch.object(provider, 'api_key', return_value='fake-key'), patch('httpx.Client') as client:
                post = client.return_value.__enter__.return_value.post
                post.return_value = response
                raw, metadata = provider.generate_api(endpoint, body, studio.CONFIG)
                self.assertEqual(post.call_count, 1)
                self.assertEqual(metadata['request_id'], 'request-test')
                self.assertEqual(raw, base64.b64decode(PNG.split(',')[1]))
                if extras:
                    self.assertEqual(post.call_args.kwargs['files'][0][0], 'image[]')
                    self.assertEqual(post.call_args.kwargs['data']['model'], 'gpt-image-2.5-sunburst')
                else:
                    self.assertEqual(post.call_args.kwargs['json']['n'], 1)

    def test_api_rejection_is_redacted_without_retry(self):
        endpoint, body, _ = self.app.images.compile(self.draft('gpt-image-2.5-flare'))
        response = Mock(status_code=429)
        response.json.return_value = {'error': {'message': 'Quota Bearer sk-test-only'}}
        with patch.object(provider, 'api_key', return_value='sk-test-only'), patch('httpx.Client') as client:
            post = client.return_value.__enter__.return_value.post
            post.return_value = response
            with self.assertRaises(ValueError) as failure:
                provider.generate_api(endpoint, body, studio.CONFIG)
            self.assertIn('429', str(failure.exception))
            self.assertNotIn('sk-test-only', str(failure.exception))
            self.assertEqual(post.call_count, 1)

    def test_subscription_adapter_uses_managed_auth_and_native_result(self):
        _, body, _ = self.app.images.compile(self.draft('gpt-image-2', extras=[{'asset_id': self.asset['id']}]))
        def rpc(method, params):
            if method == 'modelProvider/capabilities/read': return {'imageGeneration': True}
            if method == 'config/read': return {'config': {'mcp_servers': {'configured': {'url': 'https://example.test/mcp'}}}}
            if method == 'mcpServerStatus/list': return {'data': [{'name': 'example'}]}
            if method == 'thread/start':
                self.assertTrue(params['ephemeral'])
                self.assertFalse(params['config']['features.shell_tool'])
                self.assertFalse(params['config']['mcp_servers.configured.enabled'])
                self.assertFalse(params['config']['mcp_servers.example']['enabled'])
                self.assertTrue(params['config']['mcp_servers.example']['command'])
                self.assertNotIn('mcp_servers.example.enabled', params['config'])
                return {'thread': {'id': 'thread-test'}}
            return {}
        with patch.object(provider, 'codex_path', return_value='/test-only/codex'), patch.object(provider, 'CodexRPC') as cls, patch.object(provider, 'generate_api') as api:
            client = cls.return_value
            client.account.return_value = {'signed_in': True, 'plan': 'plus'}
            client.rpc.side_effect = rpc
            client.receive.side_effect = [
                {'method': 'item/completed', 'params': {'item': {'type': 'imageGeneration', 'status': 'completed', 'result': PNG.split(',')[1]}}},
                {'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}}]
            raw, metadata = provider.generate_subscription(body, studio.CONFIG)
            cls.assert_called_once_with(timeout=600)
            self.assertEqual(raw, base64.b64decode(PNG.split(',')[1]))
            self.assertEqual(metadata['requested_model'], 'gpt-image-2')
            client.close.assert_called_once()
            api.assert_not_called()

    def test_subscription_wait_budget_accepts_completion_after_three_minutes(self):
        import queue
        timeout=provider.generation_timeout('gpt-image-2',studio.CONFIG)
        self.assertEqual(timeout,600)
        self.assertEqual(provider.generation_timeout('grok-imagine-image-2.0',studio.CONFIG),180)
        client=provider.CodexRPC.__new__(provider.CodexRPC)
        client.deadline=timeout;client.timeout_message='Local waiting limit'
        client.queue=queue.Queue();client.queue.put({'method':'turn/completed','params':{}})
        with patch.object(provider.time,'monotonic',return_value=220):
            self.assertEqual(client.receive()['method'],'turn/completed')
        with patch.object(provider.time,'monotonic',return_value=601):
            with self.assertRaisesRegex(ValueError,'Local waiting limit'):client.receive()

    def test_subscription_six_sources_block_before_codex_starts(self):
        with patch.object(provider, 'CodexRPC') as rpc:
            with self.assertRaisesRegex(ValueError, 'five source images'):
                provider.generate_subscription({'model':'gpt-image-2','images':[{'url':PNG}]*6}, studio.CONFIG)
            rpc.assert_not_called()

    def test_subscription_failure_details_are_retained_and_redacted(self):
        for events, expected in (
            ([{'method':'item/completed','params':{'item':{'type':'agentMessage','text':'Reference limit exceeded Bearer sk-secret'}}},
              {'method':'turn/completed','params':{'turn':{'status':'completed'}}}], 'Reference limit exceeded'),
            ([{'method':'turn/completed','params':{'turn':{'status':'failed','error':{'message':'Quota exhausted sk-secret'}}}}], 'Quota exhausted'),
            ([{'method':'error','params':{'error':{'message':'Provider unavailable sk-secret'}}}], 'Provider unavailable'),
            ([{'method':'item/completed','params':{'item':{'type':'imageGeneration','status':'failed','failure':'Reference rejected sk-secret'}}}], 'Reference rejected'),
        ):
            with self.subTest(expected=expected), patch.object(provider, 'CodexRPC') as cls:
                client=cls.return_value
                client.account.return_value={'signed_in':True}
                client.rpc.side_effect=lambda method,params: {'imageGeneration':True} if method=='modelProvider/capabilities/read' else {'thread':{'id':'test'}} if method=='thread/start' else {}
                client.receive.side_effect=events
                with self.assertRaisesRegex(ValueError,expected) as failure:
                    provider.generate_subscription({'model':'gpt-image-2','prompt':'A circle.'},studio.CONFIG)
                self.assertNotIn('sk-secret',str(failure.exception))
                self.assertEqual(sum(call.args[0]=='turn/start' for call in client.rpc.call_args_list),1)
                client.close.assert_called_once()

    def test_subscription_cannot_accept_25_or_fall_back(self):
        with patch.object(provider, 'CodexRPC') as rpc:
            with self.assertRaises(ValueError):
                provider.generate_subscription({'model': 'gpt-image-2.5-flare'}, studio.CONFIG)
            rpc.assert_not_called()
        with patch.object(provider, 'CodexRPC') as cls, patch.object(provider, 'generate_api') as api:
            cls.return_value.account.return_value = {'signed_in': False}
            with self.assertRaises(ValueError):
                provider.generate_subscription({'model': 'gpt-image-2', 'prompt': 'A circle.'}, studio.CONFIG)
            api.assert_not_called()

    def test_private_reference_url_is_blocked(self):
        with patch.object(provider.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), patch('httpx.Client') as http:
            with self.assertRaises(ValueError):
                provider.source_bytes('https://example.test/image.png', 1024)
            http.assert_not_called()


if __name__ == '__main__':
    unittest.main()
