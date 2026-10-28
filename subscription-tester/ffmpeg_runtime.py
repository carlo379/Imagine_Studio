"""Supported local media toolchain. Linux releases older than 9.0.1 are unsupported."""
import argparse
from functools import lru_cache
from pathlib import Path
import re
import shutil
import subprocess
import sys

MIN_LINUX_VERSION = (9, 0, 1)
MIN_LINUX_TEXT = '.'.join(map(str, MIN_LINUX_VERSION))


def parse_version(output, tool):
    match = re.match(r'^' + re.escape(tool) + r' version n?(\d+)\.(\d+)(?:\.(\d+))?(?=[\s-]|$)', output)
    return tuple(int(value or 0) for value in match.groups()) if match else None


@lru_cache(maxsize=16)
def installed_version(path, tool, modified_ns):
    # Cache by executable timestamp so opening private workspaces does not keep
    # spawning version probes. A replaced executable is checked again.
    result = subprocess.run([path, '-version'], capture_output=True, text=True,
                            check=True, timeout=5)
    return parse_version(result.stdout, tool)


def require_supported_linux():
    if sys.platform != 'linux':
        return
    requirement = f'Linux requires FFmpeg and FFprobe {MIN_LINUX_TEXT} or newer. '
    upgrade = 'Install a supported release and put both tools on PATH; see subscription-tester/README.md#linux-ffmpeg.'
    for tool in ('ffmpeg', 'ffprobe'):
        path = shutil.which(tool)
        if not path:
            raise RuntimeError(requirement + f'{tool} was not found. ' + upgrade)
        try:
            version = installed_version(path, tool, Path(path).stat().st_mtime_ns)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError(requirement + f'Could not check {tool}. ' + upgrade) from None
        if version is None:
            raise RuntimeError(requirement + f'Could not identify a stable {tool} release. ' + upgrade)
        if version < MIN_LINUX_VERSION:
            found = '.'.join(map(str, version))
            raise RuntimeError(requirement + f'Found {tool} {found}. ' + upgrade)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minimum', action='store_true', help='Print the supported Linux minimum.')
    args = parser.parse_args()
    if args.minimum:
        print(MIN_LINUX_TEXT)
    else:
        try:
            require_supported_linux()
        except RuntimeError as error:
            parser.exit(1, str(error) + '\n')
