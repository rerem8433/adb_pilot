from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QMenu, QPushButton, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QStatusBar, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, AUTHOR, HOMEPAGE, VERSION, adbcore
from ..adbcore import adb
from .. import osutil
from .progress_overlay import ProgressOverlay
from ..config import CONFIG_DIR, DATA_DIR, config, user_dir
from . import style
from .apps_tab import AppsTab
from .console_tab import ConsoleTab
from .controller import Controller
from .settings_tab import SettingsTab
from .process_tab import ProcessTab
from .store_tab import StoreTab
from .tools_tab import ToolsTab
from ..i18n import _

APK_EXT = (".apk", ".apks", ".xapk", ".apkm")


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: rgba(20,20,22,0.93); color: #fff; padding: 12px 18px;"
                           "border: 1px solid #4a74d6; border-radius: 6px; font-size: 10pt;")
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
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)
        self.ctl = Controller()
        from ..config import SUBDIRS
        for sd in SUBDIRS:
            user_dir(sd)

        def _sync_debloat():
            try:
                from ..debloat import sync_lists
                sync_lists()
            except Exception:  # noqa: BLE001 - hors ligne : listes intégrées
                pass
        import threading
        threading.Thread(target=_sync_debloat, daemon=True).start()
        self._build()
        self.apply_theme()
        try:
            g = config.get("window_geometry")
            if g:
                self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        except Exception:
            pass
        self.ctl.status.connect(self.set_status)
        self.ctl.device_changed.connect(self._on_device)
        self.ctl.meta_progress.connect(self.apps.meta_progress)
        self.ctl.meta_started.connect(self._meta_started)
        self.ctl.package_meta.connect(self._meta_item)
        self.ctl.meta_progress.connect(self._meta_progress)
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
        r1.addWidget(self._hdr_btn("folder", _("Ouvrir le dossier ADB_Pilot (%s)") % user_dir(),
                                   lambda: self._open_dir(str(user_dir()))))
        r1.addStretch(1)
        conn = QGridLayout()
        conn.setHorizontalSpacing(4)
        conn.setVerticalSpacing(2)
        self.ip = QLineEdit()
        self.ip.setMinimumWidth(170)
        self.ip.setPlaceholderText(_("IP de l'appareil"))
        self.ip.setText(config.get("last_ip", ""))
        self.ip.returnPressed.connect(self._connect_clicked)
        self.ip.setStyleSheet("QLineEdit { background: rgba(0,0,0,0.25); color: #e0e0e0; "
                              "border: 1px solid #555; font-family: monospace; padding: 4px; }")
        conn.addWidget(self.ip, 0, 0)
        self.b_hist = QToolButton()
        self.b_hist.setObjectName("hdr")
        self.b_hist.setToolTip(_("Historique des connexions"))
        self.b_hist.setIconSize(QSize(22, 22))
        self.b_hist.setProperty("svg", "history")
        self.b_hist.setPopupMode(QToolButton.InstantPopup)
        self.b_hist.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        self.hist_menu = QMenu(self)
        self.hist_menu.aboutToShow.connect(self._fill_history)
        self.b_hist.setMenu(self.hist_menu)
        self._hdr_buttons.append(self.b_hist)
        self.b_scan = QPushButton(_("Détecter"))
        self.b_scan.setObjectName("scanBtn")
        self.b_scan.setIcon(style.icon("search", "#ffffff"))
        self.b_scan.setFixedHeight(30)
        self.b_scan.setToolTip(_("Rechercher les appareils Android sur le réseau local"))
        self.b_scan.clicked.connect(self._open_scan)
        conn.addWidget(self.b_scan, 0, 1)
        conn.addWidget(self.b_hist, 0, 3)
        self.b_go = QPushButton(_("GO !"))
        self.b_go.setObjectName("goBtn")
        self.b_go.setToolTip(_("Se connecter en Wi-Fi à l'IP saisie"))
        self.b_go.setFixedSize(58, 30)
        self.b_go.clicked.connect(self._connect_clicked)
        conn.addWidget(self.b_go, 0, 2)
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.addItems(["Auto", "5555", "5556", "5037"])
        self.port.setFixedWidth(80)
        self.port.setToolTip(_("Port ADB (Auto = 5555)"))
        pv = str(config.get("port", "auto"))
        self.port.setCurrentText("Auto" if pv.lower() == "auto" else pv)
        self.port.currentTextChanged.connect(self._port_changed)
        lp = QLabel(_("Port :"))
        lp.setStyleSheet("font-size: 8pt;")
        prow = QHBoxLayout()
        prow.setSpacing(4)
        prow.addStretch(1)  # bord droit du champ Port aligné sur celui du champ IP
        prow.addWidget(lp)
        prow.addWidget(self.port)
        conn.addLayout(prow, 1, 0)
        self.b_tcpip = QPushButton(_("Passer en Wi-Fi"))
        self.b_tcpip.setObjectName("tcpipBtn")
        self.b_tcpip.setToolTip(_("Active le débogage ADB en Wi-Fi sur l'appareil branché en USB "
                                "(adb tcpip) puis s'y connecte"))
        self.b_tcpip.clicked.connect(lambda: self.tools_tab.to_wifi())
        r1.addLayout(conn)
        hl.addLayout(r1)

        r2 = QHBoxLayout()
        # 3 zones : appareil (gauche) | recherche (centre) | vide (droite), gauche et droite de même largeur
        left = QWidget()
        r2l = QHBoxLayout(left)
        r2l.setContentsMargins(0, 0, 0, 0)
        r2.addWidget(left, 1)
        r2, r2_outer = r2l, r2
        r2.addWidget(self._hdr_btn("refresh", _("Rafraîchir"), self._refresh_all))
        self.dev_label = QLabel(_("Aucun appareil connecté"))
        self.dev_label.setObjectName("deviceNameOff")
        r2.addWidget(self.dev_label)
        r2.addSpacing(10)
        self.b_info = QPushButton(_("Infos appareil"))
        self.b_info.setObjectName("tcpipBtn")
        self.b_info.setEnabled(False)
        self.b_info.clicked.connect(self._show_specs)
        self._specs_text = ""
        r2.addWidget(self.b_info)
        r2.addSpacing(6)
        r2.addWidget(self.b_tcpip)
        r2.addStretch(1)
        r2 = r2_outer
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Rechercher…"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.setStyleSheet("background: rgba(0,0,0,0.25); color: #eee; border: none; padding: 5px;")
        self.search_action = self.search.addAction(style.icon("search", "#cccccc"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda t: (self.apps.set_search(t), self.store_tab.set_search(t)))
        r2.addWidget(self.search)
        r2.addWidget(QWidget(), 1)
        hl.addLayout(r2)
        root.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.apps = AppsTab(self.ctl, self)
        self.tools_tab = ToolsTab(self.ctl, self)
        self.store_tab = StoreTab(self.ctl, self)
        self.procs = ProcessTab(self.ctl, self)
        self.console = ConsoleTab(self.ctl, self)
        self.settings = SettingsTab(self.ctl, self)
        self.tabs.addTab(self.apps, "Applications")
        self.tabs.addTab(self.store_tab, "Store")
        self.tabs.addTab(self.tools_tab, _("Outils"))
        self.tabs.addTab(self.procs, _("Processus"))
        self.tabs.addTab(self.console, "Console")
        self.tabs.addTab(self.settings, _("Paramètres"))
        self.tabs.addTab(self._about(), _("À propos"))
        self.tabs.currentChanged.connect(
            lambda i: self.search.setVisible(self.tabs.widget(i) in (self.apps, self.store_tab)))
        tw = QWidget()
        tl = QVBoxLayout(tw)
        tl.setContentsMargins(4, 4, 4, 0)
        tl.addWidget(self.tabs)
        root.addWidget(tw, 1)

        sb = QStatusBar()
        self.status_lbl = QLabel(_("Prêt"))
        sb.addWidget(self.status_lbl, 1)
        self.setStatusBar(sb)
        self.toast_w = Toast(self)
        self.overlay = ProgressOverlay(central, header)

    # -- fenêtre de progression (lecture des noms / icônes) -------------------
    META_OVERLAY_MIN = 5  # en dessous, simple barre discrète

    def _meta_started(self, total):
        self._meta_overlay = total >= self.META_OVERLAY_MIN
        if self._meta_overlay:
            dev = self.ctl.current.label if self.ctl.current else ""
            self.overlay.start(_("Lecture des noms et icônes"),
                               _("%s · lecture directe dans les APK") % dev, total, on_cancel=self.ctl.cancel_meta)

    def _meta_item(self, p):
        if getattr(self, "_meta_overlay", False) and self.overlay.isVisible():
            state = "ok" if (p.label or p.icon is not None) else ("skip" if p.meta_done else "err")
            self.overlay.item(p.name, p.display, p.icon, state)

    def _meta_progress(self, n, total):
        if getattr(self, "_meta_overlay", False) and self.overlay.isVisible():
            self.overlay.set_done(n)
            if n >= total:
                self._meta_overlay = False
                self.overlay.finish(_("Noms et icônes à jour"))

    def _open_scan(self):
        from .scan_popup import ScanPopup
        if getattr(self, "_scan", None) is None:
            self._scan = ScanPopup(self)
        self._scan.open_below(self.b_scan)

    def connect_to(self, ip, port):
        """Connexion depuis la détection réseau : remplit l'IP (et le port) puis lance la connexion."""
        target = ip if str(port) in ("", "5555") else "%s:%s" % (ip, port)
        self.ip.setText(target)
        self.ctl.connect_ip(target)

    def _about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 24, 30, 24)
        lbl = QLabel(
            _("<h2>%s %s</h2>"
            "<p style='font-size:12pt'>Développé par <b>%s</b><br>"
            "<a href='%s'>%s</a></p>"
            "<p>Gestionnaire d'appareils Android via ADB pour Linux et Windows, natif (Python + Qt6).</p>"
            "<ul><li>Liste des applications avec noms, icônes et versions, filtres, recherche</li>"
            "<li>Désactiver / activer / désinstaller (utilisateur 0) / restaurer, forcer l'arrêt, "
            "effacer les données ou le cache, sauvegarder les fichiers d'installation</li>"
            "<li>Bibliothèque d'APK : APK / split APK / XAPK / APKS / APKM (glisser-déposer)</li>"
            "<li>Assistant debloat (listes debloat0-3, protection automatique des téléphones), presets, permissions</li>"
            "<li>Gestionnaire de processus, console adb / fastboot, shell, logcat</li>"
            "<li>Captures, vidéo, touches, scrcpy (enregistrement), Wi-Fi / appairage</li></ul>"
            "<p><b>Dossiers</b> : %s<br>"
            "&nbsp;&nbsp;images · videos · install · apps · store</p>"
            "<p>Composants tiers : Qt 6 / PySide6 (LGPL-3.0), "
            "<a href='https://github.com/Genymobile/scrcpy'>scrcpy</a> (Apache-2.0), descriptions "
            "<a href='https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation'>UAD-ng</a> "
            "(GPL-3.0).</p>"
            "<p>Licence : GPL-3.0. Projet indépendant, sans lien avec ADB AppControl.</p>"
            "<p style='color:#888'>Configuration : %s<br>Outils téléchargés : %s</p>")
            % (APP_NAME, VERSION, AUTHOR, HOMEPAGE, HOMEPAGE, html.escape(str(user_dir())),
               html.escape(str(CONFIG_DIR)), html.escape(str(DATA_DIR))))
        lbl.setOpenExternalLinks(True)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lay.addWidget(lbl)
        if osutil.WINDOWS and osutil.machine() == "arm64":
            warn = QLabel(_("⚠ Version Windows ARM64 (Snapdragon…) : pas encore testée sur un vrai appareil ARM. "
                            "Merci de signaler tout problème sur GitHub."))
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#ffb84d; font-weight:600;")
            lay.addWidget(warn)
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
        osutil.desktop_notify(title, body)

    def toast(self, text, ms=6000):
        self.toast_w.show_msg(text, ms)
        self.set_status(text)

    # -- appareils ---------------------------------------------------------
    def _on_device(self, dev):
        if dev is None:
            self.dev_label.setText(_("Aucun appareil connecté"))
            self.dev_label.setObjectName("deviceNameOff")
            self.set_status(_("En attente d'un appareil (USB ou Wi-Fi)…"))
        elif dev.state == "device":
            self.dev_label.setText(dev.label)
            self.dev_label.setObjectName("deviceName")
        else:
            self.dev_label.setText("%s — %s" % (dev.serial, dev.state))
            self.dev_label.setObjectName("deviceNameOff")
        self.dev_label.style().unpolish(self.dev_label)
        self.dev_label.style().polish(self.dev_label)
        net = bool(dev and dev.is_network)
        self.b_go.setToolTip(_("Déconnecter %s (re-cliquer)") % dev.serial if net
                             else _("Se connecter en Wi-Fi à l'IP saisie"))
        self.b_tcpip.setVisible(not net)
        if dev is None or dev.state != "device":
            self._specs_text = ""
            self.b_info.setText(_("Infos appareil"))
            self.b_info.setEnabled(False)

    def _port_changed(self, t):
        t = t.strip()
        config["port"] = "auto" if (not t or t.lower() == "auto") else t
        config.save()

    def _fill_history(self):
        m = self.hist_menu
        m.clear()
        hist = config.get("ip_history", [])
        names = config.get("ip_names", {})
        if not hist:
            a = m.addAction(_("(historique vide)"))
            a.setEnabled(False)
        for h in hist:
            name = names.get(h.split(":")[0])
            label = "%s  —  %s" % (name, h) if name else h
            m.addAction(style.icon("wifi", style.ACCENT_LINE), label,
                        lambda h=h: (self.ip.setText(h), self.ctl.connect_ip(h)))
        m.addSeparator()
        m.addAction(_("Déconnecter tous les appareils réseau"), lambda: self.ctl.disconnect_ip())
        if hist:
            m.addAction(_("Effacer l'historique"), self._clear_history)

    def _clear_history(self):
        config["ip_history"] = []
        config.save()

    def _on_connecting(self, target):
        self.b_go.setEnabled(False)
        self.toast(_("Connexion à %s…") % target, 15000)

    def _on_connect_result(self, target, ok, text):
        self.b_go.setEnabled(True)
        if ok:
            self.toast(_("Connecté à %s") % target, 3000)
            return
        low = (text or "").lower()
        if "authenticate" in low or "unauthorized" in low:
            hint = _("Accepte la demande de débogage qui s'affiche sur l'écran de l'appareil.")
        elif "refused" in low:
            hint = (_("L'appareil refuse la connexion : le débogage ADB réseau n'est pas activé "
                    "(Options développeur → Débogage ADB / ADB sans fil), ou le port n'est pas 5555."))
        elif "délai" in low or "timed out" in low or "no route" in low or "unreachable" in low or not low:
            hint = (_("Pas de réponse : vérifie l'IP, que l'appareil est allumé sur le même réseau, "
                    "et que le débogage ADB réseau est activé."))
        else:
            hint = text
        self.toast(_("Échec de la connexion à %s\n%s") % (target, hint), 10000)

    def _on_specs(self, sp):
        parts = []
        if sp.get("ram_gb"):
            parts.append(_("RAM %s Go") % sp["ram_gb"])
        if sp.get("storage_gb"):
            parts.append(_("Stockage %s GB") % sp["storage_gb"])
        if sp.get("android"):
            parts.append(_("Android %s") % sp["android"])
        warn = sp.get("fake") or sp.get("ram_fake")
        summary = " · ".join(parts)
        tip = [_("RAM détectée : %s") % sp.get("ram_exact", "?"),
               _("Stockage /data : %s") % sp.get("storage_exact", "?"),
               _("Android réel : %s (API %s) — lu dans framework-res.apk") % (sp.get("android", "?"), sp.get("sdk", "?")),
               _("build.prop annonce : Android %s (API %s)") % (sp.get("claimed", "?"), sp.get("claimed_sdk", "?"))]
        if sp.get("fake"):
            tip.append(_("⚠ build.prop semble modifié : la version annoncée ne correspond pas au système réel."))
        if sp.get("ram_fake"):
            tip.append(_("⚠ RAM truquée par la ROM : elle annonce %s Go, l'appareil n'en a que %s Go.")
                       % (sp["ram_fake"], sp.get("ram_gb", "?")))
        self._specs_text = summary + "\n\n" + "\n".join(tip)
        self.b_info.setText(_("Infos appareil") + ("  ⚠" if warn else ""))
        self.b_info.setToolTip(summary)
        self.b_info.setEnabled(True)

    def _show_specs(self):
        if self._specs_text:
            self.toast_w.show_msg(self._specs_text, 12000)

    def _connect_clicked(self):
        text = self.ip.text().strip()
        cur = self.ctl.current
        host = text.split(":")[0]
        if cur and cur.is_network and (not text or cur.serial.split(":")[0] == host):
            self.ctl.disconnect_ip(cur.serial)
            return
        if not text:
            self.toast(_("Saisis l'adresse IP de l'appareil (débogage ADB réseau activé)."))
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
            self.toast(_("Aucun appareil connecté."))
            return
        apks = [f for f in files if f.lower().endswith(".apk")]
        bundles = [f for f in files if f.lower().endswith((".apks", ".xapk", ".apkm"))]
        split = False
        if len(apks) > 1:
            r = QMessageBox.question(
                self, _("Plusieurs APK"),
                _("Ces %d APK forment-ils une seule application (split APK : base + config) ?\n\n"
                "Oui = installation groupée (install-multiple)\nNon = chaque APK séparément") % len(apks))
            split = r == QMessageBox.Yes
        self.toast(_("Installation de %d fichier(s)…") % (len(apks) + len(bundles)), 3000)

        def work():
            ok = 0
            jobs = ([apks] if split else [[a] for a in apks]) + [[b] for b in bundles]
            for job in jobs:
                names = ", ".join(Path(x).name for x in job)
                self.ctl.log.emit(_(">> Installation : %s") % html.escape(names), "cmd")
                if job[0].lower().endswith(APK_EXT[1:]):
                    r = adbcore.install_bundle(job[0], log=lambda s: self.ctl.log.emit(s, "info"))
                else:
                    r = adbcore.install_apks(job)
                if r.ok and "Failure" not in r.out:
                    ok += 1
                    self.ctl.log.emit(_("[Succès] : %s installé") % html.escape(names), "ok")
                else:
                    self.ctl.log.emit(_("[Erreur] : %s") % html.escape(r.text), "err")
            return ok, len(jobs)

        def done(res):
            if isinstance(res, Exception):
                return
            ok, n = res
            self.toast(_("Installation : %d/%d réussie(s)%s") % (
                ok, n, "" if ok == n else _(" — détails dans la Console")))
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
            self.toast(_("Aucun appareil connecté."))
            return
        exe = adbcore.find_adb()
        cmd = [exe, "-s", adb.serial, "shell"]
        title = _("adb shell — %s") % (self.ctl.current.label)
        term = osutil.open_terminal(cmd, title)
        if term:
            self.ctl.log.emit(">> %s %s" % (term, " ".join(cmd)), "cmd")
            return
        self.toast(_("Aucun terminal trouvé. Utilise le bouton Shell de la console."))

    def _open_dir(self, d):
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def restart(self):
        import os
        import sys
        from PySide6.QtCore import QProcess
        self.close()
        args = sys.argv[1:] if getattr(sys, "frozen", False) else ["-m", "adbpilot"] + sys.argv[1:]
        QProcess.startDetached(sys.executable, args, os.getcwd())
        QApplication.instance().quit()

    def closeEvent(self, e):
        config["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        config.save()
        self.console.shutdown()
        self.ctl.shutdown()
        super().closeEvent(e)
