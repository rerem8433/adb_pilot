"""Mises à jour : dernière release GitHub, choix du bon fichier, téléchargement et installation."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import HOMEPAGE, VERSION
from .osutil import FROZEN, MACOS, WINDOWS, app_arch, app_bundle, clean_env, ssl_context

REPO = "rerem8433/adb_pilot"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES = HOMEPAGE.rstrip("/") + "/releases"


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    url: str            # page de la release
    asset: dict | None  # fichier à installer pour CET ordinateur (None = page web seulement)


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:4]) + (0,) * (4 - len(nums[:4]))


def is_newer(remote: str, local: str = VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def install_kind() -> str:
    """'deb' (paquet Linux), 'win-setup' (Windows installé), 'mac-app' (bundle macOS), sinon 'manual'."""
    if MACOS:
        return "mac-app" if app_bundle() else "manual"
    if WINDOWS:
        if FROZEN and any(Path(sys.executable).parent.glob("unins*.exe")):
            return "win-setup"
        return "manual"
    here = Path(__file__).resolve()
    if str(here).startswith("/opt/adbpilot/") and shutil.which("dpkg"):
        return "deb"
    return "manual"


def _pick_asset(assets: list, version: str) -> dict | None:
    kind = install_kind()
    if kind == "deb":
        pat = re.compile(r"^adbpilot_.*_amd64\.deb$")
    elif kind == "mac-app":
        arch = "arm64" if app_arch() == "arm64" else "x86_64"
        pat = re.compile(r"macos-%s\.dmg$" % arch, re.I)
    elif kind == "win-setup":
        arch = "arm64" if app_arch() == "arm64" else "x64"
        pat = re.compile(r"windows-%s-setup\.exe$" % arch, re.I)
    else:
        return None
    return next((a for a in assets if pat.search(a.get("name", ""))), None)


def check(timeout=15) -> Release | None:
    """Dernière release publiée si elle est plus récente que la version installée, sinon None."""
    req = urllib.request.Request(API, headers={"User-Agent": "adbpilot/" + VERSION,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, context=ssl_context(), timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    tag = d.get("tag_name") or ""
    if d.get("draft") or d.get("prerelease") or not is_newer(tag):
        return None
    return Release(version=tag.lstrip("vV"), tag=tag, notes=d.get("body") or "",
                   url=d.get("html_url") or RELEASES, asset=_pick_asset(d.get("assets") or [], tag))


def download(asset: dict, progress=None) -> Path:
    dest = Path(tempfile.gettempdir()) / ("adbpilot-update-" + asset["name"])
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "adbpilot/" + VERSION})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, context=ssl_context(), timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
        n = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            n += len(chunk)
            if progress:
                progress(n, total)
    if asset.get("size") and tmp.stat().st_size != asset["size"]:
        tmp.unlink(missing_ok=True)
        raise IOError("téléchargement incomplet")
    tmp.replace(dest)
    return dest


def install_deb(path: Path) -> tuple[bool, str]:
    """Installe le .deb avec apt (mot de passe demandé par une fenêtre graphique via pkexec)."""
    env = clean_env()
    if shutil.which("pkexec"):
        cp = subprocess.run(["pkexec", "apt-get", "install", "-y", "--reinstall",
                             "--allow-downgrades", str(path)], capture_output=True, text=True, env=env)
        if cp.returncode == 0:
            return True, cp.stdout[-2000:]
        if cp.returncode in (126, 127):  # authentification refusée / annulée
            return False, "authentification annulée"
        return False, (cp.stderr or cp.stdout)[-2000:]
    return False, "pkexec introuvable"


def run_windows_setup(path: Path):
    """Lance l'installateur en mode silencieux ; ADB Pilot doit se fermer juste après.
    L'installateur relance ADB Pilot à la fin (voir adbpilot.iss)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)


def run_macos_update(dmg: Path):
    """Monte le .dmg, copie la nouvelle app à côté de l'actuelle, puis un script détaché attend la
    fermeture d'ADB Pilot pour remplacer l'app et la relancer."""
    app = app_bundle()
    if app is None:
        raise RuntimeError("bundle introuvable")
    mnt = Path(tempfile.mkdtemp(prefix="adbpilot-dmg-"))
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-quiet", "-mountpoint", str(mnt), str(dmg)],
                   check=True, timeout=120)
    try:
        src = next(mnt.glob("*.app"))
        new = app.with_name(app.name + ".new")
        shutil.rmtree(new, ignore_errors=True)
        subprocess.run(["ditto", str(src), str(new)], check=True, timeout=300)
    finally:
        subprocess.run(["hdiutil", "detach", "-quiet", str(mnt)], timeout=60)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(new)], capture_output=True, timeout=60)
    script = ('while kill -0 %d 2>/dev/null; do sleep 0.5; done; '
              'rm -rf "%s" && mv "%s" "%s" && open "%s"' % (os.getpid(), app, new, app, app))
    subprocess.Popen(["/bin/sh", "-c", script], start_new_session=True, close_fds=True)


def terminal_install_cmd(path: Path) -> list[str]:
    """Secours sans pkexec : terminal qui lance sudo apt install."""
    return ["sh", "-c", "sudo apt install -y --reinstall '%s'; echo; read -p 'Entrée pour fermer…' x" % path]


def cleanup_old():
    for f in Path(tempfile.gettempdir()).glob("adbpilot-update-*"):
        try:
            if f.is_file():
                os.remove(f)
        except OSError:
            pass
