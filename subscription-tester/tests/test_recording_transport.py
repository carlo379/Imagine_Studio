"""Recording bytes become one scoped HTTPS reference; mocks prove no entitlement."""
import base64
import hashlib
from contextlib import ExitStack
import unittest
from unittest.mock import Mock,patch
from recording_transport import prepare_recordings,verify_delivery,verify_public_dns,RecordingTransportError

class RecordingTransportTests(unittest.TestCase):
    def setUp(self):
        self.raw=b'RIFF'+b'\0'*4+b'WAVE'+b'\0'*20
        self.body={'model':'grok-imagine-video-1.5','reference_audios':[
            {'url':'data:audio/wav;base64,'+base64.b64encode(self.raw).decode()}]}
        self.client=Mock();self.client.get.return_value=Mock(status_code=200,content=self.raw);self.headers={'Authorization':'Bearer fixture'}
    def test_recording_url_is_managed_without_mutating_snapshot(self):
        relay=Mock(url='https://fixture.trycloudflare.com/random/recording.wav')
        with patch('recording_relay.RecordingRelay') as factory:
            factory.return_value.__enter__.return_value=relay
            with ExitStack() as resources:
                result,uploads=prepare_recordings(self.client,self.headers,self.body,resources=resources)
                self.assertEqual(result['reference_audios'],[{'url':relay.url}])
                self.assertTrue(self.body['reference_audios'][0]['url'].startswith('data:'))
                self.assertEqual(uploads[0]['sha256'],hashlib.sha256(self.raw).hexdigest())
                self.assertNotIn('url',uploads[0])
                factory.assert_called_once_with(self.raw,'audio/wav')
            factory.return_value.__exit__.assert_called_once()
        self.client.post.assert_not_called()
    def test_preset_does_not_start_relay(self):
        with patch('recording_relay.RecordingRelay') as factory:
            body={'reference_audios':[{'voice_id':'ursa'}]}
            self.assertEqual(prepare_recordings(self.client,self.headers,body),(body,[]))
            factory.assert_not_called()
    def test_relay_failure_stops_before_video(self):
        with patch('recording_relay.RecordingRelay',side_effect=RuntimeError('offline')),ExitStack() as resources:
            with self.assertRaisesRegex(RecordingTransportError,'No video was submitted'):
                prepare_recordings(self.client,self.headers,self.body,resources=resources)
        self.client.post.assert_not_called()
    def test_bad_relay_url_is_rejected(self):
        with patch('recording_relay.RecordingRelay') as factory,ExitStack() as resources:
            factory.return_value.__enter__.return_value=Mock(url='http://evil.invalid/file')
            with self.assertRaisesRegex(RecordingTransportError,'Invalid temporary audio'):
                prepare_recordings(self.client,self.headers,self.body,resources=resources)
    def test_wrong_audio_bytes_never_submit(self):
        self.client.get.return_value=Mock(status_code=200,content=b'wrong')
        with self.assertRaisesRegex(RecordingTransportError,'exact recording bytes'):
            verify_delivery(self.client,'https://fixture.trycloudflare.com/file',hashlib.sha256(self.raw).hexdigest(),timeout=0)
        self.client.post.assert_not_called()
    def test_public_dns_keeps_tls_hostname_and_checks_exact_bytes(self):
        self.client.get.return_value.json.return_value={'Answer':[{'type':1,'data':'104.16.0.1'}]}
        with patch('recording_transport.subprocess.run',return_value=Mock(returncode=0,stdout=self.raw)) as curl:
            self.assertTrue(verify_public_dns(self.client,'https://fixture.trycloudflare.com/private.wav',hashlib.sha256(self.raw).hexdigest()))
            args=curl.call_args.args[0]
            self.assertIn('fixture.trycloudflare.com:443:104.16.0.1',args)
            self.assertNotIn('--insecure',args)
    def test_public_dns_rejects_private_address(self):
        self.client.get.return_value.json.return_value={'Answer':[{'type':1,'data':'127.0.0.1'}]}
        with patch('recording_transport.subprocess.run') as curl:
            self.assertFalse(verify_public_dns(self.client,'https://fixture.trycloudflare.com/private.wav','hash'))
            curl.assert_not_called()
    def test_missing_lifetime_rejected(self):
        with self.assertRaisesRegex(RecordingTransportError,'managed lifetime'):
            prepare_recordings(self.client,self.headers,self.body)

if __name__=='__main__':unittest.main()
