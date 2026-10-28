"""Contrôleur : état de l'appareil courant, exécution en arrière-plan, journal."""
from __future__ import annotations

import html
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal

from .. import adbcore, metacache
from ..adbcore import Device, adb
from ..config import config
from ..osutil import WINDOWS
from ..i18n import _


class Controller(QObject):
    log = Signal(str, str)                 # texte, niveau (cmd/out/ok/err/info)
    devices_changed = Signal(list)
    device_changed = Signal(object)        # Device | None (prêt = state 'device')
    info_ready = Signal(dict)
    packages_ready = Signal(list)
    package_meta = Signal(object)          # Package
    meta_progress = Signal(int, int)
    meta_started = Signal(int)             # nombre d'APK à lire
    ram_ready = Signal(int, int)
    status = Signal(str)
    connecting = Signal(str)
    connect_result = Signal(str, bool, str)
    specs_ready = Signal(dict)
    _call = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.meta_pool = ThreadPoolExecutor(max_workers=3)
        self._call.connect(lambda cb, res: cb(res))
        self.devices: list[Device] = []
        self.current: Device | None = None
        self.packages = []
        self._polling = False
        self._meta_gen = 0
        self._wanted_serial = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_devices)

    # -- utilitaires -------------------------------------------------------
    def submit(self, fn, *args, done=None, **kw):
        def run():
            try:
                res = fn(*args, **kw)
            except Exception as e:  # noqa: BLE001
                res = e
                self.log.emit(_("Erreur : %s") % e, "err")
            if done is not None:
                self._call.emit(done, res)
        return self.pool.submit(run)

    def in_main(self, cb, value=None):
        self._call.emit(cb, value)

    def logcmd(self, args):
        self.log.emit(">> adb " + " ".join(args), "cmd")

    def logres(self, r, ok_msg=None):
        if r.ok:
            if r.text:
                self.log.emit(html.escape(r.text), "out")
            if ok_msg:
                self.log.emit("[Succès] : " + ok_msg, "ok")
        else:
            self.log.emit("[Erreur] : " + html.escape(r.text or _("code %d") % r.rc), "err")

    def adb_logged(self, args, timeout=120, ok_msg=None):
        self.logcmd(args)
        r = adb.run(args, timeout=timeout)
        self.logres(r, ok_msg)
        return r

    @property
    def ready(self):
        return self.current is not None and self.current.state == "device"

    # -- appareils ---------------------------------------------------------
    def start(self):
        if not adbcore.find_adb():
            self.log.emit(_("adb introuvable : télécharge-le depuis l'onglet Paramètres.") if WINDOWS else
                          _("adb introuvable. Installe-le (sudo apt install adb) ou télécharge-le "
                            "depuis l'onglet Paramètres."), "err")
        else:
            self.submit(lambda: adbcore.adb.run(["start-server"], serial=False, timeout=30),
                        done=lambda r: self._after_server(r))
        self.timer.start(2000)

    def _after_server(self, r):
        if config.get("auto_reconnect") and config.get("last_ip"):
            self.connect_ip(config["last_ip"], quiet=True)
        self.poll_devices()

    def poll_devices(self):
        if self._polling or not adbcore.find_adb():
            return
        self._polling = True

        def done(devs):
            self._polling = False
            if isinstance(devs, Exception):
                return
            self._update_devices(devs)
        self.submit(adbcore.list_devices, done=done)

    def _update_devices(self, devs):
        old = [(d.serial, d.state) for d in self.devices]
        self.devices = devs
        if old != [(d.serial, d.state) for d in devs]:
            self.devices_changed.emit(devs)
        cur = self.current
        pick = None
        if self._wanted_serial:
            pick = next((d for d in devs if d.serial == self._wanted_serial), None)
        if pick is None and cur:
            pick = next((d for d in devs if d.serial == cur.serial), None)
        if pick is None and devs:
            pick = next((d for d in devs if d.state == "device"), devs[0])
        if pick is None:
            if cur is not None:
                self._set_current(None)
            return
        if cur is None or pick.serial != cur.serial or pick.state != cur.state:
            self._set_current(pick)

    def select(self, serial):
        self._wanted_serial = serial
        d = next((d for d in self.devices if d.serial == serial), None)
        if d and (self.current is None or d.serial != self.current.serial):
            self._set_current(d)

    def _set_current(self, dev):
        self.current = dev
        adb.serial = dev.serial if dev else None
        self._meta_gen += 1
        self.device_changed.emit(dev)
        if dev and dev.state == "device":
            self.log.emit(_("Connecté à %s (%s)") % (dev.label, dev.serial), "ok")
            if dev.is_network and ":" in dev.serial:
                names = dict(config.get("ip_names", {}))
                names[dev.serial.split(":")[0]] = dev.label
                config["ip_names"] = names
                config.save()
            self.load_info()
            self.refresh_packages()
            self.refresh_ram()
        elif dev and dev.state == "unauthorized":
            self.log.emit(_("Appareil %s non autorisé : accepte la demande de débogage USB sur "
                          "l'écran de l'appareil.") % dev.serial, "err")
        elif dev and "permission" in dev.state:
            self.log.emit(_("Pas de permission USB pour %s : installe les règles udev "
                          "(sudo apt install android-sdk-platform-tools-common) puis "
                          "rebranche l'appareil.") % dev.serial, "err")

    def connect_ip(self, text, quiet=False):
        text = text.strip()
        if not text:
            return
        port = str(config.get("port", "auto")).strip()
        port = port if port.isdigit() else "5555"
        target = text if ":" in text else "%s:%s" % (text, port)
        if not quiet:
            self.connecting.emit(target)

        def work():
            if not quiet:
                # Un seul appareil à la fois : on repart d'un serveur adb propre
                self.logcmd(["disconnect"])
                adb.run(["disconnect"], serial=False, timeout=10)
                self.logcmd(["kill-server"])
                adb.run(["kill-server"], serial=False, timeout=10)
                adb.run(["start-server"], serial=False, timeout=30)
                self.logcmd(["connect", target])
            r = adb.run(["connect", target], serial=False, timeout=12)
            ok = r.ok and ("connected to" in r.out) and "failed" not in r.out and "unable" not in r.out
            if not quiet or ok:
                self.log.emit(html.escape(r.text or _("pas de réponse")), "ok" if ok else "err")
            return r, ok

        def done(res):
            if isinstance(res, Exception):
                if not quiet:
                    self.connect_result.emit(target, False, str(res))
                return
            r, ok = res
            if ok:
                hist = [h for h in config.get("ip_history", []) if h != text]
                config["ip_history"] = [text] + hist[:14]
                config["last_ip"] = text
                config.save()
                self._wanted_serial = target
            if not quiet:
                self.connect_result.emit(target, ok, r.text)
            self.poll_devices()
        self.submit(work, done=done)

    def disconnect_ip(self, serial=None):
        args = ["disconnect"] + ([serial] if serial else [])

        def work():
            self.logcmd(args)
            r = adb.run(args, serial=False, timeout=15)
            self.logres(r)
        if serial and config.get("last_ip") and serial.startswith(config["last_ip"].split(":")[0]):
            config["last_ip"] = ""
            config.save()
        self._wanted_serial = None
        self.submit(work, done=lambda _x: self.poll_devices())

    # -- informations ------------------------------------------------------
    def load_info(self):
        serial = adb.serial

        def work():
            info = adbcore.device_info()
            try:
                specs = adbcore.device_specs(info)
            except Exception:  # noqa: BLE001
                specs = {}
            info["specs"] = specs
            return info

        def done(i):
            if isinstance(i, dict) and adb.serial == serial:
                self.last_info = i
                self.info_ready.emit(i)
                self.specs_ready.emit(i.get("specs", {}))
        self.submit(work, done=done)

    def refresh_ram(self):
        if not self.ready:
            return
        self.submit(adbcore.ram_info,
                    done=lambda r: isinstance(r, tuple) and self.ram_ready.emit(*r))

    # -- paquets -----------------------------------------------------------
    def refresh_packages(self):
        if not self.ready:
            return
        self.status.emit(_("Lecture de la liste des applications…"))
        serial = self.current.serial

        def done(pkgs):
            if isinstance(pkgs, Exception) or not self.ready or self.current.serial != serial:
                return
            lang = config.get("label_lang", "fr")
            old = {p.name: p for p in self.packages}
            for p in pkgs:
                o = old.get(p.name)
                if o and o.path == p.path and o.base_size == p.base_size and (o.label or o.icon or o.meta_done):
                    p.label, p.icon, p.version, p.meta_done = o.label, o.icon, o.version, o.meta_done
                elif config.get("load_meta", True):
                    metacache.load_cached(p, lang)
            self.packages = pkgs
            self.packages_ready.emit(pkgs)
            self.status.emit(_("%d applications") % len(pkgs))
            self.log.emit(_("[Succès] : Données des applications mises à jour."), "ok")
            if config.get("load_meta", True):
                self.start_meta()
        self.submit(adbcore.list_packages, done=done)

    def start_meta(self):
        self._meta_gen += 1
        gen = self._meta_gen
        serial = adb.serial
        lang = config.get("label_lang", "fr")
        todo = [p for p in self.packages if not p.meta_done and p.label is None and p.icon is None
                and p.path and p.base_size]
        total = len(todo)
        if not total:
            return
        self._meta_total = total
        self.meta_started.emit(total)
        lock = threading.Lock()
        count = [0]

        def one(p):
            if gen != self._meta_gen:
                return
            try:
                if not metacache.fetch_meta(p, serial, lang):
                    self.log.emit(_("[Erreur] : nom/icône illisibles pour %s (%s, %d octets)")
                                  % (p.name, p.path, p.base_size), "err")
            except Exception as e:  # noqa: BLE001
                self.log.emit(_("[Erreur] : nom/icône de %s : %s") % (p.name, e), "err")
            with lock:
                count[0] += 1
                n = count[0]
            if gen == self._meta_gen:
                self.package_meta.emit(p)
                self.meta_progress.emit(n, total)
        for p in todo:
            self.meta_pool.submit(one, p)

    def cancel_meta(self):
        """Arrête la lecture des noms/icônes (les APK restants seront lus au prochain rafraîchissement)."""
        self._meta_gen += 1
        t = getattr(self, "_meta_total", 0)
        self.meta_progress.emit(t, t)

    def shutdown(self):
        """Fermeture : on déconnecte et on arrête le serveur adb (un seul appareil par session)."""
        # D'abord tout arrêter (minuteries, tâches en attente), ensuite seulement le serveur adb
        self._meta_gen += 1
        self.timer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.meta_pool.shutdown(wait=False, cancel_futures=True)
        adbcore.stop_server()
