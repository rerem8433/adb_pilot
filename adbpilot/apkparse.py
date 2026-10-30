"""Lecture minimale des APK : zip à accès aléatoire, AXML (manifeste) et ARSC (resources.arsc).

Aucune dépendance externe. L'objectif est d'extraire le nom affiché et l'icône d'une
application en ne lisant que quelques morceaux du fichier (utile quand l'APK est sur
l'appareil et qu'on le lit par morceaux via adb).
"""
from __future__ import annotations

import re
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


FW_PREFIX = "@fw:"  # chemin d'un fichier situé dans framework-res.apk


class RemoteZip:
    """Zip lu à la demande à travers un RangeReader."""

    def __init__(self, reader: RangeReader, tail: bytes | None = None):
        self.r = reader
        self.entries: dict[str, ZipEntry] = {}
        self.fw_loader = None  # -> (RemoteZip, ARSC) de framework-res.apk, pour les ressources @android:
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
        if name.startswith(FW_PREFIX):
            fw = self.fw_loader() if self.fw_loader else None
            return fw[0].read(name[len(FW_PREFIX):]) if fw else None
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
        self.fw_loader = None  # ressources du paquet 0x01 (android) lues dans framework-res.apk
        self._parse()

    def _fw(self, res_id):
        if (res_id >> 24) == 0x01 and self.fw_loader and not self.values.get(
                (0x01, (res_id >> 16) & 0xFF, res_id & 0xFFFF)):
            fw = self.fw_loader()
            return fw[1] if fw else None
        return None

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
        fw = self._fw(res_id)
        if fw is not None:
            return fw.get_string(res_id, langs, _depth)
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
        fw = self._fw(res_id)
        if fw is not None:
            return [(d, FW_PREFIX + f) for d, f in fw.get_files(res_id, _depth)]
        for v in self._lookup(res_id):
            if v.dtype == TYPE_STRING and v.data < len(self.strings):
                out.append((v.density, self.strings[v.data]))
            elif v.dtype == TYPE_REFERENCE:
                out.extend(self.get_files(v.data, _depth + 1))
        return out

    def get_color(self, res_id, _depth=0):
        fw = self._fw(res_id)
        if fw is not None:
            return fw.get_color(res_id, _depth)
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
    bmps = [(d, f) for d, f in files if not f.lower().endswith(".xml")]  # extension parfois absente
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
        self.icon_layers: tuple | None = None  # (fond, premier plan) : ("img"|"svg"|"color", valeur)
        self.icon_svg: bytes | None = None


def read_apk_meta(z: RemoteZip, langs=("fr",), framework=None) -> ApkMeta:
    """framework : fonction sans argument -> (RemoteZip, ARSC) de framework-res.apk, ou None."""
    meta = ApkMeta()
    z.fw_loader = framework
    files = z.read_many(["AndroidManifest.xml", "resources.arsc"])
    man = files.get("AndroidManifest.xml")
    if not man:
        return meta
    els = parse_axml(man)
    arsc = None
    if files.get("resources.arsc"):
        try:
            arsc = ARSC(files["resources.arsc"])
            arsc.fw_loader = framework
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
    try:
        if ic and ic[0] == TYPE_REFERENCE and arsc:
            _resolve_icon(meta, z, arsc, ic[1])
        elif ic and ic[2] and ic[2].endswith((".png", ".webp")):
            meta.icon_bytes = z.read(ic[2])
    except (struct.error, IndexError, ValueError, KeyError, zlib.error):
        pass
    return meta


# ---------------------------------------------------------------------------
# Icônes : bitmap, vector drawable (converti en SVG), adaptive-icon
# ---------------------------------------------------------------------------

def _f32(v):
    """Valeur numérique d'un attribut AXML (float, dimension ou entier)."""
    t, d, sv = v
    if t == 0x04:
        return struct.unpack("<f", struct.pack("<I", d))[0]
    if t == 0x05:  # dimension : mantisse 24 bits, radix 2 bits
        mant = d >> 8
        if mant & 0x800000:
            mant -= 0x1000000
        radix = (d >> 4) & 0x3
        return mant * (1.0, 1 / 128, 1 / 32768, 1 / 8388608)[radix]
    if t in (0x10, 0x11):
        return float(d if d < 0x80000000 else d - 0x100000000)
    if sv:
        try:
            return float(re.sub(r"[a-z]+$", "", sv))
        except ValueError:
            return 0.0
    return 0.0


def _color_of(v, arsc):
    t, d, _sv = v
    if TYPE_INT_COLOR_FIRST <= t <= TYPE_INT_COLOR_LAST:
        return d
    if t == TYPE_REFERENCE and arsc:
        return arsc.get_color(d)
    return None


def _svg_color(argb, alpha=1.0):
    a = ((argb >> 24) & 0xFF) / 255.0 * alpha
    return "#%06x" % (argb & 0xFFFFFF), a


def vector_to_svg(els, arsc):
    """Convertit un VectorDrawable (liste AXML) en SVG."""
    if not els or els[0].tag != "vector":
        return None
    root = els[0]
    vw = _f32(root.attrs["viewportWidth"]) if "viewportWidth" in root.attrs else 24.0
    vh = _f32(root.attrs["viewportHeight"]) if "viewportHeight" in root.attrs else 24.0
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %g %g">' % (vw, vh)]
    defs = []
    stack = [0]          # profondeurs des groupes ouverts
    opened = [0]         # nombre de <g> à fermer par niveau
    pending_fill = {}
    clip_n = 0
    last_path_idx = None
    for e in els[1:]:
        while len(stack) > 1 and e.depth <= stack[-1]:
            out.append("</g>" * opened.pop())
            stack.pop()
        a = e.attrs
        if e.tag == "group":
            px = _f32(a["pivotX"]) if "pivotX" in a else 0.0
            py = _f32(a["pivotY"]) if "pivotY" in a else 0.0
            tx = _f32(a["translateX"]) if "translateX" in a else 0.0
            ty = _f32(a["translateY"]) if "translateY" in a else 0.0
            sx = _f32(a["scaleX"]) if "scaleX" in a else 1.0
            sy = _f32(a["scaleY"]) if "scaleY" in a else 1.0
            rot = _f32(a["rotation"]) if "rotation" in a else 0.0
            out.append('<g transform="translate(%g %g) rotate(%g) scale(%g %g) translate(%g %g)">'
                       % (tx + px, ty + py, rot, sx, sy, -px, -py))
            stack.append(e.depth)
            opened.append(1)
        elif e.tag == "clip-path" and "pathData" in a:
            clip_n += 1
            defs.append('<clipPath id="c%d"><path d="%s"/></clipPath>' % (clip_n, a["pathData"][2]))
            out.append('<g clip-path="url(#c%d)">' % clip_n)
            opened[-1] += 1
        elif e.tag == "path" and "pathData" in a and a["pathData"][2]:
            fill = "none"
            fa = _f32(a["fillAlpha"]) if "fillAlpha" in a else 1.0
            attrs = []
            if "fillColor" in a:
                c = _color_of(a["fillColor"], arsc)
                if c is not None:
                    fill, op = _svg_color(c, fa)
                    attrs.append('fill-opacity="%.3f"' % op)
            if "strokeColor" in a:
                c = _color_of(a["strokeColor"], arsc)
                if c is not None:
                    sc, op = _svg_color(c, _f32(a["strokeAlpha"]) if "strokeAlpha" in a else 1.0)
                    attrs.append('stroke="%s" stroke-opacity="%.3f" stroke-width="%g"' % (
                        sc, op, _f32(a["strokeWidth"]) if "strokeWidth" in a else 1.0))
            if "fillType" in a and a["fillType"][1] == 1:
                attrs.append('fill-rule="evenodd"')
            out.append('<path d="%s" fill="%s" %s/>' % (a["pathData"][2], fill, " ".join(attrs)))
            last_path_idx = len(out) - 1
        elif e.tag == "gradient" and last_path_idx is not None:
            c = None
            for k in ("startColor", "centerColor", "endColor"):
                if k in a:
                    c = _color_of(a[k], arsc)
                    if c is not None:
                        break
            if c is not None:
                pending_fill[last_path_idx] = c
        elif e.tag == "item" and last_path_idx is not None and last_path_idx not in pending_fill \
                and "color" in a:
            c = _color_of(a["color"], arsc)
            if c is not None:
                pending_fill[last_path_idx] = c
    for idx, c in pending_fill.items():
        col, op = _svg_color(c)
        out[idx] = out[idx].replace('fill="none"', 'fill="%s" fill-opacity="%.3f"' % (col, op), 1)
    while len(opened) > 1:
        out.append("</g>" * opened.pop())
    out.append("</svg>")
    if defs:
        out.insert(1, "<defs>%s</defs>" % "".join(defs))
    return "".join(out).encode()


def _drawable(z, arsc, ref, depth=0):
    """Résout une ressource drawable : ('img', bytes) | ('svg', bytes) | ('color', argb) | None."""
    if depth > 4 or ref is None:
        return None
    t, d, sv = ref
    if TYPE_INT_COLOR_FIRST <= t <= TYPE_INT_COLOR_LAST:
        return ("color", d)
    if t != TYPE_REFERENCE:
        return None
    col = arsc.get_color(d)
    if col is not None:
        return ("color", col)
    files = arsc.get_files(d)
    bmp = best_bitmap(files)
    if bmp:
        data = z.read(bmp)
        return ("img", data) if data else None
    xmls = [f for _dn, f in sorted(files, key=lambda x: -_density_rank(x[0])) if f.endswith(".xml")]
    for xp in xmls:
        data = z.read(xp)
        if not data:
            continue
        els = parse_axml(data)
        if not els:
            continue
        tag = els[0].tag
        if tag == "vector":
            svg = vector_to_svg(els, arsc)
            if svg:
                return ("svg", svg)
        if tag in ("inset", "bitmap", "nine-patch", "layer-list", "selector", "ripple", "scale"):
            for e in els:
                for k in ("drawable", "src"):
                    if k in e.attrs and e.attrs[k][0] == TYPE_REFERENCE:
                        r = _drawable(z, arsc, e.attrs[k], depth + 1)
                        if r:
                            return r
        if tag == "shape":
            for e in els:
                if e.tag == "solid" and "color" in e.attrs:
                    c = _color_of(e.attrs["color"], arsc)
                    if c is not None:
                        return ("color", c)
    return None


def _resolve_icon(meta, z, arsc, res_id):
    files = arsc.get_files(res_id)
    bmp = best_bitmap(files)
    if bmp:
        meta.icon_bytes = z.read(bmp)
        return
    for _dn, xp in files:
        if not xp.endswith(".xml"):
            continue
        els = parse_axml(z.read(xp) or b"")
        if not els:
            continue
        if els[0].tag == "adaptive-icon":
            layers = {"background": None, "foreground": None}
            cur = None  # calque en cours : les enfants (<inset>, <color>…) s'y rattachent
            for e in els:
                if e.tag in layers:
                    cur = e.tag
                    if "drawable" in e.attrs:
                        layers[cur] = _drawable(z, arsc, e.attrs["drawable"])
                elif cur and layers[cur] is None:
                    for k in ("drawable", "src"):
                        if k in e.attrs:
                            layers[cur] = _drawable(z, arsc, e.attrs[k])
                            break
                    else:
                        if e.tag == "color" and "color" in e.attrs:
                            c = _color_of(e.attrs["color"], arsc)
                            layers[cur] = ("color", c) if c is not None else None
            bg, fg = layers["background"], layers["foreground"]
            if fg or bg:
                meta.icon_layers = (bg, fg)
                return
        elif els[0].tag == "vector":
            svg = vector_to_svg(els, arsc)
            if svg:
                meta.icon_svg = svg
                return
        else:
            r = _drawable(z, arsc, (TYPE_REFERENCE, res_id, None))
            if r and r[0] == "img":
                meta.icon_bytes = r[1]
                return
            if r and r[0] == "svg":
                meta.icon_svg = r[1]
                return
