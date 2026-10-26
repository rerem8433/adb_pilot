"""Récupération et cache des noms/icônes d'applications."""
from __future__ import annotations

import hashlib
import json
import threading

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from .adbcore import AdbRangeReader, Package
from .apkparse import ARSC, RemoteZip, read_apk_meta
from .config import CACHE_DIR

META_DIR = CACHE_DIR / "meta"
ICON_SIZE = 64


def _key(p: Package, lang: str):
    return hashlib.sha1(f"{p.name}|{p.path}|{p.base_size}|{lang}".encode()).hexdigest()


def load_cached(p: Package, lang: str) -> bool:
    k = _key(p, lang)
    jf = META_DIR / (k + ".json")
    if not jf.is_file():
        return False
    try:
        d = json.loads(jf.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not d.get("label") and not d.get("empty") and not (META_DIR / (k + ".png")).is_file():
        return False  # entrée vide (ancien échec de lecture) : on relit l'APK
    p.label = d.get("label") or None
    p.version = d.get("version")
    p.meta_done = True
    icf = META_DIR / (k + ".png")
    if icf.is_file():
        img = QImage(str(icf))
        if not img.isNull():
            p.icon = img
    return True


def _decode(data: bytes | None) -> QImage | None:
    if not data:
        return None
    img = QImage.fromData(data)
    return None if img.isNull() else img


def _render_svg(svg: bytes, size: int) -> QImage | None:
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer
    r = QSvgRenderer(QByteArray(svg))
    if not r.isValid():
        return None
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def _layer(pt, layer, rect, s):
    kind, val = layer
    if kind == "color":
        pt.fillRect(QRectF(0, 0, s, s), QColor.fromRgba(val & 0xFFFFFFFF))
    elif kind == "img":
        img = _decode(val)
        if img is not None:
            pt.drawImage(rect, img)
    elif kind == "svg":
        img = _render_svg(val, int(rect.width()))
        if img is not None:
            pt.drawImage(rect, img)


def _compose_adaptive(layers, s=ICON_SIZE * 2) -> QImage | None:
    bg, fg = layers
    if fg is None and bg is None:
        return None
    out = QImage(s, s, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    pt = QPainter(out)
    pt.setRenderHint(QPainter.Antialiasing)
    pt.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
    pt.setClipPath(path)
    full = s * 108 / 72  # le calque fait 108dp, la zone visible 72dp
    rect = QRectF((s - full) / 2, (s - full) / 2, full, full)
    if bg is not None:
        _layer(pt, bg, rect, s)
    else:
        pt.fillRect(QRectF(0, 0, s, s), QColor("#ffffff"))
    if fg is not None:
        _layer(pt, fg, rect, s)
    pt.end()
    return out


def icon_image(m, size=ICON_SIZE) -> QImage | None:
    """Image de l'icône à partir d'un ApkMeta (bitmap, SVG ou adaptive-icon)."""
    img = None
    if m.icon_bytes:
        img = _decode(m.icon_bytes)
    if img is None and getattr(m, "icon_svg", None):
        img = _render_svg(m.icon_svg, size * 2)
    if img is None and m.icon_layers:
        img = _compose_adaptive(m.icon_layers)
    if img is not None:
        img = img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return img


_FW: dict = {}
_FW_LOCK = threading.Lock()
FW_PATH = "/system/framework/framework-res.apk"


def framework_res(serial):
    """(RemoteZip, ARSC) de framework-res.apk de l'appareil, chargé une seule fois (icônes @android:)."""
    with _FW_LOCK:
        if serial in _FW:
            return _FW[serial]
        fw = None
        try:
            from .adbcore import adb
            r = adb.run(["-s", serial, "shell", "stat -c %s " + FW_PATH] if serial else
                        ["shell", "stat -c %s " + FW_PATH], timeout=15, serial=False)
            size = r.out.strip()
            if size.isdigit():
                z = RemoteZip(AdbRangeReader(FW_PATH, int(size), serial))
                data = z.read("resources.arsc")
                if data:
                    fw = (z, ARSC(data))
        except Exception:  # noqa: BLE001
            fw = None
        _FW[serial] = fw
        return fw


def fetch_meta(p: Package, serial: str | None, lang: str) -> bool:
    """Lit le manifeste/arsc/icône sur l'appareil et met en cache. Modifie p en place. False = APK illisible."""
    if not p.path or not p.base_size:
        return True
    # Taille exacte du fichier base.apk : la fin du zip (répertoire central) y est cherchée
    reader = AdbRangeReader(p.path, p.base_size, serial)
    z = RemoteZip(reader)
    langs = (lang,) if lang else ()
    if lang and lang != "en":
        langs = (lang, "en")
    m = read_apk_meta(z, langs=langs, framework=lambda: framework_res(serial))
    img = icon_image(m)
    p.label = m.label or None
    p.version = m.version_name
    p.icon = img
    empty = img is None and not p.label
    if empty and not m.package:
        return False
    p.meta_done = True  # manifeste illisible : pas de cache, on réessaiera au prochain rafraîchissement
    META_DIR.mkdir(parents=True, exist_ok=True)
    k = _key(p, lang)
    if empty:  # APK lu correctement mais sans nom ni icône (composant système) : normal
        (META_DIR / (k + ".json")).write_text(json.dumps({"label": None, "version": p.version, "empty": True}),
                                              encoding="utf-8")
        return True
    if img is not None:
        img.save(str(META_DIR / (k + ".png")), "PNG")
    (META_DIR / (k + ".json")).write_text(json.dumps({"label": p.label, "version": p.version}), encoding="utf-8")
    return True


def clear_cache():
    import shutil
    shutil.rmtree(META_DIR, ignore_errors=True)
