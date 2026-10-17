from __future__ import annotations

import html
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QMenu, QPushButton, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QStatusBar, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, AUTHOR, HOMEPAGE, VERSION, adbcore
from ..adbcore import adb
from ..config import CONFIG_DIR, DATA_DIR, config, user_dir
from . import style
from .apps_tab import AppsTab
from .console_tab import ConsoleTab
from .controller import Controller
from .settings_tab import SettingsTab
from .process_tab import ProcessTab
from .tools_tab import ToolsTab

APK_EXT = (".apk", ".apks", ".xapk", ".apkm")


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: rgba(20,20,22,0.93); color: #fff; padding: 12px 18px;"
                           "border: 1px solid #2fd06b; border-radius: 6px; font-size: 10pt;")
        self.hide()
        self.t = QTimer(self)
        self.t.setSingleShot(True)
        self.t.timeout.connect(self.hide)

    def show_msg(self, text, ms=5000):
        self.setText(text)
        w = min(560, self.parent().width() - 40)
        self.setFixedWidth(w)
        self.adjustSize()
        self.move((self.parent().width() - w) // 2, self.parent().height() - self.height() - 50)
        self.raise_()
        self.show()
        self.t.start(ms)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("%s %s" % (APP_NAME, VERSION))
        self.setWindowIcon(style.logo_icon())
        self.resize(1180, 760)
        self.setMinimumSize(980, 620)
        self.setAcceptDrops(True)
        self.ctl = Controller()
        from ..config import SUBDIRS
        from ..debloat import ensure_files
        for sd in SUBDIRS:
            user_dir(sd)
        ensure_files()
        self._build()
        self.apply_theme()
        try:
            g = config.get("window_geometry")
            if g:
                self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        except Exception:
            pass
        self.ctl.status.connect(self.set_status)
        self.ctl.devices_changed.connect(self._on_devices)
        self.ctl.device_changed.connect(self._on_device)
        self.ctl.meta_progress.connect(self.apps.meta_progress)
        self.ctl.connecting.connect(self._on_connecting)
        self.ctl.connect_result.connect(self._on_connect_result)
        self.ctl.specs_ready.connect(self._on_specs)
        self.ram_timer = QTimer(self)
        self.ram_timer.timeout.connect(self.ctl.refresh_ram)
        self.ram_timer.start(10000)
        QTimer.singleShot(50, self.ctl.start)

    # -- construction ------------------------------------------------------
    def _hdr_btn(self, name, tip, fn):
        b = QToolButton()
        b.setObjectName("hdr")
        b.setToolTip(tip)
        b.setIconSize(QSize(22, 22))
        b.setProperty("svg", name)
        b.clicked.connect(fn)
        self._hdr_buttons.append(b)
        return b

    def _build(self):
        self._hdr_buttons = []
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(8, 4, 10, 6)
        hl.setSpacing(2)
        r1 = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(style.logo_icon().pixmap(QSize(34, 34)))
        r1.addWidget(logo)
        r1.addSpacing(4)
        la = QLabel("ADB")
        la.setObjectName("logoA")
        lb = QLabel("Pilot")
        lb.setObjectName("logoB")
        r1.addWidget(la)
        r1.addWidget(lb)
        r1.addSpacing(14)
        r1.addWidget(self._hdr_btn("folder", "Ouvrir le dossier ADB_Pilot (%s)" % user_dir(),
                                   lambda: self._open_dir(str(user_dir()))))
        r1.addStretch(1)
        conn = QGridLayout()
        conn.setHorizontalSpacing(4)
        conn.setVerticalSpacing(2)
        self.ip = QLineEdit()
        self.ip.setMinimumWidth(170)
        self.ip.setPlaceholderText("IP de l'appareil")
        self.ip.setText(config.get("last_ip", ""))
        self.ip.returnPressed.connect(self._connect_clicked)
        self.ip.setStyleSheet("QLineEdit { background: rgba(0,0,0,0.25); color: #e0e0e0; "
                              "border: 1px solid #555; font-family: monospace; padding: 4px; }")
        conn.addWidget(self.ip, 0, 0)
        self.b_hist = QToolButton()
        self.b_hist.setObjectName("hdr")
        self.b_hist.setToolTip("Historique des connexions")
        self.b_hist.setIconSize(QSize(22, 22))
        self.b_hist.setProperty("svg", "history")
        self.b_hist.setPopupMode(QToolButton.InstantPopup)
        self.b_hist.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        self.hist_menu = QMenu(self)
        self.hist_menu.aboutToShow.connect(self._fill_history)
        self.b_hist.setMenu(self.hist_menu)
        self._hdr_buttons.append(self.b_hist)
        conn.addWidget(self.b_hist, 0, 1)
        self.b_go = QPushButton("GO !")
        self.b_go.setObjectName("goBtn")
        self.b_go.setToolTip("Se connecter en Wi-Fi à l'IP saisie")
        self.b_go.setFixedSize(58, 30)
        self.b_go.clicked.connect(self._connect_clicked)
        conn.addWidget(self.b_go, 0, 2)
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.addItems(["Auto", "5555", "5556", "5037"])
        self.port.setFixedWidth(80)
        self.port.setToolTip("Port ADB (Auto = 5555)")
        pv = str(config.get("port", "auto"))
        self.port.setCurrentText("Auto" if pv.lower() == "auto" else pv)
        self.port.currentTextChanged.connect(self._port_changed)
        lp = QLabel("Port :")
        lp.setStyleSheet("font-size: 8pt;")
        conn.addWidget(lp, 0, 3)
        conn.addWidget(self.port, 0, 4)
        self.b_tcpip = QPushButton("Passer en Wi-Fi")
        self.b_tcpip.setObjectName("tcpipBtn")
        self.b_tcpip.setToolTip("Active le débogage ADB en Wi-Fi sur l'appareil branché en USB "
                                "(adb tcpip) puis s'y connecte")
        self.b_tcpip.clicked.connect(lambda: self.tools_tab.to_wifi())
        conn.addWidget(self.b_tcpip, 1, 2, 1, 3)
        r1.addLayout(conn)
        hl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(self._hdr_btn("refresh", "Rafraîchir", self._refresh_all))
        self.dev_label = QLabel("Aucun appareil connecté")
        self.dev_label.setObjectName("deviceNameOff")
        r2.addWidget(self.dev_label)
        self.dev_specs = QLabel("")
        self.dev_specs.setObjectName("devSpecs")
        r2.addSpacing(10)
        r2.addWidget(self.dev_specs)
        self.dev_combo = QComboBox()
        self.dev_combo.setMinimumWidth(220)
        self.dev_combo.hide()
        self.dev_combo.activated.connect(lambda i: self.ctl.select(self.dev_combo.itemData(i)))
        r2.addWidget(self.dev_combo)
        r2.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.setStyleSheet("background: rgba(0,0,0,0.25); color: #eee; border: none; padding: 5px;")
        self.search_action = self.search.addAction(style.icon("search", "#cccccc"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda t: self.apps.set_search(t))
        r2.addWidget(self.search)
        hl.addLayout(r2)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.apps = AppsTab(self.ctl, self)
        self.tools_tab = ToolsTab(self.ctl, self)
        self.procs = ProcessTab(self.ctl, self)
        self.console = ConsoleTab(self.ctl, self)
        self.settings = SettingsTab(self.ctl, self)
        self.tabs.addTab(self.apps, "Applications")
        self.tabs.addTab(self.tools_tab, "Outils")
        self.tabs.addTab(self.procs, "Processus")
        self.tabs.addTab(self.console, "Console")
        self.tabs.addTab(self.settings, "Paramètres")
        self.tabs.addTab(self._about(), "À propos")
        self.tabs.currentChanged.connect(lambda i: self.search.setVisible(i == 0))
        tw = QWidget()
        tl = QVBoxLayout(tw)
        tl.setContentsMargins(4, 4, 4, 0)
        tl.addWidget(self.tabs)
        root.addWidget(tw, 1)

        sb = QStatusBar()
        self.status_lbl = QLabel("Prêt")
        sb.addWidget(self.status_lbl, 1)
        self.setStatusBar(sb)
        self.toast_w = Toast(self)

    def _about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 24, 30, 24)
        lbl = QLabel(
            "<h2>%s %s</h2>"
            "<p style='font-size:12pt'>Développé par <b>%s</b><br>"
            "<a href='%s'>%s</a></p>"
            "<p>Gestionnaire d'appareils Android via ADB pour Linux, natif (Python + Qt6).</p>"
            "<ul><li>Liste des applications avec noms, icônes et versions, filtres, recherche</li>"
            "<li>Désactiver / activer / désinstaller (utilisateur 0) / restaurer, forcer l'arrêt, "
            "effacer les données ou le cache, sauvegarder les fichiers d'installation</li>"
            "<li>Bibliothèque d'APK : APK / split APK / XAPK / APKS / APKM (glisser-déposer)</li>"
            "<li>Assistant debloat (listes debloat0-3 modifiables), presets, permissions</li>"
            "<li>Gestionnaire de processus, console adb / fastboot, shell, logcat</li>"
            "<li>Captures, vidéo, touches, scrcpy (enregistrement), Wi-Fi / appairage</li></ul>"
            "<p><b>Dossiers</b> : %s<br>"
            "&nbsp;&nbsp;images · videos · install · apps · debloat (debloat0.db à debloat3.db)</p>"
            "<p>Composants tiers : Qt 6 / PySide6 (LGPL-3.0), "
            "<a href='https://github.com/Genymobile/scrcpy'>scrcpy</a> (Apache-2.0), descriptions "
            "<a href='https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation'>UAD-ng</a> "
            "(GPL-3.0).</p>"
            "<p>Licence : GPL-3.0. Projet indépendant, sans lien avec ADB AppControl.</p>"
            "<p style='color:#888'>Configuration : %s<br>Outils téléchargés : %s</p>"
            % (APP_NAME, VERSION, AUTHOR, HOMEPAGE, HOMEPAGE, html.escape(str(user_dir())),
               html.escape(str(CONFIG_DIR)), html.escape(str(DATA_DIR))))
        lbl.setOpenExternalLinks(True)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(lbl)
        lay.addStretch(1)
        return w

    def apply_theme(self):
        name = config.get("theme", "dark")
        app = QApplication.instance()
        app.setPalette(style.palette(name))
        app.setStyleSheet(style.qss(name))
        for b in self._hdr_buttons:
            b.setIcon(style.icon(b.property("svg"), style.colors()["header_text"]))
        self.search_action.setIcon(style.icon("search", "#cccccc"))

    # -- statut / messages -------------------------------------------------
    def set_status(self, text):
        self.status_lbl.setText(text.replace("\n", " — "))

    def notify(self, title, body):
        """Toast dans la fenêtre + notification du bureau (notify-send)."""
        self.toast("%s\n%s" % (title, body), 8000)
        exe = shutil.which("notify-send")
        if exe:
            import os
            env = {k: v for k, v in os.environ.items()
                   if k not in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH")}
            try:
                subprocess.Popen([exe, "-a", "ADB Pilot", "-i", "adbpilot", title, body], env=env)
            except OSError:
                pass

    def toast(self, text, ms=6000):
        self.toast_w.show_msg(text, ms)
        self.set_status(text)

    # -- appareils ---------------------------------------------------------
    def _on_devices(self, devs):
        self.dev_combo.clear()
        for d in devs:
            state = "" if d.state == "device" else "  [%s]" % d.state
            self.dev_combo.addItem("%s  (%s)%s" % (d.label, d.serial, state), d.serial)
        cur = self.ctl.current
        if cur:
            i = self.dev_combo.findData(cur.serial)
            if i >= 0:
                self.dev_combo.setCurrentIndex(i)
        self.dev_combo.setVisible(len(devs) > 1)
        self.dev_label.setVisible(len(devs) <= 1)

    def _on_device(self, dev):
        if dev is None:
            self.dev_label.setText("Aucun appareil connecté")
            self.dev_label.setObjectName("deviceNameOff")
            self.set_status("En attente d'un appareil (USB ou Wi-Fi)…")
        elif dev.state == "device":
            self.dev_label.setText(dev.label)
            self.dev_label.setObjectName("deviceName")
        else:
            self.dev_label.setText("%s — %s" % (dev.serial, dev.state))
            self.dev_label.setObjectName("deviceNameOff")
        self.dev_label.style().unpolish(self.dev_label)
        self.dev_label.style().polish(self.dev_label)
        if dev is not None:
            i = self.dev_combo.findData(dev.serial)
            if i >= 0:
                self.dev_combo.setCurrentIndex(i)
        net = bool(dev and dev.is_network)
        self.b_go.setToolTip("Déconnecter %s (re-cliquer)" % dev.serial if net
                             else "Se connecter en Wi-Fi à l'IP saisie")
        self.b_tcpip.setVisible(not net)
        if dev is None or dev.state != "device":
            self.dev_specs.setText("")
            self.dev_specs.setToolTip("")

    def _port_changed(self, t):
        t = t.strip()
        config["port"] = "auto" if (not t or t.lower() == "auto") else t
        config.save()

    def _fill_history(self):
        m = self.hist_menu
        m.clear()
        hist = config.get("ip_history", [])
        if not hist:
            a = m.addAction("(historique vide)")
            a.setEnabled(False)
        for h in hist:
            m.addAction(h, lambda h=h: (self.ip.setText(h), self.ctl.connect_ip(h)))
        m.addSeparator()
        m.addAction("Déconnecter tous les appareils réseau", lambda: self.ctl.disconnect_ip())
        if hist:
            m.addAction("Effacer l'historique", self._clear_history)

    def _clear_history(self):
        config["ip_history"] = []
        config.save()

    def _on_connecting(self, target):
        self.b_go.setEnabled(False)
        self.toast("Connexion à %s…" % target, 15000)

    def _on_connect_result(self, target, ok, text):
        self.b_go.setEnabled(True)
        if ok:
            self.toast("Connecté à %s" % target, 3000)
            return
        low = (text or "").lower()
        if "authenticate" in low or "unauthorized" in low:
            hint = "Accepte la demande de débogage qui s'affiche sur l'écran de l'appareil."
        elif "refused" in low:
            hint = ("L'appareil refuse la connexion : le débogage ADB réseau n'est pas activé "
                    "(Options développeur → Débogage ADB / ADB sans fil), ou le port n'est pas 5555.")
        elif "délai" in low or "timed out" in low or "no route" in low or "unreachable" in low or not low:
            hint = ("Pas de réponse : vérifie l'IP, que l'appareil est allumé sur le même réseau, "
                    "et que le débogage ADB réseau est activé.")
        else:
            hint = text
        self.toast("Échec de la connexion à %s\n%s" % (target, hint), 10000)

    def _on_specs(self, sp):
        parts = []
        if sp.get("ram_gb"):
            parts.append("RAM %s Go" % sp["ram_gb"])
        if sp.get("storage_gb"):
            parts.append("Stockage %s GB" % sp["storage_gb"])
        if sp.get("android"):
            parts.append("Android %s" % sp["android"])
        warn = sp.get("fake")
        self.dev_specs.setText(" · ".join(parts) + ("  ⚠" if warn else ""))
        tip = ["RAM détectée : %s" % sp.get("ram_exact", "?"),
               "Stockage /data : %s" % sp.get("storage_exact", "?"),
               "Android réel : %s (API %s) — lu dans framework-res.apk" % (sp.get("android", "?"), sp.get("sdk", "?")),
               "build.prop annonce : Android %s (API %s)" % (sp.get("claimed", "?"), sp.get("claimed_sdk", "?"))]
        if warn:
            tip.append("⚠ build.prop semble modifié : la version annoncée ne correspond pas au système réel.")
        self.dev_specs.setToolTip("\n".join(tip))

    def _connect_clicked(self):
        text = self.ip.text().strip()
        cur = self.ctl.current
        host = text.split(":")[0]
        if cur and cur.is_network and (not text or cur.serial.split(":")[0] == host):
            self.ctl.disconnect_ip(cur.serial)
            return
        if not text:
            self.toast("Saisis l'adresse IP de l'appareil (débogage ADB réseau activé).")
            return
        self.ctl.connect_ip(text)

    def _refresh_all(self):
        self.ctl.poll_devices()
        if self.ctl.ready:
            self.ctl.load_info()
            self.ctl.refresh_packages()
            self.ctl.refresh_ram()

    # -- installation ------------------------------------------------------
    def install_dialog(self):
        self.tabs.setCurrentWidget(self.apps)
        self.apps.show_installer()

    def install_files(self, files):
        if not self.ctl.ready:
            self.toast("Aucun appareil connecté.")
            return
        apks = [f for f in files if f.lower().endswith(".apk")]
        bundles = [f for f in files if f.lower().endswith((".apks", ".xapk", ".apkm"))]
        split = False
        if len(apks) > 1:
            r = QMessageBox.question(
                self, "Plusieurs APK",
                "Ces %d APK forment-ils une seule application (split APK : base + config) ?\n\n"
                "Oui = installation groupée (install-multiple)\nNon = chaque APK séparément" % len(apks))
            split = r == QMessageBox.Yes
        self.toast("Installation de %d fichier(s)…" % (len(apks) + len(bundles)), 3000)

        def work():
            ok = 0
            jobs = ([apks] if split else [[a] for a in apks]) + [[b] for b in bundles]
            for job in jobs:
                names = ", ".join(Path(x).name for x in job)
                self.ctl.log.emit(">> Installation : %s" % html.escape(names), "cmd")
                if job[0].lower().endswith(APK_EXT[1:]):
                    r = adbcore.install_bundle(job[0], log=lambda s: self.ctl.log.emit(s, "info"))
                else:
                    r = adbcore.install_apks(job)
                if r.ok and "Failure" not in r.out:
                    ok += 1
                    self.ctl.log.emit("[Succès] : %s installé" % html.escape(names), "ok")
                else:
                    self.ctl.log.emit("[Erreur] : %s" % html.escape(r.text), "err")
            return ok, len(jobs)

        def done(res):
            if isinstance(res, Exception):
                return
            ok, n = res
            self.toast("Installation : %d/%d réussie(s)%s" % (
                ok, n, "" if ok == n else " — détails dans la Console"))
            self.ctl.refresh_packages()
        self.ctl.submit(work, done=done)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(APK_EXT)
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(APK_EXT)]
        if not files:
            return
        if self.tabs.currentWidget() is self.apps and self.apps.installer_visible():
            self.apps.installer.add_files(files)
        else:
            self.install_files(files)

    # -- divers ------------------------------------------------------------
    def open_terminal_shell(self):
        if not self.ctl.ready:
            self.toast("Aucun appareil connecté.")
            return
        exe = adbcore.find_adb()
        cmd = [exe, "-s", adb.serial, "shell"]
        title = "adb shell — %s" % (self.ctl.current.label)
        cands = [
            ("gnome-terminal", ["--title", title, "--"] + cmd),
            ("mate-terminal", ["--title", title, "-x"] + cmd),
            ("xfce4-terminal", ["--title", title, "-x"] + cmd),
            ("konsole", ["-e"] + cmd),
            ("tilix", ["-e"] + [" ".join(cmd)]),
            ("kitty", cmd),
            ("alacritty", ["-e"] + cmd),
            ("x-terminal-emulator", ["-e"] + cmd),
            ("xterm", ["-T", title, "-e"] + cmd),
        ]
        import os
        env = {k: v for k, v in os.environ.items()
               if k not in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH")}
        for term, args in cands:
            path = shutil.which(term)
            if path:
                subprocess.Popen([path] + args, env=env, start_new_session=True)
                self.ctl.log.emit(">> %s %s" % (term, " ".join(cmd)), "cmd")
                return
        self.toast("Aucun terminal trouvé. Utilise le bouton Shell de la console.")

    def _open_dir(self, d):
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _help(self):
        QMessageBox.information(
            self, "Aide",
            "<b>Connexion USB</b> : active le débogage USB sur l'appareil, branche-le et accepte la "
            "demande d'autorisation. S'il apparaît « no permissions », installe les règles udev : "
            "<code>sudo apt install android-sdk-platform-tools-common</code> puis rebranche.<br><br>"
            "<b>Connexion Wi-Fi</b> : saisis l'IP de l'appareil en haut à droite puis clique sur "
            "l'icône Wi-Fi (port 5555 par défaut, ou IP:port). Android 11+ : bouton « Appairer » "
            "dans l'onglet Outils. Re-cliquer sur l'icône Wi-Fi déconnecte.<br><br>"
            "<b>Applications</b> : coche les applis puis choisis une action en bas à droite et "
            "clique sur Appliquer. Clic droit sur une ligne pour plus d'actions, double-clic pour les "
            "infos. Glisse des APK/XAPK/APKS/APKM sur la fenêtre pour les installer.<br><br>"
            "<b>Supprimées</b> : applis désinstallées pour l'utilisateur 0 ; « Restaurer » les "
            "réinstalle sans téléchargement.")

    def closeEvent(self, e):
        config["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        config.save()
        self.console.shutdown()
        self.ctl.shutdown()
        super().closeEvent(e)
