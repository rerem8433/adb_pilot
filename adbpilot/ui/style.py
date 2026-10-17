from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

THEMES = {
    "dark": {
        "header": "#1b1b1c", "bg": "#2b2b2d", "panel": "#323235", "row": "#38383b",
        "row_alt": "#343437", "sel": "#5d6676", "text": "#f0f0f0", "muted": "#a9a9ad",
        "border": "#4a4a4e", "btn": "#3a3a3e", "btn_hover": "#47474c", "accent": "#2fd06b",
        "title": "#7fb8ff", "header_text": "#f0f0f0", "input": "#232325", "tab": "#3a3a3e",
        "tab_sel": "#f2f2f2", "tab_sel_text": "#111", "console": "#1e1e20",
    },
    "blue": {
        "header": "#1e3a7b", "bg": "#ffffff", "panel": "#ffffff", "row": "#ffffff",
        "row_alt": "#f7f8fb", "sel": "#cfe0ff", "text": "#151515", "muted": "#666a70",
        "border": "#c6c9cf", "btn": "#ffffff", "btn_hover": "#eef3ff", "accent": "#18c25a",
        "title": "#ffffff", "header_text": "#ffffff", "input": "#ffffff", "tab": "#ffffff",
        "tab_sel": "#ffffff", "tab_sel_text": "#111", "console": "#ffffff",
    },
}

_current = THEMES["dark"]


def colors():
    return _current


def _indicator_files():
    from ..config import CACHE_DIR
    d = CACHE_DIR / "ui"
    d.mkdir(parents=True, exist_ok=True)
    check = d / "check.svg"
    dot = d / "dot.svg"
    check.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" '
                     'fill="none" stroke="#0b2414" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    dot.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3.6" fill="#0b2414"/></svg>')
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
        background: #2fd06b; border-color: #2fd06b; image: url({check}); }}
    QCheckBox::indicator:hover, QTableView::indicator:hover {{ border-color: #2fd06b; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {'#8a8a90' if name == 'dark' else '#8a8f99'};
        background: {c['input']}; border-radius: 8px; }}
    QRadioButton::indicator:checked {{ background: #2fd06b; border-color: #2fd06b; image: url({dot}); }}
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
    QPushButton#goBtn {{ background: #2fd06b; color: #0b2414; font-weight: 800; font-size: 11pt;
                         border: 1px solid #22a856; border-radius: 3px; padding: 0px; }}
    QPushButton#goBtn:hover {{ background: #45dd7e; }}
    QPushButton#goBtn:disabled {{ background: #5d6676; color: #ddd; }}
    QPushButton#tcpipBtn {{ font-size: 8pt; padding: 2px 6px; background: rgba(255,255,255,0.08);
                           color: {c['header_text']}; border: 1px solid #666; }}
    QPushButton#tcpipBtn:hover {{ background: rgba(255,255,255,0.18); }}
    #devSpecs {{ color: {'#c8c8cc' if name == 'dark' else '#dfe6ff'}; font-size: 10pt; }}
    QPushButton#accent {{ background: #2fd06b; color: #0b2414; border: 1px solid #22a856; font-weight: 600; }}
    QPushButton#accent:hover {{ background: #45dd7e; }}
    QPushButton#accentSoft {{ background: #7ff0b0; color: #0b2414; border: 1px solid #44c27a; }}
    QPushButton#debloat {{ background: {'#2c2c2f' if c is THEMES['dark'] else '#7ff0b0'}; border: 1px solid {c['border']};
                           padding: 12px; text-align: left; }}
    QPushButton#phoneKey {{ padding: 3px 6px; font-size: 8pt; min-width: 34px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['panel']}; }}
    QListWidget {{ background: {c['input']}; border: 1px solid {c['border']}; }}
    QToolButton#small, QPushButton#small {{ padding: 0px; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{ background: {c['input']}; border: 1px solid {c['border']};
                padding: 4px; selection-background-color: {c['sel']}; }}
    QComboBox QAbstractItemView {{ background: {c['input']}; selection-background-color: {c['sel']}; }}
    #console {{ background: {c['console']}; font-family: "DejaVu Sans Mono", "Ubuntu Mono", monospace; font-size: 10pt; border: none; }}
    #consoleInput {{ font-family: "DejaVu Sans Mono", "Ubuntu Mono", monospace; border: none; border-bottom: 1px solid {c['border']}; background: transparent; }}
    QTableView {{ background: {c['row']}; alternate-background-color: {c['row_alt']}; gridline-color: transparent;
                  border: none; selection-background-color: {c['sel']}; selection-color: {c['text']}; }}
    QTableView::item {{ border-bottom: 1px solid {c['bg']}; padding-left: 4px; }}
    QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none; padding: 4px; font-size: 8pt; }}
    QProgressBar {{ border: 1px solid {c['border']}; background: {c['input']}; height: 10px; text-align: center; font-size: 1px; }}
    QProgressBar::chunk {{ background: #2fd06b; }}
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
    "debloat": '<rect x="6" y="2" width="12" height="20" rx="2" fill="none" stroke="{c}" stroke-width="1.6"/><path d="M9 9h6M10 12h4M9.5 15h5" stroke="{c}" stroke-width="1.6"/><rect x="2" y="10" width="20" height="5" fill="#2fd06b"/><text x="12" y="14" font-size="3.6" text-anchor="middle" font-family="sans-serif" font-weight="700" fill="#0b2414">DEBLOAT</text>',
    "logo": '<rect x="1" y="1" width="22" height="22" rx="6" fill="#1e3a7b"/><path d="M6 15.5a6 6 0 0 1 12 0z" fill="#2fd06b"/><circle cx="9.6" cy="13" r=".8" fill="#1e3a7b"/><circle cx="14.4" cy="13" r=".8" fill="#1e3a7b"/><path d="M8 8.5l1.3 2M16 8.5l-1.3 2" stroke="#2fd06b" stroke-width="1"/><path d="M5 18h14" stroke="#7fb8ff" stroke-width="1.4" stroke-linecap="round"/><path d="M7.5 20.3h9" stroke="#7fb8ff" stroke-width="1.1" stroke-linecap="round" opacity=".7"/>',
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
