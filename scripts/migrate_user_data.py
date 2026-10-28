"""Move legacy storage opaquely after shutdown; never parse project/credential files."""
import argparse
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'subscription-tester'))
from user_data import data_home, outside_source


def migrate(source, destination):
    source, destination = Path(source), outside_source(destination)
    if not source.exists():
        return False
    if source.is_symlink() or destination.exists():
        raise ValueError('Refusing to merge or overwrite storage. Keep both directories and choose a new destination.')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Atomic rename on the same volume; fail rather than partially copy credentials.
    os.rename(source, destination)
    destination.chmod(0o700 if destination.is_dir() else 0o600)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-stopped', action='store_true', required=True,
                        help='Confirm that all app servers/workers have been stopped first.')
    args = parser.parse_args()
    changed = migrate(ROOT / 'subscription-tester' / '.state', data_home())
    for parent in (ROOT, ROOT / 'subscription-tester'):
        for source in parent.glob('.env*'):
            if source.is_file():
                name = source.name if parent.name == 'subscription-tester' else 'legacy-root-' + source.name
                migrate(source, data_home() / name)
    print('Private storage moved; original files were not opened.' if changed else 'No legacy storage found.')
