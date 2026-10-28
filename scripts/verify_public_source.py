"""Verify the generated public snapshot against its local-only source manifest."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'dist' / 'github-public-source'
manifest = json.loads((ROOT / 'dist' / 'public-source-audit.json').read_text())
actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}
expected = set(manifest['included'])
errors = []
if actual != expected:
    errors.append('Snapshot file list differs from its manifest.')
for name, digest in manifest['included'].items():
    path = source / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        errors.append('Hash mismatch: ' + name)
for forbidden in ['.git', '.state', '.env', 'codex-reports', 'HANDOFF.md', 'subscription-tester/docs', 'subscription-tester/static/mock-video.mp4', 'subscription-tester/scripts/apply_episode_restructure_20261010.py']:
    if (source / forbidden).exists():
        errors.append('Excluded material found: ' + forbidden)
for path in source.rglob('*'):
    if path.is_symlink() or path.name in {'.git', '.state', '.deps', '.venv', 'node_modules'} or path.name.startswith('.env'):
        errors.append('Local-only path found: ' + str(path.relative_to(source)))
for required in ['LICENSE', 'THIRD_PARTY_LICENSES.txt', 'LICENSES/CC-BY-4.0.txt', 'subscription-tester/tests/fixtures/ducking-speech.md', 'subscription-tester/tests/fixtures/ducking-speech.wav']:
    if not (source / required).is_file():
        errors.append('Required rights record missing: ' + required)
for error in errors:
    print(error)
print('Public source scope and hashes:', 'PASS' if not errors else 'FAIL', '(' + str(len(actual)) + ' files)')
sys.exit(bool(errors))
