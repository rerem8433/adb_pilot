"""Récupération et cache des noms/icônes d'applications."""
from __future__ import annotations

import hashlib
import json

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from .adbcore import AdbRangeReader, Package
from .apkparse import RemoteZip, read_apk_meta
from .config import CACHE_DIR

META_DIR = CACHE_DIR / "meta"
ICON_SIZE = 64


def _key(p: Package, lang: str):
    return hashlib.sha1(f"{p.name}|{p.path}|{p.size}|{lang}".encode()).hexdigest()


def load_cached(p: Package, lang: str) -> bool:
    k = _key(p, lang)
    jf = META_DIR / (k + ".json")
    if not jf.is_file():
        return False
    try:
        d = json.loads(jf.read_text())
    except Exception:
        return False
    p.label = d.get("label") or None
    p.version = d.get("version")
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


def _compose_adaptive(layers) -> QImage | None:
    bg_bytes, bg_color, fg_bytes = layers
    bg, fg = _decode(bg_bytes), _decode(fg_bytes)
    if bg is None and fg is None and bg_color is None:
        return None
    s = ICON_SIZE
    out = QImage(s, s, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    pt = QPainter(out)
    pt.setRenderHint(QPainter.Antialiasing)
    pt.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(2, 2, s - 4, s - 4), s * 0.22, s * 0.22)
    pt.setClipPath(path)
    full = s * 108 / 72  # le calque fait 108dp, la zone visible 72dp
    rect = QRectF((s - full) / 2, (s - full) / 2, full, full)
    if bg_color is not None:
        c = QColor.fromRgba(bg_color & 0xFFFFFFFF)
        pt.fillRect(QRectF(0, 0, s, s), c)
    elif bg is not None:
        pt.drawImage(rect, bg)
    else:
        pt.fillRect(QRectF(0, 0, s, s), QColor("#ffffff"))
    if fg is not None:
        pt.drawImage(rect, fg)
    pt.end()
    return out


def fetch_meta(p: Package, serial: str | None, lang: str) -> None:
    """Lit le manifeste/arsc/icône sur l'appareil et met en cache. Modifie p en place."""
    if not p.path or not p.size:
        return
    reader = AdbRangeReader(p.path, p.size, serial)
    z = RemoteZip(reader)
    langs = (lang,) if lang else ()
    if lang and lang != "en":
        langs = (lang, "en")
    m = read_apk_meta(z, langs=langs)
    img = None
    if m.icon_bytes:
        img = _decode(m.icon_bytes)
    elif m.icon_layers:
        img = _compose_adaptive(m.icon_layers)
    if img is not None:
        img = img.scaled(ICON_SIZE, ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.label = m.label or None
    p.version = m.version_name
    p.icon = img
    META_DIR.mkdir(parents=True, exist_ok=True)
    k = _key(p, lang)
    if img is not None:
        img.save(str(META_DIR / (k + ".png")), "PNG")
    (META_DIR / (k + ".json")).write_text(json.dumps({"label": p.label, "version": p.version}))


def clear_cache():
    import shutil
    shutil.rmtree(META_DIR, ignore_errors=True)
