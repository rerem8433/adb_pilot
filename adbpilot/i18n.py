"""Traduction de l'interface. Le texte source est en français ; `_()` renvoie l'anglais si choisi."""
from __future__ import annotations

from .config import config

LANGS = [("fr", "Français"), ("en", "English")]


def lang() -> str:
    return config.get("ui_lang", "fr") or "fr"


def _(s: str) -> str:
    if lang() == "fr":
        return s
    from .i18n_en import EN
    return EN.get(s, s)
