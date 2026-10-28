"""Install the pinned, test-only browser locally; no desktop browser/profile access."""
import hashlib
import json
import platform
from pathlib import Path
import urllib.request
import zipfile

def install():
    root=Path(__file__).resolve().parents[1]
    pin=json.loads(Path(__file__).with_name('parity-browser.json').read_text())
    if platform.system()!='Darwin' or platform.machine()!='arm64':raise SystemExit('This pin is for macOS arm64. Configure IMAGINE_CAMERA_REFERENCE_BROWSER with a separately pinned test browser on other systems.')
    folder=root/'.validation/parity-browser';folder.mkdir(parents=True,exist_ok=True)
    archive=folder/'chrome-headless-shell.zip'
    if not archive.exists():urllib.request.urlretrieve(pin['url'],archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=pin['sha256']:raise SystemExit('The browser archive does not match the pinned SHA256. Remove it before retrying.')
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            if not (folder/member.filename).resolve().is_relative_to(folder.resolve()):raise SystemExit('Invalid archive path.')
        z.extractall(folder)
    for name in ('chrome-headless-shell','chrome_crashpad_handler'):(folder/'chrome-headless-shell-mac-arm64'/name).chmod(0o755)
    print(folder/'chrome-headless-shell-mac-arm64/chrome-headless-shell')

if __name__=='__main__':install()
