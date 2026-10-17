"""Lecture minimale des APK : zip à accès aléatoire, AXML (manifeste) et ARSC (resources.arsc).

Aucune dépendance externe. L'objectif est d'extraire le nom affiché et l'icône d'une
application en ne lisant que quelques morceaux du fichier (utile quand l'APK est sur
l'appareil et qu'on le lit par morceaux via adb).
"""
from __future__ import annotations

import struct
import zlib

# ---------------------------------------------------------------------------
# Zip à accès aléatoire
# ---------------------------------------------------------------------------

class ZipEntry:
    __slots__ = ("name", "method", "csize", "usize", "lho", "elen")

    def __init__(self, name, method, csize, usize, lho, elen):
        self.name, self.method, self.csize, self.usize, self.lho, self.elen = (
            name, method, csize, usize, lho, elen)


class RangeReader:
    """Interface : size et read_ranges([(off, len), ...]) -> [bytes, ...]."""

    size: int = 0

    def read_ranges(self, ranges):  # pragma: no cover - interface
        raise NotImplementedError

    def read(self, off, length):
        return self.read_ranges([(off, length)])[0]


class LocalReader(RangeReader):
    def __init__(self, path):
        self.path = path
        import os
        self.size = os.path.getsize(path)

    def read_ranges(self, ranges):
        out = []
        with open(self.path, "rb") as f:
            for off, ln in ranges:
                f.seek(max(0, off))
                out.append(f.read(max(0, ln)))
        return out


class BytesReader(RangeReader):
    def __init__(self, data: bytes):
        self.data = data
        self.size = len(data)

    def read_ranges(self, ranges):
        return [self.data[o:o + n] for o, n in ranges]


class RemoteZip:
    """Zip lu à la demande à travers un RangeReader."""

    def __init__(self, reader: RangeReader, tail: bytes | None = None):
        self.r = reader
        self.entries: dict[str, ZipEntry] = {}
        self._load_cd(tail)

    def _load_cd(self, tail):
        size = self.r.size
        if tail is None:
            n = min(size, 65536 + 22)
            tail = self.r.read(size - n, n)
        tail_off = size - len(tail)
        i = tail.rfind(b"PK\x05\x06")
        if i < 0:
            raise ValueError("EOCD introuvable")
        (_sig, _d, _dcd, _n1, n_entries, cd_size, cd_off, _clen) = struct.unpack_from(
            "<IHHHHIIH", tail, i)
        if cd_off == 0xFFFFFFFF:
            raise ValueError("zip64 non géré")
        if cd_off >= tail_off:
            cd = tail[cd_off - tail_off: cd_off - tail_off + cd_size]
        else:
            cd = self.r.read(cd_off, cd_size)
        p = 0
        for _ in range(n_entries):
            if cd[p:p + 4] != b"PK\x01\x02":
                break
            (method, csize, usize, nlen, elen, clen, lho) = (
                struct.unpack_from("<H", cd, p + 10)[0],
                *struct.unpack_from("<II", cd, p + 20),
                *struct.unpack_from("<HHH", cd, p + 28),
                struct.unpack_from("<I", cd, p + 42)[0],
            )
            name = cd[p + 46:p + 46 + nlen].decode("utf-8", "replace")
            self.entries[name] = ZipEntry(name, method, csize, usize, lho, elen)
            p += 46 + nlen + elen + clen

    def read_many(self, names):
        """Lit plusieurs entrées en un seul aller-retour (si possible)."""
        names = [n for n in names if n in self.entries]
        if not names:
            return {}
        ranges = []
        for n in names:
            e = self.entries[n]
            ranges.append((e.lho, 30 + len(n.encode()) + e.elen + e.csize + 1024))
        blobs = self.r.read_ranges(ranges)
        out = {}
        for n, blob in zip(names, blobs):
            e = self.entries[n]
            if blob[:4] != b"PK\x03\x04":
                continue
            nlen, elen = struct.unpack_from("<HH", blob, 26)
            start = 30 + nlen + elen
            raw = blob[start:start + e.csize]
            if len(raw) < e.csize:  # extra local plus grand que prévu
                raw = self.r.read(e.lho + start, e.csize)
            try:
                out[n] = raw if e.method == 0 else zlib.decompress(raw, -15)
            except zlib.error:
                continue
        return out

    def read(self, name):
        return self.read_many([name]).get(name)


# ---------------------------------------------------------------------------
# Pool de chaînes
# ---------------------------------------------------------------------------

def _parse_string_pool(buf, off):
    (_t, hsize, size, count, _styles, flags, s_start, _st_start) = struct.unpack_from(
        "<HHIIIIII", buf, off)
    utf8 = bool(flags & 0x100)
    offs = struct.unpack_from("<%dI" % count, buf, off + hsize)
    base = off + s_start
    strings = []
    for so in offs:
        p = base + so
        try:
            if utf8:
                n = buf[p]
                p += 2 if n & 0x80 else 1
                n = buf[p]
                if n & 0x80:
                    n = ((n & 0x7F) << 8) | buf[p + 1]
                    p += 2
                else:
                    p += 1
                strings.append(buf[p:p + n].decode("utf-8", "replace"))
            else:
                n = struct.unpack_from("<H", buf, p)[0]
                p += 2
                if n & 0x8000:
                    n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]
                    p += 2
                strings.append(buf[p:p + n * 2].decode("utf-16-le", "replace"))
        except (IndexError, struct.error):
            strings.append("")
    return strings, size


# ---------------------------------------------------------------------------
# AXML (XML binaire)
# ---------------------------------------------------------------------------

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_COLOR_FIRST = 0x1C
TYPE_INT_COLOR_LAST = 0x1F

ATTR_IDS = {
    0x01010001: "label",
    0x01010002: "icon",
    0x0101052C: "roundIcon",
    0x0101021B: "versionCode",
    0x0101021C: "versionName",
    0x01010199: "drawable",
    0x01010003: "name",
    0x0101020C: "minSdkVersion",
    0x01010270: "targetSdkVersion",
}


class AXMLElement:
    __slots__ = ("tag", "attrs", "depth")

    def __init__(self, tag, attrs, depth):
        self.tag, self.attrs, self.depth = tag, attrs, depth


def parse_axml(buf: bytes):
    """Retourne la liste des éléments (tag, attrs{name: (type, data, str)}, profondeur)."""
    if len(buf) < 8:
        return []
    _t, hsize, size = struct.unpack_from("<HHI", buf, 0)
    p = hsize
    strings: list[str] = []
    resmap: list[int] = []
    elements = []
    depth = 0
    end = min(size, len(buf))
    while p + 8 <= end:
        ctype, chsize, csize = struct.unpack_from("<HHI", buf, p)
        if csize < 8:
            break
        if ctype == 0x0001:
            strings, _ = _parse_string_pool(buf, p)
        elif ctype == 0x0180:
            n = (csize - chsize) // 4
            resmap = list(struct.unpack_from("<%dI" % n, buf, p + chsize))
        elif ctype == 0x0102:
            (_ns, name, a_start, a_size, a_count) = struct.unpack_from(
                "<IIHHH", buf, p + chsize)
            tag = strings[name] if name < len(strings) else ""
            attrs = {}
            ap = p + chsize + a_start
            for i in range(a_count):
                (_ans, aname, araw, _vs, _r0, dtype, data) = struct.unpack_from(
                    "<IIIHBBI", buf, ap + i * a_size)
                key = None
                if aname < len(resmap) and resmap[aname] in ATTR_IDS:
                    key = ATTR_IDS[resmap[aname]]
                elif aname < len(strings):
                    key = strings[aname]
                if not key:
                    continue
                sval = None
                if dtype == TYPE_STRING and data < len(strings):
                    sval = strings[data]
                elif araw != 0xFFFFFFFF and araw < len(strings):
                    sval = strings[araw]
                attrs[key] = (dtype, data, sval)
            elements.append(AXMLElement(tag, attrs, depth))
            depth += 1
        elif ctype == 0x0103:
            depth -= 1
        p += csize
    return elements


# ---------------------------------------------------------------------------
# ARSC (table de ressources)
# ---------------------------------------------------------------------------

DENSITY_ANY = 0xFFFE
DENSITY_NONE = 0xFFFF


class ResValue:
    __slots__ = ("lang", "country", "density", "dtype", "data")

    def __init__(self, lang, country, density, dtype, data):
        self.lang, self.country, self.density, self.dtype, self.data = (
            lang, country, density, dtype, data)


class ARSC:
    def __init__(self, buf: bytes):
        self.buf = buf
        self.strings: list[str] = []
        # (pkg_id, type_id, entry_id) -> [ResValue]
        self.values: dict[tuple[int, int, int], list[ResValue]] = {}
        self._parse()

    def _parse(self):
        b = self.buf
        _t, hsize, size = struct.unpack_from("<HHI", b, 0)
        p = hsize
        end = min(size, len(b))
        while p + 8 <= end:
            ctype, chsize, csize = struct.unpack_from("<HHI", b, p)
            if csize < 8:
                break
            if ctype == 0x0001:
                self.strings, _ = _parse_string_pool(b, p)
            elif ctype == 0x0200:
                self._parse_package(p, chsize, csize)
            p += csize

    def _parse_package(self, start, hsize, size):
        b = self.buf
        pkg_id = struct.unpack_from("<I", b, start + 8)[0]
        p = start + hsize
        end = start + size
        while p + 8 <= end:
            ctype, chsize, csize = struct.unpack_from("<HHI", b, p)
            if csize < 8:
                break
            if ctype == 0x0201:
                try:
                    self._parse_type(pkg_id, p, chsize, csize)
                except (struct.error, IndexError):
                    pass
            p += csize

    def _parse_type(self, pkg_id, start, hsize, size):
        b = self.buf
        type_id, flags, _res, count, entries_start = struct.unpack_from(
            "<BBHII", b, start + 8)
        cfg = start + 20
        cfg_size = struct.unpack_from("<I", b, cfg)[0]
        lang = b"" if cfg_size < 12 else b[cfg + 8:cfg + 10]
        lang = lang.rstrip(b"\x00").decode("latin-1") if lang and lang[0] < 0x80 else ""
        country = b"" if cfg_size < 12 else b[cfg + 10:cfg + 12]
        country = country.rstrip(b"\x00").decode("latin-1") if country and country[0] < 0x80 else ""
        density = struct.unpack_from("<H", b, cfg + 14)[0] if cfg_size >= 16 else 0
        idx_base = start + hsize
        data_base = start + entries_start
        pairs = []
        if flags & 0x01:  # FLAG_SPARSE
            for i in range(count):
                idx, off4 = struct.unpack_from("<HH", b, idx_base + i * 4)
                pairs.append((idx, off4 * 4))
        elif flags & 0x02:  # FLAG_OFFSET16
            for i in range(count):
                off4 = struct.unpack_from("<H", b, idx_base + i * 2)[0]
                if off4 != 0xFFFF:
                    pairs.append((i, off4 * 4))
        else:
            offs = struct.unpack_from("<%dI" % count, b, idx_base)
            pairs = [(i, o) for i, o in enumerate(offs) if o != 0xFFFFFFFF]
        for idx, off in pairs:
            e = data_base + off
            esize, eflags = struct.unpack_from("<HH", b, e)
            if eflags & 0x08:  # FLAG_COMPACT
                dtype = eflags >> 8
                data = struct.unpack_from("<I", b, e + 4)[0]
            elif eflags & 0x01:  # complex / bag
                continue
            else:
                _vs, _r0, dtype, data = struct.unpack_from("<HBBI", b, e + esize)
            self.values.setdefault((pkg_id, type_id, idx), []).append(
                ResValue(lang, country, density, dtype, data))

    def _lookup(self, res_id):
        return self.values.get(((res_id >> 24) & 0xFF, (res_id >> 16) & 0xFF, res_id & 0xFFFF), [])

    def get_string(self, res_id, langs=("fr",), _depth=0):
        vals = self._lookup(res_id)
        if not vals or _depth > 5:
            return None
        chosen = None
        for lg in langs:
            chosen = (next((v for v in vals if v.lang == lg and not v.country), None)
                      or next((v for v in vals if v.lang == lg and v.country not in ("XA", "XB")), None))
            if chosen:
                break
        if chosen is None:
            chosen = next((v for v in vals if v.lang == ""), None) or next(
                (v for v in vals if v.country not in ("XA", "XB")), vals[0])
        if chosen.dtype == TYPE_STRING and chosen.data < len(self.strings):
            return self.strings[chosen.data]
        if chosen.dtype == TYPE_REFERENCE:
            return self.get_string(chosen.data, langs, _depth + 1)
        return None

    def get_files(self, res_id, _depth=0):
        """Liste (densité, chemin) pour une ressource fichier (drawable/mipmap)."""
        out = []
        if _depth > 5:
            return out
        for v in self._lookup(res_id):
            if v.dtype == TYPE_STRING and v.data < len(self.strings):
                out.append((v.density, self.strings[v.data]))
            elif v.dtype == TYPE_REFERENCE:
                out.extend(self.get_files(v.data, _depth + 1))
        return out

    def get_color(self, res_id, _depth=0):
        for v in self._lookup(res_id):
            if TYPE_INT_COLOR_FIRST <= v.dtype <= TYPE_INT_COLOR_LAST:
                return v.data
            if v.dtype == TYPE_REFERENCE and _depth < 5:
                c = self.get_color(v.data, _depth + 1)
                if c is not None:
                    return c
        return None


def _density_rank(d):
    if d == DENSITY_ANY:
        return -1
    if d == DENSITY_NONE:
        return 1
    if d == 0:
        return 160
    return d


def best_bitmap(files, max_density=480):
    """Choisit le meilleur PNG/WebP (densité la plus proche de max_density par le haut)."""
    bmps = [(d, f) for d, f in files if f.lower().endswith((".png", ".webp", ".jpg"))]
    if not bmps:
        return None
    bmps.sort(key=lambda x: _density_rank(x[0]))
    under = [x for x in bmps if _density_rank(x[0]) <= max_density]
    return (under[-1] if under else bmps[0])[1]


# ---------------------------------------------------------------------------
# Haut niveau
# ---------------------------------------------------------------------------

class ApkMeta:
    def __init__(self):
        self.package = None
        self.label = None
        self.version_name = None
        self.icon_bytes: bytes | None = None
        self.icon_layers: tuple | None = None  # (bg_bytes|None, bg_color|None, fg_bytes|None)


def read_apk_meta(z: RemoteZip, langs=("fr",)) -> ApkMeta:
    meta = ApkMeta()
    files = z.read_many(["AndroidManifest.xml", "resources.arsc"])
    man = files.get("AndroidManifest.xml")
    if not man:
        return meta
    els = parse_axml(man)
    arsc = None
    if files.get("resources.arsc"):
        try:
            arsc = ARSC(files["resources.arsc"])
        except (struct.error, IndexError, ValueError):
            arsc = None
    app = None
    for e in els:
        if e.tag == "manifest":
            if "package" in e.attrs:
                meta.package = e.attrs["package"][2]
            if "versionName" in e.attrs:
                vn = e.attrs["versionName"]
                meta.version_name = vn[2] if vn[2] is not None else (
                    arsc.get_string(vn[1], langs) if arsc and vn[0] == TYPE_REFERENCE else None)
        elif e.tag == "application":
            app = e
            break
    if app is None:
        return meta
    lab = app.attrs.get("label")
    if lab:
        if lab[0] == TYPE_REFERENCE and arsc:
            meta.label = arsc.get_string(lab[1], langs)
        elif lab[2]:
            meta.label = lab[2]
    ic = app.attrs.get("icon") or app.attrs.get("roundIcon")
    if ic and ic[0] == TYPE_REFERENCE and arsc:
        cand = arsc.get_files(ic[1])
        bmp = best_bitmap(cand)
        if bmp:
            meta.icon_bytes = z.read(bmp)
        else:
            xmls = [f for d, f in cand if f.endswith(".xml")]
            if xmls:
                meta.icon_layers = _adaptive_layers(z, arsc, xmls[0])
    elif ic and ic[2] and ic[2].endswith((".png", ".webp")):
        meta.icon_bytes = z.read(ic[2])
    return meta


def _adaptive_layers(z, arsc, xml_path):
    data = z.read(xml_path)
    if not data:
        return None
    bg_ref = fg_ref = None
    els = parse_axml(data)
    mode = None
    for e in els:
        if e.tag in ("background", "foreground"):
            mode = e.tag
            d = e.attrs.get("drawable")
            if d:
                if mode == "background":
                    bg_ref = d
                else:
                    fg_ref = d
        elif mode and e.tag == "inset" and e.attrs.get("drawable"):
            if mode == "foreground" and fg_ref is None:
                fg_ref = e.attrs["drawable"]
    bg_bytes = bg_color = fg_bytes = None
    want = []
    if bg_ref:
        if TYPE_INT_COLOR_FIRST <= bg_ref[0] <= TYPE_INT_COLOR_LAST:
            bg_color = bg_ref[1]
        elif bg_ref[0] == TYPE_REFERENCE:
            bg_color = arsc.get_color(bg_ref[1])
            if bg_color is None:
                b = best_bitmap(arsc.get_files(bg_ref[1]))
                if b:
                    want.append(("bg", b))
    if fg_ref and fg_ref[0] == TYPE_REFERENCE:
        f = best_bitmap(arsc.get_files(fg_ref[1]))
        if f:
            want.append(("fg", f))
    if want:
        got = z.read_many([w[1] for w in want])
        for kind, path in want:
            if kind == "bg":
                bg_bytes = got.get(path)
            else:
                fg_bytes = got.get(path)
    if fg_bytes is None and bg_bytes is None and bg_color is None:
        return None
    return (bg_bytes, bg_color, fg_bytes)
