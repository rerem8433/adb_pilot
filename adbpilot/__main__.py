import os
import sys


def main():
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from . import APP_ID, APP_NAME
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
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
