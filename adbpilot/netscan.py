"""Détection des appareils Android sur le réseau local (port ADB + annonces mDNS), avec leur nom.

Sources du nom, de la plus précise à la moins précise :
  1. bannière ADB (box sans autorisation ADB : modèle exact, sans rien afficher sur la TV) ;
  2. mDNS : Google Cast (« fn= »), télécommande Android TV, débogage sans fil Android 11+ ;
  3. historique des connexions d'ADB Pilot ;
  4. nom d'hôte du réseau (DNS inverse : nom donné par la box internet).
"""
from __future__ import annotations

import ipaddress
import re
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

A_CNXN, A_AUTH = 0x4E584E43, 0x48545541
A_OPEN, A_OKAY, A_CLSE, A_WRTE = 0x4E45504F, 0x59414B4F, 0x45534C43, 0x45545257
MDNS_GROUP, MDNS_PORT = "224.0.0.251", 5353
MDNS_SERVICES = ("_adb-tls-connect._tcp.local", "_adb._tcp.local", "_googlecast._tcp.local",
                 "_androidtvremote2._tcp.local")


@dataclass
class Found:
    ip: str
    port: int | None = None          # port ADB joignable
    adb: str = ""                    # "open" (bannière lue), "trusted" (cet ordinateur déjà autorisé),
    #                                  "auth" (autorisation requise), "tls" (Android 11+),
    #                                  "port" (port ouvert mais pas de réponse ADB : autre service), ""
    name: str = ""                   # nom affiché
    model: str = ""                  # modèle lu dans la bannière ADB
    details: list = field(default_factory=list)  # infos secondaires (Cast, hôte réseau…)
    sources: set = field(default_factory=set)

    @property
    def connectable(self):
        return self.port is not None and self.adb in ("open", "trusted", "auth", "tls")


# ---------------------------------------------------------------------------
# Réseau local
# ---------------------------------------------------------------------------

COMMON_NETS = ("192.168.0.0/24", "192.168.1.0/24", "192.168.2.0/24")


def _primary_ip() -> str | None:
    """Adresse de la carte qui porte la route vers Internet (la vraie carte, pas Hyper-V/VMware/WSL)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # aucun paquet n'est envoyé (UDP)
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _usable(ip) -> bool:
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return a.is_private and not a.is_loopback and not a.is_link_local


def local_networks() -> list[ipaddress.IPv4Network]:
    """Réseau /24 de la carte principale (celle qui a la passerelle). Les cartes virtuelles
    (Hyper-V, WSL, VMware, VirtualBox) ne sont prises qu'à défaut de carte principale."""
    ip = _primary_ip()
    if ip and _usable(ip):
        return [ipaddress.IPv4Network(ip + "/24", strict=False)]
    nets = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            a = info[4][0]
            if _usable(a):
                n = ipaddress.IPv4Network(a + "/24", strict=False)
                if n not in nets:
                    nets.append(n)
    except OSError:
        pass
    return nets


def parse_networks(text: str) -> list[ipaddress.IPv4Network]:
    """« 192.168.1.0/24, 10.0.0.x 172.16.5 » -> réseaux (au plus /22 pour garder un scan rapide)."""
    out = []
    for tok in re.split(r"[\s,;]+", text or ""):
        tok = tok.strip().lower().replace(".x", ".0").replace(".*", ".0")
        if not tok:
            continue
        if re.fullmatch(r"\d+\.\d+\.\d+", tok):
            tok += ".0"
        if "/" not in tok:
            tok += "/24"
        try:
            n = ipaddress.IPv4Network(tok, strict=False)
        except ValueError:
            continue
        if n.prefixlen < 22:
            n = ipaddress.IPv4Network("%s/22" % n.network_address, strict=False)
        if n not in out:
            out.append(n)
    return out


def scan_networks(common=True, extra="", history=()) -> list[ipaddress.IPv4Network]:
    """Réseaux à analyser : celui de l'ordinateur, puis les réseaux habituels des box
    (192.168.0/1/2.x, joignables via le routeur), ceux de l'historique et ceux saisis à la main."""
    nets = list(local_networks())
    cands = []
    if common:
        cands += [ipaddress.IPv4Network(n) for n in COMMON_NETS]
    for ip in history:
        ip = str(ip).split(":")[0]
        if _usable(ip):
            cands.append(ipaddress.IPv4Network(ip + "/24", strict=False))
    cands += parse_networks(extra)
    for n in cands:
        if not any(n.subnet_of(x) for x in nets):
            nets.append(n)
    return nets


def _port_open(ip, port, timeout=0.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Bannière ADB : CNXN envoyé, réponse CNXN (modèle) ou AUTH (autorisation requise).
# On n'envoie jamais de clé : aucune demande ne s'affiche sur l'appareil.
# ---------------------------------------------------------------------------

def _adb_msg(cmd, a0, a1, data=b""):
    return struct.pack("<6I", cmd, a0, a1, len(data), sum(data) & 0xFFFFFFFF, cmd ^ 0xFFFFFFFF) + data


def _recv(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def adb_banner(ip, port=5555, timeout=1.5) -> tuple[str, dict]:
    """("open", props) si l'appareil répond sans autorisation, ("auth", {}) sinon, ("", {}) si muet."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(_adb_msg(A_CNXN, 0x01000001, 256 * 1024, b"host::\0"))
            head = _recv(s, 24)
            if len(head) < 24:
                return "", {}
            cmd, _a0, _a1, ln, _crc, _magic = struct.unpack("<6I", head)
            if cmd == A_AUTH:
                return "auth", {}
            if cmd != A_CNXN:
                return "", {}
            payload = _recv(s, min(ln, 64 * 1024)).decode("utf-8", "replace").rstrip("\0")
    except OSError:
        return "", {}
    # « device::ro.product.name=x;ro.product.model=y;ro.product.device=z;features=… »
    props = {}
    for part in payload.split("::", 1)[-1].split(";"):
        k, _sep, v = part.partition("=")
        if k and v:
            props[k.strip()] = v.strip()
    return "open", props


# ---------------------------------------------------------------------------
# Nom donné à l'appareil (Paramètres → À propos → Nom), lu avec la clé adb de l'ordinateur.
# La clé n'est utilisée que si l'appareil l'a DÉJÀ autorisée : on ne propose jamais la clé
# publique, donc aucune demande d'autorisation ne s'affiche sur l'écran de l'appareil.
# ---------------------------------------------------------------------------

_SHA1_PREFIX = bytes.fromhex("3021300906052b0e03021a05000414")
_KEY = None


def _der(data, off):
    """-> (tag, contenu, offset suivant) d'un élément DER."""
    tag, ln = data[off], data[off + 1]
    off += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(data[off:off + n], "big")
        off += n
    return tag, data[off:off + ln], off + ln


def _load_adbkey():
    """(n, d) de ~/.android/adbkey (PEM PKCS#8 ou PKCS#1), ou None."""
    global _KEY
    if _KEY is not None:
        return _KEY or None
    _KEY = False
    import base64
    import os
    for base in (os.environ.get("ANDROID_USER_HOME"), os.path.join(os.path.expanduser("~"), ".android")):
        if not base:
            continue
        p = os.path.join(base, "adbkey")
        try:
            pem = open(p, encoding="ascii", errors="ignore").read()
            der = base64.b64decode("".join(l for l in pem.splitlines() if l and not l.startswith("-----")))
            _t, seq, _o = _der(der, 0)
            # PKCS#8 : SEQUENCE { INTEGER 0, SEQUENCE algo, OCTET STRING { RSAPrivateKey } }
            _t, _v, o = _der(seq, 0)
            t2, c2, o2 = _der(seq, o)
            if t2 == 0x30:
                _t, inner, _o = _der(seq, o2)
                _t, seq, _o = _der(inner, 0)
            _t, _v, o = _der(seq, 0)          # version
            _t, n, o = _der(seq, o)           # modulus
            _t, _e, o = _der(seq, o)          # exposant public
            _t, d, o = _der(seq, o)           # exposant privé
            _KEY = (int.from_bytes(n, "big"), int.from_bytes(d, "big"))
            return _KEY
        except (OSError, ValueError, IndexError):
            continue
    return None


def _sign(key, token):
    n, d = key
    k = (n.bit_length() + 7) // 8
    t = _SHA1_PREFIX + token
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def _read_msg(s):
    head = _recv(s, 24)
    if len(head) < 24:
        raise OSError("fin")
    cmd, a0, a1, ln, _crc, _magic = struct.unpack("<6I", head)
    data = _recv(s, ln) if ln else b""
    if len(data) < ln:
        raise OSError("fin")
    return cmd, a0, a1, data


def adb_device_name(ip, port=5555, timeout=2.0) -> tuple[bool, str]:
    """(autorisé, nom personnalisé) : nom = settings global device_name si l'appareil autorise déjà
    cet ordinateur, sinon (False, "")."""
    key = _load_adbkey()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall(_adb_msg(A_CNXN, 0x01000001, 256 * 1024, b"host::\0"))
            signed = False
            while True:
                cmd, a0, _a1, data = _read_msg(s)
                if cmd == A_CNXN:
                    break
                if cmd != A_AUTH or a0 != 1 or key is None or signed:
                    return False, ""  # pas autorisé : on s'arrête là, sans proposer la clé (aucune fenêtre sur l'écran)
                s.sendall(_adb_msg(A_AUTH, 2, 0, _sign(key, data)))
                signed = True
            s.sendall(_adb_msg(A_OPEN, 1, 0, b"shell:settings get global device_name\0"))
            out = b""
            remote = 0
            while True:
                cmd, a0, _a1, data = _read_msg(s)
                if cmd == A_OKAY:
                    remote = a0
                elif cmd == A_WRTE:
                    out += data
                    s.sendall(_adb_msg(A_OKAY, 1, a0))
                elif cmd == A_CLSE:
                    break
            if remote:
                try:
                    s.sendall(_adb_msg(A_CLSE, 1, remote))
                except OSError:
                    pass
    except (OSError, struct.error):
        return False, ""
    name = out.decode("utf-8", "replace").strip()
    return True, ("" if name.lower() in ("", "null") or "\n" in name or len(name) > 64 else name)


# ---------------------------------------------------------------------------
# mDNS (requête PTR multidiffusion, réponses lues pendant ~1,5 s)
# ---------------------------------------------------------------------------

def _qname(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"


def _read_name(data, off, depth=0):
    labels = []
    while off < len(data):
        ln = data[off]
        if ln == 0:
            return ".".join(labels), off + 1
        if ln & 0xC0 == 0xC0:
            ptr = ((ln & 0x3F) << 8) | data[off + 1]
            if depth < 10:
                labels.append(_read_name(data, ptr, depth + 1)[0])
            return ".".join(x for x in labels if x), off + 2
        labels.append(data[off + 1:off + 1 + ln].decode("utf-8", "replace"))
        off += 1 + ln
    return ".".join(labels), off


def _parse_mdns(data):
    """-> liste de (type, nom, valeur) pour les enregistrements PTR, SRV, TXT, A."""
    out = []
    try:
        _id, _fl, qd, an, ns, ar = struct.unpack("!6H", data[:12])
        off = 12
        for _i in range(qd):
            _n, off = _read_name(data, off)
            off += 4
        for _i in range(an + ns + ar):
            name, off = _read_name(data, off)
            rtype, _cls, _ttl, rdlen = struct.unpack("!HHIH", data[off:off + 10])
            off += 10
            rd = data[off:off + rdlen]
            if rtype == 12:  # PTR
                out.append(("PTR", name, _read_name(data, off)[0]))
            elif rtype == 33:  # SRV
                port = struct.unpack("!H", rd[4:6])[0]
                out.append(("SRV", name, (_read_name(data, off + 6)[0], port)))
            elif rtype == 16:  # TXT
                txt, p = {}, 0
                while p < len(rd):
                    ln = rd[p]
                    k, _s, v = rd[p + 1:p + 1 + ln].decode("utf-8", "replace").partition("=")
                    txt[k] = v
                    p += 1 + ln
                out.append(("TXT", name, txt))
            elif rtype == 1 and rdlen == 4:  # A
                out.append(("A", name, socket.inet_ntoa(rd)))
            off += rdlen
    except (struct.error, IndexError, OSError):
        pass
    return out


def mdns_browse(timeout=1.5) -> list[dict]:
    """Instances trouvées : {service, instance, host, ip, port, txt}."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.bind(("", 0))
        s.settimeout(0.2)
    except OSError:
        return []
    q = struct.pack("!6H", 0, 0, len(MDNS_SERVICES), 0, 0, 0)
    for svc in MDNS_SERVICES:
        q += _qname(svc) + struct.pack("!HH", 12, 0x8001)  # PTR, réponse unicast demandée
    recs = []
    end = time.time() + timeout
    try:
        s.sendto(q, (MDNS_GROUP, MDNS_PORT))
        while time.time() < end:
            try:
                data, _addr = s.recvfrom(9000)
            except socket.timeout:
                continue
            recs += _parse_mdns(data)
    except OSError:
        pass
    finally:
        s.close()
    ptr = [(n, v) for t, n, v in recs if t == "PTR"]
    srv = {n: v for t, n, v in recs if t == "SRV"}
    txt = {n: v for t, n, v in recs if t == "TXT"}
    a = {n: v for t, n, v in recs if t == "A"}
    out = []
    for service, inst in ptr:
        if service not in MDNS_SERVICES:
            continue
        host, port = srv.get(inst, ("", None))
        out.append({"service": service, "instance": inst[:-len(service) - 1] if inst.endswith(service) else inst,
                    "host": host, "ip": a.get(host, ""), "port": port, "txt": txt.get(inst, {})})
    return out


# ---------------------------------------------------------------------------
# Scan complet
# ---------------------------------------------------------------------------

def _nice_model(props):
    model = props.get("ro.product.model") or props.get("ro.product.name") or ""
    return model.replace("_", " ").strip()


def scan(port=5555, known_names=None, progress=None, stop=lambda: False, nets=None) -> list[Found]:
    """progress(n, total, found_list) est appelé pendant le scan (depuis un fil de travail)."""
    known_names = known_names or {}
    nets = nets if nets is not None else local_networks()
    hosts = list(dict.fromkeys(str(h) for n in nets for h in n.hosts()))  # sans doublon, ordre conservé
    ports = [port] + ([5555] if port != 5555 else [])
    found: dict[str, Found] = {}
    total = len(hosts) + 1
    done = [0]

    def probe(ip):
        if stop():
            return
        for p in ports:
            if _port_open(ip, p):
                f = found.setdefault(ip, Found(ip))
                f.port = p
                f.adb = "auth"
                break
        done[0] += 1
        if progress and done[0] % 8 == 0:
            progress(done[0], total, list(found.values()))

    with ThreadPoolExecutor(max_workers=128) as ex:
        mdns_future = ex.submit(mdns_browse, 2.0)
        list(ex.map(probe, hosts))
        try:
            services = mdns_future.result(timeout=5)
        except Exception:  # noqa: BLE001
            services = []

    # mDNS : noms Cast / Android TV, débogage sans fil (port variable)
    for sv in services:
        ip = sv["ip"]
        if not ip:
            continue
        f = found.setdefault(ip, Found(ip))
        txt = sv["txt"]
        if sv["service"].startswith("_googlecast"):
            nm = txt.get("fn") or sv["instance"]
            md = txt.get("md", "")
            f.details.append("Google Cast" + (" · " + md if md else ""))
            f.name = f.name or nm
            f.sources.add("cast")
        elif sv["service"].startswith("_androidtvremote2"):
            f.name = f.name or sv["instance"]
            f.sources.add("atv")
        elif sv["service"].startswith("_adb-tls-connect") and sv["port"]:
            if f.port is None:
                f.port, f.adb = sv["port"], "tls"
            f.sources.add("adb-tls")
        elif sv["service"].startswith("_adb._tcp") and sv["port"] and f.port is None:
            f.port, f.adb = sv["port"], "auth"

    # Bannière ADB (modèle exact si pas d'autorisation requise) + nom réseau
    def enrich(f: Found):
        cast = f.name if "cast" in f.sources or "atv" in f.sources else ""
        if f.port and f.adb == "auth":
            state, props = adb_banner(f.ip, f.port)
            if state == "":
                f.adb = "port"  # le port répond mais ce n'est pas ADB (ou pas un appareil Android)
            if state == "open":
                f.adb = "open"
                f.model = _nice_model(props)
                if props.get("ro.product.device") and props.get("ro.product.device") not in f.model:
                    f.details.insert(0, props["ro.product.device"])
        try:
            host = socket.gethostbyaddr(f.ip)[0].split(".")[0]
            if host and host != f.ip:
                f.details.append(host)
                f.sources.add("dns")
        except (OSError, UnicodeError):
            pass
        trusted, dev_name = adb_device_name(f.ip, f.port) if f.port and f.adb in ("open", "auth") else (False, "")
        if trusted and f.adb == "auth":
            f.adb = "trusted"  # l'appareil a déjà autorisé cet ordinateur
        if dev_name:
            f.sources.add("name")
        hist = known_names.get(f.ip)
        # Priorité : nom donné à l'appareil > nom Cast / Android TV > historique > modèle > nom réseau > IP
        f.name = (dev_name or cast or hist or f.model or f.name
                  or (f.details[-1] if "dns" in f.sources and f.details else "") or f.ip)
        if f.model and f.model != f.name and f.model not in f.details:
            f.details.insert(0, f.model)

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(enrich, list(found.values())))
    if progress:
        progress(total, total, list(found.values()))
    order = {"open": 0, "trusted": 0, "auth": 1, "tls": 2, "port": 3, "": 4}
    return sorted(found.values(), key=lambda f: (order.get(f.adb, 3), tuple(int(x) for x in f.ip.split("."))))
