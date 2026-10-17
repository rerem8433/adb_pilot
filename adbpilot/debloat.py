"""Listes de debloat (base communautaire UAD-ng, GPL-3.0)."""
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "uad_lists.json"

LEVELS = [
    ("Basique", "#8fd18f",
     "Bloatware courant des box et téléphones : applis préinstallées, services "
     "constructeur/opérateur, démos et outils d'usine (liste debloat0)."),
    ("Sûr", "#32d65a",
     "Basique + applis secondaires sans impact sur le système "
     "(calculatrice, fonds d'écran, outils constructeur…) (debloat0 + debloat1)."),
    ("Moyen", "#e6e62e",
     "Sûr + services constructeur plus profonds et applis Google « lite » "
     "(debloat0 à debloat2). À relire attentivement."),
    ("Maximal", "#ff4d4d",
     "Tout : ajoute des composants comme le Play Store ou la sauvegarde système "
     "(debloat0 à debloat3). Relis chaque ligne avant d'appliquer."),
]

REMOVAL_FR = {
    "Recommended": "Recommandé",
    "Advanced": "Avancé",
    "Expert": "Expert",
    "Unsafe": "Risqué",
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
        return json.loads(DATA.read_text())
    except Exception:
        return {}


def info(pkg: str):
    return db().get(pkg)


DEFAULTS_DIR = Path(__file__).resolve().parent / "data" / "debloat"


def level_file(level: int) -> Path:
    """Fichier texte du niveau (un paquet par ligne), dans ~/ADB_Pilot/debloat."""
    from .config import user_dir
    d = user_dir("debloat")
    f = d / ("debloat%d.db" % level)
    if not f.exists():
        src = DEFAULTS_DIR / f.name
        try:
            f.write_text(src.read_text() if src.is_file() else "")
        except OSError:
            pass
    return f


def ensure_files():
    for lv in range(4):
        level_file(lv)


_cache: dict = {}


def _read(level: int) -> set:
    f = level_file(level)
    try:
        key = (level, f.stat().st_mtime, f.stat().st_size)
    except OSError:
        return set()
    if key not in _cache:
        pkgs = set()
        for ln in f.read_text(errors="replace").splitlines():
            ln = ln.split("#", 1)[0].strip().replace("package:", "")
            if ln:
                pkgs.add(ln)
        _cache[key] = pkgs
    return _cache[key]


def level_packages(level: int) -> set:
    """Niveaux cumulatifs : Sûr = Basique + Sûr, Moyen = … + Moyen, etc."""
    out = set()
    for lv in range(level + 1):
        out |= _read(lv)
    return out


def matches_level(pkg: str, level: int) -> bool:
    return pkg in level_packages(level)
