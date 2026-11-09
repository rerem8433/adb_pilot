from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHeaderView

THEMES = {
    "dark": {
        "header": "#1b1b1c", "bg": "#2b2b2d", "panel": "#323235", "row": "#38383b",
        "row_alt": "#343437", "sel": "#5d6676", "text": "#f0f0f0", "muted": "#a9a9ad",
        "border": "#4a4a4e", "btn": "#3a3a3e", "btn_hover": "#47474c", "accent": "#4a74d6",
        "title": "#7fb8ff", "header_text": "#f0f0f0", "input": "#232325", "tab": "#3a3a3e",
        "tab_sel": "#f2f2f2", "tab_sel_text": "#111", "console": "#1e1e20",
    },
    "blue": {
        "header": "#1e3a7b", "bg": "#ffffff", "panel": "#ffffff", "row": "#ffffff",
        "row_alt": "#f7f8fb", "sel": "#cfe0ff", "text": "#151515", "muted": "#666a70",
        "border": "#c6c9cf", "btn": "#ffffff", "btn_hover": "#eef3ff", "accent": "#1e3a7b",
        "title": "#ffffff", "header_text": "#ffffff", "input": "#ffffff", "tab": "#ffffff",
        "tab_sel": "#ffffff", "tab_sel_text": "#111", "console": "#ffffff",
    },
}

_current = THEMES["dark"]


def colors():
    return _current


ACCENT, ACCENT_LINE = "#24448f", "#4a74d6"


def _indicator_files():
    from ..config import CACHE_DIR
    d = CACHE_DIR / "ui"
    d.mkdir(parents=True, exist_ok=True)
    check = d / "check.svg"
    dot = d / "dot.svg"
    check.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" '
                     'fill="none" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    dot.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3.6" fill="#ffffff"/></svg>', encoding="utf-8")
    return check.as_posix(), dot.as_posix()


def qss(name: str) -> str:
    global _current
    c = THEMES.get(name, THEMES["dark"])
    _current = c
    try:
        check, dot = _indicator_files()
    except OSError:
        check = dot = ""
    return f"""
    QCheckBox::indicator, QTableView::indicator, QListWidget::indicator, QGroupBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {'#8a8a90' if name == 'dark' else '#8a8f99'};
        background: {c['input']}; border-radius: 2px; }}
    QCheckBox::indicator:checked, QTableView::indicator:checked, QListWidget::indicator:checked {{
        background: #24448f; border-color: #4a74d6; image: url({check}); }}
    QCheckBox::indicator:hover, QTableView::indicator:hover {{ border-color: #4a74d6; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {'#8a8a90' if name == 'dark' else '#8a8f99'};
        background: {c['input']}; border-radius: 8px; }}
    QRadioButton::indicator:checked {{ background: #24448f; border-color: #4a74d6; image: url({dot}); }}
    QWidget {{ color: {c['text']}; font-size: 10pt; }}
    QMainWindow, #central, QDialog {{ background: {c['bg']}; }}
    #header {{ background: {c['header']}; }}
    #header QLabel {{ color: {c['header_text']}; }}
    #logoA {{ font-size: 22pt; font-weight: 300; color: {c['title']}; }}
    #logoB {{ font-size: 18pt; font-weight: 600; color: {c['header_text']}; }}
    #deviceName {{ font-size: 13pt; font-weight: 600; color: {c['accent']}; }}
    #deviceNameOff {{ font-size: 13pt; font-weight: 600; color: {c['muted']}; }}
    #muted, .muted {{ color: {c['muted']}; }}
    QToolButton#hdr {{ border: none; background: transparent; padding: 3px; border-radius: 4px; }}
    QToolButton#hdr:hover {{ background: rgba(255,255,255,0.12); }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-top: none; background: {c['panel']}; top: -1px; }}
    QTabBar::tab {{ background: {c['tab']}; border: 1px solid {c['border']}; padding: 4px 12px;
                    margin-right: 1px; color: {c['text']}; }}
    QTabBar::tab:selected {{ background: {c['tab_sel']}; color: {c['tab_sel_text']}; border-bottom-color: {c['tab_sel']}; }}
    QTabBar::tab:hover:!selected {{ background: {c['btn_hover']}; }}
    QPushButton {{ background: {c['btn']}; border: 1px solid {c['border']}; padding: 6px 10px;
                   border-radius: 2px; }}
    QPushButton:hover {{ background: {c['btn_hover']}; }}
    QPushButton:pressed {{ background: {c['sel']}; }}
    QPushButton:disabled {{ color: {c['muted']}; }}
    QPushButton:checked {{ background: {c['sel']}; }}
    QPushButton#goBtn {{ background: #24448f; color: #ffffff; font-weight: 800; font-size: 11pt;
                         border: 1px solid #4a74d6; border-radius: 3px; padding: 0px; }}
    QPushButton#goBtn:hover {{ background: #2d55b0; }}
    QPushButton#goBtn:disabled {{ background: #5d6676; color: #ddd; }}
    QPushButton#scanBtn {{ background: rgba(255,255,255,0.10); color: {c['header_text']}; border: 1px solid #4a74d6;
                          border-radius: 3px; padding: 0px 10px; font-weight: 600; }}
    QPushButton#scanBtn:hover {{ background: rgba(74,116,214,0.35); }}
    QPushButton#tcpipBtn {{ font-size: 8pt; padding: 2px 6px; background: rgba(255,255,255,0.08);
                           color: {c['header_text']}; border: 1px solid #666; }}
    QPushButton#tcpipBtn:hover {{ background: rgba(255,255,255,0.18); }}
    QPushButton#tcpipBtn:disabled {{ color: #8a8a8e; border-color: #444; }}
    #devSpecs {{ color: {'#c8c8cc' if name == 'dark' else '#dfe6ff'}; font-size: 10pt; }}
    #storeBody {{ background: {c['panel']}; }}
    #storeSection {{ font-size: 13pt; font-weight: 700; padding: 10px 2px 2px 2px; color: {c['text']}; }}
    QFrame#storeCard {{ background: {c['row'] if name == 'dark' else '#ffffff'}; border: 1px solid {c['border']};
                        border-radius: 14px; }}
    QFrame#storeCard:hover {{ border: 1px solid #4a74d6; }}
    QFrame#storeCard QLabel {{ background: transparent; border: none; }}
    #cardTitle {{ font-size: 12pt; font-weight: 700; }}
    #cardSub {{ font-size: 8pt; color: {c['muted']}; }}
    #cardDesc {{ font-size: 9pt; color: {c['text']}; }}
    #cardState {{ font-size: 9pt; }}
    QPushButton#cardBtn {{ background: #24448f; color: #ffffff; border: none; border-radius: 15px;
                           padding: 6px 16px; font-weight: 700; min-height: 18px; }}
    QPushButton#cardBtn:hover {{ background: #2d55b0; }}
    QPushButton#cardBtn:disabled {{ background: #5d6676; color: #ddd; }}
    QToolButton#cardGhost {{ background: transparent; color: {c['text']}; border: 1px solid {c['border']};
                             border-radius: 14px; padding: 5px 12px; }}
    QToolButton#cardGhost:hover {{ border-color: #4a74d6; }}
    QToolButton#cardGhost::menu-indicator {{ image: none; }}
    QPushButton#chip {{ background: transparent; border: 1px solid {c['border']}; border-radius: 15px;
                        padding: 5px 14px; }}
    QPushButton#chip:checked {{ background: #24448f; color: #ffffff; border-color: #4a74d6; font-weight: 700; }}
    QPushButton#accent {{ background: #24448f; color: #ffffff; border: 1px solid #4a74d6; font-weight: 600; }}
    QPushButton#accent:hover {{ background: #2d55b0; }}
    QPushButton#accent:disabled {{ background: #3b4660; color: #9aa3b8; border-color: #3b4660; }}
    QPushButton#accentSoft {{ background: #9db8f0; color: #0e1d40; border: 1px solid #6f92dc; }}
    QPushButton#accentSoft:hover {{ background: #b5caf5; }}
    QPushButton#debloat {{ background: {'#2c2c2f' if c is THEMES['dark'] else '#9db8f0'}; border: 1px solid {c['border']};
                           padding: 12px; text-align: left; }}
    QPushButton#phoneKey {{ padding: 3px 6px; font-size: 8pt; min-width: 34px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['panel']}; }}
    QListWidget {{ background: {c['input']}; border: 1px solid {c['border']}; }}
    QToolButton#small, QPushButton#small {{ padding: 0px; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['input']}; border: 1px solid {c['border']};
                padding: 4px; selection-background-color: {c['sel']}; }}
    QComboBox QAbstractItemView {{ background: {c['input']}; selection-background-color: {c['sel']}; }}
    #console {{ background: {c['console']}; font-family: "DejaVu Sans Mono", "Ubuntu Mono", "Cascadia Mono", Consolas, Menlo, monospace; font-size: 10pt; border: none; }}
    #consoleInput {{ font-family: "DejaVu Sans Mono", "Ubuntu Mono", "Cascadia Mono", Consolas, Menlo, monospace; border: none; border-bottom: 1px solid {c['border']}; background: transparent; }}
    QTableView {{ background: {c['row']}; alternate-background-color: {c['row_alt']}; gridline-color: transparent;
                  border: none; selection-background-color: {c['sel']}; selection-color: {c['text']}; }}
    QTableView::item {{ border-bottom: 1px solid {c['bg']}; padding-left: 4px; }}
    QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none; padding: 4px; font-size: 8pt; }}
    QHeaderView::section:horizontal {{ border-right: 1px solid {c['border']}; }}
    QHeaderView::section:horizontal:hover {{ color: {c['text']}; }}
    QProgressBar {{ border: 1px solid {c['border']}; background: {c['input']}; height: 10px; text-align: center; font-size: 1px; }}
    QProgressBar::chunk {{ background: #4a74d6; }}
    QGroupBox {{ border: 1px solid {c['border']}; margin-top: 14px; padding: 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {c['muted']}; }}
    QScrollBar:vertical {{ background: {c['bg']}; width: 12px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 30px; }}
    QStatusBar {{ background: {c['header']}; color: {c['header_text']}; }}
    QStatusBar QLabel {{ color: {c['header_text']}; }}
    QToolTip {{ background: #202022; color: #f0f0f0; border: 1px solid #555; padding: 4px; }}
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; }}
    QMenu::item:selected {{ background: {c['sel']}; }}
    QRadioButton, QCheckBox {{ spacing: 5px; }}
    """


SVG = {
    "folder": '<path d="M3 6h6l2 2h10v11H3z" fill="none" stroke="{c}" stroke-width="1.6" stroke-linejoin="round"/>',
    "cloud": '<path d="M7 18h10a4 4 0 0 0 .5-8 6 6 0 0 0-11.4 1.5A3.3 3.3 0 0 0 7 18z" fill="none" stroke="{c}" stroke-width="1.6"/><path d="M12 10v6m-2.5-2.5L12 16l2.5-2.5" fill="none" stroke="{c}" stroke-width="1.6"/>',
    "help": '<circle cx="12" cy="12" r="9" fill="none" stroke="{c}" stroke-width="1.6"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7" fill="none" stroke="{c}" stroke-width="1.6"/><circle cx="12" cy="17" r="1" fill="{c}"/>',
    "refresh": '<path d="M19 12a7 7 0 1 1-2-4.9" fill="none" stroke="{c}" stroke-width="2.2"/><path d="M19 4v4h-4" fill="none" stroke="{c}" stroke-width="2.2"/>',
    "history": '<path d="M5 12a7 7 0 1 0 2-4.9" fill="none" stroke="{c}" stroke-width="2"/><path d="M5 4v4h4" fill="none" stroke="{c}" stroke-width="2"/><path d="M12 8v4l3 2" fill="none" stroke="{c}" stroke-width="2"/>',
    "wifi": '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.3a9.5 9.5 0 0 1 13 0M8.6 15.4a5 5 0 0 1 6.8 0" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="18.5" r="1.5" fill="{c}"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6" fill="none" stroke="{c}" stroke-width="1.8"/><path d="M15 15l5 5" stroke="{c}" stroke-width="1.8"/>',
    "usb": '<path d="M12 3v14M12 3l-2 3h4zM8 9v3l4 2M16 8v3l-4 2" fill="none" stroke="{c}" stroke-width="1.6"/><circle cx="12" cy="19" r="2" fill="{c}"/>',
    "terminal": '<rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="{c}" stroke-width="1.6"/><path d="M7 10l3 2-3 2M12 15h5" fill="none" stroke="{c}" stroke-width="1.6"/>',
    "theme": '<circle cx="12" cy="12" r="8" fill="none" stroke="{c}" stroke-width="1.6"/><path d="M12 4a8 8 0 0 0 0 16z" fill="{c}"/>',
    "app": '<rect x="3" y="3" width="18" height="18" rx="5" fill="{c}"/><path d="M8 15.5a4 4 0 0 1 8 0z" fill="#ffffff"/><circle cx="10.3" cy="13.6" r=".55" fill="{c}"/><circle cx="13.7" cy="13.6" r=".55" fill="{c}"/><path d="M9.2 10.6l.8 1.4M14.8 10.6l-.8 1.4" stroke="#ffffff" stroke-width=".7"/>',
    "debloat": '<rect x="6" y="2" width="12" height="20" rx="2" fill="none" stroke="{c}" stroke-width="1.6"/><path d="M9 9h6M10 12h4M9.5 15h5" stroke="{c}" stroke-width="1.6"/><rect x="2" y="10" width="20" height="5" fill="#24448f"/><text x="12" y="14" font-size="3.6" text-anchor="middle" font-family="sans-serif" font-weight="700" fill="#ffffff">DEBLOAT</text>',
    "logo": '<rect x="1" y="1" width="22" height="22" rx="6" fill="#1e3a7b"/><path d="M6 15.5a6 6 0 0 1 12 0z" fill="#2fd06b"/><circle cx="9.6" cy="13" r=".8" fill="#1e3a7b"/><circle cx="14.4" cy="13" r=".8" fill="#1e3a7b"/><path d="M8 8.5l1.3 2M16 8.5l-1.3 2" stroke="#2fd06b" stroke-width="1"/><path d="M5 18h14" stroke="#7fb8ff" stroke-width="1.4" stroke-linecap="round"/><path d="M7.5 20.3h9" stroke="#7fb8ff" stroke-width="1.1" stroke-linecap="round" opacity=".7"/>',
    "power": '<path d="M12 3v8" stroke="{c}" stroke-width="2.4" stroke-linecap="round"/><path d="M7.2 6.4a7.5 7.5 0 1 0 9.6 0" fill="none" stroke="{c}" stroke-width="2.4" stroke-linecap="round"/>',
    "camera": '<path d="M4 8h3.2l1.6-2.4h6.4L16.8 8H20v11H4z" fill="none" stroke="{c}" stroke-width="1.9" stroke-linejoin="round"/><circle cx="12" cy="13.3" r="3.4" fill="none" stroke="{c}" stroke-width="1.9"/>',
    "mute": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="{c}"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "plus": '<path d="M12 5v14M5 12h14" stroke="{c}" stroke-width="2.6" stroke-linecap="round"/>',
    "minus": '<path d="M5 12h14" stroke="{c}" stroke-width="2.6" stroke-linecap="round"/>',
    "home": '<path d="M4 11.5L12 4.5l8 7V20h-5.5v-5h-5v5H4z" fill="{c}"/>',
    "back": '<path d="M19 12H6M11 6l-6 6 6 6" fill="none" stroke="{c}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    "recents": '<rect x="5" y="5" width="14" height="14" rx="2.5" fill="none" stroke="{c}" stroke-width="2.3"/>',
    "gear": '<path d="M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8z" fill="none" stroke="{c}" stroke-width="2"/><path d="M12 2.8l1.6 2.6 3-.6.6 3 2.6 1.6-1.4 2.6 1.4 2.6-2.6 1.6-.6 3-3-.6L12 21.2l-1.6-2.6-3 .6-.6-3-2.6-1.6 1.4-2.6-1.4-2.6 2.6-1.6.6-3 3 .6z" fill="none" stroke="{c}" stroke-width="1.6" stroke-linejoin="round"/>',
    "menu": '<path d="M5 7h14M5 12h14M5 17h14" stroke="{c}" stroke-width="2.3" stroke-linecap="round"/>',
    "up": '<path d="M6 15l6-6 6 6" fill="none" stroke="{c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
    "down": '<path d="M6 9l6 6 6-6" fill="none" stroke="{c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
    "left": '<path d="M15 6l-6 6 6 6" fill="none" stroke="{c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
    "right": '<path d="M9 6l6 6-6 6" fill="none" stroke="{c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
}


def palette(name: str):
    from PySide6.QtGui import QColor, QPalette
    c = THEMES.get(name, THEMES["dark"])
    pal = QPalette()
    roles = {
        QPalette.Window: c["bg"], QPalette.WindowText: c["text"], QPalette.Base: c["input"],
        QPalette.AlternateBase: c["row_alt"], QPalette.Text: c["text"], QPalette.Button: c["btn"],
        QPalette.ButtonText: c["text"], QPalette.Highlight: c["sel"],
        QPalette.HighlightedText: c["text"], QPalette.ToolTipBase: "#202022",
        QPalette.ToolTipText: "#f0f0f0", QPalette.PlaceholderText: c["muted"],
        QPalette.Link: "#4da3ff" if name == "dark" else "#1e5bd0", QPalette.Mid: c["border"],
        QPalette.Light: c["btn_hover"], QPalette.Midlight: c["btn_hover"], QPalette.Dark: c["border"],
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(c["muted"]))
    return pal


def svg_image(name: str, size=24, color="#ffffff") -> QImage:
    body = SVG[name].replace("{c}", color)
    data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    r = QSvgRenderer(QByteArray(data.encode()))
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    return img


def icon(name: str, color="#ffffff", size=48) -> QIcon:
    return QIcon(QPixmap.fromImage(svg_image(name, size, color)))


def logo_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(svg_image("logo", s)))
    return ic


ICON_SIZE = QSize(18, 18)


class _RowFitter(QObject):
    """Ajuste la hauteur des lignes d'un tableau pour en afficher ~n à l'écran."""

    def __init__(self, view, n, min_h, max_icon):
        super().__init__(view)
        self.view, self.n, self.min_h, self.max_icon = view, n, min_h, max_icon
        self.last = 0
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Resize:
            self.apply()
        return False

    def apply(self):
        h = max(self.min_h, self.view.viewport().height() // self.n)
        if h != self.last:
            self.last = h
            vh = self.view.verticalHeader()
            vh.setSectionResizeMode(QHeaderView.Fixed)
            vh.setDefaultSectionSize(h)
            ic = max(24, min(self.max_icon, h - 14))
            self.view.setIconSize(QSize(ic, ic))


def fit_rows(view, n=10, min_h=40, max_icon=56):
    view._row_fitter = _RowFitter(view, n, min_h, max_icon)


def resizable_columns(header, key, widths, fixed=()):
    """Colonnes redimensionnables à la souris (comme Nemo), largeurs mémorisées dans la config.

    widths : {colonne: largeur par défaut}. La dernière colonne remplit l'espace restant."""
    from ..config import config
    from PySide6.QtCore import QTimer
    header.setStretchLastSection(True)
    header.setMinimumSectionSize(36)
    saved = config.get(key) or {}
    last = header.count() - 1
    for col, w in widths.items():
        header.setSectionResizeMode(col, QHeaderView.Fixed if col in fixed else QHeaderView.Interactive)
        if col != last:
            header.resizeSection(col, int(saved.get(str(col), w)))
    timer = QTimer(header)
    timer.setSingleShot(True)
    timer.setInterval(600)

    def save():
        config[key] = {str(c): header.sectionSize(c) for c in widths if c != last}
        config.save()
    timer.timeout.connect(save)
    header.sectionResized.connect(lambda *_a: timer.start())
    header._save_timer = timer
