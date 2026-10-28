"""Check publication content; optional private terms stay outside published source."""
import argparse
import json
from pathlib import Path
import re


def findings(root, terms=()):
    root = Path(root)
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            yield str(path.relative_to(root)), 0, 'symlink'
            continue
        if not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if any(part in {'.git', '.state', 'user-data', 'workspaces', 'codex-reports'} for part in path.relative_to(root).parts) or path.name.startswith('.env'):
            yield relative, 0, 'private storage'
            continue
        if path.suffix == '.wav':
            continue  # separately reviewed, explicitly licensed fixture
        text = path.read_text(errors='replace')
        for number, line in enumerate(text.splitlines(), 1):
            if any(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', line, re.I) for term in terms):
                yield relative, number, 'private identifier'
            if re.search(r'/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/', line):
                # Generic route fixture, not a user filesystem location.
                if '/home/workshop' not in line:
                    yield relative, number, 'personal filesystem path'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--terms-file', type=Path, help='Private JSON list of identifiers; never include this file in source.')
    args = parser.parse_args()
    terms = json.loads(args.terms_file.read_text()) if args.terms_file else []
    result = list(findings(args.directory, terms))
    for path, line, reason in result:
        print(f'{path}:{line}: {reason}')  # never echo matching identifiers or credentials
    print(f'Publication privacy: {len(result)} findings')
    raise SystemExit(bool(result))
