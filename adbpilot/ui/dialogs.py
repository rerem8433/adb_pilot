from __future__ import annotations

import html
import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from .. import adbcore, debloat
from ..adbcore import adb, q
from . import style


class DebloatWizard(QDialog):
    def __init__(self, parent=None, device_pkgs=()):
        super().__init__(parent)
        self.setWindowTitle("Assistant debloat")
        self.setFixedSize(600, 400)
        self.level = 1
        self.device_pkgs = set(device_pkgs)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        side = QFrame()
        side.setStyleSheet("background: #1e3a7b;")
        side.setFixedWidth(200)
        sl = QVBoxLayout(side)
        t = QLabel("Niveau de nettoyage :")
        t.setStyleSheet("color: white;")
        sl.addWidget(t)
        box = QFrame()
        box.setStyleSheet("QFrame { border: 2px solid #d02020; } QLabel { border: none; }")
        bl = QHBoxLayout(box)
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 3)
        self.slider.setValue(1)
        self.slider.setTickPosition(QSlider.TicksRight)
        self.slider.valueChanged.connect(self._changed)
        bl.addWidget(self.slider)
        labels = QVBoxLayout()
        for i in reversed(range(4)):
            name, color, _ = debloat.LEVELS[i]
            lb = QLabel(name)
            lb.setStyleSheet("color: %s; font-size: 11pt; font-weight: 600;" % color)
            labels.addWidget(lb)
            if i:
                labels.addStretch(1)
        bl.addLayout(labels)
        sl.addWidget(box, 1)
        v = QLabel("Listes ADB Pilot (debloat0-3)")
        v.setStyleSheet("color: #c8d4f0; font-size: 7pt;")
        v.setAlignment(Qt.AlignCenter)
        sl.addWidget(v)
        lay.addWidget(side)

        main = QWidget()
        main.setObjectName("wizMain")
        main.setStyleSheet("#wizMain { background: white; } #wizMain QLabel { color: #111; }")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(16, 14, 16, 16)
        h = QLabel("Assistant debloat")
        h.setStyleSheet("font-size: 12pt; font-weight: 700;")
        ml.addWidget(h)
        intro = QLabel("Selon le niveau choisi, la liste des applications jugées inutiles est "
                       "cochée dans l'onglet Applications. Relis et ajuste la liste avant de "
                       "cliquer sur Appliquer : rien n'est désactivé sans ta validation.")
        intro.setWordWrap(True)
        intro.setStyleSheet("font-style: italic; font-size: 9pt;")
        ml.addWidget(intro)
        ml.addSpacing(6)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setAlignment(Qt.AlignCenter)
        self.desc.setMinimumHeight(86)
        self.desc.setStyleSheet("border: 1px solid #555; padding: 10px; font-size: 10pt;")
        ml.addWidget(self.desc)
        self.src = QLabel()
        self.src.setWordWrap(True)
        self.src.setStyleSheet("font-size: 8pt; color: #333;")
        ml.addWidget(self.src)
        ml.addStretch(1)
        ok = QPushButton("APPLIQUER")
        ok.setStyleSheet("QPushButton { background: #7ff0b0; color: #0b2414; border: 1px solid #44c27a; "
                         "font-weight: 600; } QPushButton:hover { background: #9af5c4; }")
        ok.setMinimumHeight(40)
        ok.setMinimumWidth(160)
        ok.clicked.connect(self.accept)
        ml.addWidget(ok, 0, Qt.AlignHCenter)
        lay.addWidget(main, 1)
        self._changed(1)

    def _changed(self, v):
        self.level = v
        name, color, text = debloat.LEVELS[v]
        self.desc.setText("<b>%s</b> : %s" % (name, text))
        self._update_src()

    def _update_src(self):
        v = self.level
        pk = debloat.level_packages(v)
        n_dev = len(pk & self.device_pkgs) if self.device_pkgs else None
        files = " + ".join("debloat%d.db" % i for i in range(v + 1))
        txt = "Listes : %s — %d paquets" % (files, len(pk))
        if n_dev is not None:
            txt += ", <b>%d présent(s) et actif(s) sur cet appareil</b>" % n_dev
        txt += "<br><span style='color:#555'>Dossier : %s</span>" % html.escape(
            str(debloat.level_file(0).parent))
        self.src.setText(txt)

    def showEvent(self, e):
        super().showEvent(e)
        self._update_src()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange and self.isActiveWindow():
            self._update_src()


class PermissionsDialog(QDialog):
    def __init__(self, ctl, pkg, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.pkg = pkg
        self.setWindowTitle("Permissions")
        self.resize(460, 520)
        lay = QVBoxLayout(self)
        t = QLabel(pkg.name)
        t.setStyleSheet("font-size: 8pt;")
        lay.addWidget(t)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.btn = QPushButton("Appliquer les permissions")
        self.btn.setObjectName("accent")
        self.btn.setMinimumHeight(36)
        self.btn.clicked.connect(self._apply)
        lay.addWidget(self.btn)
        n = QLabel("Coche/décoche pour accorder/retirer. En rouge : permissions d'exécution "
                   "(modifiables). Les autres ne sont en général pas modifiables via adb, sauf "
                   "permissions de développement (ex. WRITE_SECURE_SETTINGS).")
        n.setWordWrap(True)
        n.setStyleSheet("font-size: 8pt;")
        lay.addWidget(n)
        self.initial = {}
        self.list.addItem("Chargement…")
        ctl.submit(lambda: adbcore.parse_permissions(adbcore.dumpsys_package(pkg.name), pkg.name),
                   done=self._loaded)

    def _loaded(self, perms):
        self.list.clear()
        if isinstance(perms, Exception):
            return
        for perm, granted, runtime in sorted(perms, key=lambda x: (not x[2], x[0])):
            short = perm.replace("android.permission.", "")
            it = QListWidgetItem(short)
            it.setData(Qt.UserRole, perm)
            it.setToolTip(perm)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if granted else Qt.Unchecked)
            if runtime:
                it.setForeground(QColor("#ff4d4d"))
            self.list.addItem(it)
            self.initial[perm] = granted
        if not perms:
            self.list.addItem("Aucune permission demandée.")

    def _filter(self, t):
        t = t.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _apply(self):
        changes = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            perm = it.data(Qt.UserRole)
            if not perm:
                continue
            on = it.checkState() == Qt.Checked
            if on != self.initial.get(perm):
                changes.append((perm, on))
        if not changes:
            self.accept()
            return
        name = self.pkg.name

        def work():
            for perm, on in changes:
                self.ctl.log.emit(">> pm %s %s %s" % ("grant" if on else "revoke", name, perm), "cmd")
                r = adbcore.grant(name, perm, on)
                if r.ok and not r.text:
                    self.ctl.log.emit("[Succès] : %s %s" % (perm, "accordée" if on else "retirée"), "ok")
                else:
                    self.ctl.log.emit("[Erreur] : " + html.escape(r.text.splitlines()[0] if r.text else "échec"), "err")
        self.ctl.submit(work)
        self.accept()


class AppInfoDialog(QDialog):
    def __init__(self, ctl, pkg, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.pkg = pkg
        self.setWindowTitle(pkg.display)
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        ic = QLabel()
        if pkg.icon is not None:
            ic.setPixmap(QPixmap.fromImage(pkg.icon).scaled(56, 56, Qt.KeepAspectRatio,
                                                           Qt.SmoothTransformation))
        else:
            ic.setPixmap(style.icon("app", "#3ddc84", 64).pixmap(QSize(56, 56)))
        top.addWidget(ic)
        t = QLabel("<b style='font-size:13pt'>%s</b><br>%s" % (html.escape(pkg.display), pkg.name))
        t.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top.addWidget(t, 1)
        lay.addLayout(top)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        lay.addStretch(1)
        d = debloat.info(pkg.name)
        if d:
            dl = QLabel("<b>Debloat : %s</b> (%s)<br>%s" % (
                debloat.REMOVAL_FR.get(d.get("removal"), "?"), d.get("list", ""),
                html.escape(d.get("description", "")).replace("\n", "<br>")))
            dl.setWordWrap(True)
            dl.setStyleSheet("font-size: 9pt;")
            lay.addWidget(dl)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        ctl.submit(lambda: adbcore.parse_app_info(adbcore.dumpsys_package(pkg.name), pkg.name),
                   done=self._loaded)

    def _loaded(self, info):
        if isinstance(info, Exception):
            return
        p = self.pkg
        rows = [
            ("Version", "%s (%s)" % (info.get("versionName") or p.version or "?", info.get("versionCode", "?"))),
            ("Type", "Système" if p.system else "Utilisateur"),
            ("État", "Supprimée (utilisateur 0)" if p.deleted else ("Désactivée" if p.disabled else "Active")),
            ("SDK cible / min", "%s / %s" % (info.get("targetSdk", "?"), info.get("minSdk", "?"))),
            ("ABI", info.get("primaryCpuAbi", "")),
            ("Installée le", info.get("firstInstallTime", "")),
            ("Mise à jour le", info.get("lastUpdateTime", "")),
            ("Installée par", info.get("installer", "")),
            ("UID", info.get("uid", "")),
            ("APK", p.path),
            ("Données", info.get("dataDir", "")),
        ]
        for k, v in rows:
            lb = QLabel(html.escape(v or "–"))
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lb.setWordWrap(True)
            self.form.addRow(k + " :", lb)


class ResolutionDialog(QDialog):
    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle("Résolution de l'écran")
        lay = QVBoxLayout(self)
        self.cur = QLabel("Lecture…")
        lay.addWidget(self.cur)
        f = QFormLayout()
        self.size = QLineEdit()
        self.size.setPlaceholderText("ex. 1080x1920")
        self.dens = QLineEdit()
        self.dens.setPlaceholderText("ex. 420")
        f.addRow("Taille :", self.size)
        f.addRow("Densité (dpi) :", self.dens)
        lay.addLayout(f)
        row = QHBoxLayout()
        b_set = QPushButton("Appliquer")
        b_set.clicked.connect(self._apply)
        b_reset = QPushButton("Réinitialiser")
        b_reset.clicked.connect(self._reset)
        row.addWidget(b_set)
        row.addWidget(b_reset)
        lay.addLayout(row)
        ctl.submit(lambda: adb.shell("wm size; wm density").out, done=self._loaded)

    def _loaded(self, out):
        if isinstance(out, Exception):
            return
        self.cur.setText(out.strip())
        m = re.findall(r"(\d+x\d+)", out)
        if m:
            self.size.setText(m[-1])
        d = re.findall(r"density: (\d+)", out)
        if d:
            self.dens.setText(d[-1])

    def _apply(self):
        cmds = []
        if re.match(r"^\d+x\d+$", self.size.text().strip()):
            cmds.append("wm size " + self.size.text().strip())
        if self.dens.text().strip().isdigit():
            cmds.append("wm density " + self.dens.text().strip())
        for c in cmds:
            self.ctl.submit(self.ctl.adb_logged, ["shell", c])
        self.accept()

    def _reset(self):
        self.ctl.submit(self.ctl.adb_logged, ["shell", "wm size reset; wm density reset"])
        self.accept()


class PairDialog(QDialog):
    """Appairage Android 11+ (débogage sans fil)."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle("Appairer un appareil (Android 11+)")
        lay = QVBoxLayout(self)
        info = QLabel("Sur l'appareil : Options développeur → Débogage sans fil → "
                      "« Associer l'appareil avec un code d'association ».")
        info.setWordWrap(True)
        lay.addWidget(info)
        f = QFormLayout()
        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.1.50:37123")
        self.code = QLineEdit()
        self.code.setPlaceholderText("123456")
        self.conn = QLineEdit()
        self.conn.setPlaceholderText("Adresse de connexion (IP:port affiché sur l'écran principal)")
        f.addRow("IP:port d'association :", self.host)
        f.addRow("Code :", self.code)
        f.addRow("IP:port de connexion :", self.conn)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._go)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _go(self):
        host, code, conn = self.host.text().strip(), self.code.text().strip(), self.conn.text().strip()
        if not host or not code:
            return

        def work():
            self.ctl.logcmd(["pair", host, "******"])
            r = adb.run(["pair", host, code], serial=False, timeout=30)
            self.ctl.logres(r)
            return r
        self.ctl.submit(work, done=lambda r: conn and self.ctl.connect_ip(conn))
        self.accept()


def quote_input_text(t: str) -> str:
    out = t.replace("%", "\\%").replace(" ", "%s")
    return q(out)
