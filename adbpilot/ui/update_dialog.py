"""Fenêtre « Mise à jour disponible » : notes de version, téléchargement et installation en un clic."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QTextBrowser, QVBoxLayout)

from .. import VERSION, osutil, updater
from ..config import config
from ..i18n import _
from . import style


def check_updates(main, manual=False):
    """Vérifie GitHub en arrière-plan. manual=True : message aussi quand tout est à jour / en erreur."""
    def done(rel):
        if isinstance(rel, Exception):
            if manual:
                main.toast(_("Impossible de vérifier les mises à jour : %s") % rel)
            return
        if rel is None:
            if manual:
                main.toast(_("ADB Pilot est à jour (version %s).") % VERSION)
            return
        if not manual and config.get("update_skip") == rel.version:
            return
        UpdateDialog(main, rel).exec()
    main.ctl.submit(updater.check, done=done)


class UpdateDialog(QDialog):
    def __init__(self, main, rel: updater.Release):
        super().__init__(main)
        self.main, self.rel = main, rel
        self.kind = updater.install_kind() if rel.asset else "manual"
        self.setWindowTitle(_("Mise à jour disponible"))
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(style.logo_icon().pixmap(48, 48))
        top.addWidget(logo, 0, Qt.AlignTop)
        t = QLabel(_("<b style='font-size:14pt'>ADB Pilot %s est disponible</b><br>"
                     "<span style='color:#a9a9ad'>Version installée : %s</span>") % (rel.version, VERSION))
        top.addWidget(t, 1)
        lay.addLayout(top)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.notes or _("(pas de notes de version)"))
        lay.addWidget(notes, 1)
        self.state = QLabel()
        self.state.setWordWrap(True)
        self.state.setStyleSheet("color: #a9a9ad;")
        lay.addWidget(self.state)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        lay.addWidget(self.bar)
        bot = QHBoxLayout()
        self.b_skip = QPushButton(_("Ignorer cette version"))
        self.b_skip.clicked.connect(self._skip)
        bot.addWidget(self.b_skip)
        bot.addStretch(1)
        self.b_later = QPushButton(_("Plus tard"))
        self.b_later.clicked.connect(self.reject)
        bot.addWidget(self.b_later)
        if self.kind == "manual":
            self.b_go = QPushButton(_("Ouvrir la page de téléchargement"))
            self.state.setText(_("Installation automatique indisponible pour cette version d'ADB Pilot "
                                 "(portable ou lancée depuis les sources)."))
        else:
            self.b_go = QPushButton(_("Télécharger et installer"))
            self.state.setText(_("Fichier : %s (%.1f Mo)") % (rel.asset["name"], rel.asset.get("size", 0) / 1048576))
        self.b_go.setObjectName("accent")
        self.b_go.setMinimumHeight(34)
        self.b_go.clicked.connect(self._go)
        self.b_go.setDefault(True)
        bot.addWidget(self.b_go)
        lay.addLayout(bot)

    def _skip(self):
        config["update_skip"] = self.rel.version
        config.save()
        self.reject()

    def _busy(self, on):
        for b in (self.b_go, self.b_skip, self.b_later):
            b.setEnabled(not on)

    def _go(self):
        if self.kind == "manual":
            QDesktopServices.openUrl(QUrl(self.rel.url))
            self.accept()
            return
        self._busy(True)
        self.bar.show()
        self.bar.setMaximum(0)
        self.state.setText(_("Téléchargement…"))
        ctl = self.main.ctl

        def prog(n, total):
            ctl.in_main(lambda _v: (self.bar.setMaximum(max(total, 1)), self.bar.setValue(n),
                                    self.state.setText(_("Téléchargement… %.1f / %.1f Mo")
                                                       % (n / 1048576, total / 1048576))), None)

        def work():
            path = updater.download(self.rel.asset, prog)
            if self.kind == "deb":
                ctl.in_main(lambda _v: (self.bar.setMaximum(0),
                                        self.state.setText(_("Installation… (mot de passe administrateur demandé)"))),
                            None)
                return path, updater.install_deb(path)
            if self.kind == "mac-app":
                ctl.in_main(lambda _v: (self.bar.setMaximum(0), self.state.setText(_("Installation…"))), None)
                try:
                    updater.run_macos_update(path)
                except Exception as e:  # noqa: BLE001
                    return path, (False, str(e))
                return path, (True, "")
            return path, None
        ctl.submit(work, done=self._downloaded)

    def _downloaded(self, res):
        if isinstance(res, Exception):
            self._busy(False)
            self.bar.hide()
            self.state.setText(_("Échec du téléchargement : %s") % res)
            return
        path, inst = res
        if self.kind == "mac-app":
            if not inst[0]:
                self._busy(False)
                self.bar.hide()
                self.state.setText(_("Échec de l'installation : %s") % inst[1])
                return
            self.state.setText(_("Mise à jour prête : ADB Pilot va redémarrer."))
            QApplication.instance().processEvents()
            self.main.close()
            QApplication.instance().quit()
            return
        if self.kind == "win-setup":
            self.state.setText(_("Lancement de l'installateur… ADB Pilot va se fermer puis redémarrer."))
            try:
                updater.run_windows_setup(path)
            except OSError as e:
                self._busy(False)
                self.state.setText(_("Impossible de lancer l'installateur : %s") % e)
                return
            QApplication.instance().processEvents()
            self.main.close()
            QApplication.instance().quit()
            return
        ok, msg = inst
        self.bar.hide()
        if ok:
            self.state.setText(_("Mise à jour installée."))
            if QMessageBox.question(self, _("Mise à jour installée"),
                                    _("ADB Pilot %s est installé. Redémarrer maintenant ?") % self.rel.version
                                    ) == QMessageBox.Yes:
                self.accept()
                self.main.restart()
            else:
                self.accept()
            return
        self._busy(False)
        if msg == "pkexec introuvable":
            # Secours : terminal avec sudo apt install
            osutil.open_terminal(updater.terminal_install_cmd(path), _("Mise à jour d'ADB Pilot"))
            self.state.setText(_("Installation lancée dans un terminal (mot de passe demandé)."))
        elif msg == "authentification annulée":
            self.state.setText(_("Installation annulée (mot de passe non saisi)."))
        else:
            self.state.setText(_("Échec de l'installation : %s") % (msg.strip().splitlines() or [""])[-1])
