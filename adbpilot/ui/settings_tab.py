from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .. import adbcore, metacache, tools_dl
from ..config import config, user_dir


class SettingsTab(QWidget):
    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(sc)
        body = QWidget()
        sc.setWidget(body)
        lay = QHBoxLayout(body)
        lay.setContentsMargins(12, 8, 12, 12)
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()
        lay.addLayout(col1, 1)
        lay.addSpacing(12)
        lay.addLayout(col2, 1)

        # Outils
        g = QGroupBox("Outils")
        f = QFormLayout(g)
        self.adb_path = self._path_row(f, "adb :", "adb_path")
        self.scrcpy_path = self._path_row(f, "scrcpy :", "scrcpy_path")
        self.lbl_tools = QLabel()
        self.lbl_tools.setWordWrap(True)
        self.lbl_tools.setStyleSheet("font-size: 8pt;")
        f.addRow(self.lbl_tools)
        row = QHBoxLayout()
        b1 = QPushButton("Télécharger adb (Google)")
        b1.clicked.connect(lambda: self._download("adb"))
        b2 = QPushButton("Télécharger scrcpy (GitHub)")
        b2.clicked.connect(lambda: self._download("scrcpy"))
        row.addWidget(b1)
        row.addWidget(b2)
        f.addRow(row)
        col1.addWidget(g)

        # Applications
        g = QGroupBox("Liste des applications")
        f = QFormLayout(g)
        self.cb_meta = self._check(f, "Charger les noms et icônes (lecture des APK sur l'appareil)", "load_meta")
        self.lang = QComboBox()
        for code, lab in [("fr", "Français"), ("en", "Anglais"), ("", "Par défaut de l'APK")]:
            self.lang.addItem(lab, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(config.get("label_lang", "fr"))))
        self.lang.currentIndexChanged.connect(lambda _: self._set("label_lang", self.lang.currentData()))
        f.addRow("Langue des noms :", self.lang)
        b = QPushButton("Vider le cache des noms/icônes")
        b.clicked.connect(self._clear_cache)
        f.addRow(b)
        col1.addWidget(g)

        g = QGroupBox("Installation / désinstallation")
        f = QFormLayout(g)
        self._check(f, "Accorder toutes les permissions à l'installation (-g)", "install_grant")
        self._check(f, "Remplacer si déjà installée (-r)", "install_replace")
        self._check(f, "Autoriser le retour à une version antérieure (-d)", "install_downgrade")
        self._check(f, "Garder les données à la désinstallation (-k)", "uninstall_keep_data")
        col1.addWidget(g)

        g = QGroupBox("Connexion")
        f = QFormLayout(g)
        self._check(f, "Se reconnecter à la dernière IP au démarrage", "auto_reconnect")
        self._check(f, "Ouvrir le shell dans la console dès la connexion", "auto_shell")
        col1.addWidget(g)
        col1.addStretch(1)

        # scrcpy
        g = QGroupBox("scrcpy")
        f = QFormLayout(g)
        br = QLineEdit(config.get("scrcpy_bitrate", "8M"))
        br.textChanged.connect(lambda t: self._set("scrcpy_bitrate", t.strip()))
        f.addRow("Débit vidéo :", br)
        fps = QSpinBox()
        fps.setRange(0, 240)
        fps.setSpecialValueText("illimité")
        fps.setValue(int(config.get("scrcpy_max_fps") or 0))
        fps.valueChanged.connect(lambda v: self._set("scrcpy_max_fps", v))
        f.addRow("FPS max :", fps)
        self._check(f, "Sans audio", "scrcpy_no_audio")
        self._check(f, "Éteindre l'écran de l'appareil", "scrcpy_turn_screen_off")
        self._check(f, "Garder l'appareil éveillé", "scrcpy_stay_awake")
        self._check(f, "Afficher les touches", "scrcpy_show_touches")
        self._check(f, "Toujours au premier plan", "scrcpy_always_on_top")
        ex = QLineEdit(config.get("scrcpy_extra", ""))
        ex.setPlaceholderText("ex. --video-codec=h265 --keyboard=uhid")
        ex.textChanged.connect(lambda t: self._set("scrcpy_extra", t))
        f.addRow("Options en plus :", ex)
        col2.addWidget(g)

        g = QGroupBox("Interface")
        f = QFormLayout(g)
        th = QComboBox()
        th.addItem("Sombre", "dark")
        th.addItem("Bleu (clair)", "blue")
        th.setCurrentIndex(max(0, th.findData(config.get("theme", "dark"))))
        th.currentIndexChanged.connect(lambda _: (self._set("theme", th.currentData()),
                                                  self.main.apply_theme()))
        f.addRow("Thème :", th)
        sd = QLineEdit(config.get("screens_dir", ""))
        sd.textChanged.connect(lambda t: self._set("screens_dir", t))
        bsd = QPushButton("…")
        bsd.setFixedWidth(32)
        bsd.clicked.connect(lambda: (lambda d: d and sd.setText(d))(
            QFileDialog.getExistingDirectory(self, "Dossier des captures", sd.text())))
        r = QHBoxLayout()
        r.addWidget(sd, 1)
        r.addWidget(bsd)
        f.addRow("Captures d'écran :", r)
        idir = QLineEdit(config.get("install_dir", "") or str(user_dir("install")))
        idir.textChanged.connect(lambda t: self._set("install_dir", t.strip()))
        bid = QPushButton("…")
        bid.setFixedWidth(32)
        bid.clicked.connect(lambda: (lambda d: d and idir.setText(d))(
            QFileDialog.getExistingDirectory(self, "Dossier des APK à installer", idir.text())))
        r2 = QHBoxLayout()
        r2.addWidget(idir, 1)
        r2.addWidget(bid)
        f.addRow("APK à installer :", r2)
        col2.addWidget(g)
        col2.addStretch(1)
        self.refresh_tools()

    def _set(self, k, v):
        config[k] = v
        config.save()

    def _check(self, form, text, key):
        cb = QCheckBox(text)
        cb.setChecked(bool(config.get(key)))
        cb.toggled.connect(lambda v: self._set(key, v))
        form.addRow(cb)
        return cb

    def _path_row(self, form, label, key):
        le = QLineEdit(config.get(key, ""))
        le.setPlaceholderText("automatique")
        le.textChanged.connect(lambda t: (self._set(key, t.strip()), self.refresh_tools()))
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(lambda: (lambda p: p and le.setText(p))(
            QFileDialog.getOpenFileName(self, label, str(Path.home()))[0]))
        r = QHBoxLayout()
        r.addWidget(le, 1)
        r.addWidget(b)
        form.addRow(label, r)
        return le

    def refresh_tools(self):
        a = adbcore.find_adb()
        s = adbcore.find_scrcpy()
        self.lbl_tools.setText("adb utilisé : %s<br>scrcpy utilisé : %s" % (
            a or "<span style='color:#ff5c5c'>introuvable</span>",
            s or "<span style='color:#ff5c5c'>introuvable</span>"))
        tt = getattr(self.main, "tools_tab", None)
        if tt:
            tt.refresh_scrcpy_label()

    def _clear_cache(self):
        metacache.clear_cache()
        for p in self.ctl.packages:
            p.label = None
            p.icon = None
        self.ctl.refresh_packages()
        self.main.set_status("Cache vidé, relecture des noms et icônes…")

    def _download(self, what):
        self.main.set_status("Téléchargement de %s…" % what)

        def prog(n, total):
            if total:
                self.ctl.status.emit("Téléchargement de %s… %d %%" % (what, n * 100 // total))

        def work():
            if what == "adb":
                return tools_dl.install_platform_tools(prog)
            return tools_dl.install_scrcpy(prog)

        def done(r):
            if isinstance(r, Exception):
                self.main.toast("Échec du téléchargement : %s" % r)
                return
            self.ctl.log.emit("[Succès] : %s installé : %s" % (what, r), "ok")
            self.main.set_status("%s installé" % what)
            self.refresh_tools()
            if what == "adb":
                self.ctl.start()
        self.ctl.submit(work, done=done)

