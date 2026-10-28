"""Gestionnaire de processus : applications en cours, RAM, forcer l'arrêt."""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QLabel,
                               QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import adbcore
from ..adbcore import adb, q
from . import style
from ..i18n import _

# toybox d'abord : sur une box rootée avec BusyBox (Magisk), « ps » est celui de BusyBox, sans -A / RSS
PS_SCRIPT = ("head -3 /proc/meminfo; echo @@PS; toybox ps -A -o PID,USER,RSS,NAME 2>/dev/null || "
             "ps -A -o PID,USER,RSS,NAME 2>/dev/null; echo @@TOP; "
             "dumpsys activity activities 2>/dev/null | grep -m 4 -E 'ResumedActivity'")


class Proc:
    __slots__ = ("pid", "user", "rss", "name", "pkg")

    def __init__(self, pid, user, rss, name):
        self.pid, self.user, self.rss, self.name = pid, user, rss, name
        self.pkg = name.split(":")[0]


def _parse_ps(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    hdr = lines[0].split()
    try:
        i_pid, i_user = hdr.index("PID"), hdr.index("USER")
        i_rss = hdr.index("RSS") if "RSS" in hdr else None
    except ValueError:
        return []
    out = []
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) < len(hdr) - 1 or not parts[i_pid].isdigit():
            continue
        rss = 0
        if i_rss is not None and i_rss < len(parts) and parts[i_rss].isdigit():
            rss = int(parts[i_rss])
        name = parts[-1]
        out.append(Proc(int(parts[i_pid]), parts[i_user], rss, name))
    return out


def list_processes():
    r = adb.shell(PS_SCRIPT, timeout=30)
    ps_part, _, top_part = r.out.partition("@@TOP")
    mem_part, _, ps_part = ps_part.partition("@@PS")
    mm = re.search(r"MemTotal:\s+(\d+)", mem_part)
    total = int(mm.group(1)) if mm else 0
    ma = re.search(r"MemAvailable:\s+(\d+)", mem_part) or re.search(r"MemFree:\s+(\d+)", mem_part)
    used = total - int(ma.group(1)) if (ma and total) else 0
    procs = _parse_ps(ps_part)
    if len(procs) < 5:  # ancien toolbox ps (Android < 8) : pas de -A / -o
        procs = _parse_ps(adb.shell("toybox ps 2>/dev/null || ps", timeout=30).out)
    m = re.search(r"\s([\w.]+)/[\w.$]+", top_part)
    top = m.group(1) if m else None
    return procs, top, (total, used)


def fmt_mem(kb):
    if kb >= 1024 * 1024:
        return ("%.2f " % (kb / 1048576)).replace(".", ",") + _("Go")
    return ("%.1f " % (kb / 1024)).replace(".", ",") + _("Mo")


class NumItem(QTableWidgetItem):
    def __init__(self, text, value):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0)


class ProcessTab(QWidget):
    COLS = ["Application", _("Processus"), "RAM"]

    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self._busy = False
        self.procs: list[Proc] = []
        self.mem_total = 0
        self.mem_used = 0
        self.top = None
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        ctl.device_changed.connect(self._on_device)
        main.tabs.currentChanged.connect(self._tab_changed)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        top = QHBoxLayout()
        self.cb_apps = QCheckBox(_("Applications uniquement"))
        self.cb_apps.setChecked(True)
        self.cb_apps.toggled.connect(lambda _x: self._fill())
        top.addWidget(self.cb_apps)
        self.cb_auto = QCheckBox(_("Actualisation auto (3 s)"))
        self.cb_auto.setChecked(True)
        self.cb_auto.toggled.connect(self._auto_toggled)
        top.addWidget(self.cb_auto)
        top.addStretch(1)
        self.lbl = QLabel()
        top.addWidget(self.lbl)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setIconSize(QSize(26, 26))
        style.fit_rows(self.table, 10)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        h = self.table.horizontalHeader()
        style.resizable_columns(h, "cols_procs", {0: 360, 1: 320, 2: 110})
        h.setHighlightSections(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)

        bot = QHBoxLayout()
        b_ref = QPushButton(_("Rafraîchir"))
        b_ref.clicked.connect(self.refresh)
        b_stop = QPushButton(_("Forcer l'arrêt"))
        b_stop.clicked.connect(lambda: self.force_stop(self._selected()))
        b_all = QPushButton(_("Libérer la mémoire (tout)"))
        b_all.setToolTip("am kill-all : arrête tous les processus en arrière-plan sans risque")
        b_all.clicked.connect(self.kill_all)
        for b in (b_ref, b_stop, b_all):
            b.setMinimumHeight(36)
            bot.addWidget(b)
        bot.addStretch(1)
        lay.addLayout(bot)

    # -- cycle -------------------------------------------------------------
    def _tab_changed(self, i):
        visible = self.main.tabs.widget(i) is self
        if visible:
            self.refresh()
            if self.cb_auto.isChecked():
                self.timer.start(3000)
        else:
            self.timer.stop()

    def _auto_toggled(self, on):
        if on and self.main.tabs.currentWidget() is self:
            self.timer.start(3000)
        else:
            self.timer.stop()

    def _on_device(self, dev):
        self.procs = []
        self.table.setRowCount(0)
        self.lbl.setText("")
        if dev is not None and dev.state == "device" and self.main.tabs.currentWidget() is self:
            self.refresh()

    def refresh(self):
        if self._busy or not self.ctl.ready:
            return
        self._busy = True

        def done(res):
            self._busy = False
            if isinstance(res, Exception):
                return
            self.procs, self.top, (self.mem_total, self.mem_used) = res
            if adbcore._REAL_RAM_KB:  # RAM gonflée par la ROM : on se base sur la vraie capacité
                self.mem_total = min(self.mem_total or adbcore._REAL_RAM_KB, adbcore._REAL_RAM_KB)
                self.mem_used = min(self.mem_used, self.mem_total)
            self._fill()
        self.ctl.submit(list_processes, done=done)

    def _fill(self):
        pk = {p.name: p for p in self.ctl.packages}
        rows = [p for p in self.procs if p.pkg in pk or not self.cb_apps.isChecked()]
        sel = {it.data(Qt.UserRole) for it in self.table.selectedItems() if it.column() == 0}
        sort_col = self.table.horizontalHeader().sortIndicatorSection()
        order = self.table.horizontalHeader().sortIndicatorOrder()
        if self.table.rowCount() == 0 and not sel:
            sort_col, order = 2, Qt.DescendingOrder
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        placeholder = style.icon("app", "#3ddc84", 64)
        bold = QFont()
        bold.setBold(True)
        muted = QBrush(QColor(style.colors()["muted"]))
        for r, p in enumerate(rows):
            pkg = pk.get(p.pkg)
            label = pkg.display if pkg else p.name
            fg = self.top is not None and p.pkg == self.top and ":" not in p.name
            it = QTableWidgetItem(("▶ " if fg else "") + label)
            it.setData(Qt.UserRole, p.pid)
            if pkg is not None:
                it.setIcon(QIcon(QPixmap.fromImage(pkg.icon)) if pkg.icon is not None else placeholder)
            if fg:
                it.setFont(bold)
                it.setForeground(QBrush(QColor("#7fa4ff")))
                it.setToolTip(_("Application au premier plan"))
            self.table.setItem(r, 0, it)
            ip = QTableWidgetItem(p.name)
            ip.setForeground(muted)
            self.table.setItem(r, 1, ip)
            pct = (p.rss * 100.0 / self.mem_total) if self.mem_total and p.rss else 0
            ir = NumItem(("%.1f %%" % pct).replace(".", ",") if p.rss else "", p.rss)
            ir.setToolTip(_("%s · PID %d · %s") % (fmt_mem(p.rss), p.pid, p.user))
            self.table.setItem(r, 2, ir)
        self.table.setSortingEnabled(True)
        self.table.sortItems(sort_col, order)
        if sel:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(Qt.UserRole) in sel:
                    self.table.selectRow(r)
        # La somme des RSS compte plusieurs fois la mémoire partagée (bibliothèques, zygote) :
        # on affiche plutôt la RAM réellement utilisée par le système, comme l'onglet Applications.
        if self.mem_total:
            self.lbl.setText(_("%d processus · RAM utilisée : %s / %s (%d %%)") % (
                len(rows), fmt_mem(self.mem_used), fmt_mem(self.mem_total),
                round(self.mem_used * 100.0 / self.mem_total)))
        else:
            self.lbl.setText(_("%d processus") % len(rows))
        self.lbl.setToolTip(_("La colonne RAM indique la mémoire résidente (RSS) de chaque processus. "
                              "Une partie est partagée entre processus : additionner la colonne "
                              "dépasse donc la RAM réellement utilisée."))

    # -- actions -----------------------------------------------------------
    def _selected(self) -> list[Proc]:
        pids = {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectionModel().selectedRows()}
        return [p for p in self.procs if p.pid in pids]

    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        if not self.table.item(row, 0).isSelected():
            self.table.selectRow(row)
        sel = self._selected()
        if not sel:
            return
        m = QMenu(self)
        for text, fn in [(_("Forcer l'arrêt"), lambda: self.force_stop(sel)),
                         (_("Tuer le processus (kill -9)"), lambda: self.kill_pid(sel))]:
            a = QAction(text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        pk = {p.name: p for p in self.ctl.packages}
        p0 = pk.get(sel[0].pkg)
        if p0 is not None:
            m.addSeparator()
            from .dialogs import AppInfoDialog
            m.addAction(_("Infos sur l'application…"), lambda: AppInfoDialog(self.ctl, p0, self).exec())
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _run(self, label, cmds):
        if not cmds or not self.ctl.ready:
            return

        def work():
            for c in cmds:
                self.ctl.log.emit(">> adb shell " + html.escape(c), "cmd")
                r = adb.shell(c, timeout=20)
                if r.text:
                    self.ctl.log.emit(html.escape(r.text), "out" if r.ok else "err")
        self.main.set_status(label)
        self.ctl.submit(work, done=lambda _x: QTimer.singleShot(600, self.refresh))

    def force_stop(self, procs):
        pkgs = sorted({p.pkg for p in procs})
        if not pkgs:
            self.main.toast(_("Sélectionne un ou plusieurs processus."))
            return
        if any(x in pkgs for x in ("android", "com.android.systemui", "system_server")):
            if QMessageBox.question(self, _("Attention"), _("La sélection contient un composant système "
                                    "critique. Forcer l'arrêt peut faire redémarrer l'interface. Continuer ?")) != QMessageBox.Yes:
                return
        self._run(_("Arrêt forcé : %s") % ", ".join(pkgs), ["am force-stop " + q(x) for x in pkgs])

    def kill_pid(self, procs):
        self._run("kill -9", ["kill -9 %d" % p.pid for p in procs])

    def kill_all(self):
        self._run(_("Libération de la mémoire"), ["am kill-all"])
