"""Détection des appareils Android sur le réseau local (port ADB + annonces mDNS), avec leur nom.

Sources du nom, de la plus précise à la moins précise :
  1. bannière ADB (box sans autorisation ADB : modèle exact, sans rien afficher sur la TV) ;
  2. mDNS : Google Cast (« fn= »), télécommande Android TV, débogage sans fil Android 11+ ;
  3. historique des connexions d'ADB Pilot ;
  4. nom d'hôte du réseau (DNS inverse : nom donné par la box internet).
"""
from __future__ import annotations

import ipaddress
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

A_CNXN, A_AUTH = 0x4E584E43, 0x48545541
MDNS_GROUP, MDNS_PORT = "224.0.0.251", 5353
MDNS_SERVICES = ("_adb-tls-connect._tcp.local", "_adb._tcp.local", "_googlecast._tcp.local",
                 "_androidtvremote2._tcp.local")


@dataclass
class Found:
    ip: str
    port: int | None = None          # port ADB joignable
    adb: str = ""                    # "open" (bannière lue), "auth" (autorisation requise), "tls" (Android 11+), ""
    name: str = ""                   # nom affiché
    model: str = ""                  # modèle lu dans la bannière ADB
    details: list = field(default_factory=list)  # infos secondaires (Cast, hôte réseau…)
    sources: set = field(default_factory=set)

    @property
    def connectable(self):
        return self.port is not None


# ---------------------------------------------------------------------------
# Réseau local
# ---------------------------------------------------------------------------

def local_networks() -> list[ipaddress.IPv4Network]:
    """Réseau(x) /24 de l'ordinateur (adresse de sortie vers Internet + adresses de la machine)."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # aucun paquet n'est envoyé (UDP)
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    nets = []
    for ip in ips:
        a = ipaddress.IPv4Address(ip)
        if a.is_private and not a.is_loopback and not a.is_link_local:
            n = ipaddress.IPv4Network(ip + "/24", strict=False)
            if n not in nets:
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


def scan(port=5555, known_names=None, progress=None, stop=lambda: False) -> list[Found]:
    """progress(n, total, found_list) est appelé pendant le scan (depuis un fil de travail)."""
    known_names = known_names or {}
    nets = local_networks()
    hosts = [str(h) for n in nets for h in n.hosts()]
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
        if f.port and f.adb == "auth":
            state, props = adb_banner(f.ip, f.port)
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
        hist = known_names.get(f.ip)
        f.name = f.model or hist or f.name or (f.details[-1] if "dns" in f.sources and f.details else "") or f.ip

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(enrich, list(found.values())))
    if progress:
        progress(total, total, list(found.values()))
    order = {"open": 0, "auth": 1, "tls": 2, "": 3}
    return sorted(found.values(), key=lambda f: (order.get(f.adb, 3), tuple(int(x) for x in f.ip.split("."))))
