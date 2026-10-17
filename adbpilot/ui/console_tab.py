from __future__ import annotations

import html
import platform
import time

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from .. import VERSION, adbcore
from ..adbcore import adb
from ..config import config

LEVEL_COLORS = {"dark": {"cmd": "#a9a9ad", "out": "#e8e8e8", "ok": "#4cd964", "err": "#ff5c5c",
                         "info": "#7fb8ff", "logcat": "#c8c8c8", "shell": "#e8e8e8"},
                "blue": {"cmd": "#666", "out": "#111", "ok": "#11a84a", "err": "#d01010",
                         "info": "#1e3a7b", "logcat": "#333", "shell": "#111"}}


class HistoryLine(QLineEdit):
    def __init__(self):
        super().__init__()
        self.history: list[str] = []
        self.pos = 0

    def push(self, t):
        if t and (not self.history or self.history[-1] != t):
            self.history.append(t)
        self.pos = len(self.history)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Up and self.history:
            self.pos = max(0, self.pos - 1)
            self.setText(self.history[self.pos])
            return
        if e.key() == Qt.Key_Down and self.history:
            self.pos = min(len(self.history), self.pos + 1)
            self.setText(self.history[self.pos] if self.pos < len(self.history) else "")
            return
        super().keyPressEvent(e)


class ConsoleTab(QWidget):
    def __init__(self, ctl, main):
        super().__init__()
        self.ctl = ctl
        self.main = main
        self.mode = "adb"  # adb | shell | fastboot
        self.shell_proc: QProcess | None = None
        self.logcat_proc: QProcess | None = None
        self._build()
        ctl.log.connect(self.append)
        ctl.device_changed.connect(self._on_device)
        self._banner()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        top = QHBoxLayout()
        self.out = QTextBrowser()
        self.out.setObjectName("console")
        self.out.setOpenLinks(False)
        self.out.anchorClicked.connect(lambda u: QDesktopServices.openUrl(u))
        self.out.document().setMaximumBlockCount(6000)
        top.addWidget(self.out, 1)
        side = QGridLayout()
        side.setSpacing(0)
        b_copy = QPushButton("Copier\nle journal")
        b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out.toPlainText()))
        b_clear = QPushButton("Effacer\nla console")
        b_clear.clicked.connect(self.out.clear)
        self.b_logcat = QPushButton("Logcat")
        self.b_logcat.setCheckable(True)
        self.b_logcat.toggled.connect(self.toggle_logcat)
        self.b_shell = QPushButton("Shell")
        self.b_shell.setCheckable(True)
        self.b_shell.toggled.connect(self.toggle_shell)
        b_term = QPushButton("Terminal\nexterne")
        b_term.clicked.connect(self.main.open_terminal_shell)
        b_kill = QPushButton("Ctrl+C\n(stop)")
        b_kill.clicked.connect(self.interrupt)
        for i, b in enumerate([b_copy, b_clear, self.b_logcat, self.b_shell, b_term, b_kill]):
            b.setFixedSize(84, 46)
            b.setStyleSheet("font-size: 8pt; padding: 2px;")
            side.addWidget(b, i // 2, i % 2)
        sw = QWidget()
        sw.setLayout(side)
        col = QVBoxLayout()
        col.addWidget(sw)
        col.addStretch(1)
        top.addLayout(col)
        lay.addLayout(top, 1)

        row = QHBoxLayout()
        self.prefix = QLabel("adb:>")
        self.prefix.setStyleSheet("font-family: monospace; font-weight: 600;")
        row.addWidget(self.prefix)
        self.inp = HistoryLine()
        self.inp.setObjectName("consoleInput")
        self.inp.returnPressed.connect(self.enter)
        row.addWidget(self.inp, 1)
        bx = QToolButton()
        bx.setText("x")
        bx.setAutoRaise(True)
        bx.clicked.connect(self.inp.clear)
        row.addWidget(bx)
        b_enter = QPushButton("ENTRÉE")
        b_enter.setFixedSize(110, 40)
        b_enter.clicked.connect(self.enter)
        row.addWidget(b_enter)
        lay.addLayout(row)

        bot = QHBoxLayout()
        self.b_fastboot = QPushButton("fastboot")
        self.b_fastboot.setCheckable(True)
        self.b_fastboot.setStyleSheet("font-size: 8pt; padding: 2px 6px;")
        self.b_fastboot.toggled.connect(self._fastboot_toggled)
        bot.addWidget(self.b_fastboot)
        bot.addStretch(1)
        bot.addWidget(QLabel("Commandes rapides"))
        b_add = QPushButton("+")
        b_add.setObjectName("small")
        b_add.setFixedSize(26, 24)
        b_add.setToolTip("Ajouter la commande saisie")
        b_add.clicked.connect(self._fast_add)
        b_del = QPushButton("−")
        b_del.setObjectName("small")
        b_del.setFixedSize(26, 24)
        b_del.setToolTip("Supprimer la commande choisie")
        b_del.clicked.connect(self._fast_del)
        bot.addWidget(b_add)
        bot.addWidget(b_del)
        self.fast = QComboBox()
        self.fast.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.fast.setMinimumWidth(320)
        self._fill_fast()
        self.fast.activated.connect(self._fast_pick)
        bot.addWidget(self.fast, 1)
        lay.addLayout(bot)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.out.clear)

    def _banner(self):
        self.append("### %s" % time.strftime("%d.%m.%Y %H:%M:%S"), "cmd")
        try:
            cpu = ""
            with open("/proc/cpuinfo") as f:
                for ln in f:
                    if ln.startswith("model name"):
                        cpu = ln.split(":", 1)[1].strip()
                        break
            with open("/proc/meminfo") as f:
                mem = int(f.readline().split()[1]) // 1048576
            self.append("### %s / RAM %d Go" % (html.escape(cpu), mem + 1), "cmd")
        except Exception:
            pass
        osname = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux") if hasattr(
            platform, "freedesktop_os_release") else "Linux"
        self.append("### %s / Python %s" % (html.escape(osname), platform.python_version()), "cmd")
        self.append("### ADB Pilot %s · adb : %s" % (VERSION, html.escape(adbcore.find_adb() or "introuvable")), "cmd")
        self.append("", "out")

    # -- sortie ------------------------------------------------------------
    def append(self, text, level="out"):
        c = LEVEL_COLORS["blue" if config.get("theme") == "blue" else "dark"]
        color = c.get(level, c["out"])
        if level == "cmd" and text.startswith(">>"):
            text = "<br>" + text
        body = text if ("<a " in text or "<br>" in text) else text.replace("\n", "<br>")
        body = body.replace("  ", "&nbsp; ")
        sb = self.out.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 4
        self.out.append("<span style='color:%s; white-space: pre-wrap;'>%s</span>" % (color, body))
        if at_end:
            self.out.moveCursor(QTextCursor.End)
            sb.setValue(sb.maximum())

    # -- saisie ------------------------------------------------------------
    def enter(self):
        t = self.inp.text().strip()
        self.inp.clear()
        self.inp.push(t)
        if self.mode == "shell":
            if self.shell_proc and self.shell_proc.state() == QProcess.Running:
                self.append("$ " + html.escape(t), "cmd")
                self.shell_proc.write((t + "\n").encode())
            return
        if not t:
            return
        args = adbcore.split_cmd(t)
        if args and args[0] in ("adb", "fastboot"):
            if args[0] == "fastboot":
                self.b_fastboot.setChecked(True)
            args = args[1:]
        if self.mode == "fastboot":
            exe = adbcore.find_fastboot()
            self.append(">> fastboot " + html.escape(" ".join(args)), "cmd")
            if not exe:
                self.append("[Erreur] : fastboot introuvable (sudo apt install fastboot)", "err")
                return
            self._run_proc(exe, args)
            return
        if args and args[0] == "shell" and len(args) == 1:
            self.append(">> adb shell (ouverture dans un terminal)", "cmd")
            self.main.open_terminal_shell()
            return
        exe = adbcore.find_adb()
        if not exe:
            self.append("[Erreur] : adb introuvable", "err")
            return
        full = (["-s", adb.serial] if adb.serial and args and args[0] not in (
            "devices", "connect", "disconnect", "pair", "kill-server", "start-server", "version",
            "mdns") else []) + args
        self.append(">> adb " + html.escape(" ".join(args)), "cmd")
        self._run_proc(exe, full, after=self._after_adb(args))

    def _after_adb(self, args):
        if args and args[0] in ("connect", "disconnect", "kill-server", "start-server", "tcpip", "usb"):
            return self.ctl.poll_devices
        return None

    def _run_proc(self, exe, args, after=None):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(lambda: self.append(
            html.escape(bytes(p.readAll()).decode("utf-8", "replace").rstrip("\n")), "out"))

        def fin(code, _s):
            if code != 0:
                self.append("(code de sortie %d)" % code, "err")
            if after:
                after()
            p.deleteLater()
        p.finished.connect(fin)
        p.start(exe, args)
        self._last = p

    def interrupt(self):
        if self.mode == "shell" and self.shell_proc:
            self.shell_proc.kill()
            self.append("Shell interrompu.", "info")
            if self.b_shell.isChecked():
                self._start_shell()
        p = getattr(self, "_last", None)
        try:
            if p is not None and p.state() == QProcess.Running:
                p.kill()
                self.append("Commande interrompue.", "info")
        except RuntimeError:
            pass

    # -- shell interactif ----------------------------------------------------
    def toggle_shell(self, on):
        if on:
            if not self.ctl.ready:
                self.append("[Erreur] : aucun appareil connecté", "err")
                self.b_shell.setChecked(False)
                return
            self.b_fastboot.setChecked(False)
            self._start_shell()
            self.mode = "shell"
            self.prefix.setText("shell:>")
            self.inp.setFocus()
        else:
            proc, self.shell_proc = self.shell_proc, None
            if proc:
                proc.write(b"exit\n")
                proc.waitForFinished(500)
                proc.kill()
            self.mode = "fastboot" if self.b_fastboot.isChecked() else "adb"
            self.prefix.setText(self.mode + ":>")
            self.append("Shell fermé.", "info")

    def _start_shell(self):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(lambda: self.append(
            html.escape(bytes(p.readAll()).decode("utf-8", "replace").rstrip("\n")), "shell"))
        p.finished.connect(lambda *_: self.mode == "shell" and self.shell_proc is p and self._shell_died())
        p.start(adbcore.find_adb(), ["-s", adb.serial, "shell"])
        self.shell_proc = p
        self.append(">> adb shell  (session interactive : tape tes commandes, « exit » ou bouton "
                    "Shell pour quitter)", "cmd")
        p.write(b"echo \"$(getprop ro.product.model) | Android $(getprop ro.build.version.release) | $(id -un 2>/dev/null || whoami)\"\n")

    def _shell_died(self):
        self.append("La session shell s'est terminée.", "info")
        self.shell_proc = None
        self.b_shell.blockSignals(True)
        self.b_shell.setChecked(False)
        self.b_shell.blockSignals(False)
        self.mode = "fastboot" if self.b_fastboot.isChecked() else "adb"
        self.prefix.setText(self.mode + ":>")

    def _fastboot_toggled(self, on):
        if on and self.b_shell.isChecked():
            self.b_shell.setChecked(False)
        self.mode = "fastboot" if on else ("shell" if self.b_shell.isChecked() else "adb")
        self.prefix.setText(self.mode + ":>")

    def _on_device(self, dev):
        if self.shell_proc and (dev is None or dev.state != "device" or
                                dev.serial not in " ".join(self.shell_proc.arguments())):
            self.b_shell.setChecked(False)
        if dev is not None and dev.state == "device" and config.get("auto_shell"):
            self.main.tabs.setCurrentWidget(self)
            if not self.b_shell.isChecked():
                self.b_shell.setChecked(True)

    # -- logcat ------------------------------------------------------------
    def toggle_logcat(self, on):
        if on:
            if not self.ctl.ready:
                self.append("[Erreur] : aucun appareil connecté", "err")
                self.b_logcat.setChecked(False)
                return
            p = QProcess(self)
            p.setProcessChannelMode(QProcess.MergedChannels)
            p.readyRead.connect(lambda: self.append(
                html.escape(bytes(p.readAll()).decode("utf-8", "replace").rstrip("\n")), "logcat"))
            p.start(adbcore.find_adb(), ["-s", adb.serial, "logcat", "-v", "time", "-T", "200"])
            self.logcat_proc = p
            self.append(">> adb logcat (bouton Logcat pour arrêter)", "cmd")
        elif self.logcat_proc:
            self.logcat_proc.kill()
            self.logcat_proc = None
            self.append("Logcat arrêté.", "info")

    # -- commandes rapides ---------------------------------------------------
    def _fill_fast(self):
        self.fast.clear()
        self.fast.addItems(config.get("fast_commands", []))
        self.fast.setCurrentIndex(-1)

    def _fast_pick(self, i):
        self.inp.setText(self.fast.itemText(i))
        self.inp.setFocus()

    def _fast_add(self):
        t = self.inp.text().strip()
        if not t:
            return
        lst = config.get("fast_commands", [])
        if t not in lst:
            lst.append(t)
            config["fast_commands"] = lst
            config.save()
            self._fill_fast()

    def _fast_del(self):
        t = self.fast.currentText()
        lst = [x for x in config.get("fast_commands", []) if x != t]
        config["fast_commands"] = lst
        config.save()
        self._fill_fast()

    def shutdown(self):
        for p in (self.shell_proc, self.logcat_proc):
            if p:
                p.kill()

