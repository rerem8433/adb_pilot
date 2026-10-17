"""Couche adb : exécution des commandes, appareils, paquets, lecture d'APK à distance."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .apkparse import RangeReader
from .config import DATA_DIR, config

BLOCK = 4096


def q(s: str) -> str:
    """Quote pour le shell Android (mksh/toybox)."""
    return "'" + str(s).replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# Localisation des binaires
# ---------------------------------------------------------------------------

def find_adb() -> str | None:
    p = config.get("adb_path") or ""
    if p and os.access(p, os.X_OK):
        return p
    c = DATA_DIR / "platform-tools" / "adb"
    if c.is_file() and os.access(c, os.X_OK):
        return str(c)
    w = shutil.which("adb")
    if w:
        return w
    c = DATA_DIR / "scrcpy" / "adb"
    if c.is_file() and os.access(c, os.X_OK):
        return str(c)
    return None


def find_scrcpy() -> str | None:
    p = config.get("scrcpy_path") or ""
    if p and os.access(p, os.X_OK):
        return p
    c = DATA_DIR / "scrcpy" / "scrcpy"
    if c.is_file() and os.access(c, os.X_OK):
        return str(c)
    return shutil.which("scrcpy")


def find_fastboot() -> str | None:
    adb = find_adb()
    if adb:
        c = Path(adb).with_name("fastboot")
        if c.is_file():
            return str(c)
    return shutil.which("fastboot")


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------

@dataclass
class Result:
    rc: int
    out: str
    err: str

    @property
    def ok(self):
        return self.rc == 0

    @property
    def text(self):
        return (self.out + ("\n" + self.err if self.err.strip() else "")).strip()


class Adb:
    def __init__(self):
        self.serial: str | None = None

    @property
    def path(self):
        return find_adb()

    def _base(self, serial=True):
        p = self.path
        if not p:
            raise FileNotFoundError("adb introuvable")
        base = [p]
        if serial and self.serial:
            base += ["-s", self.serial]
        return base

    def run(self, args, timeout=60, serial=True, input_bytes=None) -> Result:
        try:
            cp = subprocess.run(self._base(serial) + list(args), capture_output=True,
                                timeout=timeout, input=input_bytes)
        except FileNotFoundError as e:
            return Result(127, "", str(e))
        except subprocess.TimeoutExpired:
            return Result(124, "", "délai dépassé")
        return Result(cp.returncode, cp.stdout.decode("utf-8", "replace"),
                      cp.stderr.decode("utf-8", "replace"))

    def run_bytes(self, args, timeout=120, serial=True) -> bytes:
        cp = subprocess.run(self._base(serial) + list(args), capture_output=True, timeout=timeout)
        return cp.stdout

    def shell(self, cmd: str, timeout=60) -> Result:
        return self.run(["shell", cmd], timeout=timeout)

    def exec_out(self, cmd: str, timeout=120) -> bytes:
        return self.run_bytes(["exec-out", cmd], timeout=timeout)


adb = Adb()


# ---------------------------------------------------------------------------
# Appareils
# ---------------------------------------------------------------------------

@dataclass
class Device:
    serial: str
    state: str
    attrs: dict = field(default_factory=dict)

    @property
    def model(self):
        return self.attrs.get("model", "").replace("_", " ")

    @property
    def is_network(self):
        return ":" in self.serial or self.serial.startswith("adb-")

    @property
    def label(self):
        m = self.model or self.serial
        return m


def list_devices() -> list[Device]:
    r = adb.run(["devices", "-l"], timeout=10, serial=False)
    devs = []
    for line in r.out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, rest = parts[0], parts[1:]
        state_words = []
        attrs = {}
        for w in rest:
            if re.match(r"^[a-z_]+:\S", w) and not w.startswith(("http", "https")):
                k, _, v = w.partition(":")
                attrs[k] = v
            elif not attrs:
                state_words.append(w)
        state = " ".join(state_words) or rest[0]
        devs.append(Device(serial, state, attrs))
    return devs


PROPS = {
    "brand": "ro.product.brand",
    "manufacturer": "ro.product.manufacturer",
    "model": "ro.product.model",
    "device": "ro.product.device",
    "serial": "ro.serialno",
    "board": "ro.board.platform",
    "hardware": "ro.hardware",
    "abi": "ro.product.cpu.abi",
    "release": "ro.build.version.release",
    "sdk": "ro.build.version.sdk",
    "build": "ro.build.display.id",
    "fingerprint": "ro.build.fingerprint",
    "security_patch": "ro.build.version.security_patch",
    "soc_manufacturer": "ro.soc.manufacturer",
    "soc_model": "ro.soc.model",
    "product_board": "ro.product.board",
    "chipname": "ro.chipname",
    "vendor_sdk": "ro.vendor.build.version.sdk",
    "vndk": "ro.vndk.version",
}


def device_info() -> dict:
    r = adb.shell("getprop", timeout=15)
    props = dict(re.findall(r"^\[([^\]]+)\]: \[(.*)\]$", r.out, re.M))
    info = {k: props.get(v, "") for k, v in PROPS.items()}
    if not info["serial"]:
        info["serial"] = adb.serial or ""
    return info


SDK_RELEASE = {14: "4.0", 15: "4.0.3", 16: "4.1", 17: "4.2", 18: "4.3", 19: "4.4", 20: "4.4W",
               21: "5.0", 22: "5.1", 23: "6.0", 24: "7.0", 25: "7.1", 26: "8.0", 27: "8.1",
               28: "9", 29: "10", 30: "11", 31: "12", 32: "12L", 33: "13", 34: "14", 35: "15",
               36: "16", 37: "17"}

AMLOGIC = {"gxbb": "S905", "gxl": "S905X/S905W/S905L", "gxm": "S912", "g12a": "S905X2",
           "g12b": "S922X/A311D", "sm1": "S905X3", "sc2": "S905X4", "s4": "S905Y4/S905W2",
           "t5d": "T962D", "txlx": "T962", "tm2": "T962E2", "s5": "S905X5"}
ALLWINNER = {"cupid": "H616/H618", "petrel": "H6", "dolphin": "H3", "sun50iw9p1": "H616/H618/H313",
             "sun50iw6p1": "H6", "sun50iw1p1": "A64/H64", "sun50iw2p1": "H5", "sun8iw7p1": "H3",
             "sun50iw12p1": "H713", "sun50iw10p1": "A133"}
QUALCOMM = {"msm8917": "Snapdragon 425", "msm8937": "Snapdragon 430", "msm8940": "Snapdragon 435",
            "msm8953": "Snapdragon 625", "msm8996": "Snapdragon 820", "msm8998": "Snapdragon 835",
            "sdm450": "Snapdragon 450", "sdm660": "Snapdragon 660", "sdm710": "Snapdragon 710",
            "sdm845": "Snapdragon 845", "msmnile": "Snapdragon 855", "kona": "Snapdragon 865",
            "lahaina": "Snapdragon 888", "taro": "Snapdragon 8 Gen 1", "kalama": "Snapdragon 8 Gen 2",
            "pineapple": "Snapdragon 8 Gen 3", "trinket": "Snapdragon 665", "bengal": "Snapdragon 662/460",
            "lito": "Snapdragon 765", "atoll": "Snapdragon 720G", "holi": "Snapdragon 480",
            "sm6150": "Snapdragon 675", "sm7150": "Snapdragon 730"}


def soc_name(info: dict, cpuinfo: str = "") -> str:
    plat = (info.get("board") or "").lower()
    hw = (info.get("hardware") or "").lower()
    man, model = info.get("soc_manufacturer") or "", info.get("soc_model") or ""
    m = re.search(r"^Hardware\s*:\s*(.+)$", cpuinfo, re.M)
    hwline = m.group(1).strip() if m else ""
    if plat in AMLOGIC or hw == "amlogic" or "amlogic" in hwline.lower():
        return "Amlogic %s" % AMLOGIC.get(plat, model or plat.upper())
    if plat.startswith("rk") or hw.startswith("rk") or "rockchip" in hwline.lower():
        chip = plat if plat.startswith("rk3") else (re.search(r"rk\d+", hwline.lower()) or [plat or hw])[0]
        return "Rockchip %s" % chip.upper()
    if plat in ALLWINNER or hw.startswith("sun") or "allwinner" in (man + hwline).lower():
        return "Allwinner %s" % ALLWINNER.get(plat, ALLWINNER.get(hw, model or plat or hw))
    if re.match(r"mt\d+", plat) or re.match(r"mt\d+", hw) or man.lower().startswith("mediatek"):
        return "MediaTek %s" % (model or (plat if plat.startswith("mt") else hw)).upper()
    if plat in QUALCOMM or hw == "qcom" or man.upper() in ("QTI", "QUALCOMM"):
        name = QUALCOMM.get(plat)
        return "Qualcomm %s%s" % (name or (model or plat).upper(), " (%s)" % model if model and name else "")
    if plat.startswith("exynos") or hw.startswith("exynos") or "samsung" in man.lower():
        chip = plat if plat.startswith("exynos") else (hw if hw.startswith("exynos") else model)
        return "Samsung %s" % chip.replace("exynos", "Exynos ").strip()
    if plat.startswith(("ums", "sp", "sc9")) or "unisoc" in (man + hwline).lower():
        return "Unisoc %s" % (model or plat).upper()
    if plat.startswith(("tegra", "t210")) or hw.startswith(("tegra", "foster", "darcy")):
        return "NVIDIA Tegra X1"
    if man and model:
        return "%s %s" % (man, model)
    return hwline or plat or hw or "?"


def _round_up(value, steps):
    for st in steps:
        if value <= st:
            return st
    return round(value)


def _fmt_num(x):
    return ("%g" % x).replace(".", ",")


def _real_sdk():
    r = adb.shell("stat -c %s /system/framework/framework-res.apk", timeout=10)
    size = r.out.strip()
    if not size.isdigit():
        return None, None
    from .apkparse import RemoteZip, parse_axml
    z = RemoteZip(AdbRangeReader("/system/framework/framework-res.apk", int(size), adb.serial))
    man = z.read("AndroidManifest.xml")
    if not man:
        return None, None
    for e in parse_axml(man):
        if e.tag == "manifest":
            a = e.attrs
            code = None
            for k in ("platformBuildVersionCode", "compileSdkVersion", "versionCode"):
                if k in a:
                    t, d, sv = a[k]
                    code = d if t == 0x10 else (int(sv) if sv and sv.isdigit() else None)
                    if code and not (14 <= code <= 60):
                        code = None
                    if code:
                        break
            name = None
            for k in ("platformBuildVersionName", "compileSdkVersionCodename", "versionName"):
                if k in a and a[k][2]:
                    name = a[k][2]
                    break
            return code, name
    return None, None


def device_specs(info: dict) -> dict:
    script = ("head -1 /proc/meminfo; echo @@DF; df -k /data 2>/dev/null || df /data; "
              "echo @@CPU; grep -iE '^(Hardware|model name|Processor)' /proc/cpuinfo | head -3; "
              "echo @@NCPU; ls -d /sys/devices/system/cpu/cpu[0-9]* 2>/dev/null | wc -l; "
              "echo @@FREQ; cat /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq 2>/dev/null")
    out = adb.shell(script, timeout=20).out
    sec = {"MEM": ""}
    cur = "MEM"
    for ln in out.splitlines():
        if ln.startswith("@@"):
            cur = ln[2:].strip()
            sec[cur] = ""
        else:
            sec[cur] = sec.get(cur, "") + ln + "\n"
    sp: dict = {}
    m = re.search(r"MemTotal:\s+(\d+)", sec.get("MEM", ""))
    if m:
        gb = int(m.group(1)) / 1048576
        sp["ram_exact"] = "%s Go (MemTotal)" % _fmt_num(round(gb, 2))
        sp["ram_gb"] = _fmt_num(_round_up(gb * 1.0, [0.5, 1, 1.5, 2, 3, 4, 6, 8, 10, 12, 16, 18, 24, 32]))
    df = sec.get("DF", "")
    total_kb = None
    for ln in df.splitlines()[1:]:
        parts = ln.split()
        if len(parts) >= 2:
            if parts[1].isdigit():
                total_kb = int(parts[1])
            else:
                mm = re.match(r"([\d.,]+)([KMGT])", parts[1])
                if mm:
                    mult = {"K": 1, "M": 1024, "G": 1048576, "T": 1073741824}[mm.group(2)]
                    total_kb = float(mm.group(1).replace(",", ".")) * mult
            if total_kb:
                break
    if total_kb:
        gb = total_kb / 1048576
        sp["storage_exact"] = "%s Go utilisables" % _fmt_num(round(gb, 1))
        sp["storage_gb"] = _fmt_num(_round_up(gb, [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]))
    cpuinfo = sec.get("CPU", "")
    sp["soc"] = soc_name(info, cpuinfo)
    n = sec.get("NCPU", "").strip()
    sp["cores"] = int(n) if n.isdigit() else None
    freqs = [int(x) for x in sec.get("FREQ", "").split() if x.isdigit()]
    sp["max_ghz"] = round(max(freqs) / 1e6, 2) if freqs else None
    try:
        code, name = _real_sdk()
    except Exception:  # noqa: BLE001
        code, name = None, None
    if not code:
        for k in ("vendor_sdk", "vndk"):
            v = info.get(k) or ""
            if v.isdigit():
                code = int(v)
                break
    claimed_sdk = info.get("sdk") or ""
    sp["claimed"] = info.get("release") or "?"
    sp["claimed_sdk"] = claimed_sdk or "?"
    if code:
        sp["sdk"] = code
        rel = SDK_RELEASE.get(code)
        sp["android"] = rel or (name if name and name[0].isdigit() else str(code))
        sp["fake"] = claimed_sdk.isdigit() and int(claimed_sdk) != code
    else:
        sp["sdk"] = claimed_sdk or "?"
        sp["android"] = info.get("release") or "?"
        sp["fake"] = False
    return sp


def ram_info():
    r = adb.shell("cat /proc/meminfo", timeout=10)
    vals = dict(re.findall(r"^(\w+):\s+(\d+)", r.out, re.M))
    total = int(vals.get("MemTotal", 0)) // 1024
    avail = int(vals.get("MemAvailable", vals.get("MemFree", 0))) // 1024
    return total - avail, total


def device_ip():
    r = adb.shell("ip -o -4 addr show 2>/dev/null; ip route 2>/dev/null", timeout=10)
    for iface in ("wlan0", "eth0", "wlan1"):
        m = re.search(r"\d+:\s+%s\s+inet\s+(\d+\.\d+\.\d+\.\d+)" % iface, r.out)
        if m:
            return m.group(1)
    m = re.search(r"src (\d+\.\d+\.\d+\.\d+)", r.out)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Paquets
# ---------------------------------------------------------------------------

@dataclass
class Package:
    name: str
    path: str = ""
    size: int = 0
    system: bool = False
    disabled: bool = False
    deleted: bool = False
    label: str | None = None
    icon: object = None  # QImage
    version: str | None = None

    @property
    def display(self):
        return self.label or self.name


LIST_SCRIPT = (
    "echo @@ALL; pm list packages -f -u 2>/dev/null; "
    "echo @@INST; pm list packages 2>/dev/null; "
    "echo @@SYS; pm list packages -s -u 2>/dev/null; "
    "echo @@DIS; pm list packages -d 2>/dev/null; "
    "echo @@SIZE; pm list packages -f -u 2>/dev/null | while read -r l; do "
    "p=${l#package:}; p=${p%=*}; echo \"$(stat -c %s \"$p\" 2>/dev/null)|$p\"; done"
)


def list_packages() -> list[Package]:
    r = adb.shell(LIST_SCRIPT, timeout=120)
    sections: dict[str, list[str]] = {}
    cur = None
    for line in r.out.splitlines():
        line = line.strip()
        if line.startswith("@@"):
            cur = line[2:]
            sections[cur] = []
        elif cur and line:
            sections[cur].append(line)

    def names(sec):
        return {ln[8:] for ln in sections.get(sec, []) if ln.startswith("package:")}

    pkgs: dict[str, Package] = {}
    for ln in sections.get("ALL", []):
        if not ln.startswith("package:"):
            continue
        path, _, name = ln[8:].rpartition("=")
        if not name:
            continue
        pkgs[name] = Package(name=name, path=path)
    sizes = {}
    for ln in sections.get("SIZE", []):
        sz, _, path = ln.partition("|")
        if sz.isdigit():
            sizes[path] = int(sz)
    inst, sysp, dis = names("INST"), names("SYS"), names("DIS")
    for p in pkgs.values():
        p.size = sizes.get(p.path, 0)
        p.system = p.name in sysp or p.path.startswith(("/system", "/product", "/vendor",
                                                        "/system_ext", "/apex", "/odm"))
        p.disabled = p.name in dis
        p.deleted = p.name not in inst
    return sorted(pkgs.values(), key=lambda p: p.name)


def package_paths(name) -> list[str]:
    r = adb.shell("pm path " + q(name), timeout=20)
    return [ln[8:].strip() for ln in r.out.splitlines() if ln.startswith("package:")]


def dumpsys_package(name) -> str:
    return adb.shell("dumpsys package " + q(name), timeout=30).out


def parse_permissions(dump: str, name: str):
    """Retourne liste de (permission, accordée, runtime)."""
    # Ne garder que la section du paquet demandé
    m = re.search(r"Package \[%s\]" % re.escape(name), dump)
    sect = dump[m.start():] if m else dump
    requested = []
    granted: dict[str, bool] = {}
    runtime = set()
    mode = None
    for line in sect.splitlines():
        s = line.strip()
        if s.startswith("Package [") and not s.startswith("Package [%s]" % name) and requested:
            break
        if s == "requested permissions:":
            mode = "req"
            continue
        if s == "install permissions:":
            mode = "inst"
            continue
        if s == "runtime permissions:":
            mode = "rt"
            continue
        if s.endswith(":") and not s.startswith("android.") and "permission" not in s:
            if mode in ("req", "inst", "rt") and not re.match(r"^[\w.]+:", s):
                mode = None
        if mode == "req":
            if re.match(r"^[\w.]+(?:: restricted=\w+)?$", s):
                requested.append(s.split(":")[0])
            elif s:
                mode = None
        elif mode in ("inst", "rt"):
            mm = re.match(r"^([\w.]+): granted=(true|false)", s)
            if mm:
                granted[mm.group(1)] = mm.group(2) == "true"
                if mode == "rt":
                    runtime.add(mm.group(1))
            elif s and not s.startswith("User "):
                mode = None
    seen = []
    for p in requested + [k for k in granted if k not in requested]:
        if p not in seen:
            seen.append(p)
    return [(p, granted.get(p, False), p in runtime) for p in seen]


def parse_app_info(dump: str, name: str) -> dict:
    m = re.search(r"Package \[%s\]" % re.escape(name), dump)
    sect = dump[m.start():] if m else dump
    keys = {
        "versionName": r"versionName=(\S+)",
        "versionCode": r"versionCode=(\d+)",
        "targetSdk": r"targetSdk=(\d+)",
        "minSdk": r"minSdk=(\d+)",
        "codePath": r"codePath=(\S+)",
        "dataDir": r"dataDir=(\S+)",
        "firstInstallTime": r"firstInstallTime=([^\n]+)",
        "lastUpdateTime": r"lastUpdateTime=([^\n]+)",
        "installer": r"installerPackageName=(\S+)",
        "uid": r"(?:userId|appId)=(\d+)",
        "primaryCpuAbi": r"primaryCpuAbi=(\S+)",
    }
    return {k: (re.search(rx, sect).group(1).strip() if re.search(rx, sect) else "")
            for k, rx in keys.items()}


# ---------------------------------------------------------------------------
# Lecture d'APK à distance (dd par blocs, plusieurs plages en un appel)
# ---------------------------------------------------------------------------

class AdbRangeReader(RangeReader):
    def __init__(self, path: str, size: int, serial: str | None = None):
        self.path = path
        self.size = size
        self.serial = serial

    def read_ranges(self, ranges):
        cmds = []
        plan = []
        for off, ln in ranges:
            off = max(0, off)
            end = min(self.size, off + ln)
            if end <= off:
                plan.append((0, 0, 0))
                continue
            s = off // BLOCK
            e = (end + BLOCK - 1) // BLOCK
            expected = min(e * BLOCK, self.size) - s * BLOCK
            cmds.append("dd if=%s bs=%d skip=%d count=%d 2>/dev/null" % (q(self.path), BLOCK, s, e - s))
            plan.append((expected, off - s * BLOCK, end - off))
        if not cmds:
            return [b"" for _ in ranges]
        args = ["exec-out", "; ".join(cmds)]
        base = [find_adb() or "adb"]
        if self.serial:
            base += ["-s", self.serial]
        data = subprocess.run(base + args, capture_output=True, timeout=180).stdout
        out = []
        p = 0
        for expected, rel, n in plan:
            chunk = data[p:p + expected]
            p += expected
            out.append(chunk[rel:rel + n])
        return out


# ---------------------------------------------------------------------------
# Actions sur les paquets
# ---------------------------------------------------------------------------

def act_disable(p: Package):
    return adb.shell("pm disable-user --user 0 " + q(p.name))


def act_enable(p: Package):
    return adb.shell("pm enable " + q(p.name))


def act_uninstall(p: Package):
    keep = config.get("uninstall_keep_data", True)
    if p.system:
        return adb.shell("pm uninstall %s--user 0 %s" % ("-k " if keep else "", q(p.name)))
    return adb.shell("pm uninstall %s%s" % ("-k " if keep else "", q(p.name)))


def act_restore(p: Package):
    r = adb.shell("cmd package install-existing --user 0 " + q(p.name))
    if "inaccessible or not found" in r.out or not r.ok or "Unknown command" in r.out:
        r = adb.shell("pm install-existing --user 0 " + q(p.name))
    return r


def act_force_stop(p: Package):
    return adb.shell("am force-stop " + q(p.name))


def act_clear(p: Package):
    return adb.shell("pm clear " + q(p.name))


def act_clear_cache(p: Package):
    """Android 14+ : pm clear --cache-only. Renvoie rc=2 si non supporté."""
    r = adb.shell("pm clear --cache-only " + q(p.name))
    low = r.text.lower()
    if r.ok and "success" in low:
        return r
    if "unknown" in low or "error" in low or "usage" in low or not r.ok or "exception" in low:
        return Result(2, r.out, r.err or "cache-only non supporté")
    return r


def trim_all_caches():
    return adb.shell("pm trim-caches 999999M")


def act_launch(p: Package):
    return adb.shell("monkey -p %s -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || "
                     "monkey -p %s -c android.intent.category.LEANBACK_LAUNCHER 1" % (q(p.name), q(p.name)))


def extract_apk(p: Package, dest_dir: str) -> tuple[bool, str]:
    paths = package_paths(p.name) or ([p.path] if p.path else [])
    if not paths:
        return False, "chemin introuvable"
    base = (p.label or p.name).replace("/", "_")
    dest = Path(dest_dir)
    if len(paths) == 1:
        target = dest / f"{base}_{p.name}.apk"
        r = adb.run(["pull", paths[0], str(target)], timeout=600)
        return r.ok, str(target) if r.ok else r.text
    folder = dest / f"{base}_{p.name}"
    folder.mkdir(parents=True, exist_ok=True)
    for sp in paths:
        r = adb.run(["pull", sp, str(folder / Path(sp).name)], timeout=600)
        if not r.ok:
            return False, r.text
    return True, str(folder)


def _safe(s: str) -> str:
    return re.sub(r"[^\w.()+]+", "-", s.strip()).strip("-") or "app"


def backup_apk(p: Package, device_label: str) -> tuple[bool, str]:
    """Sauvegarde dans ~/ADB_Pilot/apps/<appareil>/nomappli_(paquet)_version.apk (.apks si split)."""
    from .config import user_dir
    paths = package_paths(p.name) or ([p.path] if p.path else [])
    if not paths:
        return False, "chemin introuvable"
    version = p.version
    if not version:
        m = re.search(r"versionName=(\S+)", dumpsys_package(p.name))
        version = m.group(1) if m else "inconnue"
    dest = user_dir("apps") / re.sub(r"[^\w.\-]+", "_", device_label).strip("_")
    dest.mkdir(parents=True, exist_ok=True)
    base = "%s_(%s)_%s" % (_safe(p.label or p.name.split(".")[-1]), p.name, _safe(version))
    if len(paths) == 1:
        target = dest / (base + ".apk")
        r = adb.run(["pull", paths[0], str(target)], timeout=900)
        return r.ok, str(target) if r.ok else r.text
    import tempfile
    import zipfile
    tmp = Path(tempfile.mkdtemp(prefix="adbpilot_bk_"))
    try:
        for sp in paths:
            r = adb.run(["pull", sp, str(tmp / Path(sp).name)], timeout=900)
            if not r.ok:
                return False, r.text
        target = dest / (base + ".apks")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as z:
            for f in sorted(tmp.iterdir()):
                z.write(f, f.name)
        return True, str(target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def grant(pkg, perm, on=True):
    return adb.shell("pm %s %s %s" % ("grant" if on else "revoke", q(pkg), q(perm)))


# ---------------------------------------------------------------------------
# Installation (APK, split, XAPK/APKS/APKM)
# ---------------------------------------------------------------------------

def install_flags():
    f = []
    if config.get("install_replace", True):
        f.append("-r")
    if config.get("install_grant", True):
        f.append("-g")
    if config.get("install_downgrade"):
        f.append("-d")
    return f


def install_apks(apks: list[str]) -> Result:
    flags = install_flags()
    if len(apks) == 1:
        r = adb.run(["install"] + flags + apks, timeout=900)
        if not r.ok and "-g" in flags and "Unknown option" in r.text:
            r = adb.run(["install"] + [x for x in flags if x != "-g"] + apks, timeout=900)
        return r
    return adb.run(["install-multiple"] + flags + apks, timeout=1200)


def install_bundle(path: str, log=lambda s: None) -> Result:
    import tempfile
    import zipfile
    tmp = tempfile.mkdtemp(prefix="adbpilot_")
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
    except (zipfile.BadZipFile, RuntimeError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return Result(1, "", "Archive illisible (APKM chiffré ?) : %s" % e)
    try:
        apks = sorted(str(p) for p in Path(tmp).rglob("*.apk"))
        if not apks:
            return Result(1, "", "Aucun APK dans l'archive")
        # base.apk en premier
        apks.sort(key=lambda s: (0 if Path(s).name in ("base.apk",) else 1, s))
        r = install_apks(apks)
        obb_root = Path(tmp) / "Android" / "obb"
        if r.ok and obb_root.is_dir():
            for d in obb_root.iterdir():
                if d.is_dir():
                    log("Copie des OBB : %s" % d.name)
                    adb.run(["push", str(d), "/sdcard/Android/obb/"], timeout=3600)
        return r
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def split_cmd(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()
