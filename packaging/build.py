#!/usr/bin/env python3
"""Construit le .deb et l'archive portable d'ADB Pilot.

Usage : python3 packaging/build.py <site-packages contenant PySide6> <dossier de sortie>
"""
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from adbpilot import APP_ID, VERSION  # noqa: E402

SITE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
BUILD = OUT / "build"
STAGE = BUILD / "deb"
OPT = STAGE / "opt" / APP_ID
LIB = OPT / "lib"

KEEP_MODULES = {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtDBus"}
KEEP_PLUGINS = {
    "platforms": {"libqxcb.so", "libqwayland.so", "libqoffscreen.so", "libqminimal.so"},
    "platformthemes": None, "platforminputcontexts": {"libcomposeplatforminputcontextplugin.so",
                                                      "libibusplatforminputcontextplugin.so"},
    "imageformats": {"libqgif.so", "libqico.so", "libqjpeg.so", "libqsvg.so", "libqwebp.so"},
    "iconengines": None, "xcbglintegrations": None,
    "wayland-decoration-client": None, "wayland-graphics-integration-client": None,
    "wayland-shell-integration": None,
}


def sh(*a, **kw):
    return subprocess.run(a, check=True, **kw)


def prune_pyside(dst: Path):
    for f in list(dst.iterdir()):
        n = f.name
        if n.endswith(".abi3.so") and n.split(".")[0] not in KEEP_MODULES:
            f.unlink()
        elif n.endswith(".pyi") or n in ("__pycache__", "doc", "glue", "include", "typesystems",
                                         "scripts", "support", "assistant", "designer", "linguist",
                                         "lrelease", "lupdate", "qmlformat", "qmllint", "qmlls",
                                         "svgtoqml", "lib") or n.startswith("libpyside6qml"):
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    qt = dst / "Qt"
    for d in ("qml", "libexec", "metatypes", "resources"):
        shutil.rmtree(qt / d, ignore_errors=True)
    tr = qt / "translations"
    for f in tr.iterdir():
        if not re.match(r"^qtbase_(fr|en)\.qm$", f.name):
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    pl = qt / "plugins"
    for d in list(pl.iterdir()):
        keep = KEEP_PLUGINS.get(d.name, "drop")
        if keep == "drop":
            shutil.rmtree(d)
        elif keep is not None:
            for f in d.iterdir():
                if f.name not in keep:
                    f.unlink()
    # Fermeture des dépendances dans Qt/lib
    qtlib = qt / "lib"
    roots = [p for p in dst.glob("*.so*")] + [p for p in pl.rglob("*.so")]
    env = dict(os.environ, LD_LIBRARY_PATH=f"{qtlib}:{dst}:{dst.parent / 'shiboken6'}")
    needed, todo = set(), list(roots)
    while todo:
        so = todo.pop()
        out = subprocess.run(["ldd", str(so)], capture_output=True, text=True, env=env).stdout
        for m in re.finditer(r"=> (\S+)", out):
            p = Path(m.group(1)).resolve()
            if p.parent == qtlib.resolve() and p.name not in needed:
                needed.add(p.name)
                todo.append(p)
    for f in qtlib.iterdir():
        if f.is_file() and f.name not in needed and not f.is_symlink():
            real_names = {Path(os.path.realpath(x)).name for x in needed}
            if f.name not in real_names:
                f.unlink()
    for f in qtlib.iterdir():
        if f.is_symlink() and not f.exists():
            f.unlink()
    return needed


def missing_system_libs(dst: Path):
    qtlib = dst / "Qt" / "lib"
    env = dict(os.environ, LD_LIBRARY_PATH=f"{qtlib}:{dst}:{dst.parent / 'shiboken6'}")
    miss, sysdeps = set(), set()
    for so in list(dst.glob("*.so*")) + list((dst / "Qt").rglob("*.so*")):
        out = subprocess.run(["ldd", str(so)], capture_output=True, text=True, env=env).stdout
        for ln in out.splitlines():
            if "not found" in ln:
                miss.add((ln.split()[0], so.name))
            m = re.search(r"=> (/(?:usr/)?lib\S+)", ln)
            if m:
                sysdeps.add(Path(m.group(1)).name)
    return miss, sysdeps


def render_icons(dest: Path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=f"{LIB}")
    code = (
        "import sys;from PySide6.QtGui import QGuiApplication;app=QGuiApplication(sys.argv);"
        "from adbpilot.ui.style import svg_image, SVG;"
        f"import pathlib;d=pathlib.Path({str(dest)!r});"
        "[(d/f'{s}x{s}'/'apps').mkdir(parents=True,exist_ok=True) or svg_image('logo',s).save(str(d/f'{s}x{s}'/'apps'/'adbpilot.png')) for s in (32,48,64,128,256,512)];"
        "(d/'scalable'/'apps').mkdir(parents=True,exist_ok=True);"
        "(d/'scalable'/'apps'/'adbpilot.svg').write_text('<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\">'+SVG['logo']+'</svg>')"
    )
    sh(sys.executable, "-c", code, env=env)


DESKTOP = """[Desktop Entry]
Type=Application
Name=ADB Pilot
GenericName=Gestionnaire Android ADB
Comment=Gérer les applications d'un appareil Android via ADB (debloat, installation, scrcpy, console)
Exec=adbpilot %F
Icon=adbpilot
Terminal=false
Categories=Utility;Development;
Keywords=adb;android;apk;debloat;scrcpy;fastboot;
MimeType=application/vnd.android.package-archive;
StartupWMClass=adbpilot
"""

LAUNCHER = """#!/bin/sh
# Lanceur ADB Pilot : utilise le Python 3 du système (>= 3.10).
HERE="$(dirname "$(readlink -f "$0")")"
LIBDIR="${ADBPILOT_LIB:-%s}"
[ -d "$LIBDIR" ] || LIBDIR="$HERE/lib"
for py in python3 python3.13 python3.12 python3.11 python3.10 python3.14; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$py"; break
  fi
done
if [ -z "$PY" ]; then
  echo "ADB Pilot : Python 3.10 ou plus récent est requis." >&2; exit 1
fi
export PYTHONPATH="$LIBDIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
exec "$PY" -s -m adbpilot "$@"
"""


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    LIB.mkdir(parents=True)
    shutil.copytree(ROOT / "adbpilot", LIB / "adbpilot",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(SITE / "PySide6", LIB / "PySide6", symlinks=True)
    shutil.copytree(SITE / "shiboken6", LIB / "shiboken6", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyi"))
    needed = prune_pyside(LIB / "PySide6")
    print("Qt libs gardées :", len(needed))
    miss, sysdeps = missing_system_libs(LIB / "PySide6")
    print("Bibliothèques système liées :", " ".join(sorted(sysdeps)))
    if miss:
        print("ABSENTES sur la machine de build :", sorted(miss))

    # Lanceurs
    bin_dir = STAGE / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / APP_ID).write_text(LAUNCHER % f"/opt/{APP_ID}/lib")
    (bin_dir / APP_ID).chmod(0o755)
    app_dir = STAGE / "usr" / "share" / "applications"
    app_dir.mkdir(parents=True)
    (app_dir / f"{APP_ID}.desktop").write_text(DESKTOP)
    render_icons(STAGE / "usr" / "share" / "icons" / "hicolor")
    doc = STAGE / "usr" / "share" / "doc" / APP_ID
    doc.mkdir(parents=True)
    (doc / "copyright").write_text(
        "ADB Pilot — ParadoxXx Squad — GPL-3.0-or-later.\n"
        "https://github.com/rerem8433/adb_pilot\n"
        "Inclut PySide6/Qt (LGPL-3.0) et la base de debloat UAD-ng (GPL-3.0).\n")
    size_kb = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file() and not f.is_symlink()) // 1024
    deb = STAGE / "DEBIAN"
    deb.mkdir()
    (deb / "control").write_text(f"""Package: {APP_ID}
Version: {VERSION}
Section: utils
Priority: optional
Architecture: amd64
Installed-Size: {size_kb}
Depends: python3 (>= 3.10), libc6 (>= 2.34), libxcb-cursor0, libxkbcommon-x11-0, libxkbcommon0, libxcb-icccm4, libxcb-keysyms1, libxcb-image0, libxcb-render-util0, libxcb-shape0, libxcb-xkb1, libxcb-randr0, libxcb-util1, libegl1, libgl1, libfontconfig1, libfreetype6, libdbus-1-3, libglib2.0-0, libwayland-client0, libwayland-cursor0, libwayland-egl1
Recommends: adb, scrcpy, android-sdk-platform-tools-common
Suggests: fastboot
Maintainer: ParadoxXx Squad <noreply@localhost>
Homepage: https://github.com/rerem8433/adb_pilot
Description: Gestionnaire d'appareils Android via ADB (clone Linux d'AppControl)
 Liste des applications avec noms et icônes, debloat (base UAD-ng),
 désactivation / désinstallation / restauration, installation APK / XAPK /
 APKS / APKM, presets, permissions, console adb/fastboot avec shell
 interactif, logcat, captures, enregistrement vidéo et scrcpy.
""")
    (deb / "postinst").write_text("#!/bin/sh\nset -e\n"
                                  "command -v update-desktop-database >/dev/null && update-desktop-database -q || true\n"
                                  "command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true\n")
    (deb / "postrm").write_text("#!/bin/sh\nset -e\n"
                                "command -v update-desktop-database >/dev/null && update-desktop-database -q || true\n")
    for f in ("postinst", "postrm"):
        (deb / f).chmod(0o755)
    for p in STAGE.rglob("*"):
        if p.is_dir():
            p.chmod(0o755)
        elif p.is_file() and not p.is_symlink() and p.parent != deb:
            p.chmod(0o755 if (os.access(p, os.X_OK) or p.suffix == ".so" or ".so." in p.name) else 0o644)
    deb_file = OUT / f"{APP_ID}_{VERSION}_amd64.deb"
    sh("dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(STAGE), str(deb_file))

    # Archive portable
    port = BUILD / f"ADB-Pilot-{VERSION}-linux-x86_64"
    shutil.copytree(LIB, port / "lib", symlinks=True)
    # libxcb-cursor (Qt >= 6.5) absent par défaut sur certaines installations : copie de secours
    shutil.copy(ROOT / "packaging" / "vendor" / "libxcb-cursor.so.0",
                port / "lib" / "PySide6" / "Qt" / "lib" / "libxcb-cursor.so.0")
    (port / "adbpilot").write_text(LAUNCHER % "$HERE/lib")
    (port / "adbpilot").chmod(0o755)
    shutil.copy(STAGE / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "adbpilot.png", port / "adbpilot.png")
    (port / "LISEZMOI.txt").write_text(
        "ADB Pilot (portable)\n\nLancer : ./adbpilot\n\n"
        "Dépendances système (déjà présentes sur Ubuntu/Mint de bureau) : python3 >= 3.10, "
        "libxcb-cursor0.\nadb et scrcpy : sudo apt install adb scrcpy (ou Paramètres → Télécharger).\n")
    tgz = OUT / f"ADB-Pilot-{VERSION}-linux-x86_64.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        t.add(port, arcname=port.name)
    print(deb_file, deb_file.stat().st_size // 1048576, "Mo")
    print(tgz, tgz.stat().st_size // 1048576, "Mo")


if __name__ == "__main__":
    main()
