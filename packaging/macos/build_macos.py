#!/usr/bin/env python3
"""Construit ADB Pilot pour macOS (Apple Silicon ou Intel, selon le Mac qui compile) :
« ADB Pilot.app » (PyInstaller) + adb/fastboot + scrcpy, puis un .dmg.

    python packaging/macos/build_macos.py   ->  dist/ADB-Pilot-<version>-macos-<arm64|x86_64>.dmg

Non signée par un compte développeur Apple (signature « ad hoc » seulement) : au premier
lancement, macOS demande une autorisation (Réglages Système → Confidentialité et sécurité).
"""
from __future__ import annotations

import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from adbpilot import VERSION  # noqa: E402

ARCH = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
BUILD = ROOT / "build" / ("mac-" + ARCH)
DIST = ROOT / "dist"
APP = BUILD / "dist" / "ADB Pilot.app"
PT_URL = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
SCRCPY_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
BUNDLE_ID = "fr.paradoxxx.adbpilot"


def get(url: str) -> bytes:
    headers = {"User-Agent": "adbpilot-build"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url:
        headers["Authorization"] = "Bearer " + tok
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
        return r.read()


def make_icns(dest: Path):
    """Icône .icns générée depuis le logo SVG de l'application."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        make_icns.app = QGuiApplication(sys.argv[:1])
    from adbpilot.ui.style import svg_image
    img = svg_image("logo", 1024)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    Image.open(io.BytesIO(bytes(buf.data()))).save(dest, format="ICNS")


def tools(dest: Path):
    """adb/fastboot (Google, universel) et scrcpy (build macOS de la bonne architecture)."""
    dest.mkdir(parents=True, exist_ok=True)
    print("platform-tools…")
    with zipfile.ZipFile(io.BytesIO(get(PT_URL))) as z:
        z.extractall(dest)  # -> tools/platform-tools
    meta = json.loads(get(SCRCPY_API))
    arch = "aarch64" if ARCH == "arm64" else "x86_64"
    asset = next(a for a in meta["assets"]
                 if "macos" in a["name"] and arch in a["name"] and a["name"].endswith(".tar.gz"))
    print("scrcpy", meta["tag_name"], asset["name"], "…")
    tmp = BUILD / "scrcpy"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(get(asset["browser_download_url"])), mode="r:gz") as t:
        t.extractall(tmp, filter="data")
    exe = next(p for p in tmp.rglob("scrcpy") if p.is_file())
    shutil.copytree(exe.parent, dest / "scrcpy", symlinks=True)
    for f in list((dest / "platform-tools").iterdir()) + list((dest / "scrcpy").iterdir()):
        if f.is_file() and f.suffix in ("", ".dylib") and not f.name.startswith("."):
            f.chmod(0o755)
    (dest / "VERSIONS.txt").write_text("scrcpy %s\nplatform-tools latest (%s)\n" % (meta["tag_name"], PT_URL),
                                       encoding="utf-8")


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)
    icns = BUILD / "adbpilot.icns"
    make_icns(icns)
    sep = os.pathsep
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "ADB Pilot", "--icon", str(icns), "--osx-bundle-identifier", BUNDLE_ID,
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--paths", str(ROOT),
        "--add-data", "%s%sadbpilot/data" % (ROOT / "adbpilot" / "data", sep),
        "--collect-submodules", "adbpilot",
        "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "tkinter",
        str(ROOT / "packaging" / "windows" / "launcher.py"),
    ], check=True)
    if os.environ.get("ADBPILOT_SKIP_TOOLS"):
        (APP / "Contents" / "Resources" / "tools").mkdir(parents=True, exist_ok=True)
    else:
        tools(APP / "Contents" / "Resources" / "tools")
    # Infos du bundle : version, nom affiché, Mac minimum
    plist = APP / "Contents" / "Info.plist"
    for key, val in (("CFBundleShortVersionString", VERSION), ("CFBundleVersion", VERSION),
                     ("CFBundleDisplayName", "ADB Pilot"), ("LSMinimumSystemVersion", "12.0"),
                     ("NSHighResolutionCapable", "true")):
        typ = "-bool" if val == "true" else "-string"
        subprocess.run(["defaults", "write", str(plist), key, typ, val], check=True)
    subprocess.run(["plutil", "-convert", "xml1", str(plist)], check=True)
    # Signature « ad hoc » de tout le bundle (obligatoire sur Apple Silicon après l'ajout des outils)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], check=True)
    # .dmg : l'app + un raccourci vers « Applications » pour l'installation par glisser-déposer
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    subprocess.run(["ditto", str(APP), str(stage / "ADB Pilot.app")], check=True)
    (stage / "Applications").symlink_to("/Applications")
    shutil.copy(HERE / "LISEZMOI-macOS.txt", stage / "LISEZMOI - README.txt")
    dmg = DIST / ("ADB-Pilot-%s-macos-%s.dmg" % (VERSION, ARCH))
    dmg.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", "ADB Pilot", "-srcfolder", str(stage),
                    "-ov", "-format", "UDZO", str(dmg)], check=True)
    print("OK :", dmg)


if __name__ == "__main__":
    main()
