"""Private user storage, independent of the installed application source."""
import os
from pathlib import Path
import sys


def data_home():
    override = os.environ.get('IMAGINE_STUDIO_DATA_DIR')
    if override:
        path = Path(override).expanduser().resolve()
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library' / 'Application Support' / 'Imagine Studio'
    elif sys.platform == 'win32':
        path = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'Imagine Studio'
    else:
        path = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'imagine-studio'
    return outside_source(path)


def outside_source(path):
    path = Path(path).expanduser().resolve()
    source = Path(__file__).resolve().parent.parent
    if path == source or source in path.parents:
        raise ValueError('User data must be outside the application checkout. Choose a private data directory.')
    return path


def require_migration():
    # Check directory existence only. Never inspect old project or credential files.
    legacy = Path(__file__).resolve().parent / '.state'
    if legacy.exists():
        raise ValueError('Legacy workspace found. Stop the server and run scripts/migrate_user_data.py before starting. No data was moved.')


def relocated_path(value):
    """Resolve saved optional model paths after opaque legacy storage migration."""
    path = Path(value).expanduser().resolve()
    legacy = Path(__file__).resolve().parent / '.state'
    if path.is_relative_to(legacy):
        return data_home() / path.relative_to(legacy)
    return path
