from __future__ import annotations

import html
import re
import platform
import time

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from .. import VERSION, adbcore
from ..adbcore import adb
from .. import osutil
from ..config import config
from ..i18n import _, lang

LEVEL_COLORS = {"dark": {"cmd": "#a9a9ad", "out": "#e8e8e8", "ok": "#4cd964", "err": "#ff5c5c",
                         "info": "#7fb8ff", "logcat": "#c8c8c8", "shell": "#e8e8e8"},
                "blue": {"cmd": "#666", "out": "#111", "ok": "#11a84a", "err": "#d01010",
                         "info": "#1e3a7b", "logcat": "#333", "shell": "#111"}}


def split_host_commands(text):
    """Découpe une saisie en commandes adb/fastboot successives.

    Une nouvelle commande commence après un retour à la ligne, « && » ou « ; » situé hors
    guillemets ET suivi de « adb » ou « fastboot ». Le reste (y compris ; | && à l'intérieur
    d'une commande shell) est laissé intact pour le shell de l'appareil.
    Renvoie [(commande, séparateur_précédent), …].
    """
    out, buf, sep = [], [], None
    i, n, quote = 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf += [c, text[i + 1]]
            i += 2
            continue
        # « …; done adb reboot » : après done/fi/esac, le shell n'accepte pas d'argument,
        # donc un « adb »/« fastboot » qui suit est forcément une nouvelle commande.
        if c in " \t" and re.search(r"(^|[;&|])\s*(done|fi|esac)$", "".join(buf)) and \
                re.match(r"^\s+(adb|fastboot)\b", text[i:]):
            out.append(("".join(buf).strip(), sep))
            buf, sep = [], ";"
            i += 1
            continue
        for tok in ("&&", ";", "\n"):
            if text.startswith(tok, i):
                rest = text[i + len(tok):].lstrip(" \t")
                if re.match(r"^(adb|fastboot)\b", rest) or (tok == "\n" and rest.strip()):
                    cmd = "".join(buf).strip()
                    if cmd:
                        out.append((cmd, sep))
                    buf, sep = [], tok if tok != "\n" else ";"
                    i += len(tok)
                    break
        else:
            buf.append(c)
            i += 1
    cmd = "".join(buf).strip()
    if cmd:
        out.append((cmd, sep))
    return out


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
        b_copy = QPushButton(_("Copier\nle journal"))
        b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out.toPlainText()))
        b_clear = QPushButton(_("Effacer\nla console"))
        b_clear.clicked.connect(self.out.clear)
        self.b_logcat = QPushButton("Logcat")
        self.b_logcat.setCheckable(True)
        self.b_logcat.toggled.connect(self.toggle_logcat)
        self.b_shell = QPushButton("Shell")
        self.b_shell.setCheckable(True)
        self.b_shell.toggled.connect(self.toggle_shell)
        b_term = QPushButton(_("Terminal\nexterne"))
        b_term.clicked.connect(self.main.open_terminal_shell)
        b_kill = QPushButton(_("Ctrl+C\n(stop)"))
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
        b_enter = QPushButton(_("ENTRÉE"))
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
        bot.addWidget(QLabel(_("Commandes rapides")))
        b_add = QPushButton("+")
        b_add.setObjectName("small")
        b_add.setFixedSize(26, 24)
        b_add.setToolTip(_("Ajouter la commande saisie"))
        b_add.clicked.connect(self._fast_add)
        b_del = QPushButton("−")
        b_del.setObjectName("small")
        b_del.setFixedSize(26, 24)
        b_del.setToolTip(_("Supprimer la commande choisie"))
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
        cpu, ram = osutil.host_cpu_ram()
        if cpu or ram:
            self.append("### %s / RAM %d Go" % (html.escape(cpu), ram), "cmd")
        self.append("### %s / Python %s" % (html.escape(osutil.os_name()), platform.python_version()), "cmd")
        self.append("### ADB Pilot %s · adb : %s" % (VERSION, html.escape(adbcore.find_adb() or "introuvable")), "cmd")
        self.append("", "out")

    # -- sortie ------------------------------------------------------------
    def append(self, text, level="out"):
        if lang() == "en":
            text = text.replace("[Succès] : ", "[Success]: ").replace("[Erreur] : ", "[Error]: ")
        c = LEVEL_COLORS["blue" if config.get("theme") == "blue" else "dark"]
        color = c.get(level, c["out"])
        if level == "cmd" and text.startswith(">>"):
            text = "<br>" + text
        body = text if ("<a " in text or "<br>" in text) else text.replace("\n", "<br>")
        body = body.replace("  ", "&nbsp; ")
        sb = self.out.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 4
        self.out.append(_("<span style='color:%s; white-space: pre-wrap;'>%s</span>") % (color, body))
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
        cmds = split_host_commands(t)
        if len(cmds) == 1 and cmds[0][0].strip() in ("shell", "adb shell"):
            self.append(_(">> adb shell (ouverture dans un terminal)"), "cmd")
            self.main.open_terminal_shell()
            return
        self._queue = cmds
        self._run_next(True)

    def _run_next(self, prev_ok):
        while self._queue:
            raw, sep = self._queue.pop(0)
            if sep == "&&" and not prev_ok:
                self.append(_("Commande suivante annulée (la précédente a échoué)."), "err")
                self._queue = []
                return
            job = self._prepare(raw)
            if job is None:
                continue
            exe, full, shown, after = job
            self.append(shown, "cmd")

            def done(code, after=after):
                if after:
                    after()
                self._run_next(code == 0)
            self._run_proc(exe, full, done=done)
            return

    def _prepare(self, raw):
        """Prépare (programme, arguments, texte affiché, rappel) pour une commande saisie."""
        raw = raw.strip()
        prog = "fastboot" if self.mode == "fastboot" else "adb"
        m = re.match(r"^(adb|fastboot)\b\s*", raw)
        if m:
            prog = m.group(1)
            raw = raw[m.end():]
            if prog == "fastboot":
                self.b_fastboot.setChecked(True)
        if prog == "fastboot":
            exe = adbcore.find_fastboot()
            if not exe:
                self.append(_("[Erreur] : fastboot introuvable (Paramètres → Télécharger adb)") if osutil.WINDOWS
                            else _("[Erreur] : fastboot introuvable (sudo apt install fastboot)"), "err")
                return None
            args = adbcore.split_cmd(raw)
            return exe, args, ">> fastboot " + html.escape(raw), None
        exe = adbcore.find_adb()
        if not exe:
            self.append(_("[Erreur] : adb introuvable"), "err")
            return None
        # options globales d'adb (-s SERIE, -t ID, -d, -e…)
        opts = []
        while True:
            mo = re.match(r"^(-[st])\s+(\S+)\s*|^(-[deHL]\S*)\s*", raw)
            if not mo:
                break
            opts += [mo.group(1), mo.group(2)] if mo.group(1) else [mo.group(3)]
            raw = raw[mo.end():]
        ms = re.match(r"^(shell|exec-out)\b\s*", raw)
        if ms:
            # La commande distante est transmise telle quelle, en UN seul argument :
            # ; | && > $ et guillemets sont interprétés par le shell de l'appareil.
            remote = raw[ms.end():].strip()
            inner = adbcore.split_cmd(remote) if remote[:1] in "\"'" else None
            if inner is not None and len(inner) == 1 and remote[-1:] == remote[:1]:
                remote = inner[0]
            args = [ms.group(1)] + ([remote] if remote else [])
        else:
            args = adbcore.split_cmd(raw)
        if not opts and adb.serial and args and args[0] not in (
                "devices", "connect", "disconnect", "pair", "kill-server", "start-server", "version", "mdns"):
            opts = ["-s", adb.serial]
        return exe, opts + args, ">> adb " + html.escape(raw), self._after_adb(args)

    def _after_adb(self, args):
        if args and args[0] in ("connect", "disconnect", "kill-server", "start-server", "tcpip", "usb"):
            return self.ctl.poll_devices
        return None

    def _run_proc(self, exe, args, after=None, done=None):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(lambda: self.append(
            html.escape(bytes(p.readAll()).decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")), "out"))

        def fin(code, _s):
            if code != 0:
                self.append(_("(code de sortie %d)") % code, "err")
            if after:
                after()
            p.deleteLater()
            if done:
                done(code)
        p.finished.connect(fin)
        p.start(exe, args)
        self._last = p

    def interrupt(self):
        if self.mode == "shell" and self.shell_proc:
            self.shell_proc.kill()
            self.append(_("Shell interrompu."), "info")
            if self.b_shell.isChecked():
                self._start_shell()
        p = getattr(self, "_last", None)
        try:
            if p is not None and p.state() == QProcess.Running:
                p.kill()
                self.append(_("Commande interrompue."), "info")
        except RuntimeError:
            pass

    # -- shell interactif ----------------------------------------------------
    def toggle_shell(self, on):
        if on:
            if not self.ctl.ready:
                self.append(_("[Erreur] : aucun appareil connecté"), "err")
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
            self.append(_("Shell fermé."), "info")

    def _start_shell(self):
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(lambda: self.append(
            html.escape(bytes(p.readAll()).decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")), "shell"))
        p.finished.connect(lambda *_: self.mode == "shell" and self.shell_proc is p and self._shell_died())
        p.start(adbcore.find_adb(), ["-s", adb.serial, "shell"])
        self.shell_proc = p
        self.append(_(">> adb shell  (session interactive : tape tes commandes, « exit » ou bouton "
                    "Shell pour quitter)"), "cmd")
        p.write(b"echo \"$(getprop ro.product.model) | Android $(getprop ro.build.version.release) | $(id -un 2>/dev/null || whoami)\"\n")

    def _shell_died(self):
        self.append(_("La session shell s'est terminée."), "info")
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
                self.append(_("[Erreur] : aucun appareil connecté"), "err")
                self.b_logcat.setChecked(False)
                return
            p = QProcess(self)
            p.setProcessChannelMode(QProcess.MergedChannels)
            p.readyRead.connect(lambda: self.append(
                html.escape(bytes(p.readAll()).decode("utf-8", "replace").replace("\r\n", "\n").rstrip("\n")), "logcat"))
            p.start(adbcore.find_adb(), ["-s", adb.serial, "logcat", "-v", "time", "-T", "200"])
            self.logcat_proc = p
            self.append(_(">> adb logcat (bouton Logcat pour arrêter)"), "cmd")
        elif self.logcat_proc:
            self.logcat_proc.kill()
            self.logcat_proc = None
            self.append(_("Logcat arrêté."), "info")

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

