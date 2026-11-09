import os
import sys


def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    if sys.platform == "win32":
        try:  # icône et regroupement propres dans la barre des tâches
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ParadoxXxSquad.ADBPilot")
        except Exception:  # noqa: BLE001
            pass
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        import threading
        from .osutil import macos_unquarantine
        threading.Thread(target=macos_unquarantine, daemon=True).start()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from . import APP_ID, APP_NAME
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
    # Icône de l'application (barre des tâches Windows, Alt+Tab, toutes les fenêtres)
    from PySide6.QtGui import QIcon
    from .ui import style as _style
    ico = os.path.join(os.path.dirname(sys.executable), "adbpilot.ico") if getattr(sys, "frozen", False) else ""
    app.setWindowIcon(QIcon(ico) if ico and os.path.isfile(ico) else _style.logo_icon())
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)
    if tr.load(QLocale("fr_FR"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(tr)
    from .ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    files = [a for a in sys.argv[1:] if a.lower().endswith((".apk", ".apks", ".xapk", ".apkm"))]
    if files:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(4000, lambda: w.install_files(files))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
