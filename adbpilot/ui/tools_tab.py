from __future__ import annotations

import html
import re
import shlex
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .. import adbcore
from ..adbcore import adb
from ..config import config, user_dir
from .dialogs import PairDialog


class PhoneFrame(QWidget):
    """Maquette de téléphone affichant la dernière capture d'écran."""

    def __init__(self, on_click):
        super().__init__()
        self.img: QImage | None = None
        self.on_click = on_click
        self.setMinimumSize(190, 330)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Cliquer pour rafraîchir l'aperçu")

    def set_image(self, img):
        self.img = img
        self.update()

    def mousePressEvent(self, e):
        self.on_click()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height() - 8
        landscape = self.img is not None and self.img.width() > self.img.height()
        ratio = 0.5 if not landscape else 1.7
        w = min(self.width() - 8, h * ratio)
        if landscape:
            h = min(h, w / ratio)
        x = (self.width() - w) / 2
        y = (self.height() - h) / 2
        body = QRectF(x, y, w, h)
        path = QPainterPath()
        path.addRoundedRect(body, 26, 26)
        p.fillPath(path, QColor("#2a2a2c"))
        p.setPen(QPen(QColor("#5a5a5e"), 2))
        p.drawPath(path)
        m = 10
        top = 30 if not landscape else 12
        scr = QRectF(x + m, y + top, w - 2 * m, h - top - (34 if not landscape else 12))
        p.fillRect(scr, QColor("#000"))
        if self.img is not None:
            sc = self.img.scaled(int(scr.width()), int(scr.height()), Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation)
            p.drawImage(int(scr.center().x() - sc.width() / 2), int(scr.center().y() - sc.height() / 2), sc)
        else:
            p.setPen(QColor("#888"))
            p.drawText(scr, Qt.AlignCenter | Qt.TextWordWrap, "Cliquer ici\npour un aperçu\nde l'écran")
        if not landscape:
            pen = QPen(QColor("#777"), 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(int(x + w / 2 - 18), int(y + 15), int(x + w / 2 + 18), int(y + 15))
            p.setPen(QPen(QColor("#999"), 1.5))
            cy = y + h - 17
            p.drawText(QRectF(x + w * 0.2 - 10, cy - 9, 20, 18), Qt.AlignCenter, "◁")
            p.drawEllipse(QRectF(x + w / 2 - 5, cy - 5, 10, 10))
            p.drawRect(QRectF(x + w * 0.8 - 5, cy - 5, 10, 10))
        p.end()


class ToolsTab(QWidget):
    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self.rec_proc: QProcess | None = None
        self.rec_remote = "/sdcard/adbpilot_rec.mp4"
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
        self.lbl_info = QLabel("Aucun appareil")
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        il.addWidget(self.lbl_info)
        il.addStretch(1)
        lay.addWidget(info, 0, Qt.AlignTop)
        lay.addStretch(1)

        lcol = QVBoxLayout()
        lcol.addStretch(1)
        lcol.addWidget(self._btn("Capture d'écran", self.screenshot))
        self.b_rec = self._btn("Enregistrement\nvidéo", self.toggle_record)
        lcol.addWidget(self.b_rec)
        lcol.addSpacing(30)
        self.b_reboot = self._btn("Redémarrer ▾", self.reboot_menu)
        lcol.addWidget(self.b_reboot)
        lcol.addStretch(1)
        lay.addLayout(lcol)

        self.phone = PhoneFrame(self.screenshot_preview)
        self.phone.setFixedWidth(240)
        lay.addWidget(self.phone)

        rcol = QVBoxLayout()
        rcol.addStretch(1)
        keys = QGridLayout()
        keys.setSpacing(4)
        for i, (t, code) in enumerate([("Vol +", 24), ("Vol −", 25), ("Power", 26), ("Muet", 164),
                                       ("Accueil", 3), ("Retour", 4), ("Récents", 187), ("Menu", 82)]):
            b = QPushButton(t)
            b.setObjectName("phoneKey")
            b.clicked.connect(lambda _=False, c=code: self.keyevent(c))
            keys.addWidget(b, i % 4, i // 4)
        rcol.addLayout(keys)
        rcol.addSpacing(24)
        self.lbl_scrcpy = QLabel()
        self.lbl_scrcpy.setAlignment(Qt.AlignCenter)
        rcol.addWidget(self.lbl_scrcpy)
        self.b_scrcpy = self._btn("Contrôler l'écran\n(scrcpy)", self.launch_scrcpy, 180, 60)
        rcol.addWidget(self.b_scrcpy, 0, Qt.AlignHCenter)
        self.cb_record = QCheckBox("Enregistrer la vidéo")
        self.cb_record.setToolTip("Enregistre la session scrcpy dans %s" % user_dir("videos"))
        self.cb_record.setChecked(bool(config.get("scrcpy_record")))
        self.cb_record.toggled.connect(lambda v: (config.__setitem__("scrcpy_record", v), config.save()))
        rcol.addWidget(self.cb_record, 0, Qt.AlignHCenter)
        resrow = QHBoxLayout()
        resrow.addStretch(1)
        resrow.addWidget(QLabel("Résolution :"))
        self.cmb_res = QComboBox()
        for v in (480, 720, 1080, 1920):
            self.cmb_res.addItem("%d px" % v, v)
        self.cmb_res.setCurrentIndex(max(0, self.cmb_res.findData(int(config.get("scrcpy_res", 1080)))))
        self.cmb_res.setToolTip("Taille maximale de l'image scrcpy (plus grand côté)")
        self.cmb_res.currentIndexChanged.connect(
            lambda _: (config.__setitem__("scrcpy_res", self.cmb_res.currentData()), config.save()))
        resrow.addWidget(self.cmb_res)
        resrow.addStretch(1)
        rcol.addLayout(resrow)
        rcol.addSpacing(16)
        rcol.addWidget(self._btn("Appairer (Android 11+)", lambda: PairDialog(self.ctl, self).exec(), 180, 36), 0, Qt.AlignHCenter)
        rcol.addStretch(1)
        lay.addLayout(rcol)
        lay.addStretch(1)
        self.refresh_scrcpy_label()

    def refresh_scrcpy_label(self):
        exe = adbcore.find_scrcpy()
        if exe:
            self.lbl_scrcpy.setText("<span style='color:#2fd06b'>scrcpy installé</span>")

            def ver():
                import subprocess
                try:
                    out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                         timeout=10).stdout
                except Exception:  # noqa: BLE001
                    return None
                m = re.search(r"scrcpy\s+v?([\d.]+)", out)
                return m.group(1) if m else None
            self.ctl.submit(ver, done=lambda v: isinstance(v, str) and self.lbl_scrcpy.setText(
                "<span style='color:#2fd06b'>scrcpy v%s installé</span>" % v))
        else:
            self.lbl_scrcpy.setText("<span style='color:#ff5c5c'>scrcpy introuvable</span><br>"
                                    "<span style='font-size:8pt'>sudo apt install scrcpy<br>ou Paramètres → Télécharger</span>")

    def _need(self):
        if not self.ctl.ready:
            self.main.toast("Aucun appareil connecté.")
            return False
        return True

    # -- infos -------------------------------------------------------------
    def _on_device(self, dev):
        if dev is None or dev.state != "device":
            self.lbl_info.setText("Aucun appareil" if dev is None else "%s\n%s" % (dev.serial, dev.state))
            self.phone.set_image(None)

    def _on_info(self, i):
        sp = i.get("specs") or {}
        cpu = sp.get("soc") or i.get("board") or i.get("hardware")
        extra = []
        if sp.get("cores"):
            extra.append("%d cœurs" % sp["cores"])
        if sp.get("max_ghz"):
            extra.append(("%.2f GHz" % sp["max_ghz"]).replace(".", ","))
        if extra:
            cpu = "%s\n%s" % (cpu, " · ".join(extra))
        if sp.get("android"):
            android = "%s (API %s)" % (sp["android"], sp.get("sdk"))
            if sp.get("fake"):
                android += "\n⚠ build.prop annonce %s" % i.get("release")
        else:
            android = "%s (API %s)" % (i.get("release"), i.get("sdk"))
        mem = []
        if sp.get("ram_gb"):
            mem.append("RAM %s Go" % sp["ram_gb"])
        if sp.get("storage_gb"):
            mem.append("Stockage %s GB" % sp["storage_gb"])
        rows = [("Modèle", i.get("model")), ("N° de série", i.get("serial")),
                ("Processeur", cpu), ("Mémoire", " · ".join(mem)), ("ABI", i.get("abi")),
                ("Android", android), ("ROM", i.get("build"))]
        txt = "<b style='font-size:12pt'>%s</b><br>" % html.escape(i.get("brand", "") or i.get("manufacturer", ""))
        for k, v in rows:
            if v:
                txt += "<b>%s :</b><br>%s<br>" % (k, html.escape(v).replace("\n", "<br>"))
        self.lbl_info.setText(txt)

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

    def screenshot_preview(self):
        if not self._need():
            return
        self.ctl.submit(self._grab, done=lambda r: (not isinstance(r, Exception) and not r[1].isNull()
                                                     and self.phone.set_image(r[1])))

    def screenshot(self):
        if not self._need():
            return
        dev = self.ctl.current

        def done(r):
            if isinstance(r, Exception):
                return
            data, img = r
            if img.isNull():
                self.ctl.log.emit("[Erreur] : capture impossible", "err")
                return
            self.phone.set_image(img)
            name = "%s_%s.png" % (self._devname(dev), time.strftime("%Y_%m_%d_%H_%M_%S"))
            f = self._screens_dir() / name
            f.write_bytes(data)
            self.ctl.log.emit("[Succès] : Capture enregistrée : <a href='file://%s'>%s</a>" % (
                html.escape(str(f)), html.escape(str(f))), "ok")
            self.main.set_status("Capture enregistrée : %s" % f)
        self.ctl.submit(self._grab, done=done)

    def toggle_record(self):
        if self.rec_proc is None:
            if not self._need():
                return
            self.rec_proc = QProcess(self)
            self.rec_proc.setProgram(adbcore.find_adb())
            self.rec_proc.setArguments(["-s", adb.serial, "shell", "screenrecord", self.rec_remote])
            self.rec_proc.finished.connect(self._rec_finished)
            self.rec_proc.start()
            self.b_rec.setText("■ Arrêter\nl'enregistrement")
            self.b_rec.setStyleSheet("color: #ff5c5c;")
            self.ctl.log.emit(">> adb shell screenrecord %s (3 min max)" % self.rec_remote, "cmd")
        else:
            self.ctl.submit(lambda: adb.shell("pkill -INT screenrecord || killall -INT screenrecord"))

    def _rec_finished(self):
        self.rec_proc = None
        self.b_rec.setText("Enregistrement\nvidéo")
        self.b_rec.setStyleSheet("")
        dev = self.ctl.current
        name = "%s_%s.mp4" % (self._devname(dev), time.strftime("%Y_%m_%d_%H_%M_%S"))
        f = user_dir("videos") / name

        def work():
            time.sleep(1)
            r = adb.run(["pull", self.rec_remote, str(f)], timeout=300)
            adb.shell("rm -f " + self.rec_remote)
            return r
        def done(r):
            if getattr(r, "ok", False):
                self.ctl.log.emit("[Succès] : Vidéo enregistrée : <a href='file://%s'>%s</a>" % (f, f), "ok")
                self.main.notify("Vidéo enregistrée", str(f))
            else:
                self.ctl.log.emit("[Erreur] : récupération de la vidéo impossible", "err")
        self.ctl.submit(work, done=done)

    def reboot_menu(self):
        if not self._need():
            return
        m = QMenu(self)
        for label, args in [("Redémarrer", ["reboot"]), ("Recovery", ["reboot", "recovery"]),
                            ("Bootloader", ["reboot", "bootloader"]),
                            ("Fastboot (fastbootd)", ["reboot", "fastboot"]),
                            ("Éteindre", ["shell", "reboot", "-p"])]:
            m.addAction(label, lambda a=args: self.ctl.submit(self.ctl.adb_logged, a))
        m.exec(self.b_reboot.mapToGlobal(self.b_reboot.rect().bottomLeft()))

    def to_wifi(self):
        if not self._need():
            return
        dev = self.ctl.current
        if dev.is_network:
            self.main.toast("L'appareil est déjà connecté en Wi-Fi.")
            return

        port = str(config.get("port", "auto"))
        port = port if port.isdigit() else "5555"

        def work():
            ip = adbcore.device_ip()
            self.ctl.adb_logged(["tcpip", port], timeout=20)
            time.sleep(2)
            return ip
        self.ctl.submit(work, done=lambda ip: (self.ctl.connect_ip(ip) if isinstance(ip, str)
                                               else self.ctl.log.emit("[Erreur] : IP introuvable", "err")))

    def launch_scrcpy(self):
        if not self._need():
            return
        exe = adbcore.find_scrcpy()
        if not exe:
            self.main.toast("scrcpy introuvable : sudo apt install scrcpy, ou Paramètres → Télécharger scrcpy.")
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
            html.escape(bytes(proc.readAll()).decode("utf-8", "replace").rstrip()), "out"))
        def finished(code, _s):
            self.ctl.log.emit("scrcpy terminé (code %d)" % code, "info")
            if rec_file is not None and rec_file.is_file() and rec_file.stat().st_size > 0:
                self.ctl.log.emit("[Succès] : Vidéo enregistrée : <a href='file://%s'>%s</a>" % (
                    rec_file, rec_file), "ok")
                self.main.notify("Vidéo enregistrée", str(rec_file))
        proc.finished.connect(finished)
        self.ctl.log.emit(">> scrcpy " + " ".join(shlex.quote(a) for a in args), "cmd")
        proc.start()
        self._scrcpy = proc


def open_url(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

