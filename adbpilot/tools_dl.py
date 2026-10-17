"""Téléchargement d'adb (platform-tools) et de scrcpy dans ~/.local/share/adbpilot."""
from __future__ import annotations

import io
import json
import shutil
import stat
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from .config import DATA_DIR

PT_URL = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
SCRCPY_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
UA = {"User-Agent": "adbpilot"}


def _get(url, progress=None, timeout=60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        n = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            buf.write(chunk)
            n += len(chunk)
            if progress:
                progress(n, total)
        return buf.getvalue()


def _chmod_x(p: Path):
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_platform_tools(progress=None) -> str:
    data = _get(PT_URL, progress)
    dest = DATA_DIR / "platform-tools"
    tmp = DATA_DIR / "platform-tools.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                continue
            z.extract(info, tmp)
    src = tmp / "platform-tools"
    for f in ("adb", "fastboot"):
        if (src / f).exists():
            _chmod_x(src / f)
    shutil.rmtree(dest, ignore_errors=True)
    src.rename(dest)
    shutil.rmtree(tmp, ignore_errors=True)
    return str(dest / "adb")


def install_scrcpy(progress=None) -> str:
    meta = json.loads(_get(SCRCPY_API, timeout=30))
    asset = next((a for a in meta.get("assets", [])
                  if "linux" in a["name"] and "x86_64" in a["name"] and a["name"].endswith(".tar.gz")), None)
    if not asset:
        raise RuntimeError("Pas de build Linux x86_64 dans la dernière version de scrcpy (%s)"
                           % meta.get("tag_name"))
    data = _get(asset["browser_download_url"], progress, timeout=120)
    dest = DATA_DIR / "scrcpy"
    tmp = DATA_DIR / "scrcpy.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        members = [m for m in t.getmembers()
                   if not m.name.startswith("/") and ".." not in Path(m.name).parts
                   and (m.isfile() or m.isdir())]
        t.extractall(tmp, members=members)
    exe = next(tmp.rglob("scrcpy"), None)
    if exe is None or not exe.is_file():
        raise RuntimeError("binaire scrcpy absent de l'archive")
    root = exe.parent
    for f in root.iterdir():
        if f.is_file() and f.name in ("scrcpy", "adb"):
            _chmod_x(f)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(root), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    return "%s (%s)" % (dest / "scrcpy", meta.get("tag_name", "?"))

