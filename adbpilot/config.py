import json
import os
from pathlib import Path

from . import APP_ID
from .osutil import app_dirs

CONFIG_DIR, CACHE_DIR, DATA_DIR = app_dirs(APP_ID)
PRESETS_DIR = CONFIG_DIR / "presets"

# Dossier utilisateur centralisé (sans espace, pratique en ligne de commande)
HOME_DIR = Path(os.environ.get("ADBPILOT_HOME", Path.home() / "ADB_Pilot"))
SUBDIRS = ("images", "videos", "install", "apps")


def user_dir(name: str = "") -> Path:
    p = HOME_DIR / name if name else HOME_DIR
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _pictures_dir():
    return str(HOME_DIR / "images")


DEFAULTS = {
    "adb_path": "",
    "scrcpy_path": "",
    "theme": "dark",
    "label_lang": "fr",
    "load_meta": True,
    "install_grant": True,
    "install_replace": True,
    "install_downgrade": False,
    "uninstall_keep_data": True,
    "auto_reconnect": True,
    "update_check": True,
    "update_skip": "",
    "auto_shell": False,
    "ip_history": [],
    "last_ip": "",
    "screens_dir": "",
    "scrcpy_max_size": 0,
    "scrcpy_bitrate": "8M",
    "scrcpy_max_fps": 0,
    "scrcpy_no_audio": False,
    "scrcpy_turn_screen_off": False,
    "scrcpy_stay_awake": True,
    "scrcpy_show_touches": False,
    "scrcpy_always_on_top": False,
    "scrcpy_extra": "",
    "fast_commands": [
        "devices -l",
        "shell getprop ro.build.version.release",
        "shell dumpsys battery",
        "shell wm size",
        "shell pm list packages -3",
        "reboot",
    ],
    "window_geometry": "",
    "install_dir": "",
    "layout_version": 0,
    "port": "auto",
    "scrcpy_record": False,
    "scrcpy_res": 1080,
}


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = CONFIG_DIR / "config.json"
        try:
            self.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass
        if self.get("layout_version", 0) < 2:
            self._migrate()
        if not self.get("screens_dir"):
            self["screens_dir"] = _pictures_dir()

    def _migrate(self):
        """1.2 : tout est centralisé dans ~/ADB_Pilot."""
        import shutil
        self["screens_dir"] = str(HOME_DIR / "images")
        self["install_dir"] = str(HOME_DIR / "install")
        old = Path.home() / "ADB Pilot" / "install"
        new = HOME_DIR / "install"
        try:
            if old.is_dir():
                new.mkdir(parents=True, exist_ok=True)
                for f in old.rglob("*"):
                    if f.is_file():
                        dst = new / f.relative_to(old)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        if not dst.exists():
                            shutil.move(str(f), str(dst))
        except OSError:
            pass
        self["layout_version"] = 2
        self.save()

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass


config = Config()
