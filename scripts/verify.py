"""Run offline project suites from any working directory; never invoke live mode."""
from pathlib import Path
import subprocess
import sys
import os
import signal

ROOT = Path(__file__).resolve().parents[1] / 'subscription-tester'
python = ROOT / '.venv' / 'bin' / 'python'
if not python.exists():
    raise SystemExit('Run sh setup.sh --mock-only in subscription-tester first.')
subprocess.run([str(python), str(ROOT / 'ffmpeg_runtime.py')], check=True)
# Isolate modules so server/thread mocks cannot leak into unrelated suites.
if not (ROOT / '.deps' / 'hermes' / 'hermes_cli' / 'auth.py').is_file():
    raise SystemExit('Full offline auth tests require the pinned Hermes source. Run sh setup.sh (no sign-in or live calls).')
commands = [[str(python), '-m', 'unittest', 'discover', '-s', 'tests', '-p', p.name, '-q']
            for p in sorted((ROOT / 'tests').glob('test_*.py'))]
commands += [['node', str(p.relative_to(ROOT))] for p in sorted((ROOT / 'tests').glob('test_*.js'))]
failures = []
for command in commands:
    print('Running:', ' '.join(command), flush=True)
    process = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
    try:
        code = process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        # Include fixture renderers, not just the parent test process.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        print('Timed out after 180 seconds:', ' '.join(command), flush=True)
        code = 124
    if code:
        failures.append(' '.join(command))
print('Verification:', 'PASS' if not failures else 'FAIL', flush=True)
for failure in failures:
    print('Failed:', failure)
sys.exit(bool(failures))
