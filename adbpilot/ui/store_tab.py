"""Onglet Store : installer des applications en un clic (catalogue maintenu sur GitHub)."""
from __future__ import annotations

import html
import threading

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from .. import adbcore, store
from ..config import config
from ..i18n import _, lang

PALETTE = ["#e5533d", "#2f80ed", "#27ae60", "#9b51e0", "#f2994a", "#00a3a3", "#d63384", "#5c6bc0"]


def letter_icon(name: str, size=64) -> QPixmap:
    color = QColor(PALETTE[sum(map(ord, name)) % len(PALETTE)])
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    p.fillPath(path, color)
    p.setPen(QColor("white"))
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, name[:1].upper())
    p.end()
    return QPixmap.fromImage(img)


def rounded(pix: QPixmap, size=64) -> QPixmap:
    pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    p.setClipPath(path)
    p.drawPixmap(int((size - pix.width()) / 2), int((size - pix.height()) / 2), pix)
    p.end()
    return QPixmap.fromImage(img)


class AppCard(QFrame):
    install_clicked = Signal(object)

    def __init__(self, app: dict):
        super().__init__()
        self.app = app
        self.meta = store.cached_meta(app) or {}
        self.icon_url_path = None
        self.setObjectName("storeCard")
        self.setFixedSize(320, 134)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(56, 56)
        top.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel(app.get("name", "?"))
        self.title.setTextFormat(Qt.PlainText)
        self.title.setObjectName("cardTitle")
        col.addWidget(self.title)
        desc = app.get("desc_en") if lang() == "en" and app.get("desc_en") else app.get("desc", "")
        self.desc = QLabel(desc)
        self.desc.setTextFormat(Qt.PlainText)
        self.desc.setObjectName("cardDesc")
        self.desc.setWordWrap(True)
        col.addWidget(self.desc)
        col.addStretch(1)
        top.addLayout(col, 1)
        lay.addLayout(top, 1)
        # Progression à gauche du bouton : ne prend pas de place sur la description
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        prog = QVBoxLayout()
        prog.setSpacing(3)
        prog.addStretch(1)
        self.state = QLabel()
        self.state.setObjectName("cardState")
        self.state.setTextFormat(Qt.RichText)
        self.state.hide()
        prog.addWidget(self.state)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        self.bar.hide()
        prog.addWidget(self.bar)
        prog.addStretch(1)
        bottom.addLayout(prog, 1)
        self.b_main = QPushButton(_("Installer"))
        self.b_main.setObjectName("cardBtn")
        self.b_main.setCursor(Qt.PointingHandCursor)
        self.b_main.clicked.connect(lambda: self.install_clicked.emit(self))
        bottom.addWidget(self.b_main)
        lay.addLayout(bottom)
        self.update_icon()

    def update_icon(self):
        pix = QPixmap()
        for path in (self.icon_url_path, self.meta.get("icon_path")):
            if path:
                pix = QPixmap(path)
                if not pix.isNull():
                    break
        self.icon.setPixmap(rounded(pix, 56) if not pix.isNull() else letter_icon(self.app.get("name", "?"), 56))

    def set_meta(self, meta):
        if meta and not meta.get("error"):
            self.meta = meta
        self.update_icon()

    def set_progress(self, text, value=None, maximum=None):
        text = self.state.fontMetrics().elidedText(text, Qt.ElideRight, 190)
        self.state.setText("<span style='color:#7fb8ff'>%s</span>" % html.escape(text))
        self.state.show()
        if value is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, max(1, maximum or 1))
            self.bar.setValue(value)
        self.bar.show()

    def set_busy(self, busy):
        self.b_main.setEnabled(not busy)
        if not busy:
            self.bar.hide()
            self.state.hide()


class StoreTab(QWidget):
    _sig = Signal(object, object)  # (callable, valeur) exécuté dans le fil principal

    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self.catalog = {}
        self.cards: dict[str, AppCard] = {}
        self.category = "all"
        self.search = ""
        self._meta_started = False
        self._sig.connect(lambda fn, v: fn(v))
        self._build()
        self.load()
        main.tabs.currentChanged.connect(self._tab_changed)
        # Le catalogue est maintenu sur GitHub : synchronisation silencieuse au démarrage
        threading.Thread(target=self._sync, daemon=True).start()

    # -- construction ------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        self.chips = QButtonGroup(self)
        self.chips.setExclusive(True)
        self.chips.buttonClicked.connect(self._chip)
        bar = QHBoxLayout()
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        bar.addLayout(self.chip_row)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("storeBody")
        self.grid = QVBoxLayout(self.body)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(6)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

    def _cat_name(self, c):
        return c.get("name_en") if lang() == "en" and c.get("name_en") else c.get("name", c.get("id"))

    def load(self):
        self.catalog = store.load_catalog()
        for b in self.chips.buttons():
            self.chips.removeButton(b)
            b.deleteLater()
        cats = [{"id": "all", "name": _("Tout")}] + self.catalog.get("categories", [])
        ids = {c["id"] for c in cats}
        if self.category not in ids:
            self.category = "all"
        for c in cats:
            b = QPushButton(self._cat_name(c))
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("cat", c["id"])
            b.setChecked(c["id"] == self.category)
            self.chips.addButton(b)
            self.chip_row.addWidget(b)
        for c in self.cards.values():
            c.setParent(None)
            c.deleteLater()
        self.cards = {a["id"]: AppCard(a) for a in self.catalog.get("apps", []) if a.get("id")}
        for c in self.cards.values():
            c.install_clicked.connect(self.install)
        self._layout_cards()
        self._meta_started = False
        if self.isVisible():
            self.start_meta()

    def _sync(self):
        try:
            changed = store.sync_catalog()
        except Exception:  # noqa: BLE001 - hors ligne ou catalogue absent : on garde la copie locale
            return
        if changed:
            self._sig.emit(lambda _v: self.load(), None)

    def _chip(self, b):
        self.category = b.property("cat")
        self._layout_cards()
        self.scroll.verticalScrollBar().setValue(0)

    def set_search(self, t):
        self.search = t.strip().lower()
        self._layout_cards()

    def _columns(self):
        w = self.scroll.viewport().width() if self.isVisible() else self.width() - 40
        return max(1, (w - 8) // 332)

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_cols", None) != self._columns():
            self._layout_cards()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_cols", None) != self._columns():
            self._layout_cards()

    def _clear(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                if isinstance(w, AppCard):
                    w.setParent(None)
                else:
                    w.deleteLater()
            elif it.layout() is not None:
                self._clear(it.layout())
                it.layout().deleteLater()

    def _layout_cards(self):
        self._clear(self.grid)
        self._cols = cols = self._columns()
        cats = self.catalog.get("categories", [])
        known = {c["id"] for c in cats}
        apps_all = self.catalog.get("apps", [])
        groups = [(c, [a for a in apps_all if a.get("category") == c["id"]]) for c in cats]
        other = [a for a in apps_all if a.get("category") not in known]
        if other:
            groups.append(({"id": "_other", "name": _("Autres")}, other))
        shown = 0
        for c, apps in groups:
            if self.category not in ("all", c["id"]):
                continue
            apps = [a for a in apps if a.get("id") in self.cards and self._match(a)]
            if not apps:
                continue
            title = QLabel(self._cat_name(c))
            title.setObjectName("storeSection")
            self.grid.addWidget(title)
            g = QGridLayout()
            g.setHorizontalSpacing(12)
            g.setVerticalSpacing(12)
            for i, a in enumerate(apps):
                card = self.cards[a["id"]]
                g.addWidget(card, i // cols, i % cols, Qt.AlignLeft | Qt.AlignTop)
                card.show()
            g.setColumnStretch(cols, 1)
            self.grid.addLayout(g)
            shown += len(apps)
        if not shown:
            empty = QLabel(_("Aucune application ne correspond."))
            empty.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(empty)
        self.grid.addStretch(1)

    def _match(self, a):
        s = self.search
        return not s or s in a.get("name", "").lower() or s in (a.get("desc") or "").lower()

    # -- icônes -------------------------------------------------------------
    def _tab_changed(self, i):
        if self.main.tabs.widget(i) is self:
            self.start_meta()

    def _abi(self):
        info = getattr(self.ctl, "last_info", None) or {}
        return info.get("abi") or ""

    def start_meta(self):
        if self._meta_started:
            return
        self._meta_started = True
        cards = list(self.cards.values())
        abi, lg = self._abi(), config.get("label_lang", "fr")

        def work():
            for c in cards:
                if c.app.get("icon"):
                    try:
                        path = store.fetch_icon_url(c.app)
                        self._sig.emit(lambda p, c=c: (setattr(c, "icon_url_path", p), c.update_icon()), path)
                        continue
                    except Exception:  # noqa: BLE001 - on retombe sur l'icône de l'APK
                        pass
                if c.meta.get("icon_path"):
                    continue
                try:
                    meta = store.fetch_meta(c.app, abi, lg)
                except Exception as e:  # noqa: BLE001
                    meta = {"error": str(e)}
                self._sig.emit(lambda m, c=c: c.set_meta(m), meta)
        threading.Thread(target=work, daemon=True).start()

    # -- installation --------------------------------------------------------
    def install(self, card: AppCard):
        app = card.app
        src = app.get("source") or {}
        if "page" in src:
            QDesktopServices.openUrl(QUrl(src["page"]))
            self.main.toast(_("Ce site demande un navigateur : télécharge l'APK puis glisse-le sur la "
                              "fenêtre d'ADB Pilot pour l'installer."), 8000)
            return
        if not self.ctl.ready:
            self.main.toast(_("Aucun appareil connecté."))
            return
        if app.get("unofficial") and QMessageBox.question(
                self, _("Source non officielle"),
                _("%s provient d'un site tiers (%s). Installer quand même ?") % (app["name"], store.host_of(app))
        ) != QMessageBox.Yes:
            return
        card.set_busy(True)
        card.set_progress(_("Recherche du fichier…"))
        abi = self._abi()
        name = app["name"]

        def ui(fn):
            return lambda *a: self._sig.emit(lambda _v: fn(*a), None)

        prog = ui(lambda n, t: card.set_progress(
            _("Téléchargement… %d %%") % (n * 100 // t) if t else _("Téléchargement… %.1f Mo") % (n / 1048576),
            n if t else None, t or None))

        def work():
            res = store.resolve(app, abi)
            url, fname = res["url"], res["name"]
            self.ctl.log.emit(">> Store : %s ← %s" % (html.escape(name), html.escape(url)), "cmd")
            path = store.download(url, fname, app["id"], progress=prog)
            ui(lambda: card.set_progress(_("Installation sur l'appareil…")))()
            if path.suffix.lower() == ".apk":
                r = adbcore.install_apks([str(path)])
            else:
                r = adbcore.install_bundle(str(path), log=lambda s: self.ctl.log.emit(s, "info"))
            return r

        def done(r):
            card.set_busy(False)
            if isinstance(r, Exception):
                self.ctl.log.emit("[Erreur] : %s — %s" % (html.escape(name), html.escape(str(r))), "err")
                self.main.toast(_("%s : échec — %s") % (name, r), 9000)
                return
            if r.ok and "Failure" not in r.out:
                self.ctl.log.emit("[Succès] : %s installé" % html.escape(name), "ok")
                self.main.toast(_("%s installé") % name, 4000)
                self.ctl.refresh_packages()
            else:
                self.ctl.log.emit("[Erreur] : %s — %s" % (html.escape(name), html.escape(r.text)), "err")
                self.main.toast(_("%s : échec de l'installation — détails dans la Console") % name, 8000)
        self.ctl.submit(work, done=done)
