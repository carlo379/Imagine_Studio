"""Check local Markdown link targets in Git-eligible docs (not remote URLs/anchors)."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '--', '*.md'], cwd=ROOT, text=True).splitlines()
errors = []
for name in set(paths):
    path = ROOT / name
    if not path.is_file():
        continue
    for line, text in enumerate(path.read_text().splitlines(), 1):
        for link in re.findall(r'\]\(<?([^)>]+)>?\)', text):
            target = link.split('#')[0]
            if not target or ':' in target or target.startswith('//'):
                continue
            if not (path.parent / target).exists():
                errors.append(f'{name}:{line}: {target}')
for error in sorted(errors):
    print(error)
print(f'Local documentation links: {len(errors)} missing targets (remote URLs and anchors not checked).')
sys.exit(bool(errors))
