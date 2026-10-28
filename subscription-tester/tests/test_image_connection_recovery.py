import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from workspace_accounts import WorkspaceAccounts

class ConnectionRecoveryTests(unittest.TestCase):
    def test_personal_codex_reconnect_preserves_workspace_and_uses_device_auth(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home,'auth.json').write_text('{}')
            manager=WorkspaceAccounts.__new__(WorkspaceAccounts)
            manager.legacy=SimpleNamespace(mock=False)
            manager.jobs={}
            app=SimpleNamespace(spawn=lambda fn:fn())
            manager.app=Mock(return_value=app)
            manager.profile=Mock(side_effect=AssertionError('Personal login must not create a private profile'))
            process=Mock(stdout=iter(['https://auth.openai.com/device\n','ABCD-EFGHI\n']),wait=Mock(return_value=0),poll=Mock(return_value=0))
            with patch.dict('os.environ',{'CODEX_HOME':home}),patch('openai_images.codex_path',return_value='mock-codex'),patch('workspace_accounts.subprocess.Popen',return_value=process) as launch:
                result=manager.codex_login(SimpleNamespace(workspace_id='local-owner'))
            self.assertEqual(result['status'],'connected')
            self.assertEqual(launch.call_args.args[0],['mock-codex','login','--device-auth'])
            self.assertEqual(launch.call_args.kwargs['env']['CODEX_HOME'],home)
            self.assertEqual(next(iter(manager.jobs.values()))['target'],'local-owner')
            manager.profile.assert_not_called()

if __name__=='__main__':unittest.main()
