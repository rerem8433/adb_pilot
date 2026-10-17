"""Page « Installer » : bibliothèque d'APK (dossier install + dossier par appareil)."""
from __future__ import annotations

import html
import json
import re
import shutil
import zipfile
from pathlib import Path

from PySide6.QtCore import QFile, QFileSystemWatcher, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import adbcore
from ..apkparse import BytesReader, LocalReader, RemoteZip, read_apk_meta
from ..config import PRESETS_DIR, config, user_dir
from . import style

EXTS = (".apk", ".apks", ".xapk", ".apkm")
COLS = ["", "Application", "Fichier", "Paquet", "Version", "Sur l'appareil", "Taille"]
C_CHECK, C_NAME, C_FILE, C_PKG, C_VER, C_STATE, C_SIZE = range(7)


def install_root() -> Path:
    p = config.get("install_dir") or str(user_dir("install"))
    return Path(p)


def safe_name(s: str) -> str:
    return re.sub(r"[^\w.\- ]+", "_", s).strip() or "appareil"


class ApkFileInfo:
    __slots__ = ("path", "size", "mtime", "label", "package", "version", "icon")

    def __init__(self, path: Path):
        st = path.stat()
        self.path, self.size, self.mtime = path, st.st_size, st.st_mtime
        self.label = self.package = self.version = None
        self.icon = None


def _img(data):
    if not data:
        return None
    img = QImage.fromData(data)
    return None if img.isNull() else img.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _from_apk_meta(info, m):
    info.label = m.label
    info.package = m.package
    info.version = m.version_name
    if m.icon_bytes:
        info.icon = _img(m.icon_bytes)
    elif m.icon_layers:
        from ..metacache import _compose_adaptive
        info.icon = _compose_adaptive(m.icon_layers)


def read_file_info(path: Path) -> ApkFileInfo:
    info = ApkFileInfo(path)
    lang = config.get("label_lang", "fr")
    langs = (lang, "en") if lang and lang != "en" else ((lang,) if lang else ())
    try:
        if path.suffix.lower() == ".apk":
            _from_apk_meta(info, read_apk_meta(RemoteZip(LocalReader(str(path))), langs=langs))
            return info
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            meta = None
            for jn in ("manifest.json", "info.json", "meta.sai_v2.json", "meta.sai_v1.json"):
                if jn in names:
                    try:
                        meta = json.loads(z.read(jn).decode("utf-8", "replace"))
                    except ValueError:
                        meta = None
                    break
            if isinstance(meta, dict):
                info.label = meta.get("name") or meta.get("app_name") or meta.get("label")
                info.package = meta.get("package_name") or meta.get("pname") or meta.get("package")
                info.version = (meta.get("version_name") or meta.get("release_version")
                                or meta.get("version_name_str"))
            icon_name = next((n for n in ("icon.png", "icon.webp", "icon.jpg") if n in names), None)
            if icon_name:
                info.icon = _img(z.read(icon_name))
            if not info.package or info.icon is None:
                base = next((n for n in names if n.endswith("base.apk")), None) or next(
                    (n for n in names if n.endswith(".apk") and "config." not in n and "split_" not in n), None)
                if base and z.getinfo(base).file_size < 400 * 1048576:
                    m = read_apk_meta(RemoteZip(BytesReader(z.read(base))), langs=langs)
                    if not info.package:
                        info.label, info.package, info.version = (info.label or m.label, m.package,
                                                                  info.version or m.version_name)
                    if info.icon is None:
                        tmp = ApkFileInfo.__new__(ApkFileInfo)
                        tmp.icon = None
                        _from_apk_meta(tmp, m)
                        info.icon = tmp.icon
    except Exception:  # noqa: BLE001 - fichier illisible : on affiche juste le nom
        pass
    return info


def _vkey(v):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-_ ]", v or ""))[:6]


class SortItem(QTableWidgetItem):
    def __init__(self, text, key):
        super().__init__(text)
        self.key = key

    def __lt__(self, other):
        try:
            return self.key < getattr(other, "key", self.key)
        except TypeError:
            return str(self.key) < str(getattr(other, "key", ""))


class InstallerPage(QWidget):
    def __init__(self, ctl, main, apps_tab):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self.apps_tab = apps_tab
        self.cache: dict[str, ApkFileInfo] = {}
        self.files: list[ApkFileInfo] = []
        self.checked: set[str] = set()
        self.mode = "install"  # install | device
        self.search = ""
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._debounce.start(400))
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.refresh)
        self._gen = 0
        self.setAcceptDrops(True)
        self._build()
        ctl.device_changed.connect(lambda _d: self._on_device())
        ctl.packages_ready.connect(lambda _p: self._fill())

    # -- construction ------------------------------------------------------
    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        left = QVBoxLayout()
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 0)
        self.cb_all = QCheckBox("Tout sélectionner")
        self.cb_all.clicked.connect(self._select_all)
        top.addWidget(self.cb_all)
        tot = QVBoxLayout()
        tot.setSpacing(0)
        t1 = QLabel("Total :")
        t1.setStyleSheet("font-size: 7pt;")
        self.lbl_total = QLabel("0")
        tot.addWidget(t1)
        tot.addWidget(self.lbl_total)
        top.addSpacing(16)
        top.addLayout(tot)
        top.addSpacing(20)
        self.lbl_hint = QLabel()
        self.lbl_hint.setStyleSheet("font-size: 9pt;")
        top.addWidget(self.lbl_hint, 1)
        left.addLayout(top)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setIconSize(QSize(30, 30))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(C_CHECK, QHeaderView.Fixed)
        h.resizeSection(C_CHECK, 30)
        h.setSectionResizeMode(C_NAME, QHeaderView.Stretch)
        for c, w in ((C_FILE, 160), (C_PKG, 190), (C_VER, 100), (C_STATE, 150), (C_SIZE, 85)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
            h.resizeSection(c, w)
        h.setHighlightSections(False)
        self.table.itemChanged.connect(self._item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda idx: self.install(self._row_files([idx.row()])))
        left.addWidget(self.table, 1)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 6, 6, 6)
        right.setSpacing(6)
        b_back = QPushButton("  ←  Retour aux applications")
        b_back.setStyleSheet("text-align: left;")
        b_back.setMinimumHeight(36)
        b_back.clicked.connect(self.apps_tab.show_apps)
        right.addWidget(b_back)
        g = QGridLayout()
        g.setSpacing(0)
        b_lp = QPushButton("Charger un preset")
        b_lp.clicked.connect(self.load_preset)
        b_sp = QPushButton("Enregistrer le preset")
        b_sp.clicked.connect(self.save_preset)
        for b in (b_lp, b_sp):
            b.setMinimumHeight(40)
        g.addWidget(b_lp, 0, 0)
        g.addWidget(b_sp, 0, 1)
        right.addLayout(g)
        right.addSpacing(12)
        lab = QLabel("Dossier des fichiers :")
        lab.setAlignment(Qt.AlignCenter)
        right.addWidget(lab)
        g2 = QGridLayout()
        g2.setSpacing(0)
        self.b_inst_dir = QPushButton("Dossier\nInstall")
        self.b_dev_dir = QPushButton("Dossier\nde l'appareil")
        self.dir_group = QButtonGroup(self)
        for i, b in enumerate((self.b_inst_dir, self.b_dev_dir)):
            b.setCheckable(True)
            b.setMinimumHeight(48)
            self.dir_group.addButton(b, i)
            g2.addWidget(b, 0, i)
        self.b_inst_dir.setChecked(True)
        self.dir_group.idClicked.connect(self._set_mode)
        right.addLayout(g2)
        b_open = QPushButton("Ouvrir le dossier")
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder()))))
        right.addWidget(b_open)
        right.addSpacing(10)
        row = QHBoxLayout()
        acts = QVBoxLayout()
        b_add = QPushButton("＋  Ajouter des APK")
        b_add.setStyleSheet("text-align: left; color: #2fd06b; font-weight: 600;")
        b_add.clicked.connect(self.add_dialog)
        b_del = QPushButton("－  Supprimer")
        b_del.setStyleSheet("text-align: left; color: #ff5c5c; font-weight: 600;")
        b_del.clicked.connect(lambda: self.delete(self._targets(selected_only=True)))
        acts.addWidget(b_add)
        acts.addWidget(b_del)
        row.addLayout(acts, 1)
        self.b_quick = QPushButton("Installation\nrapide")
        self.b_quick.setObjectName("accentSoft")
        self.b_quick.setMinimumSize(120, 72)
        self.b_quick.clicked.connect(lambda: self.install(self._targets()))
        row.addWidget(self.b_quick)
        right.addLayout(row)
        right.addSpacing(10)
        for text, key in [("Accorder les permissions (-g)", "install_grant"),
                          ("Remplacer si déjà installée (-r)", "install_replace"),
                          ("Autoriser une version antérieure (-d)", "install_downgrade")]:
            cb = QCheckBox(text)
            cb.setChecked(bool(config.get(key)))
            cb.toggled.connect(lambda v, k=key: (config.__setitem__(k, v), config.save()))
            right.addWidget(cb)
        right.addStretch(1)
        self.lbl_sel = QLabel("Sélection : 0")
        self.lbl_sel.setStyleSheet("border: 1px solid %s; padding: 4px;" % style.colors()["border"])
        right.addWidget(self.lbl_sel)
        w = QWidget()
        w.setLayout(right)
        w.setFixedWidth(290)
        lay.addWidget(w)

    # -- dossiers ----------------------------------------------------------
    def device_name(self):
        d = self.ctl.current
        return safe_name(d.label) if d else None

    def folder(self) -> Path:
        root = install_root()
        if self.mode == "device" and self.device_name():
            f = root / self.device_name()
        else:
            f = root
        f.mkdir(parents=True, exist_ok=True)
        return f

    def _on_device(self):
        name = self.device_name()
        self.b_dev_dir.setText("Dossier\n%s" % (name or "de l'appareil"))
        self.b_dev_dir.setEnabled(bool(name))
        if not name and self.mode == "device":
            self.b_inst_dir.setChecked(True)
            self.mode = "install"
        if self.isVisible():
            self.refresh()
        else:
            self._fill()

    def _set_mode(self, i):
        self.mode = "device" if i == 1 else "install"
        self.checked.clear()
        self.refresh()

    # -- liste -------------------------------------------------------------
    def refresh(self):
        folder = self.folder()
        for d in self.watcher.directories():
            self.watcher.removePath(d)
        self.watcher.addPath(str(folder))
        self.lbl_hint.setText("Glisse des APK ici ou copie-les dans <b>%s</b>" % html.escape(str(folder)))
        paths = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTS),
                       key=lambda p: p.name.lower())
        self.files = []
        todo = []
        for p in paths:
            key = str(p)
            st = p.stat()
            c = self.cache.get(key)
            if c is None or c.mtime != st.st_mtime or c.size != st.st_size:
                c = ApkFileInfo(p)
                self.cache[key] = c
                todo.append(c)
            self.files.append(c)
        names = {str(f.path) for f in self.files}
        self.checked &= names
        self._fill()
        if todo:
            self._gen += 1
            gen = self._gen

            def work():
                return [(c, read_file_info(c.path)) for c in todo]

            def done(res):
                if isinstance(res, Exception) or gen != self._gen:
                    return
                for c, info in res:
                    c.label, c.package, c.version, c.icon = info.label, info.package, info.version, info.icon
                self._fill()
            self.ctl.submit(work, done=done)

    def set_search(self, t):
        self.search = t.strip().lower()
        self._fill()

    def _visible_files(self):
        s = self.search
        if not s:
            return self.files
        return [f for f in self.files if s in f.path.name.lower() or s in (f.label or "").lower()
                or s in (f.package or "").lower()]

    def _fill(self):
        dev = {p.name: p for p in self.ctl.packages}
        files = self._visible_files()
        self.table.blockSignals(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(files))
        placeholder = style.icon("app", "#7fb8ff", 64)
        muted = QBrush(QColor(style.colors()["muted"]))
        bigf = QFont()
        bigf.setPointSizeF(11)
        for r, f in enumerate(files):
            key = str(f.path)
            ck = QTableWidgetItem()
            ck.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            ck.setCheckState(Qt.Checked if key in self.checked else Qt.Unchecked)
            ck.setData(Qt.UserRole, key)
            self.table.setItem(r, C_CHECK, ck)
            name = f.label or f.path.stem
            it = SortItem(name, name.lower())
            it.setIcon(QIcon(QPixmap.fromImage(f.icon)) if f.icon is not None else placeholder)
            it.setFont(bigf)
            it.setData(Qt.UserRole, key)
            it.setToolTip("%s<br>%s" % (html.escape(name), html.escape(str(f.path))))
            self.table.setItem(r, C_NAME, it)
            fi = QTableWidgetItem(f.path.name)
            fi.setForeground(muted)
            self.table.setItem(r, C_FILE, fi)
            pi = QTableWidgetItem(f.package or "")
            pi.setForeground(muted)
            self.table.setItem(r, C_PKG, pi)
            vi = SortItem(f.version or "", _vkey(f.version))
            vi.setForeground(muted)
            self.table.setItem(r, C_VER, vi)
            state, color = "", None
            if f.package and self.ctl.ready:
                p = dev.get(f.package)
                if p is None or p.deleted:
                    state, color = "Non installée", None
                elif not f.version or not p.version:
                    state, color = "Installée", "#7fb8ff"
                elif _vkey(f.version) > _vkey(p.version):
                    state, color = "Mise à jour (%s)" % p.version, "#e6c22e"
                elif _vkey(f.version) < _vkey(p.version):
                    state, color = "Plus récente installée (%s)" % p.version, "#ff8c3a"
                else:
                    state, color = "Installée (identique)", "#2fd06b"
            si = QTableWidgetItem(state)
            if color:
                si.setForeground(QBrush(QColor(color)))
            self.table.setItem(r, C_STATE, si)
            zi = SortItem(("%.2f Mo" % (f.size / 1048576)).replace(".", ","), f.size)
            zi.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
            zi.setForeground(muted)
            self.table.setItem(r, C_SIZE, zi)
        self.table.setSortingEnabled(True)
        self.table.blockSignals(False)
        self._counts()

    def _counts(self):
        self.lbl_total.setText(str(self.table.rowCount()))
        self.lbl_sel.setText("Sélection : %d" % len(self.checked))
        vis = {str(f.path) for f in self._visible_files()}
        self.cb_all.setChecked(bool(vis) and vis <= self.checked)

    def _item_changed(self, it):
        if it.column() != C_CHECK:
            return
        key = it.data(Qt.UserRole)
        if it.checkState() == Qt.Checked:
            self.checked.add(key)
        else:
            self.checked.discard(key)
        self._counts()

    def _select_all(self, on):
        keys = {str(f.path) for f in self._visible_files()}
        if on:
            self.checked |= keys
        else:
            self.checked -= keys
        self._fill()

    def _row_files(self, rows):
        out = []
        for r in rows:
            it = self.table.item(r, C_NAME)
            if it is not None:
                f = self.cache.get(it.data(Qt.UserRole))
                if f:
                    out.append(f)
        return out

    def _targets(self, selected_only=False):
        sel_rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if selected_only and sel_rows:
            return self._row_files(sel_rows)
        if self.checked:
            return [f for f in self.files if str(f.path) in self.checked]
        return self._row_files(sel_rows)

    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        if not self.table.item(row, C_NAME).isSelected():
            self.table.selectRow(row)
        sel = self._row_files(sorted({i.row() for i in self.table.selectionModel().selectedRows()}))
        m = QMenu(self)
        m.addAction("Installer", lambda: self.install(sel))
        m.addSeparator()
        other = "install" if self.mode == "device" else "device"
        if self.device_name():
            m.addAction("Copier vers le dossier %s" % ("Install" if other == "install" else self.device_name()),
                        lambda: self.copy_to(sel, other))
        m.addAction("Afficher dans le dossier", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(sel[0].path.parent))))
        m.addSeparator()
        m.addAction("Supprimer (corbeille)", lambda: self.delete(sel))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # -- fichiers ----------------------------------------------------------
    def add_files(self, files):
        folder = self.folder()
        n = 0
        for f in files:
            src = Path(f)
            if not src.is_file() or src.suffix.lower() not in EXTS:
                continue
            dst = folder / src.name
            if src.resolve() == dst.resolve():
                continue
            if dst.exists():
                if QMessageBox.question(self, "Fichier existant", "%s existe déjà dans le dossier. Le remplacer ?"
                                        % src.name) != QMessageBox.Yes:
                    continue
            shutil.copy2(src, dst)
            self.checked.add(str(dst))
            n += 1
        if n:
            self.main.toast("%d fichier(s) ajouté(s) à %s" % (n, folder), 3000)
        self.refresh()

    def add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Ajouter des applications", str(Path.home()),
            "Applications Android (*.apk *.apks *.xapk *.apkm)")
        if files:
            self.add_files(files)

    def copy_to(self, files, mode):
        root = install_root()
        dest = root / self.device_name() if mode == "device" else root
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f.path, dest / f.path.name)
        self.main.toast("%d fichier(s) copié(s) vers %s" % (len(files), dest), 3000)

    def delete(self, files):
        if not files:
            self.main.toast("Sélectionne d'abord des fichiers (clic sur la ligne).")
            return
        lst = "\n".join("• " + f.path.name for f in files[:12])
        if QMessageBox.question(self, "Supprimer", "Mettre à la corbeille %d fichier(s) ?\n\n%s"
                                % (len(files), lst)) != QMessageBox.Yes:
            return
        for f in files:
            if not QFile.moveToTrash(str(f.path)):
                try:
                    f.path.unlink()
                except OSError:
                    pass
            self.checked.discard(str(f.path))
        self.refresh()

    # -- installation ------------------------------------------------------
    def install(self, files):
        if not self.ctl.ready:
            self.main.toast("Aucun appareil connecté.")
            return
        if not files:
            self.main.toast("Coche les applications à installer.")
            return
        self.b_quick.setEnabled(False)
        total = len(files)

        def work():
            ok = 0
            for i, f in enumerate(files, 1):
                self.ctl.status.emit("Installation %d/%d : %s…" % (i, total, f.path.name))
                self.ctl.log.emit(">> Installation : %s" % html.escape(f.path.name), "cmd")
                if f.path.suffix.lower() == ".apk":
                    r = adbcore.install_apks([str(f.path)])
                else:
                    r = adbcore.install_bundle(str(f.path), log=lambda s: self.ctl.log.emit(s, "info"))
                if r.ok and "Failure" not in r.out:
                    ok += 1
                    self.ctl.log.emit("[Succès] : %s installé" % html.escape(f.path.name), "ok")
                else:
                    self.ctl.log.emit("[Erreur] : %s — %s" % (html.escape(f.path.name), html.escape(r.text)), "err")
            return ok

        def done(ok):
            self.b_quick.setEnabled(True)
            if isinstance(ok, Exception):
                return
            self.main.toast("Installation : %d/%d réussie(s)%s" % (
                ok, total, "" if ok == total else " — détails dans la Console"))
            self.ctl.refresh_packages()
        self.ctl.submit(work, done=done)

    # -- presets -----------------------------------------------------------
    def save_preset(self):
        names = sorted(Path(k).name for k in self.checked)
        if not names:
            self.main.toast("Coche d'abord les fichiers à mettre dans le preset.")
            return
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getSaveFileName(self, "Enregistrer le preset d'installation",
                                           str(PRESETS_DIR / "install.json"), "Preset (*.json)")
        if not f:
            return
        if not f.endswith(".json"):
            f += ".json"
        Path(f).write_text(json.dumps({"install_files": names}, indent=1, ensure_ascii=False))
        self.main.set_status("Preset enregistré (%d fichiers)" % len(names))

    def load_preset(self):
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getOpenFileName(self, "Charger un preset d'installation", str(PRESETS_DIR),
                                           "Preset (*.json)")
        if not f:
            return
        try:
            d = json.loads(Path(f).read_text())
        except ValueError:
            return
        names = set(d.get("install_files", [])) if isinstance(d, dict) else set()
        self.checked = {str(x.path) for x in self.files if x.path.name in names}
        self._fill()
        self.main.set_status("Preset chargé : %d/%d fichiers trouvés" % (len(self.checked), len(names)))

    # -- glisser-déposer ---------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_files([u.toLocalFile() for u in e.mimeData().urls()])
