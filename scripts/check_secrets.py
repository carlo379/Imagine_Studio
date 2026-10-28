"""Redacted history/eligible-source scan. Never open local env/state/credential stores."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if not shutil.which('gitleaks'):
    raise SystemExit('Install Gitleaks 8.30.1 or newer, then rerun this script.')
paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
for name in paths:
    if Path(name).name in {'agent-token','vault-key','host-id','auth.json'} or Path(name).suffix == '.enc':
        raise SystemExit('Private credential-store path is eligible for Git; remove it from the index before scanning.')
    if re.search(r'(^|/)(\.env[^/]*|\.state|\.venv|node_modules|\.deps|secrets?)(/|$)|\.(pem|key|p12|pfx)$', name, re.I):
        raise SystemExit('Sensitive path is eligible for Git. Inspect its filename locally before scanning.')
failed = False
with tempfile.TemporaryDirectory(prefix='imagine-redacted-scan-') as temp:
    tracked = Path(temp) / 'source'
    tracked.mkdir()
    for name in set(paths):
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            continue
        target = tracked / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for label, args in [('history', ['git', '--log-opts=--all']), ('eligible source', ['dir', str(tracked)])]:
        report = Path(temp) / (label + '.json')
        result = subprocess.run(['gitleaks', *args, '--config', str(ROOT / '.gitleaks.toml'), '--gitleaks-ignore-path', str(ROOT / '.gitleaksignore'), '--redact=100', '--no-banner', '--report-format=json', '--report-path', str(report)], cwd=ROOT, capture_output=True)
        findings = json.loads(report.read_text()) if report.exists() else []
        print(label + ': exit=' + str(result.returncode) + ', findings=' + str(len(findings)))
        for finding in findings:
            # Print locations only, never matched text or secret values.
            name = finding.get('File', '').removeprefix(str(tracked) + '/')
            print(name, finding.get('StartLine'), finding.get('RuleID'))
        if result.returncode not in (0, 1):
            print('Scanner execution failed; inspect its configuration/tool version.')
        failed |= result.returncode != 0
sys.exit(failed)
