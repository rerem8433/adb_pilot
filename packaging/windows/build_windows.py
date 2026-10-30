#!/usr/bin/env python3
"""Construit ADB Pilot pour Windows (x64 ou ARM64) : dossier PyInstaller + adb/fastboot + scrcpy.

À lancer sur Windows avec le Python de l'architecture visée (x64 ou ARM64) :
    python packaging/windows/build_windows.py            -> dist/ADB-Pilot-<arch>/
L'installateur (.exe) est produit ensuite par Inno Setup (voir adbpilot.iss / le workflow GitHub).
"""
from __future__ import annotations

import io
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from adbpilot import VERSION  # noqa: E402

ARCH = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
BUILD = ROOT / "build" / ("win-" + ARCH)
DIST = ROOT / "dist"
APPDIR = DIST / ("ADB-Pilot-" + ARCH)
PT_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
SCRCPY_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"


def get(url: str) -> bytes:
    headers = {"User-Agent": "adbpilot-build"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        headers["Authorization"] = "Bearer " + tok
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
        return r.read()


def extract(data: bytes, dest: Path):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(dest)


def make_icon(dest: Path):
    """Icône multi-tailles générée depuis le logo SVG de l'application."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        make_icon.app = QGuiApplication(sys.argv[:1])  # garde l'application en vie
    from adbpilot.ui.style import svg_image
    img = svg_image("logo", 256)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    Image.open(io.BytesIO(bytes(buf.data()))).save(
        dest, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def tools(dest: Path):
    """adb/fastboot (Google) et scrcpy (win64 : tourne aussi en émulation sur Windows ARM)."""
    dest.mkdir(parents=True, exist_ok=True)
    print("platform-tools…")
    extract(get(PT_URL), dest)  # -> tools/platform-tools
    meta = json.loads(get(SCRCPY_API))
    asset = next(a for a in meta["assets"] if "win64" in a["name"] and a["name"].endswith(".zip"))
    print("scrcpy", meta["tag_name"], "…")
    tmp = BUILD / "scrcpy"
    shutil.rmtree(tmp, ignore_errors=True)
    extract(get(asset["browser_download_url"]), tmp)
    exe = next(tmp.rglob("scrcpy.exe"))
    shutil.copytree(exe.parent, dest / "scrcpy")
    (dest / "VERSIONS.txt").write_text("scrcpy %s\nplatform-tools latest (%s)\n" % (meta["tag_name"], PT_URL),
                                       encoding="utf-8")


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(APPDIR, ignore_errors=True)
    BUILD.mkdir(parents=True)
    ico = BUILD / "adbpilot.ico"
    make_icon(ico)
    sep = os.pathsep
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "ADB Pilot", "--icon", str(ico),
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--paths", str(ROOT),
        "--add-data", "%s%sadbpilot/data" % (ROOT / "adbpilot" / "data", sep),
        "--collect-submodules", "adbpilot",
        # modules Qt inutiles : installateur plus léger
        "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "tkinter",
        str(HERE / "launcher.py"),
    ], check=True)
    shutil.move(str(BUILD / "dist" / "ADB Pilot"), str(APPDIR))
    if os.environ.get("ADBPILOT_SKIP_TOOLS"):  # tests hors ligne
        (APPDIR / "tools").mkdir()
    else:
        tools(APPDIR / "tools")
    shutil.copy(ico, APPDIR / "adbpilot.ico")
    shutil.copy(ROOT / "LICENSE", APPDIR / "LICENSE.txt")
    # Archive portable
    DIST.mkdir(exist_ok=True)
    zname = DIST / ("ADB-Pilot-%s-windows-%s-portable" % (VERSION, ARCH))
    shutil.make_archive(str(zname), "zip", root_dir=DIST, base_dir=APPDIR.name)
    print("OK :", APPDIR, "et", zname.with_suffix(".zip"))


if __name__ == "__main__":
    main()
