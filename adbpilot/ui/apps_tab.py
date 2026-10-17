from __future__ import annotations

import html
import json
import re
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel, Qt,
                            Signal)
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox,
                               QProgressBar, QPushButton, QRadioButton, QSizePolicy, QStackedWidget, QTableView,
                               QVBoxLayout, QWidget)

from .. import adbcore, debloat
from ..adbcore import Package
from ..config import PRESETS_DIR
from . import style
from .dialogs import AppInfoDialog, DebloatWizard, PermissionsDialog

COL_CHECK, COL_NAME, COL_PKG, COL_VERSION, COL_SIZE = range(5)
HEADERS = ["", "Nom de l'application", "Paquet", "Version", "Taille"]


def fmt_size(n):
    if not n:
        return ""
    return ("%.2f" % (n / 1048576)).replace(".", ",") + " Mo"


class AppModel(QAbstractTableModel):
    checked_changed = Signal()

    def __init__(self):
        super().__init__()
        self.pkgs: list[Package] = []
        self.index_of: dict[str, int] = {}
        self.checked: set[str] = set()
        self._placeholder = None
        self._icon_cache: dict[int, QIcon] = {}

    def placeholder(self):
        if self._placeholder is None:
            self._placeholder = style.icon("app", "#3ddc84", 64)
        return self._placeholder

    def set_packages(self, pkgs):
        self.beginResetModel()
        self.pkgs = list(pkgs)
        self.index_of = {p.name: i for i, p in enumerate(self.pkgs)}
        names = set(self.index_of)
        self.checked &= names
        self._icon_cache.clear()
        self.endResetModel()
        self.checked_changed.emit()

    def update_package(self, p: Package):
        i = self.index_of.get(p.name)
        if i is None:
            return
        self.pkgs[i] = p
        self._icon_cache.pop(id(p), None)
        self.dataChanged.emit(self.index(i, 0), self.index(i, len(HEADERS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.pkgs)

    def columnCount(self, parent=QModelIndex()):
        return len(HEADERS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[s]
        return None

    def flags(self, idx):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if idx.column() == COL_CHECK:
            f |= Qt.ItemIsUserCheckable
        return f

    def data(self, idx, role=Qt.DisplayRole):
        p = self.pkgs[idx.row()]
        c = idx.column()
        if role == Qt.UserRole:
            return p
        if c == COL_CHECK and role == Qt.CheckStateRole:
            return Qt.Checked if p.name in self.checked else Qt.Unchecked
        if role == Qt.DisplayRole:
            if c == COL_NAME:
                return p.display
            if c == COL_PKG:
                return p.name
            if c == COL_SIZE:
                return fmt_size(p.size)
            if c == COL_VERSION:
                return p.version or ""
        if role == Qt.UserRole + 1:  # tri
            if c == COL_NAME:
                return p.display.lower()
            if c == COL_SIZE:
                return p.size
            if c == COL_VERSION:
                return ".".join("%09d" % (int(x) if x.isdigit() else 0)
                                for x in (re.split(r"[.\-_ ]", p.version or "") + ["0"] * 6)[:6])
            if c == COL_CHECK:
                return 0 if p.name in self.checked else 1
            return p.name
        if role == Qt.DecorationRole and c == COL_NAME:
            ic = self._icon_cache.get(id(p))
            if ic is None:
                ic = QIcon(QPixmap.fromImage(p.icon)) if p.icon is not None else self.placeholder()
                self._icon_cache[id(p)] = ic
            return ic
        if role == Qt.ForegroundRole:
            if p.deleted:
                return QBrush(QColor("#ff5c5c"))
            if p.disabled:
                return QBrush(QColor("#8a8a8e"))
            if c in (COL_PKG, COL_SIZE, COL_VERSION):
                return QBrush(QColor(style.colors()["muted"]))
        if role == Qt.FontRole and c == COL_NAME:
            f = QFont()
            f.setPointSizeF(11)
            if p.disabled or p.deleted:
                f.setItalic(True)
            return f
        if role == Qt.TextAlignmentRole and c == COL_SIZE:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            lines = ["<b>%s</b><br>%s" % (html.escape(p.display), html.escape(p.name))]
            if p.version:
                lines.append("Version : %s" % html.escape(p.version))
            state = "supprimée (utilisateur 0)" if p.deleted else ("désactivée" if p.disabled else "active")
            lines.append("%s · %s" % ("Système" if p.system else "Utilisateur", state))
            lines.append(html.escape(p.path))
            lv = next((i for i in range(4) if debloat.matches_level(p.name, i)), None)
            if lv is not None:
                lines.append("<hr><b>Liste debloat : %s</b> (debloat%d.db)" % (debloat.LEVELS[lv][0], lv))
            d = debloat.info(p.name)
            if d and d.get("description"):
                lines.append("<span style='color:#aaa'>%s</span>" % html.escape(
                    d["description"].strip().splitlines()[0][:160]))
            return "<br>".join(lines)
        return None

    def setData(self, idx, value, role=Qt.EditRole):
        if idx.column() == COL_CHECK and role == Qt.CheckStateRole:
            p = self.pkgs[idx.row()]
            if Qt.CheckState(value) == Qt.Checked:
                self.checked.add(p.name)
            else:
                self.checked.discard(p.name)
            self.dataChanged.emit(idx, idx)
            self.checked_changed.emit()
            return True
        return False

    def set_checked(self, names, on=True):
        names = set(names) & set(self.index_of)
        if on:
            self.checked |= names
        else:
            self.checked -= names
        if self.pkgs:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.pkgs) - 1, 0))
        self.checked_changed.emit()


class AppFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.mode = "all"
        self.text = ""
        self.setSortRole(Qt.UserRole + 1)
        self.setDynamicSortFilter(False)

    def set_mode(self, m):
        self.mode = m
        self.invalidateFilter()

    def set_text(self, t):
        self.text = t.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        p: Package = self.sourceModel().pkgs[row]
        m = self.mode
        if m == "deleted":
            ok = p.deleted
        elif p.deleted:
            ok = False
        elif m == "system":
            ok = p.system
        elif m == "user":
            ok = not p.system
        elif m == "disabled":
            ok = p.disabled
        else:
            ok = True
        if ok and self.text:
            ok = self.text in p.name.lower() or (p.label and self.text in p.label.lower())
        return ok


BACKUP = "Sauvegarder le fichier d'installation"
ACTIONS = [
    ("Désactiver", adbcore.act_disable, True),
    ("Activer", adbcore.act_enable, False),
    ("Désinstaller", adbcore.act_uninstall, True),
    ("Restaurer (réinstaller)", adbcore.act_restore, False),
    ("Forcer l'arrêt", adbcore.act_force_stop, False),
    ("Effacer les données", adbcore.act_clear, True),
    ("Effacer le cache", adbcore.act_clear_cache, False),
    (BACKUP, None, False),
]
COMBO_ACTIONS = ["Désactiver", "Désinstaller", "Effacer les données", "Effacer le cache", BACKUP]
WIPE_CAPABLE = ("Désactiver", "Désinstaller")


class AppsTab(QWidget):
    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self.model = AppModel()
        self.proxy = AppFilter()
        self.proxy.setSourceModel(self.model)
        self._build()
        ctl.packages_ready.connect(self._on_packages)
        ctl.package_meta.connect(self.model.update_package)
        ctl.ram_ready.connect(self._on_ram)
        ctl.device_changed.connect(self._on_device)
        self.model.checked_changed.connect(self._update_counts)

    # -- construction ------------------------------------------------------
    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        page = QWidget()
        self.stack.addWidget(page)
        from .installer import InstallerPage
        self.installer = InstallerPage(self.ctl, self.main, self)
        self.stack.addWidget(self.installer)
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        left = QVBoxLayout()
        left.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 0)
        self.cb_all = QCheckBox("Tout sélectionner")
        self.cb_all.clicked.connect(self._select_all)
        top.addWidget(self.cb_all)
        tot = QVBoxLayout()
        tot.setSpacing(0)
        t1 = QLabel("Total :")
        t1.setObjectName("muted")
        t1.setStyleSheet("font-size: 7pt;")
        self.lbl_total = QLabel("0")
        tot.addWidget(t1)
        tot.addWidget(self.lbl_total)
        top.addSpacing(16)
        top.addLayout(tot)
        top.addStretch(1)
        self.filters = QButtonGroup(self)
        for i, (lab, mode) in enumerate([("Toutes", "all"), ("Système", "system"),
                                         ("Utilisateur", "user"), ("Désactivées", "disabled"),
                                         ("Supprimées", "deleted")]):
            rb = QRadioButton(lab)
            rb.setProperty("mode", mode)
            if i == 0:
                rb.setChecked(True)
            self.filters.addButton(rb, i)
            top.addWidget(rb)
        self.filters.buttonClicked.connect(lambda b: self._set_mode(b.property("mode")))
        left.addLayout(top)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(COL_NAME, Qt.AscendingOrder)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(40)
        self.view.setIconSize(QSize(30, 30))
        self.view.setShowGrid(False)
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideRight)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        h.resizeSection(COL_CHECK, 30)
        h.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_PKG, QHeaderView.Interactive)
        h.resizeSection(COL_PKG, 320)
        h.setSectionResizeMode(COL_VERSION, QHeaderView.Interactive)
        h.resizeSection(COL_VERSION, 120)
        h.setSectionResizeMode(COL_SIZE, QHeaderView.Fixed)
        h.resizeSection(COL_SIZE, 90)
        h.setHighlightSections(False)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(self._double_click)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._update_counts())
        left.addWidget(self.view, 1)
        self.meta_bar = QProgressBar()
        self.meta_bar.setMaximumHeight(4)
        self.meta_bar.setTextVisible(False)
        self.meta_bar.hide()
        left.addWidget(self.meta_bar)
        lay.addLayout(left, 1)

        # Panneau droit
        right = QVBoxLayout()
        right.setContentsMargins(0, 6, 6, 6)
        right.setSpacing(6)
        grid = QGridLayout()
        grid.setSpacing(0)
        b_upd = QPushButton("Mettre à jour les données")
        b_upd.clicked.connect(self.ctl.refresh_packages)
        b_lp = QPushButton("Charger un preset")
        b_lp.clicked.connect(self.load_preset)
        b_sp = QPushButton("Enregistrer le preset")
        b_sp.clicked.connect(self.save_preset)
        b_perm = QPushButton("Permissions")
        b_perm.clicked.connect(self._permissions_selected)
        b_up = QPushButton("Envoyer des fichiers")
        b_up.clicked.connect(self.push_files)
        b_inst = QPushButton("Installer…")
        b_inst.clicked.connect(self.show_installer)
        grid.addWidget(b_upd, 0, 0, 1, 2)
        grid.addWidget(b_lp, 1, 0)
        grid.addWidget(b_sp, 1, 1)
        grid.addWidget(b_perm, 2, 0)
        grid.addWidget(b_up, 2, 1)
        grid.addWidget(b_inst, 3, 0, 1, 2)
        for b in (b_upd, b_lp, b_sp, b_perm, b_up, b_inst):
            b.setMinimumHeight(40)
        right.addLayout(grid)
        right.addSpacing(10)
        ram = QHBoxLayout()
        ram.addWidget(QLabel("RAM"))
        ram.addStretch(1)
        self.lbl_ram = QLabel("– / – Mo")
        ram.addWidget(self.lbl_ram)
        right.addLayout(ram)
        self.bar_ram = QProgressBar()
        self.bar_ram.setTextVisible(False)
        self.bar_ram.setMaximumHeight(10)
        right.addWidget(self.bar_ram)
        right.addSpacing(18)
        b_wiz = QPushButton("  Trouver et désactiver\n  le bloatware de l'appareil")
        b_wiz.setObjectName("debloat")
        b_wiz.setIcon(style.icon("debloat", "#cfcfcf", 64))
        b_wiz.setIconSize(QSize(34, 34))
        b_wiz.clicked.connect(self.open_wizard)
        right.addWidget(b_wiz)
        right.addStretch(1)
        self.lbl_sel = QLabel("Sélection : 0")
        self.lbl_sel.setStyleSheet("border: 1px solid %s; padding: 4px;" % style.colors()["border"])
        right.addWidget(self.lbl_sel)
        self.cb_wipe = QCheckBox("Effacer aussi les données de l'appli")
        right.addWidget(self.cb_wipe)
        act = QHBoxLayout()
        self.cmb_action = QComboBox()
        self.cmb_action.addItems(COMBO_ACTIONS)
        self.cmb_action.currentTextChanged.connect(
            lambda t: self.cb_wipe.setVisible(t in WIPE_CAPABLE))
        self.cmb_action.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        act.addWidget(self.cmb_action, 1)
        b_apply = QPushButton("Appliquer")
        b_apply.setMinimumHeight(40)
        b_apply.setMinimumWidth(90)
        b_apply.clicked.connect(self.apply_action)
        act.addWidget(b_apply)
        right.addLayout(act)
        w = QWidget()
        w.setLayout(right)
        w.setFixedWidth(290)
        lay.addWidget(w)

    # -- événements --------------------------------------------------------
    def show_installer(self):
        self.installer.refresh()
        self.stack.setCurrentWidget(self.installer)

    def show_apps(self):
        self.stack.setCurrentIndex(0)

    def installer_visible(self):
        return self.stack.currentWidget() is self.installer

    def _on_device(self, dev):
        serial = dev.serial if dev else None
        if serial != getattr(self, "_serial", None):
            self._serial = serial
            self.model.checked.clear()
            self.cmb_action.setCurrentText("Désactiver")
            self.cb_wipe.setChecked(False)
        if dev is None or dev.state != "device":
            self.model.set_packages([])
            self.lbl_total.setText("0")
            self.lbl_ram.setText("– / – Mo")
            self.bar_ram.setValue(0)

    def _on_packages(self, pkgs):
        sort_col = self.view.horizontalHeader().sortIndicatorSection()
        order = self.view.horizontalHeader().sortIndicatorOrder()
        self.model.set_packages(pkgs)
        self.proxy.sort(sort_col, order)
        self._update_counts()

    def _on_ram(self, used, total):
        self.lbl_ram.setText("%d / %d Mo" % (used, total))
        self.bar_ram.setMaximum(max(total, 1))
        self.bar_ram.setValue(used)

    def meta_progress(self, n, total):
        if n >= total:
            self.meta_bar.hide()
            self.proxy.invalidate()
            self.proxy.sort(self.view.horizontalHeader().sortIndicatorSection(),
                            self.view.horizontalHeader().sortIndicatorOrder())
            self.main.set_status("Noms et icônes à jour")
        else:
            self.meta_bar.show()
            self.meta_bar.setMaximum(total)
            self.meta_bar.setValue(n)
            if n % 10 == 0:
                self.main.set_status("Lecture des noms et icônes… %d/%d" % (n, total))

    def _set_mode(self, mode):
        self.proxy.set_mode(mode)
        self._update_counts()

    def set_search(self, text):
        self.installer.set_search(text)
        self.proxy.set_text(text)
        self._update_counts()

    def _update_counts(self):
        self.lbl_total.setText(str(self.proxy.rowCount()))
        n = len(self.model.checked)
        self.lbl_sel.setText("Sélection : %d" % n)
        vis = [self.proxy.mapToSource(self.proxy.index(r, 0)).row() for r in range(self.proxy.rowCount())]
        allv = bool(vis) and all(self.model.pkgs[r].name in self.model.checked for r in vis)
        self.cb_all.setChecked(allv)

    def _select_all(self, on):
        names = [self.model.pkgs[self.proxy.mapToSource(self.proxy.index(r, 0)).row()].name
                 for r in range(self.proxy.rowCount())]
        self.model.set_checked(names, on)

    # -- sélection ---------------------------------------------------------
    def selected_packages(self) -> list[Package]:
        rows = {self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedRows()}
        return [self.model.pkgs[r] for r in sorted(rows)]

    def target_packages(self) -> list[Package]:
        if self.model.checked:
            return [p for p in self.model.pkgs if p.name in self.model.checked]
        return self.selected_packages()

    def _pkg_at(self, proxy_idx) -> Package | None:
        if not proxy_idx.isValid():
            return None
        return self.model.pkgs[self.proxy.mapToSource(proxy_idx).row()]

    def _double_click(self, idx):
        if idx.column() == COL_CHECK:
            return
        p = self._pkg_at(idx)
        if p:
            AppInfoDialog(self.ctl, p, self).exec()

    def _context_menu(self, pos):
        idx = self.view.indexAt(pos)
        p = self._pkg_at(idx)
        if not p:
            return
        sel = self.selected_packages()
        if p not in sel:
            self.view.selectRow(idx.row())
            sel = [p]
        m = QMenu(self)

        def add(text, fn, enabled=True):
            a = QAction(text, m)
            a.setEnabled(enabled)
            a.triggered.connect(fn)
            m.addAction(a)
        add("Infos…", lambda: AppInfoDialog(self.ctl, p, self).exec())
        add("Lancer", lambda: self.run_action(adbcore.act_launch, [p], "Lancement"), not p.deleted)
        add("Permissions…", lambda: PermissionsDialog(self.ctl, p, self).exec(), not p.deleted)
        m.addSeparator()
        add("Cocher", lambda: self.model.set_checked([x.name for x in sel], True))
        add("Décocher", lambda: self.model.set_checked([x.name for x in sel], False))
        m.addSeparator()
        for name, fn, confirm in ACTIONS:
            if fn is None:
                add(name, lambda: self.backup(sel))
            else:
                add(name, lambda _=False, f=fn, n=name, c=confirm: self.run_action(f, sel, n, c))
        m.addSeparator()
        add("Copier le nom du paquet", lambda: QGuiApplication.clipboard().setText(
            "\n".join(x.name for x in sel)))
        m.exec(self.view.viewport().mapToGlobal(pos))

    # -- actions -----------------------------------------------------------
    def apply_action(self):
        name = self.cmb_action.currentText()
        pkgs = self.target_packages()
        if not pkgs:
            self.main.toast("Aucune application cochée.")
            return
        fn, confirm = next((f, c) for n, f, c in ACTIONS if n == name)
        if fn is None:
            self.backup(pkgs)
        else:
            wipe = self.cb_wipe.isChecked() and name in WIPE_CAPABLE
            self.run_action(fn, pkgs, name, confirm, wipe=wipe)

    def run_action(self, fn, pkgs, name, confirm=False, wipe=False):
        if not self.ctl.ready:
            self.main.toast("Aucun appareil connecté.")
            return
        if confirm:
            lst = "\n".join("• %s (%s)" % (p.display, p.name) for p in pkgs[:15])
            if len(pkgs) > 15:
                lst += "\n… et %d autres" % (len(pkgs) - 15)
            extra = "\n\n⚠ Les données de ces applications seront aussi effacées." if wipe else ""
            if QMessageBox.question(self, name, "%s %d application(s) ?\n\n%s%s" % (
                    name, len(pkgs), lst, extra)) != QMessageBox.Yes:
                return
        self.main.set_status("%s…" % name)

        def good(r):
            return r.ok and not any(w in r.out for w in ("Failure", "Error", "Exception"))

        def work():
            ok = 0
            for p in pkgs:
                if wipe:
                    self.ctl.log.emit(">> Effacer les données : %s" % p.name, "cmd")
                    rc = adbcore.act_clear(p)
                    self.ctl.log.emit(html.escape(rc.text or ""), "out" if good(rc) else "err")
                r = fn(p)
                self.ctl.log.emit(">> %s : %s" % (name, p.name), "cmd")
                if fn is adbcore.act_clear_cache and r.rc == 2:
                    self.ctl.log.emit("Vidage du cache appli par appli non supporté avant Android 14 "
                                      "(sans root) : vidage du cache de toutes les applications "
                                      "(pm trim-caches).", "info")
                    rt = adbcore.trim_all_caches()
                    self.ctl.log.emit("[Succès] : caches vidés" if rt.ok else "[Erreur] : " + html.escape(rt.text),
                                      "ok" if rt.ok else "err")
                    return len(pkgs) if rt.ok else 0
                if good(r):
                    ok += 1
                    if r.text:
                        self.ctl.log.emit(html.escape(r.text), "out")
                else:
                    self.ctl.log.emit("[Erreur] : " + html.escape(r.text or "échec"), "err")
            return ok

        def done(ok):
            if isinstance(ok, Exception):
                return
            self.main.toast("%s : %d/%d réussie(s)" % (name, ok, len(pkgs)), 4000)
            self.ctl.log.emit("[Succès] : %s — %d/%d" % (name, ok, len(pkgs)),
                              "ok" if ok == len(pkgs) else "err")
            if fn not in (adbcore.act_launch, adbcore.act_force_stop, adbcore.act_clear_cache):
                self.ctl.refresh_packages()
                self.ctl.refresh_ram()
        self.ctl.submit(work, done=done)

    def backup(self, pkgs):
        if not self.ctl.ready or not pkgs:
            return
        dev = self.ctl.current.label
        self.main.set_status("Sauvegarde de %d application(s)…" % len(pkgs))

        def work():
            n, last = 0, None
            for p in pkgs:
                self.ctl.log.emit(">> Sauvegarde de %s" % p.name, "cmd")
                ok, msg = adbcore.backup_apk(p, dev)
                self.ctl.log.emit(("[Succès] : " if ok else "[Erreur] : ") + html.escape(msg),
                                  "ok" if ok else "err")
                n += ok
                if ok:
                    last = msg
            return n, last

        def done(res):
            if isinstance(res, Exception):
                return
            n, last = res
            folder = str(Path(last).parent) if last else ""
            self.main.toast("%d fichier(s) sauvegardé(s)%s" % (n, ("\n" + folder) if folder else ""), 6000)
        self.ctl.submit(work, done=done)

    def _permissions_selected(self):
        sel = self.selected_packages() or self.target_packages()
        if not sel:
            self.main.toast("Sélectionne une application (clic sur sa ligne).")
            return
        PermissionsDialog(self.ctl, sel[0], self).exec()

    def push_files(self):
        if not self.ctl.ready:
            self.main.toast("Aucun appareil connecté.")
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Envoyer vers /sdcard/Download", str(Path.home()))
        if not files:
            return

        def work():
            for f in files:
                self.ctl.adb_logged(["push", f, "/sdcard/Download/"], timeout=3600,
                                    ok_msg="%s envoyé dans /sdcard/Download" % Path(f).name)
        self.ctl.submit(work, done=lambda _: self.main.set_status("Envoi terminé"))

    # -- presets -----------------------------------------------------------
    def save_preset(self):
        names = sorted(self.model.checked)
        if not names:
            self.main.toast("Coche d'abord les applications à mettre dans le preset.")
            return
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getSaveFileName(self, "Enregistrer le preset",
                                           str(PRESETS_DIR / "preset.json"), "Preset (*.json)")
        if not f:
            return
        if not f.endswith(".json"):
            f += ".json"
        Path(f).write_text(json.dumps({"packages": names}, indent=1))
        self.main.set_status("Preset enregistré (%d applis)" % len(names))

    def load_preset(self):
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getOpenFileName(self, "Charger un preset", str(PRESETS_DIR),
                                           "Preset (*.json *.txt)")
        if not f:
            return
        txt = Path(f).read_text(errors="replace")
        try:
            d = json.loads(txt)
            names = d.get("packages", []) if isinstance(d, dict) else list(d)
        except ValueError:
            names = [ln.strip().replace("package:", "") for ln in txt.splitlines() if ln.strip()]
        self.model.checked.clear()
        self.model.set_checked(names, True)
        found = len(self.model.checked)
        self.main.set_status("Preset chargé : %d/%d applis présentes sur l'appareil" % (found, len(names)))

    # -- debloat -----------------------------------------------------------
    def open_wizard(self):
        if not self.model.pkgs:
            self.main.toast("Connecte un appareil et attends le chargement des applications.")
            return
        dlg = DebloatWizard(self, [p.name for p in self.model.pkgs if not p.deleted and not p.disabled])
        if dlg.exec():
            level = dlg.level
            names = [p.name for p in self.model.pkgs
                     if not p.deleted and not p.disabled and debloat.matches_level(p.name, level)]
            self.model.checked.clear()
            self.model.set_checked(names, True)
            self.filters.button(0).setChecked(True)
            self._set_mode("all")
            self.view.sortByColumn(COL_CHECK, Qt.AscendingOrder)
            self.cmb_action.setCurrentText("Désactiver")
            self.main.toast("%d application(s) cochée(s) (niveau %s). Vérifie la liste puis clique "
                            "sur Appliquer pour les désactiver." % (len(names), debloat.LEVELS[level][0]))
