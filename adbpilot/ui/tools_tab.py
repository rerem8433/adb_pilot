from __future__ import annotations

import html
import re
import shlex
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QToolButton, QVBoxLayout, QWidget)

from .. import adbcore
from ..adbcore import adb
from ..config import config, user_dir
from ..osutil import WINDOWS, no_window
from . import style
from .dialogs import PairDialog
from ..i18n import _


class RemoteControl(QWidget):
    """Télécommande Android TV dessinée ; chaque touche envoie un keyevent à l'appareil."""

    W, H = 210, 560

    def __init__(self, tools):
        super().__init__()
        self.tools = tools
        self.setFixedSize(self.W, self.H)
        cx = self.W // 2
        self.dpad_c = (cx, 206)
        # (icône, tooltip, x centre, y centre, taille, style, action)
        keys = [
            ("power", _("Alimentation (éteindre, redémarrer…)"), 46, 46, 42, "red", self.tools.power_menu),
            ("camera", _("Capture d'écran"), self.W - 46, 46, 42, "grey", self.tools.screenshot),
            ("menu", "Menu", 46, 108, 42, "grey", lambda: self.tools.keyevent(82)),
            ("gear", _("Paramètres Android"), self.W - 46, 108, 42, "grey", self.tools.open_settings),
            ("up", _("Haut"), cx, 206 - 50, 34, "dpad", lambda: self.tools.keyevent(19)),
            ("down", _("Bas"), cx, 206 + 50, 34, "dpad", lambda: self.tools.keyevent(20)),
            ("left", _("Gauche"), cx - 50, 206, 34, "dpad", lambda: self.tools.keyevent(21)),
            ("right", _("Droite"), cx + 50, 206, 34, "dpad", lambda: self.tools.keyevent(22)),
            (None, "OK", cx, 206, 50, "ok", lambda: self.tools.keyevent(23)),
            ("back", _("Retour"), 46, 318, 42, "grey", lambda: self.tools.keyevent(4)),
            ("home", _("Accueil"), cx, 334, 46, "white", lambda: self.tools.keyevent(3)),
            ("recents", _("Applications récentes"), self.W - 46, 318, 42, "grey", lambda: self.tools.keyevent(187)),
            ("mute", _("Muet"), cx, 430, 38, "grey", lambda: self.tools.keyevent(164)),
            ("plus", _("Volume +"), 46, 398, 36, "rocker", lambda: self.tools.keyevent(24)),
            ("minus", _("Volume −"), 46, 462, 36, "rocker", lambda: self.tools.keyevent(25)),
            ("up", _("Chaîne +"), self.W - 46, 398, 36, "rocker", lambda: self.tools.keyevent(166)),
            ("down", _("Chaîne −"), self.W - 46, 462, 36, "rocker", lambda: self.tools.keyevent(167)),
        ]
        styles = {
            "red": ("#d83a3a", "#ef5a5a", "#ffffff"),
            "grey": ("#454c5c", "#5a6274", "#ffffff"),
            "white": ("#f2f3f5", "#ffffff", "#454c5c"),
            "dpad": ("transparent", "rgba(255,255,255,0.10)", "#e8e8ea"),
            "ok": ("#14171d", "#22262f", "#ffffff"),
            "rocker": ("transparent", "rgba(255,255,255,0.10)", "#ffffff"),
        }
        for icon_name, tip, x, y, size, st, fn in keys:
            bg, hover, fg = styles[st]
            b = QToolButton(self)
            b.setFixedSize(size, size)
            b.move(int(x - size / 2), int(y - size / 2))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QToolButton { background: %s; border: none; border-radius: %dpx; }"
                "QToolButton:hover { background: %s; }"
                "QToolButton:pressed { background: #24448f; }" % (bg, size // 2, hover))
            if icon_name:
                b.setIcon(style.icon(icon_name, fg, 64))
                b.setIconSize(QSize(int(size * 0.5), int(size * 0.5)))
            b.clicked.connect(fn)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        body = QRectF(6, 4, self.W - 12, self.H - 8)
        path = QPainterPath()
        path.addRoundedRect(body, 44, 44)
        p.fillPath(path, QColor("#2c3240"))
        p.setPen(QPen(QColor("#4a5163"), 1.5))
        p.drawPath(path)
        # micro
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#11141a"))
        p.drawEllipse(QRectF(self.W / 2 - 3, 44, 6, 6))
        # pavé directionnel
        cx, cy = self.dpad_c
        p.setBrush(QColor("#1b1f27"))
        p.drawEllipse(QRectF(cx - 80, cy - 80, 160, 160))
        p.setBrush(QColor("#2c3240"))
        p.drawEllipse(QRectF(cx - 30, cy - 30, 60, 60))
        # bascules volume / chaîne
        p.setBrush(QColor("#454c5c"))
        for x in (46, self.W - 46):
            p.drawRoundedRect(QRectF(x - 22, 372, 44, 116), 22, 22)
        # nom
        p.setPen(QColor("#8a91a3"))
        f = p.font()
        f.setPointSizeF(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, self.H - 50, self.W, 20), Qt.AlignCenter, "ADB Pilot")
        p.end()


class ToolsTab(QWidget):
    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self._build()
        ctl.info_ready.connect(self._on_info)
        ctl.device_changed.connect(self._on_device)

    def _btn(self, text, fn, w=132, h=44, obj=None):
        b = QPushButton(text)
        b.setFixedSize(w, h)
        if obj:
            b.setObjectName(obj)
        b.clicked.connect(fn)
        return b

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        info = QFrame()
        info.setFrameShape(QFrame.StyledPanel)
        info.setFixedWidth(220)
        il = QVBoxLayout(info)
        self.lbl_info = QLabel(_("Aucun appareil"))
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        il.addWidget(self.lbl_info)
        il.addStretch(1)
        lay.addWidget(info, 0, Qt.AlignTop)
        lay.addStretch(1)

        self.remote = RemoteControl(self)
        lay.addWidget(self.remote, 0, Qt.AlignVCenter)
        lay.addSpacing(40)

        rcol = QVBoxLayout()
        rcol.addStretch(1)
        self.lbl_scrcpy = QLabel()
        self.lbl_scrcpy.setAlignment(Qt.AlignCenter)
        rcol.addWidget(self.lbl_scrcpy)
        self.b_scrcpy = self._btn(_("Contrôler l'écran\n(scrcpy)"), self.launch_scrcpy, 180, 60)
        rcol.addWidget(self.b_scrcpy, 0, Qt.AlignHCenter)
        self.cb_record = QCheckBox(_("Enregistrer la vidéo"))
        self.cb_record.setToolTip(_("Enregistre la session scrcpy dans %s") % user_dir("videos"))
        self.cb_record.setChecked(bool(config.get("scrcpy_record")))
        self.cb_record.toggled.connect(lambda v: (config.__setitem__("scrcpy_record", v), config.save()))
        rcol.addWidget(self.cb_record, 0, Qt.AlignHCenter)
        resrow = QHBoxLayout()
        resrow.addStretch(1)
        resrow.addWidget(QLabel(_("Résolution :")))
        self.cmb_res = QComboBox()
        for v in (480, 720, 1080, 1920):
            self.cmb_res.addItem("%d px" % v, v)
        self.cmb_res.setCurrentIndex(max(0, self.cmb_res.findData(int(config.get("scrcpy_res", 1080)))))
        self.cmb_res.setToolTip(_("Taille maximale de l'image scrcpy (plus grand côté)"))
        self.cmb_res.currentIndexChanged.connect(
            lambda _x: (config.__setitem__("scrcpy_res", self.cmb_res.currentData()), config.save()))
        resrow.addWidget(self.cmb_res)
        resrow.addStretch(1)
        rcol.addLayout(resrow)
        self.lbl_audio = QLabel()
        self.lbl_audio.setAlignment(Qt.AlignCenter)
        self.lbl_audio.setWordWrap(True)
        self.lbl_audio.setFixedWidth(200)
        self.lbl_audio.setStyleSheet("font-size: 8pt; color: #e6c22e;")
        self.lbl_audio.hide()
        rcol.addWidget(self.lbl_audio, 0, Qt.AlignHCenter)
        rcol.addSpacing(16)
        rcol.addWidget(self._btn(_("Appairer (Android 11+)"), lambda: PairDialog(self.ctl, self).exec(), 180, 36), 0, Qt.AlignHCenter)
        rcol.addStretch(1)
        lay.addLayout(rcol)
        lay.addStretch(1)
        self.refresh_scrcpy_label()

    def refresh_scrcpy_label(self):
        exe = adbcore.find_scrcpy()
        if exe:
            self.lbl_scrcpy.setText(_("<span style='color:#2fd06b'>scrcpy installé</span>"))

            def ver():
                import subprocess
                try:
                    out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                         timeout=10, **no_window()).stdout
                except Exception:  # noqa: BLE001
                    return None
                m = re.search(r"scrcpy\s+v?([\d.]+)", out)
                return m.group(1) if m else None
            self.ctl.submit(ver, done=lambda v: isinstance(v, str) and self.lbl_scrcpy.setText(
                _("<span style='color:#2fd06b'>scrcpy v%s installé</span>") % v))
        else:
            self.lbl_scrcpy.setText(_("<span style='color:#ff5c5c'>scrcpy introuvable</span><br>"
                                    "<span style='font-size:8pt'>Paramètres → Télécharger</span>") if WINDOWS else
                                    _("<span style='color:#ff5c5c'>scrcpy introuvable</span><br>"
                                    "<span style='font-size:8pt'>sudo apt install scrcpy<br>ou Paramètres → Télécharger</span>"))

    def _need(self):
        if not self.ctl.ready:
            self.main.toast(_("Aucun appareil connecté."))
            return False
        return True

    # -- infos -------------------------------------------------------------
    def _on_device(self, dev):
        if dev is None or dev.state != "device":
            self.lbl_audio.hide()
            self.lbl_info.setText(_("Aucun appareil") if dev is None else "%s\n%s" % (dev.serial, dev.state))

    def _on_info(self, i):
        sp = i.get("specs") or {}
        try:
            sdk = int(sp.get("sdk") or i.get("sdk") or 0)
        except (TypeError, ValueError):
            sdk = 0
        if 0 < sdk < 30:
            self.lbl_audio.setText(_("Pas de son avec scrcpy : il faut Android 11 ou plus "
                                   "(cet appareil est en Android %s)") % (sp.get("android") or i.get("release")))
            self.lbl_audio.show()
        else:
            self.lbl_audio.hide()
        cpu = sp.get("soc") or i.get("board") or i.get("hardware")
        extra = []
        if sp.get("cores"):
            extra.append(_("%d cœurs") % sp["cores"])
        if sp.get("max_ghz"):
            extra.append(("%.2f GHz" % sp["max_ghz"]).replace(".", ","))
        if extra:
            cpu = "%s\n%s" % (cpu, " · ".join(extra))
        if sp.get("android"):
            android = "%s (API %s)" % (sp["android"], sp.get("sdk"))
            if sp.get("fake"):
                android += _("\n⚠ build.prop annonce %s") % i.get("release")
        else:
            android = "%s (API %s)" % (i.get("release"), i.get("sdk"))
        mem = []
        if sp.get("ram_gb"):
            mem.append(_("RAM %s Go") % sp["ram_gb"])
            if sp.get("ram_fake"):
                mem[-1] += _("\n⚠ la ROM annonce %s Go") % sp["ram_fake"]
        if sp.get("storage_gb"):
            mem.append(_("Stockage %s GB") % sp["storage_gb"])
        stor = None
        if sp.get("storage_total"):
            tot, used = sp["storage_total"], sp.get("storage_used")
            if used is not None:
                stor = _("%s Go utilisés sur %s Go\n%d %% occupé") % (
                    ("%.1f" % used).replace(".", ","), ("%.1f" % tot).replace(".", ","), round(100 * used / tot))
            else:
                stor = _("%s Go") % ("%.1f" % tot).replace(".", ",")
        rows = [(_("Modèle"), i.get("model")), (_("N° de série"), i.get("serial")),
                (_("Processeur"), cpu), (_("Mémoire"), "\n".join(mem)),
                (_("Stockage utilisateur"), stor), (_("Écran"), self._screen(sp)), ("ABI", i.get("abi")),
                ("Android", android), ("ROM", i.get("build"))]
        txt = _("<b style='font-size:12pt'>%s</b><br><span style='font-size:5pt'>&nbsp;</span><br>") % html.escape(i.get("brand", "") or i.get("manufacturer", ""))
        for k, v in rows:
            if v:
                txt += _("<b>%s :</b><br>%s<br>") % (k, html.escape(v).replace("\n", "<br>"))
        self.lbl_info.setText(txt)

    @staticmethod
    def _screen(sp):
        if not sp.get("res"):
            return None
        res = sp["res"].replace("x", " × ")
        if sp.get("res_over") and sp["res_over"] != sp["res"]:
            res += _(" (forcée : %s)") % sp["res_over"].replace("x", " × ")
        dpi = sp.get("dpi")
        if dpi:
            res += "\n" + _("Densité %s dpi") % dpi
            if sp.get("dpi_over") and sp["dpi_over"] != dpi:
                res += _(" (forcée : %s)") % sp["dpi_over"]
        return res

    # -- actions -----------------------------------------------------------
    def keyevent(self, code):
        if self._need():
            self.ctl.submit(lambda: adb.shell("input keyevent %d" % code))

    def _screens_dir(self):
        d = Path(config.get("screens_dir") or user_dir("images"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _devname(dev):
        return re.sub(r"[^\w.\-]+", "_", (dev.label if dev else "appareil")).strip("_")

    def _grab(self):
        data = adb.exec_out("screencap -p", timeout=30)
        img = QImage.fromData(data, "PNG")
        return data, img

    def screenshot(self):
        if not self._need():
            return
        dev = self.ctl.current

        def done(r):
            if isinstance(r, Exception):
                return
            data, img = r
            if img.isNull():
                self.ctl.log.emit(_("[Erreur] : capture impossible"), "err")
                return
            name = "%s_%s.png" % (self._devname(dev), time.strftime("%Y_%m_%d_%H_%M_%S"))
            f = self._screens_dir() / name
            f.write_bytes(data)
            self.ctl.log.emit(_("[Succès] : Capture enregistrée : <a href='%s'>%s</a>") % (
                html.escape(QUrl.fromLocalFile(str(f)).toString()), html.escape(str(f))), "ok")
            self.main.notify(_("Capture d'écran enregistrée"), str(f))
        self.ctl.submit(self._grab, done=done)

    def power_menu(self):
        if not self._need():
            return
        m = QMenu(self)
        for label, args in [(_("Éteindre"), ["shell", "reboot", "-p"]),
                            (_("Redémarrer"), ["reboot"]),
                            (_("Redémarrer en recovery"), ["reboot", "recovery"]),
                            (_("Redémarrer en bootloader"), ["reboot", "bootloader"]),
                            (_("Redémarrer en fastboot (fastbootd)"), ["reboot", "fastboot"])]:
            m.addAction(label, lambda a=args: self.ctl.submit(self.ctl.adb_logged, a))
        m.addSeparator()
        m.addAction(_("Mettre en veille / réveiller"), lambda: self.keyevent(26))
        btn = self.sender() if isinstance(self.sender(), QWidget) else self.remote
        m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def open_settings(self):
        if self._need():
            self.ctl.submit(lambda: adb.shell("am start -a android.settings.SETTINGS"))

    def to_wifi(self):
        if not self._need():
            return
        dev = self.ctl.current
        if dev.is_network:
            self.main.toast(_("L'appareil est déjà connecté en Wi-Fi."))
            return

        port = str(config.get("port", "auto"))
        port = port if port.isdigit() else "5555"

        def work():
            ip = adbcore.device_ip()
            self.ctl.adb_logged(["tcpip", port], timeout=20)
            time.sleep(2)
            return ip
        self.ctl.submit(work, done=lambda ip: (self.ctl.connect_ip(ip) if isinstance(ip, str)
                                               else self.ctl.log.emit(_("[Erreur] : IP introuvable"), "err")))

    def launch_scrcpy(self):
        if not self._need():
            return
        exe = adbcore.find_scrcpy()
        if not exe:
            self.main.toast(_("scrcpy introuvable : Paramètres → Télécharger scrcpy.") if WINDOWS else
                            _("scrcpy introuvable : sudo apt install scrcpy, ou Paramètres → Télécharger scrcpy."))
            return
        args = ["-s", adb.serial]
        c = config
        args += ["-m", str(self.cmb_res.currentData() or 1080)]
        if c.get("scrcpy_bitrate"):
            args += ["-b", str(c["scrcpy_bitrate"])]
        if c.get("scrcpy_max_fps"):
            args += ["--max-fps", str(c["scrcpy_max_fps"])]
        if c.get("scrcpy_no_audio"):
            args += ["--no-audio"]
        if c.get("scrcpy_turn_screen_off"):
            args += ["-S"]
        if c.get("scrcpy_stay_awake"):
            args += ["-w"]
        if c.get("scrcpy_show_touches"):
            args += ["-t"]
        if c.get("scrcpy_always_on_top"):
            args += ["--always-on-top"]
        dev = self.ctl.current
        args += ["--window-title", dev.label if dev else "scrcpy"]
        rec_file = None
        if self.cb_record.isChecked():
            rec_file = user_dir("videos") / ("%s_scrcpy_%s.mp4" % (self._devname(dev), time.strftime("%Y_%m_%d_%H_%M_%S")))
            args += ["--record", str(rec_file)]
        if c.get("scrcpy_extra"):
            args += shlex.split(c["scrcpy_extra"])
        env = QProcessEnvironment.systemEnvironment()
        env.insert("ADB", adbcore.find_adb() or "adb")
        srv = Path(exe).with_name("scrcpy-server")
        if srv.is_file():
            env.insert("SCRCPY_SERVER_PATH", str(srv))
        for k in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH"):
            env.remove(k)
        proc = QProcess(self)
        proc.setProcessEnvironment(env)
        proc.setProgram(exe)
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyRead.connect(lambda: self.ctl.log.emit(
            html.escape(bytes(proc.readAll()).decode("utf-8", "replace").replace("\r\n", "\n").rstrip()), "out"))
        def finished(code, _s):
            self.ctl.log.emit(_("scrcpy terminé (code %d)") % code, "info")
            if rec_file is not None and rec_file.is_file() and rec_file.stat().st_size > 0:
                self.ctl.log.emit(_("[Succès] : Vidéo enregistrée : <a href='%s'>%s</a>") % (
                    html.escape(QUrl.fromLocalFile(str(rec_file)).toString()), html.escape(str(rec_file))), "ok")
                self.main.notify(_("Vidéo enregistrée"), str(rec_file))
        proc.finished.connect(finished)
        self.ctl.log.emit(">> scrcpy " + " ".join(shlex.quote(a) for a in args), "cmd")
        proc.start()
        self._scrcpy = proc


def open_url(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

