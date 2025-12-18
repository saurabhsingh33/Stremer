import os
import requests
import tempfile
import subprocess
from packaging import version as pkg_version
from PyQt6.QtWidgets import QMessageBox

# Configure your GitHub repo here or via env vars STREMER_REPO_OWNER / STREMER_REPO_NAME
DEFAULT_OWNER = "saurabhsingh33"
DEFAULT_REPO = "Stremer"


def _repo():
    owner = os.environ.get("STREMER_REPO_OWNER", DEFAULT_OWNER)
    repo = os.environ.get("STREMER_REPO_NAME", DEFAULT_REPO)
    if owner == "OWNER" or repo == "REPO":
        raise RuntimeError("Configure STREMER_REPO_OWNER/STREMER_REPO_NAME or set DEFAULT_OWNER/DEFAULT_REPO in updater.py")
    return owner, repo


def is_newer(latest: str, current: str) -> bool:
    try:
        return pkg_version.parse(latest.lstrip('v')) > pkg_version.parse(current.lstrip('v'))
    except Exception:
        return latest != current


def check_latest_release():
    owner, repo = _repo()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(api_url, timeout=10, headers=headers)
    r.raise_for_status()
    return r.json()


def get_windows_asset_url(release_json: dict) -> str | None:
    assets = release_json.get("assets", [])
    for a in assets:
        name = a.get("name", "")
        if name.lower() == "stremer-client-setup.exe":
            return a.get("browser_download_url")
    return None


def download_asset(url: str, filename: str, progress_cb=None) -> str:
    tmpdir = tempfile.mkdtemp(prefix="stremer-update-")
    out = os.path.join(tmpdir, filename)
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(out, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(int(done * 100 / total))
    return out


def launch_installer(path: str):
    try:
        # NSIS supports /S for silent. We run normally so user can confirm elevation.
        subprocess.Popen([path])
        QMessageBox.information(None, "Update", "Installer launched. Close the app if prompted.")
    except Exception as e:
        QMessageBox.critical(None, "Update", f"Failed to launch installer: {e}")


def message(parent, text: str):
    QMessageBox.information(parent, "Updates", text)
