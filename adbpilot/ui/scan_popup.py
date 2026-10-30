"""Fenêtre « Détecter » : liste des appareils Android trouvés sur le réseau local."""
from __future__ import annotations

import html
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import netscan
from ..config import config
from ..i18n import _
from . import style

STATE = {  # libellé, couleur, connectable
    "open": (lambda: _("ADB ouvert"), "#2fd06b", True),
    "auth": (lambda: _("ADB actif · autorisation à accepter sur l'écran"), "#7fa4ff", True),
    "tls": (lambda: _("Débogage sans fil (Android 11+)"), "#ffb84d", True),
    "": (lambda: _("ADB fermé"), "#77777b", False),
}


class _Bridge(QObject):
    progress = Signal(int, int, object)
    done = Signal(object, float)


class ScanPopup(QFrame):
    def __init__(self, main):
        # Panneau DANS la fenêtre (pas de Qt.Popup) : un popup système capture clavier et souris,
        # ce qui bloquait les raccourcis globaux du bureau (ex. Impr. écran).
        super().__init__(main)
        self.main = main
        self.hide()
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(36)
        sh.setOffset(0, 8)
        sh.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(sh)
        QApplication.instance().installEventFilter(self)
        self.setObjectName("scanPop")
        self.setStyleSheet("QFrame#scanPop { background: #2f2f33; border: 1.5px solid %s; border-radius: 12px; }"
                           "QFrame#scanPop QLabel { background: transparent; }" % style.ACCENT_LINE)
        self.setFixedWidth(780)
        self._running = False
        self._stop = False
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        t = QLabel(_("Appareils Android sur le réseau"))
        t.setStyleSheet("font-size: 12pt; font-weight: 700;")
        top.addWidget(t)
        top.addStretch(1)
        self.b_again = QPushButton(_("Relancer"))
        self.b_again.clicked.connect(self.start)
        top.addWidget(self.b_again)
        lay.addLayout(top)
        self.sub = QLabel()
        self.sub.setStyleSheet("color: #a9a9ad; font-size: 9pt;")
        lay.addWidget(self.sub)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([_("Appareil"), "IP", "Port", _("État"), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._connect_row(r))
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, wd in ((1, 120), (2, 62), (3, 240), (4, 112)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            h.resizeSection(c, wd)
        lay.addWidget(self.table)
        self.empty = QLabel()
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: #a9a9ad; padding: 12px;")
        self.empty.hide()
        lay.addWidget(self.empty)
        hint = QLabel(_("Nom lu via ADB, mDNS (Cast / Android TV / débogage sans fil), l'historique ou le "
                        "réseau · double-clic = connecter"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8a8e; font-size: 8pt;")
        lay.addWidget(hint)
        self.rows: list = []

    # -- ouverture / scan -----------------------------------------------------
    def open_below(self, button):
        if self.isVisible():  # second clic sur « Détecter » : referme
            self.hide()
            return
        self._button = button
        self._place()
        self.show()
        self.raise_()
        if not self._running:
            self.start()

    def _place(self):
        b = getattr(self, "_button", None)
        if b is None:
            return
        g = b.mapTo(self.main, QPoint(0, b.height() + 6))
        x = min(g.x() + b.width() - self.width() + 190, self.main.width() - self.width() - 8)
        self.move(max(8, x), g.y())

    def eventFilter(self, obj, ev):  # noqa: N802
        if self.isVisible():
            t = ev.type()
            if t == QEvent.MouseButtonPress and isinstance(obj, QWidget) and obj.window() is self.main:
                pos = self.mapFromGlobal(ev.globalPosition().toPoint())
                b = getattr(self, "_button", None)
                on_button = b is not None and b.rect().contains(b.mapFromGlobal(ev.globalPosition().toPoint()))
                if not self.rect().contains(pos) and not on_button:
                    self.hide()  # clic en dehors : on referme (le clic continue normalement)
            elif t == QEvent.KeyPress and ev.key() == Qt.Key_Escape and obj.window() is self.main:
                self.hide()
                return True
            elif t == QEvent.Resize and obj is self.main:
                self._place()
        return False

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop = False
        self.b_again.setEnabled(False)
        nets = netscan.local_networks()
        self._nets = ", ".join(str(n) for n in nets) or "?"
        self.sub.setText(_("Analyse de %s…") % self._nets)
        self.bar.setMaximum(0)
        self.bar.show()
        self._fill([])
        port = str(config.get("port", "auto"))
        port = int(port) if port.isdigit() else 5555
        names = dict(config.get("ip_names", {}))
        t0 = time.time()

        def run():
            try:
                res = netscan.scan(port, names, progress=lambda n, tot, f: self.bridge.progress.emit(n, tot, f),
                                   stop=lambda: self._stop)
            except Exception:  # noqa: BLE001
                res = []
            self.bridge.done.emit(res, time.time() - t0)
        threading.Thread(target=run, daemon=True).start()

    def _on_progress(self, n, total, found):
        self.bar.setMaximum(total)
        self.bar.setValue(n)
        self.sub.setText(_("Analyse de %s… %d/%d") % (self._nets, n, total))
        self._fill(sorted(found, key=lambda f: tuple(int(x) for x in f.ip.split("."))), partial=True)

    def _on_done(self, found, secs):
        self._running = False
        self.b_again.setEnabled(True)
        self.bar.hide()
        n_adb = sum(1 for f in found if f.connectable)
        self.sub.setText(_("%s · analysé en %.0f s · %d appareil(s) avec ADB, %d au total")
                         % (self._nets, secs, n_adb, len(found)))
        self._fill(found)

    # -- tableau ---------------------------------------------------------------
    def _fill(self, found, partial=False):
        self.rows = list(found)
        cur = self.main.ctl.current
        cur_ip = cur.serial.split(":")[0] if cur and cur.is_network else None
        self.table.setRowCount(len(self.rows))
        for r, f in enumerate(self.rows):
            label, color, can = STATE.get(f.adb, STATE[""])
            name = f.name or f.ip
            extra = [d for d in f.details if d and d != name]
            lab = QLabel("<b>%s</b><br><span style='color:#a9a9ad;font-size:8pt'>%s</span>"
                         % (html.escape(name), html.escape(" · ".join(dict.fromkeys(extra))) or "&nbsp;"))
            lab.setContentsMargins(6, 0, 0, 0)
            lab.setEnabled(can)
            self.table.setCellWidget(r, 0, lab)
            for c, v in ((1, f.ip), (2, str(f.port) if f.port else "—")):
                it = QTableWidgetItem(v)
                it.setForeground(QColor("#dcdcdc" if can else "#77777b"))
                self.table.setItem(r, c, it)
            if partial and f.adb == "auth":
                st_txt, st_col = _("Port ADB ouvert…"), "#a9a9ad"
            else:
                st_txt, st_col = label(), color
            st = QTableWidgetItem(("● " if can else "○ ") + st_txt)
            st.setForeground(QColor(st_col))
            st.setToolTip(st_txt)
            self.table.setItem(r, 3, st)
            self.table.removeCellWidget(r, 4)
            if can:
                w = QWidget()
                bl = QHBoxLayout(w)
                bl.setContentsMargins(4, 6, 8, 6)
                connected = cur_ip == f.ip
                b = QPushButton(_("Connecté") if connected else _("Connecter"))
                b.setObjectName("accent")
                b.setEnabled(not connected)
                b.clicked.connect(lambda _x=False, row=r: self._connect_row(row))
                bl.addWidget(b)
                self.table.setCellWidget(r, 4, w)
        shown = min(len(self.rows), 7)
        self.table.setFixedHeight(46 * shown + 30)
        self.table.setVisible(bool(self.rows))
        if not self.rows and not self._running:
            self.empty.setText(_("Aucun appareil trouvé. Vérifie que le débogage ADB réseau est activé sur "
                                 "l'appareil et qu'il est sur le même réseau que l'ordinateur."))
            self.empty.show()
        else:
            self.empty.hide()
        self.adjustSize()
        self.raise_()

    def _connect_row(self, row):
        if not (0 <= row < len(self.rows)):
            return
        f = self.rows[row]
        if not f.connectable:
            return
        if f.name and f.name != f.ip:  # le nom trouvé sert ensuite dans l'historique
            names = dict(config.get("ip_names", {}))
            names.setdefault(f.ip, f.name)
            config["ip_names"] = names
            config.save()
        self.hide()
        self.main.connect_to(f.ip, f.port)
