import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from cryptography.fernet import Fernet
from studio_server import Studio
from workspace_accounts import CredentialProfile, WorkspaceAccounts


class ConnectionStatusTests(unittest.TestCase):
    def test_grok_generation_connection_is_separate_from_workspace_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Studio(mock=True,storage=folder)
            manager=WorkspaceAccounts(app)
            self.addCleanup(manager.sql.close);self.addCleanup(app.productions.sql.close)
            app.update(signed_in=True,auth_status='connected')
            with patch('httpx.Client',side_effect=AssertionError('No provider calls')):
                status=manager.status('local-owner')
            self.assertTrue(status['grok_connection']['signed_in'])
            self.assertEqual(status['grok_connection']['status'],'connected')
            self.assertFalse(status['grok_connection']['verified'])
            self.assertFalse(status['grok_identity_available'])
            self.assertIn('does not verify',status['grok_identity_message'])

    def test_unresponsive_credential_helper_has_a_deadline_and_is_killed(self):
        process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        with tempfile.TemporaryDirectory() as folder:
            profile=CredentialProfile(Path(folder),Fernet(Fernet.generate_key()))
            started=time.monotonic()
            with patch('workspace_accounts.subprocess.Popen',return_value=process):
                with self.assertRaisesRegex(ValueError,'timed out'):
                    profile.grok('headers',timeout=.05)
            self.assertIsNotNone(process.poll())
            self.assertLess(time.monotonic()-started,3)

    def test_connection_check_does_not_wait_indefinitely_for_a_signin_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            profile=CredentialProfile(Path(folder),Fernet(Fernet.generate_key()))
            ready=threading.Event();release=threading.Event()
            def hold():
                with profile.credential_lock('hermes'):ready.set();release.wait(3)
            thread=threading.Thread(target=hold);thread.start();ready.wait(1)
            try:
                with patch('workspace_accounts.subprocess.Popen',side_effect=AssertionError('Busy check must not launch a helper')):
                    with self.assertRaisesRegex(ValueError,'busy'):profile.grok('headers',timeout=.02)
            finally:release.set();thread.join()
