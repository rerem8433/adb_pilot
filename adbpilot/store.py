"""Store : catalogue d'applications, résolution des liens, métadonnées à distance, cache d'APK."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .apkparse import RangeReader, RemoteZip, read_apk_meta
from .config import CACHE_DIR, user_dir
from .osutil import ssl_context

BUNDLED = Path(__file__).resolve().parent / "data" / "store.json"
REMOTE_CATALOG = "https://raw.githubusercontent.com/rerem8433/adb_pilot/main/store/catalog.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) ADBPilot"
META_DIR = CACHE_DIR / "store"


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

CACHED = CACHE_DIR / "store" / "catalog.json"


def _valid(d):
    return isinstance(d, dict) and isinstance(d.get("apps"), list)


def load_catalog() -> dict:
    """Catalogue : dernière copie téléchargée depuis GitHub, sinon celui fourni avec l'appli."""
    for f in (CACHED, BUNDLED):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if _valid(d):
                return d
        except (OSError, ValueError):
            continue
    return {"categories": [], "apps": []}


def sync_catalog(url: str = REMOTE_CATALOG) -> bool:
    """Télécharge le catalogue publié sur GitHub. Renvoie True s'il a changé."""
    data = _get(url, timeout=15)
    d = json.loads(data.decode("utf-8"))
    if not _valid(d):
        raise ValueError("catalogue invalide")
    new = json.dumps(d, sort_keys=True)
    try:
        old = json.dumps(json.loads(CACHED.read_text(encoding="utf-8")), sort_keys=True)
    except (OSError, ValueError):
        old = None
    if new == old:
        return False
    CACHED.parent.mkdir(parents=True, exist_ok=True)
    CACHED.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    return True


def fetch_icon_url(app: dict):
    """Icône fournie par le catalogue (champ "icon" = URL d'un PNG), mise en cache."""
    url = app.get("icon")
    if not url:
        return None
    f = META_DIR / ("icon_%s_%s.png" % (app["id"], hashlib.sha1(url.encode()).hexdigest()[:10]))
    if not f.is_file():
        data = _get(url, timeout=20)
        META_DIR.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    return str(f)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _req(url, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h)


def _get(url, timeout=30) -> bytes:
    with urllib.request.urlopen(_req(url), context=ssl_context(), timeout=timeout) as r:
        return r.read()


class HttpRangeReader(RangeReader):
    """Lecture partielle d'un fichier distant (requêtes Range)."""

    def __init__(self, url: str):
        with urllib.request.urlopen(_req(url, {"Range": "bytes=0-0"}), context=ssl_context(), timeout=20) as r:
            self.url = r.geturl()
            cr = r.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)$", cr)
            if r.status != 206 or not m:
                raise IOError("le serveur ne gère pas les requêtes partielles")
            self.size = int(m.group(1))

    def read_ranges(self, ranges):
        out = []
        for off, ln in ranges:
            off = max(0, off)
            end = min(self.size, off + ln) - 1
            if end < off:
                out.append(b"")
                continue
            with urllib.request.urlopen(_req(self.url, {"Range": "bytes=%d-%d" % (off, end)}),
                                        context=ssl_context(), timeout=30) as r:
                out.append(r.read())
        return out


# ---------------------------------------------------------------------------
# Résolution des sources
# ---------------------------------------------------------------------------

def _abi_family(abi: str) -> str:
    abi = (abi or "").lower()
    if "arm64" in abi or "aarch64" in abi:
        return "arm64"
    if "x86_64" in abi:
        return "x86_64"
    if "x86" in abi:
        return "x86"
    return "arm"


ABI_NAMES = {"arm64": "arm64-v8a", "arm": "armeabi-v7a", "x86": "x86", "x86_64": "x86_64"}


def resolve(app: dict, abi: str = "") -> dict:
    """Renvoie {"url", "name", "version"?} ou {"page"} pour un lien manuel. Lève une exception sinon."""
    src = app.get("source") or {}
    fam = _abi_family(abi)
    if "url" in src:
        name = Path(urllib.parse.urlparse(src["url"]).path).name or app["id"] + ".apk"
        return {"url": src["url"], "name": name}
    if "github" in src:
        rel = json.loads(_get("https://api.github.com/repos/%s/releases/latest" % src["github"], 20))
        pat = src.get("asset_" + fam) or src.get("asset") or r"\.apk$"
        assets = [a for a in rel.get("assets", []) if re.search(pat, a["name"])]
        if not assets:
            raise LookupError("aucun APK correspondant dans la dernière version GitHub")
        a = assets[0]
        return {"url": a["browser_download_url"], "name": a["name"],
                "version": (rel.get("tag_name") or "").lstrip("v"), "size": a.get("size")}
    if "index" in src:
        html_ = _get(src["index"], 20).decode("utf-8", "replace")
        pat = src.get("pattern", r"[^\"'<>]+\.apk").replace("{abi}", re.escape(ABI_NAMES[fam]))
        names = sorted(set(re.findall(pat, html_)))
        if not names:
            raise LookupError("aucun APK trouvé sur %s" % src["index"])
        name = names[-1]
        return {"url": urllib.parse.urljoin(src["index"], name), "name": name}
    if "page" in src:
        return {"page": src["page"]}
    raise ValueError("source inconnue")


def host_of(app: dict) -> str:
    src = app.get("source") or {}
    if "github" in src:
        return "GitHub · " + src["github"]
    u = src.get("url") or src.get("index") or src.get("page") or ""
    pu = urllib.parse.urlparse(u)
    m = re.match(r"^/([^/]+)/([^/]+)/", pu.path)
    if pu.netloc == "github.com" and m:
        return "GitHub · %s/%s" % (m.group(1), m.group(2))
    return pu.netloc.replace("www.", "")


# ---------------------------------------------------------------------------
# Métadonnées (icône, version, paquet) lues à distance puis mises en cache
# ---------------------------------------------------------------------------

def meta_key(app: dict) -> str:
    return hashlib.sha1(json.dumps(app.get("source"), sort_keys=True).encode()).hexdigest()[:16]


def cached_meta(app: dict):
    f = META_DIR / (app["id"] + "_" + meta_key(app) + ".json")
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    icon = META_DIR / (app["id"] + "_" + meta_key(app) + ".png")
    d["icon_path"] = str(icon) if icon.is_file() else None
    return d


def fetch_meta(app: dict, abi: str, lang: str = "fr") -> dict:
    """Lit icône/version/paquet dans l'APK distant sans le télécharger entièrement."""
    res = resolve(app, abi)
    if "page" in res:
        return {"page": res["page"]}
    z = RemoteZip(HttpRangeReader(res["url"]))
    langs = (lang, "en") if lang and lang != "en" else ("en",)
    m = read_apk_meta(z, langs=langs)
    meta = {"package": m.package, "version": m.version_name or res.get("version"),
            "label": m.label, "url": res["url"], "name": res["name"]}
    from .metacache import icon_image
    img = icon_image(m, 96)
    META_DIR.mkdir(parents=True, exist_ok=True)
    base = META_DIR / (app["id"] + "_" + meta_key(app))
    if img is not None and not img.isNull():
        img.save(str(base) + ".png", "PNG")
        meta["icon_path"] = str(base) + ".png"
    base.with_suffix(".json").write_text(json.dumps({k: v for k, v in meta.items() if k != "icon_path"}), encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

def apk_cache_dir() -> Path:
    d = user_dir("store")
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(url: str, name: str, app_id: str, progress=None, cancel=lambda: False) -> Path:
    name = re.sub(r"[^\w.\-]+", "_", name)
    if not name.lower().endswith((".apk", ".apks", ".xapk", ".apkm")):
        name += ".apk"
    dest = apk_cache_dir() / ("%s__%s" % (app_id, name))
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(_req(url), context=ssl_context(), timeout=60) as r, open(tmp, "wb") as f:
        ctype = r.headers.get("Content-Type", "")
        total = int(r.headers.get("Content-Length") or 0)
        n = 0
        while True:
            if cancel():
                raise InterruptedError("annulé")
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            n += len(chunk)
            if progress:
                progress(n, total)
    with open(tmp, "rb") as f:
        head = f.read(4)
    if head != b"PK\x03\x04":
        tmp.unlink(missing_ok=True)
        raise IOError("le fichier reçu n'est pas un APK (%s) : le lien a sans doute expiré ou "
                      "demande un navigateur" % (ctype or "type inconnu"))
    tmp.replace(dest)
    return dest
