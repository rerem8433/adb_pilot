"""Fenêtre de progression par-dessus l'écran principal (bloque l'interface pendant une opération)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from . import style
from ..i18n import _

ROWS = 4  # nombre de lignes de détail visibles
STATES = {  # symbole, couleur
    "wait": ("·", "#8a8a8e"),
    "run": ("⟳", "#7fa4ff"),
    "ok": ("✔", "#2fd06b"),
    "err": ("✖", "#ff5c5c"),
    "skip": ("–", "#8a8a8e"),
}


class _Row(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.setFixedHeight(28)
        self.state = QLabel()
        self.state.setFixedWidth(16)
        self.icon = QLabel()
        self.icon.setFixedSize(24, 24)
        self.text = QLabel()
        self.text.setTextFormat(Qt.PlainText)
        lay.addWidget(self.state)
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)

    def set(self, label, icon, state, detail=""):
        sym, col = STATES.get(state, STATES["wait"])
        self.state.setText(sym)
        self.state.setStyleSheet("color:%s; font-weight:700;" % col)
        if icon is not None and not icon.isNull():
            self.icon.setPixmap(QPixmap.fromImage(icon).scaled(
                24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.icon.setPixmap(style.icon("app", "#5d6676", 48).pixmap(24, 24))
        txt = label + ((" — " + detail) if detail else "")
        self.text.setText(self.text.fontMetrics().elidedText(txt, Qt.ElideRight, 380))
        self.text.setStyleSheet("color:%s;" % ("#ff9b9b" if state == "err" else "#dcdcdc"))
        self.show()


class ProgressOverlay(QWidget):
    """Voile + carte centrale. start() / item() / advance() / finish()."""

    def __init__(self, parent, header=None):
        super().__init__(parent)
        self.header = header
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        self.on_cancel = None
        self.items: dict = {}   # clé -> [label, icône, état, détail]
        self.order: list = []
        self.done = 0
        self.total = 0
        self.errors = 0
        self.cancelled = False

        self.card = QFrame(self)
        self.card.setObjectName("progressCard")
        self.card.setFixedWidth(520)
        self.card.setStyleSheet(
            "QFrame#progressCard { background: #2f2f33; border: 1.5px solid %s; border-radius: 16px; }"
            "QFrame#progressCard QLabel { background: transparent; border: none; }" % style.ACCENT_LINE)
        sh = QGraphicsDropShadowEffect(self.card)
        sh.setBlurRadius(40)
        sh.setOffset(0, 8)
        sh.setColor(QColor(0, 0, 0, 160))
        self.card.setGraphicsEffect(sh)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(style.logo_icon().pixmap(QSize(40, 40)))
        top.addWidget(logo, 0, Qt.AlignTop)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 14pt; font-weight: 700; color: #f0f0f0;")
        self.sub = QLabel()
        self.sub.setStyleSheet("font-size: 9pt; color: #a9a9ad;")
        tcol.addWidget(self.title)
        tcol.addWidget(self.sub)
        top.addLayout(tcol, 1)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setStyleSheet("QProgressBar { background: #232325; border: none; border-radius: 5px; }"
                               "QProgressBar::chunk { border-radius: 5px; background: qlineargradient("
                               "x1:0, y1:0, x2:1, y2:0, stop:0 %s, stop:1 #7fa4ff); }" % style.ACCENT_LINE)
        lay.addWidget(self.bar)
        cnt = QHBoxLayout()
        self.count = QLabel()
        self.pct = QLabel()
        for w in (self.count, self.pct):
            w.setStyleSheet("font-weight: 700; color: #f0f0f0;")
        cnt.addWidget(self.count)
        cnt.addStretch(1)
        cnt.addWidget(self.pct)
        lay.addLayout(cnt)
        self.rows = [_Row() for _i in range(ROWS)]
        for r in self.rows:
            lay.addWidget(r)
        bot = QHBoxLayout()
        bot.addStretch(1)
        self.btn = QPushButton(_("Annuler"))
        self.btn.setMinimumSize(130, 34)
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setStyleSheet("QPushButton { background: #3a3a3e; border: 1px solid #5a5a60; border-radius: 8px; }"
                               "QPushButton:hover { background: #47474c; }")
        self.btn.clicked.connect(self._button)
        bot.addWidget(self.btn)
        lay.addLayout(bot)
        self._hide_t = QTimer(self)
        self._hide_t.setSingleShot(True)
        self._hide_t.timeout.connect(self.close_overlay)
        parent.installEventFilter(self)

    # -- API ---------------------------------------------------------------
    def start(self, title, subtitle, total, on_cancel=None):
        self._hide_t.stop()
        self.items.clear()
        self.order.clear()
        self.done = self.errors = 0
        self.total = max(1, total)
        self.cancelled = False
        self.on_cancel = on_cancel
        self.title.setText(title)
        self.sub.setText(subtitle)
        self.btn.setText(_("Annuler"))
        self.btn.setEnabled(True)
        self._refresh()
        self._geometry()
        self.show()
        self.raise_()
        self.setFocus()

    def item(self, key, label, icon=None, state="run", detail=""):
        """Ajoute ou met à jour une ligne (les plus récentes restent visibles)."""
        if key not in self.items:
            self.order.append(key)
        self.items[key] = [label, icon, state, detail]
        if state == "err":
            self.errors += 1
        self._refresh()

    def advance(self, n=1):
        self.done = min(self.total, self.done + n)
        self._refresh()

    def set_done(self, n):
        self.done = min(self.total, n)
        self._refresh()

    def finish(self, title=None):
        """Fin : fermeture automatique, sauf s'il y a eu des échecs (on laisse lire)."""
        self.on_cancel = None
        if self.cancelled:
            self.title.setText(_("Opération annulée"))
        elif title:
            self.title.setText(title)
        if self.errors:
            self.sub.setText(_("%d échec(s) — détails dans la Console") % self.errors)
            self.btn.setText(_("Fermer"))
            self.btn.setEnabled(True)
            self._show_errors_first()
        else:
            self.set_done(self.total if not self.cancelled else self.done)
            self._hide_t.start(700)

    def close_overlay(self):
        self._hide_t.stop()
        self.hide()

    # -- interne -----------------------------------------------------------
    def _button(self):
        if self.on_cancel is None:  # bouton « Fermer »
            self.close_overlay()
            return
        self.cancelled = True
        self.btn.setEnabled(False)
        self.btn.setText(_("Annulation…"))
        cb, self.on_cancel = self.on_cancel, None
        cb()

    def _show_errors_first(self):
        errs = [k for k in self.order if self.items[k][2] == "err"]
        others = [k for k in self.order if self.items[k][2] != "err"]
        self.order = others + errs  # les échecs à la fin = visibles
        self._refresh()

    def _refresh(self):
        self.bar.setMaximum(self.total)
        self.bar.setValue(self.done)
        self.count.setText("%d / %d" % (self.done, self.total))
        self.pct.setText("%d %%" % (100 * self.done // self.total))
        keys = self.order[-ROWS:]
        for i, r in enumerate(self.rows):
            if i < len(keys):
                r.set(*self.items[keys[i]])
            else:
                r.hide()
        if self.isVisible():
            self._geometry()

    def _geometry(self):
        p = self.parentWidget()
        self.setGeometry(0, 0, p.width(), p.height())
        top = self._top()
        self.card.layout().activate()
        self.card.setFixedHeight(self.card.layout().sizeHint().height())
        self.card.move((self.width() - self.card.width()) // 2,
                       top + max(10, (self.height() - top - self.card.height()) // 2))

    def _top(self):
        return self.header.height() if self.header is not None else 0

    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.parentWidget() and ev.type() == QEvent.Resize and self.isVisible():
            self._geometry()
        return False

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        top = self._top()
        p.fillRect(QRectF(0, top, self.width(), self.height() - top), QColor(10, 10, 12, 165))
        p.end()

    # Tout clic / touche sur le voile est absorbé : l'interface derrière est inaccessible
    def mousePressEvent(self, e):  # noqa: N802
        e.accept()

    def mouseReleaseEvent(self, e):  # noqa: N802
        e.accept()

    def wheelEvent(self, e):  # noqa: N802
        e.accept()

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape and self.btn.isEnabled():
            self._button()
        e.accept()
