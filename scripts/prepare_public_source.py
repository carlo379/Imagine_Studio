"""Create a reviewable public source snapshot; never export Git/private history."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'dist' / 'github-public-source'
ROOT_FILES = {'.gitignore', '.gitattributes', '.gitleaks.toml', '.gitleaksignore',
              'README.md', 'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md', '.github/dependabot.yml',
              'THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_LICENSES.txt'}
PUBLIC_DOCS = {'docs/CONFIGURATION.md', 'docs/PUBLIC_RELEASE.md'}
GUIDES = {'Grok_Imagine_Prompting_Guide.md', 'grok-imagine-image-2.0-prompting-guide.md', 'gpt-image-2.0-2.5-prompting-guide.md'}
APP_DOCS = {'README.md', 'AGENT_API.md', 'AGENT_API_REFERENCE.md', 'USER_GUIDE.md', 'FILMMAKING_TOOLS_GUIDE.md',
            'IMAGE_STUDIO_GUIDE.md', 'PRODUCTION_WORKSPACE_GUIDE.md', 'SCRIPT_TEMPLATE_GUIDE.md',
            'SERIES_BOOKS_GUIDE.md', 'STORY_STUDIO_GUIDE.md', 'SCRIPT_TEMPLATE.txt'}
SCRIPTS = {'scripts/verify.py', 'scripts/check_docs.py', 'scripts/check_secrets.py', 'scripts/prepare_public_source.py', 'scripts/verify_public_source.py', 'scripts/check_public_privacy.py', 'scripts/migrate_user_data.py', 'scripts/install_linux_ffmpeg.sh'}
APP_SCRIPTS = {'demo_song_performance.py', 'build_frontend.mjs', 'camera-isolation.cjs', 'camera-reference.cjs', 'install_parity_browser.py', 'parity-browser.json'}
MEDIA = {'subscription-tester/tests/fixtures/ducking-speech.wav'}
PUBLIC_DATA = {'package.json', 'package-lock.json', 'studio-config.json', 'tsconfig.json', 'prompt_check_rules.json', 'static/camera-presets.json', 'static/build/manifest.json'}

def eligible(name):
    path = Path(name)
    if re.search(r'(^|/)(\.env[^/]*|\.state|\.deps|\.venv|node_modules|secrets?|user-data|workspaces|exports|backups|screenshots|codex-reports)(/|$)', name):
        return False
    if name in ROOT_FILES or name in PUBLIC_DOCS or name in SCRIPTS or name in MEDIA:
        return True
    if name.startswith('.github/workflows/') or name.startswith('LICENSES/'):
        return True
    if name.startswith('docs/prompting-guides/'):
        return path.name in GUIDES
    if not name.startswith('subscription-tester/'):
        return False
    relative = path.relative_to('subscription-tester')
    if relative.parts[0] in {'docs', 'experiments'}:
        return False
    if relative.parts[0] == 'scripts':
        return path.name in APP_SCRIPTS
    if path.suffix.lower() in {'.mp4', '.wav', '.png', '.jpg', '.webp', '.db', '.sqlite'}:
        return False
    if relative.parts[0] == 'launchagents':
        return path.name == 'imagine-studio.plist.example'
    if path.suffix.lower() == '.json':
        return str(relative) in PUBLIC_DATA
    if path.suffix.lower() in {'.md', '.txt'}:
        return len(relative.parts) == 1 and (path.name in APP_DOCS or path.name.startswith('requirements')) or name == 'subscription-tester/tests/fixtures/ducking-speech.md'
    return path.suffix.lower() in {'.py', '.js', '.cjs', '.mjs', '.ts', '.tsx', '.css', '.html', '.json', '.sh'} or path.name == '.gitignore'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--privacy-terms', type=Path, help='Private identifier list stored outside source.')
    args = parser.parse_args()
    if PUBLIC.exists():
        raise SystemExit('Public snapshot already exists. Move/remove that generated directory before rebuilding.')
    names = sorted(set(subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()))
    included = [name for name in names if eligible(name) and (ROOT / name).is_file() and not (ROOT / name).is_symlink()]
    PUBLIC.mkdir(parents=True)
    for name in included:
        destination = PUBLIC / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    # Remove links to intentionally omitted internal records while keeping the prose.
    for path in PUBLIC.rglob('*.md'):
        content = path.read_text()
        def link(match):
            target = match[2].split('#')[0]
            if target and ':' not in target and not (path.parent / target).exists():
                return match[1] + ' (internal record omitted from public source)'
            return match[0]
        content = re.sub(r'\[([^\]]+)\]\(<?([^)>]+)>?\)', link, content)
        # Historical local usernames/paths are not meaningful public setup guidance.
        content = re.sub(r'/Users/[^/\s]+/', '~/', content)
        path.write_text(content)
    release_doc = PUBLIC / 'docs' / 'PUBLIC_RELEASE.md'
    release_doc.write_text(release_doc.read_text().replace(
        'The working Git repository contains private development history. **Do not make\nthis repository or its existing history public.**',
        'This is a history-free public source edition. The private upstream repository\nand its historical materials are not part of this distribution.'))
    notices = PUBLIC / 'THIRD_PARTY_NOTICES.md'
    notices.write_text(notices.read_text().replace(
        'The\nworking repository retains private historical materials for local development;\nit must not be made public as-is.',
        'The private upstream repository retains historical materials for local\ndevelopment; those files and their history are not included in this edition.'))
    (PUBLIC / '.gitleaksignore').write_text('# No private Git history or historical suppressions are imported.\n')
    readme = PUBLIC / 'README.md'
    content = readme.read_text()
    content = (content[:content.index('## Repository scope and rights')] + '''## Source scope and license

    Original application code is MIT licensed. This snapshot intentionally omits
    private history, production records and copied provider documentation. The
    included speech fixture remains CC BY 4.0 with attribution. On first setup,
    FFmpeg creates the mock mathematical test-pattern clip locally. No original
    production media or historical binary mock clip is distributed.
    ''') if '## Repository scope and rights' in content else content
    readme.write_text(content)
    manifest = {name: hashlib.sha256((PUBLIC / name).read_bytes()).hexdigest() for name in included}
    # Manifest includes private filenames: keep it outside the public snapshot.
    (ROOT / 'dist' / 'public-source-audit.json').write_text(json.dumps({'included': manifest, 'excluded': [n for n in names if n not in included]}, indent=2)+'\n')
    from check_public_privacy import findings
    terms = json.loads(args.privacy_terms.read_text()) if args.privacy_terms else []
    violations = list(findings(PUBLIC, terms))
    if violations:
        for name, line, reason in violations:
            print(f'{name}:{line}: {reason}')
        raise SystemExit('Publication privacy failed. Snapshot is for review only; do not upload.')
    print('Public source snapshot:', PUBLIC)
    print('Included:', len(included), 'files. Git history, internal records and copied provider snapshots excluded.')

if __name__ == '__main__':
    main()
