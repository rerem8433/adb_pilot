"""Listes de debloat (base communautaire UAD-ng, GPL-3.0)."""
import json
import re
from functools import lru_cache
from pathlib import Path

from .i18n import _
from .osutil import ssl_context

DATA = Path(__file__).resolve().parent / "data" / "uad_lists.json"

LEVELS = [
    (_("Basique"), "#8fd18f",
     _("Bloatware courant des box et téléphones : applis préinstallées, services "
     "constructeur/opérateur, démos et outils d'usine (liste debloat0).")),
    (_("Sûr"), "#32d65a",
     _("Basique + applis secondaires sans impact sur le système "
     "(calculatrice, fonds d'écran, outils constructeur…) (debloat0 + debloat1).")),
    (_("Moyen"), "#e6e62e",
     _("Sûr + services constructeur plus profonds et applis Google « lite » "
     "(debloat0 à debloat2). À relire attentivement.")),
    (_("Maximal"), "#ff4d4d",
     _("Tout : ajoute des composants comme le Play Store ou la sauvegarde système "
     "(debloat0 à debloat3). Relis chaque ligne avant d'appliquer.")),
]

REMOVAL_FR = {
    "Recommended": _("Recommandé"),
    "Advanced": _("Avancé"),
    "Expert": "Expert",
    "Unsafe": _("Risqué"),
}
REMOVAL_COLOR = {
    "Recommended": "#32d65a",
    "Advanced": "#e6c22e",
    "Expert": "#ff8c3a",
    "Unsafe": "#ff4d4d",
}


@lru_cache(maxsize=1)
def db() -> dict:
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return {}


def info(pkg: str):
    return db().get(pkg)


DEFAULTS_DIR = Path(__file__).resolve().parent / "data" / "debloat"
REMOTE_BASE = "https://raw.githubusercontent.com/rerem8433/adb_pilot/main/debloat/"
PKG_RE = re.compile(r"^[A-Za-z][\w]*(\.[\w]+)+$")


def _cache_dir() -> Path:
    from .config import CACHE_DIR
    return CACHE_DIR / "debloat"


def level_file(level: int) -> Path:
    """Liste du niveau : dernière version publiée sur GitHub, sinon celle fournie avec l'appli."""
    f = _cache_dir() / ("debloat%d.db" % level)
    return f if f.is_file() else DEFAULTS_DIR / ("debloat%d.db" % level)


def _parse(text: str) -> set:
    pkgs = set()
    for ln in text.splitlines():
        ln = ln.split("#", 1)[0].strip().replace("package:", "")
        if ln and PKG_RE.match(ln):
            pkgs.add(ln)
    return pkgs


def sync_lists() -> bool:
    """Télécharge les listes publiées (silencieux). Renvoie True si quelque chose a changé."""
    import urllib.request
    texts = {}
    for lv in range(4):
        req = urllib.request.Request(REMOTE_BASE + "debloat%d.db" % lv, headers={"User-Agent": "ADBPilot"})
        with urllib.request.urlopen(req, context=ssl_context(), timeout=15) as r:
            t = r.read().decode("utf-8", "replace")
        if "<html" in t.lower() or (lv == 0 and len(_parse(t)) < 5):
            raise ValueError("liste invalide")
        texts[lv] = t
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    changed = False
    for lv, t in texts.items():
        f = d / ("debloat%d.db" % lv)
        if not f.is_file() or f.read_text(encoding="utf-8", errors="replace") != t:
            f.write_text(t, encoding="utf-8")
            changed = True
    _cache.clear()
    return changed


_cache: dict = {}


def _read(level: int) -> set:
    f = level_file(level)
    try:
        key = (str(f), f.stat().st_mtime, f.stat().st_size)
    except OSError:
        return set()
    if key not in _cache:
        _cache[key] = _parse(f.read_text(encoding="utf-8", errors="replace"))
    return _cache[key]


def level_packages(level: int) -> set:
    """Niveaux cumulatifs : Sûr = Basique + Sûr, Moyen = … + Moyen, etc."""
    out = set()
    for lv in range(level + 1):
        out |= _read(lv)
    return out


# Paquets vitaux sur un téléphone : jamais proposés par l'assistant hors box TV
PROTECTED_PHONE = (
    "com.android.providers.", "com.android.phone", "com.android.server.telecom", "com.android.dialer",
    "com.google.android.dialer", "com.android.contacts", "com.google.android.contacts", "com.android.mms",
    "com.google.android.apps.messaging", "com.android.messaging", "com.android.nfc", "com.android.stk",
    "com.google.android.ims", "com.android.ims", "com.android.cellbroadcast", "com.google.android.cellbroadcast",
    "com.android.deskclock", "com.google.android.deskclock", "com.android.captiveportallogin",
    "com.android.companiondevicemanager", "com.android.inputmethod", "com.google.android.inputmethod",
    "com.google.android.apps.inputmethod", "com.android.managedprovisioning", "com.android.vending",
    "com.google.android.gms", "com.google.android.gsf", "com.google.android.syncadapters.",
    "com.google.android.tts", "com.android.packageinstaller", "com.google.android.packageinstaller",
    "com.android.permissioncontroller", "com.google.android.permissioncontroller", "com.android.systemui",
    "com.android.settings", "com.android.launcher", "com.google.android.apps.nexuslauncher",
    "com.android.camera", "com.google.android.GoogleCamera", "com.google.android.backuptransport",
    "com.android.backupconfirm", "com.android.shell", "com.google.android.marvin.talkback",
    "com.android.bluetooth", "com.android.wifi", "com.google.android.networkstack", "com.android.networkstack",
)


def is_protected_phone(pkg: str) -> bool:
    return any(pkg == p or (p.endswith(".") and pkg.startswith(p)) or pkg.startswith(p + ".")
               or (not p.endswith(".") and pkg.startswith(p) and p.endswith(("inputmethod", "launcher", "camera")))
               for p in PROTECTED_PHONE)


def matches_level(pkg: str, level: int, is_tv: bool = True) -> bool:
    if not is_tv and is_protected_phone(pkg):
        return False
    return pkg in level_packages(level)
