"""Différences Linux / Windows / macOS regroupées ici (dossiers, outils embarqués, terminaux, sous-processus)."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
NO_APT = WINDOWS or MACOS  # pas de « sudo apt install » : on renvoie vers Paramètres → Télécharger
EXE = ".exe" if WINDOWS else ""
FROZEN = bool(getattr(sys, "frozen", False))

# Variables qui ne doivent pas fuir vers les programmes lancés (adb, scrcpy, terminal…)
_LEAKY = ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH")


def machine() -> str:
    """'x86_64', 'arm64'… (architecture réelle, même sous émulation x64 sur Windows ARM)."""
    if WINDOWS:
        arch = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").upper()
        return "arm64" if arch == "ARM64" else "x86_64"
    m = platform.machine().lower()
    return {"amd64": "x86_64", "aarch64": "arm64"}.get(m, m)


def app_arch() -> str:
    """Architecture de l'application elle-même (Python embarqué)."""
    m = platform.machine().lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64" if m in ("amd64", "x86_64") else m


def app_dirs(app_id: str) -> tuple[Path, Path, Path]:
    """(config, cache, données) de l'application — les variables XDG gardent la priorité (tests).

    Linux   : ~/.config/adbpilot, ~/.cache/adbpilot, ~/.local/share/adbpilot
    Windows : %APPDATA%\\adbpilot, %LOCALAPPDATA%\\adbpilot\\cache, %LOCALAPPDATA%\\adbpilot
    macOS   : ~/Library/Application Support/adbpilot (config + données), ~/Library/Caches/adbpilot"""
    home = Path.home()
    if MACOS:
        sup = home / "Library" / "Application Support" / app_id
        cfg, cache, data = sup, home / "Library" / "Caches" / app_id, sup / "data"
    elif WINDOWS:
        roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / app_id
        cfg, cache, data = roaming / app_id, local / "cache", local
    else:
        cfg, cache, data = home / ".config" / app_id, home / ".cache" / app_id, home / ".local" / "share" / app_id
    env = os.environ.get
    return (Path(env("XDG_CONFIG_HOME")) / app_id if env("XDG_CONFIG_HOME") else cfg,
            Path(env("XDG_CACHE_HOME")) / app_id if env("XDG_CACHE_HOME") else cache,
            Path(env("XDG_DATA_HOME")) / app_id if env("XDG_DATA_HOME") else data)


def app_bundle() -> Path | None:
    """macOS : chemin de « ADB Pilot.app » quand l'appli tourne depuis son bundle."""
    if MACOS and FROZEN:
        p = Path(sys.executable).resolve()
        for parent in p.parents:
            if parent.suffix == ".app":
                return parent
    return None


def bundled_tools_dir() -> Path | None:
    """Dossier « tools » livré avec les versions Windows / macOS (adb, fastboot, scrcpy)."""
    if FROZEN:
        exe_dir = Path(sys.executable).resolve().parent
        for d in (exe_dir / "tools", exe_dir.parent / "Resources" / "tools"):
            if d.is_dir():
                return d
    return None


def macos_unquarantine():
    """macOS : retire l'attribut de quarantaine des outils embarqués (adb, scrcpy).

    Une fois l'appli autorisée par l'utilisateur, macOS bloquerait encore ces binaires
    téléchargés avec elle ; ils sont dans le bundle de l'utilisateur, on peut les libérer."""
    if not MACOS:
        return
    for d in (bundled_tools_dir(), app_bundle()):
        if d:
            try:
                subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(d)],
                               capture_output=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired):
                pass


def is_exe(p) -> bool:
    p = Path(p)
    return p.is_file() and (WINDOWS or os.access(p, os.X_OK))


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _LEAKY}


def no_window() -> dict:
    """Arguments subprocess : pas de fenêtre console qui clignote sous Windows."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def open_terminal(cmd: list[str], title: str) -> str | None:
    """Ouvre un terminal externe qui exécute cmd. Renvoie le nom du terminal, ou None."""
    env = clean_env()
    if WINDOWS:
        wt = shutil.which("wt")
        try:
            if wt:
                subprocess.Popen([wt, "-w", "new", "--title", title] + cmd, env=env)
                return "Windows Terminal"
            subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
            return "console"
        except OSError:
            return None
    if MACOS:
        import shlex
        line = " ".join(shlex.quote(c) for c in cmd).replace("\\", "\\\\").replace('"', '\\"')
        try:
            subprocess.Popen(["osascript", "-e", 'tell application "Terminal" to do script "%s"' % line,
                              "-e", 'tell application "Terminal" to activate'], env=env)
            return "Terminal"
        except OSError:
            return None
    cands = [
        ("gnome-terminal", ["--title", title, "--"] + cmd),
        ("mate-terminal", ["--title", title, "-x"] + cmd),
        ("xfce4-terminal", ["--title", title, "-x"] + cmd),
        ("konsole", ["-e"] + cmd),
        ("tilix", ["-e"] + [" ".join(cmd)]),
        ("kitty", cmd),
        ("alacritty", ["-e"] + cmd),
        ("x-terminal-emulator", ["-e"] + cmd),
        ("xterm", ["-T", title, "-e"] + cmd),
    ]
    for term, args in cands:
        path = shutil.which(term)
        if path:
            subprocess.Popen([path] + args, env=env, start_new_session=True)
            return term
    return None


def desktop_notify(title: str, body: str):
    """Notification du bureau sous Linux (sous Windows, le toast interne suffit)."""
    if WINDOWS:
        return
    if MACOS:
        def esc(x):
            return x.replace("\\", "\\\\").replace('"', '\\"')
        try:
            subprocess.Popen(["osascript", "-e", 'display notification "%s" with title "ADB Pilot" subtitle "%s"'
                              % (esc(body), esc(title))])
        except OSError:
            pass
        return
    exe = shutil.which("notify-send")
    if exe:
        try:
            subprocess.Popen([exe, "-a", "ADB Pilot", "-i", "adbpilot", title, body], env=clean_env())
        except OSError:
            pass


def os_name() -> str:
    if WINDOWS:
        rel, ver = platform.release(), platform.version()
        try:
            if rel == "10" and int(ver.split(".")[2]) >= 22000:
                rel = "11"
        except (IndexError, ValueError):
            pass
        return "Windows %s (%s) %s" % (rel, ver, machine())
    if MACOS:
        return "macOS %s %s" % (platform.mac_ver()[0] or "?", machine())
    if hasattr(platform, "freedesktop_os_release"):
        try:
            return platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except OSError:
            pass
    return "Linux"


def host_cpu_ram() -> tuple[str, int]:
    """(modèle du processeur, RAM en Go arrondie) de l'ordinateur."""
    cpu, ram = "", 0
    if MACOS:
        def sysctl(k):
            try:
                return subprocess.run(["sysctl", "-n", k], capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                return ""
        cpu = sysctl("machdep.cpu.brand_string")
        mem = sysctl("hw.memsize")
        ram = round(int(mem) / 1073741824) if mem.isdigit() else 0
        return cpu, ram
    if WINDOWS:
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            ram = round(m.ullTotalPhys / 1073741824)
        except Exception:  # noqa: BLE001
            pass
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except Exception:  # noqa: BLE001
            cpu = platform.processor()
        return cpu, ram
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for ln in f:
                if ln.startswith("model name"):
                    cpu = ln.split(":", 1)[1].strip()
                    break
        with open("/proc/meminfo", encoding="utf-8") as f:
            ram = int(f.readline().split()[1]) // 1048576 + 1
    except Exception:  # noqa: BLE001
        pass
    return cpu, ram


_SSL_CTX = None


def ssl_context():
    """Contexte HTTPS : magasin du système + certifi s'il est embarqué (versions Windows / portables)."""
    global _SSL_CTX
    if _SSL_CTX is None:
        import ssl
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except Exception:  # noqa: BLE001
            pass
        _SSL_CTX = ctx
    return _SSL_CTX
