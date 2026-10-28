"""Proxy output downloads and explicit recovery disposal; no provider calls."""
import base64
import copy
import socket
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import httpx
from agent_api import APIError
from agent_openapi import specification
import openai_images
import studio_server
from test_studio import PNG

RAW=base64.b64decode(PNG.split(',')[1])


def addresses(ip):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]


def download_client(status=200,raw=RAW,mime='image/png'):
    factory=MagicMock();response=factory.return_value.__enter__.return_value.stream.return_value.__enter__.return_value
    response.status_code=status;response.headers={'content-type':mime};response.iter_bytes.return_value=[raw]
    return factory


class ResultDownloadTests(unittest.TestCase):
    def test_trusted_results_allow_benchmark_proxy_without_auth_or_redirects(self):
        for host in ('imgen.x.ai','images.x.ai','api.x.ai'):
            for ip in ('198.18.0.1','198.19.255.254','8.8.8.8'):
                with self.subTest(host=host,ip=ip),patch.object(openai_images.socket,'getaddrinfo',return_value=addresses(ip)),patch('httpx.Client',download_client()) as factory:
                    self.assertEqual(openai_images.grok_result_bytes('https://'+host+'/result.png',1024),(RAW,'image/png'))
                    self.assertFalse(factory.call_args.kwargs['follow_redirects']);self.assertFalse(factory.call_args.kwargs['trust_env'])
                    client=factory.return_value.__enter__.return_value
                    self.assertEqual(client.stream.call_args.args,('GET','https://'+host+'/result.png'))
                    self.assertNotIn('headers',client.stream.call_args.kwargs)

    def test_reference_inputs_keep_public_address_requirement_even_on_xai_hosts(self):
        for host in ('imgen.x.ai','arbitrary.example'):
            for ip in ('198.18.0.1','198.19.255.254','127.0.0.1','10.0.0.1'):
                with self.subTest(host=host,ip=ip),patch.object(openai_images.socket,'getaddrinfo',return_value=addresses(ip)),patch('httpx.Client') as factory:
                    with self.assertRaisesRegex(ValueError,'public internet'):openai_images.source_bytes('https://'+host+'/ref.png',1024)
                    factory.assert_not_called()

    def test_result_exception_never_allows_arbitrary_hosts_or_other_private_addresses(self):
        for url in ('https://imgen.x.ai.evil.example/a','https://evil.example/a','http://imgen.x.ai/a','https://imgen.x.ai:444/a','https://user:pass@imgen.x.ai/a'):
            with self.subTest(url=url),patch('httpx.Client') as factory:
                with self.assertRaises(ValueError):openai_images.grok_result_bytes(url,1024)
                factory.assert_not_called()
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','192.168.1.1','::1'):
            with self.subTest(ip=ip),patch.object(openai_images.socket,'getaddrinfo',return_value=addresses(ip)),patch('httpx.Client') as factory:
                with self.assertRaises(ValueError):openai_images.grok_result_bytes('https://imgen.x.ai/a',1024)
                factory.assert_not_called()

    def test_redirects_oversize_and_invalid_content_still_fail(self):
        for factory,limit in ((download_client(status=302),1024),(download_client(),1),(download_client(raw=b'not png'),1024),(download_client(mime='text/html'),1024)):
            with patch.object(openai_images.socket,'getaddrinfo',return_value=addresses('198.18.0.1')),patch('httpx.Client',factory):
                with self.assertRaises(ValueError):openai_images.grok_result_bytes('https://imgen.x.ai/result.png',limit)


class ImageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=studio_server.Studio(mock=False,storage=self.temp.name);self.addCleanup(self.app.productions.sql.close)
        self.images=self.app.images;self.app.update(signed_in=True)
        self.draft=self.images.create(dict(title='Recover me',settings=dict(prompt='A robot.',n=2)))
        self.images.dispatch('POST',['drafts',self.draft['id'],'review-prompt'],dict(expected_revision=self.draft['revision'],reviewed=True),None)
        with patch.dict(self.images.config,{'live_generations_enabled':True}),patch.object(self.app,'spawn'):
            self.images.generate(self.draft['id'],dict(approved=True,expected_revision=self.draft['revision']),'recoverable-original')
        self.job=self.images.db['jobs'][0];self.job.update(status='error',request_id='saved-provider-request',recoverable=True)
        self.output=self.images.cache(RAW,self.job);self.output['candidate_index']=0;self.job['outputs']=[self.output]
        self.images.persist();self.app.update(phase='error')

    def call(self,data):
        return self.app.agent.dispatch('POST','/agent/v1/image-studio/jobs/'+self.job['id']+'/discard',data)[1]

    def test_resume_downloads_through_proxy_without_post_or_duplicate_candidates(self):
        factory=download_client();client=factory.return_value.__enter__.return_value
        client.get.return_value=httpx.Response(200,json={'status':'done','data':[{'url':'https://imgen.x.ai/first.png'},{'url':'https://imgen.x.ai/second.png'}]})
        with patch.object(self.app,'spawn') as spawn:self.images.resume(self.job)
        self.assertIsNone(spawn.call_args.args[-1])
        with patch('httpx.Client',factory),patch.object(openai_images.socket,'getaddrinfo',return_value=addresses('198.18.0.1')),patch.object(studio_server,'oauth_headers',return_value={'Authorization':'Bearer test-only'}):
            self.images.worker(self.job,self.job['endpoint'],None)
        self.assertEqual(self.job['status'],'done',self.job['message']);self.assertFalse(self.job['recoverable'])
        client.post.assert_not_called();client.stream.assert_called_once()
        self.assertEqual(self.job['outputs'][0]['id'],self.output['id']);self.assertEqual(len(self.job['outputs']),2)

    def test_discard_requires_confirmation_and_current_request_then_unlocks_and_audits(self):
        original=copy.deepcopy(self.job);draft=copy.deepcopy(self.images.draft(self.draft['id']))
        for data in ({},{'confirmed':False},{'confirmed':True,'request_id':'wrong'}):
            with self.assertRaises(APIError):self.call(data)
        with patch('httpx.Client') as http:
            discarded=self.call(dict(confirmed=True,request_id=self.job['request_id'],reason='Switch to a different model'))
            http.assert_not_called()
        self.assertEqual(discarded['status'],'discarded');self.assertFalse(discarded['recoverable'])
        self.assertEqual(discarded['outputs'],original['outputs']);self.assertEqual(discarded['draft'],original['draft'])
        self.assertEqual(self.images.draft(draft['id']),draft)
        audit=self.app.productions.get(discarded['discard_audit_id'],'image-job-audit')
        self.assertEqual(audit['action'],'discard-recovery');self.assertTrue(audit['confirmed'])
        self.assertEqual(audit['reason'],'Switch to a different model')
        self.call(dict(confirmed=True,request_id=self.job['request_id']))
        self.assertEqual(len(self.app.productions.all('image-job-audit')),1)
        with self.assertRaises(APIError):self.images.resume(self.job)
        self.app.mock=True
        with patch.object(self.app,'spawn') as spawn:
            # Preserve the original job's live mode when checking the lock.
            self.job['mock']=True
            edited=self.images.edit(draft['id'],dict(expected_revision=draft['revision'],settings={**draft['settings'],'model':'gpt-image-2','n':1,'resolution':'auto','quality':'auto'}))
            self.images.dispatch('POST',['drafts',edited['id'],'review-prompt'],dict(expected_revision=edited['revision'],reviewed=True),None)
            fresh=self.images.generate(edited['id'],dict(approved=True,expected_revision=edited['revision']),'different-model-after-discard')
        self.assertEqual(fresh['model'],'gpt-image-2');spawn.assert_called_once()

    def test_pending_jobs_cannot_be_discarded_and_discard_persists_after_restart(self):
        self.job['status']='pending'
        with self.assertRaises(APIError):self.call(dict(confirmed=True,request_id=self.job['request_id']))
        self.job['status']='error';self.call(dict(confirmed=True,request_id=self.job['request_id']))
        restarted=studio_server.Studio(mock=False,storage=self.temp.name)
        try:
            self.assertEqual(restarted.images.job(self.job['id'])['status'],'discarded')
            self.assertEqual(len(restarted.productions.all('image-job-audit')),1)
        finally:restarted.productions.sql.close()

    def test_openapi_discovers_confirmed_discard_contract(self):
        schema=specification()['paths']['/image-studio/jobs/{id}/discard']['post']['requestBody']['content']['application/json']['schema']
        self.assertEqual(set(schema['required']),{'confirmed','request_id'})
        self.assertEqual(schema['properties']['confirmed'],{'const':True})

    def test_failed_discard_write_leaves_recovery_and_audit_unchanged(self):
        original=copy.deepcopy(self.job)
        with patch.object(self.images,'persist',side_effect=[OSError('disk write failed'),None]):
            with self.assertRaises(OSError):self.call(dict(confirmed=True,request_id=self.job['request_id']))
        self.assertEqual(self.job,original)
        self.assertEqual(self.app.productions.all('image-job-audit'),[])
