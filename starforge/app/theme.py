"""原生界面主题：Qt Widgets 深色 + NMS 风格的橙/青点缀。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


def _palette(atmosphere: bool = False) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#060a14" if atmosphere else "#0a0c11"))
    p.setColor(QPalette.WindowText, QColor("#e2e7f0"))
    p.setColor(QPalette.Base, QColor("#08111d" if atmosphere else "#0e1118"))
    p.setColor(QPalette.AlternateBase, QColor("#0c1624" if atmosphere else "#12161f"))
    p.setColor(QPalette.ToolTipBase, QColor("#101a28" if atmosphere else "#161b26"))
    p.setColor(QPalette.ToolTipText, QColor("#e2e7f0"))
    p.setColor(QPalette.Text, QColor("#e2e7f0"))
    p.setColor(QPalette.Button, QColor("#0d1624" if atmosphere else "#161b26"))
    p.setColor(QPalette.ButtonText, QColor("#e2e7f0"))
    p.setColor(QPalette.BrightText, QColor("#ff5c5c"))
    p.setColor(QPalette.Link, QColor("#f0b45c" if atmosphere else "#6aa9ff"))
    p.setColor(QPalette.Highlight, QColor("#1f6f86" if atmosphere else "#2f6fd0"))
    p.setColor(QPalette.HighlightedText, QColor("#f2f7ff"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#5f6a7d"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#5f6a7d"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5f6a7d"))
    p.setColor(QPalette.Disabled, QPalette.Base, QColor("#0b0e14"))
    p.setColor(QPalette.Disabled, QPalette.Button, QColor("#10141c"))
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#25303f"))
    p.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor("#8b95a7"))
    return p


QSS = """
QWidget { color: #e2e7f0; }
QMainWindow, QDialog { background: #0a0c11; }
QFrame#navRail { background: #0d1119; border-right: 1px solid #1e2432; }
QFrame#commandBar { background: #0b0f16; border-bottom: 1px solid #1e2432; }
QFrame#jobDock { background: #0b0f16; border-top: 1px solid #1e2432; }
QFrame#card { background: #0f141d; border: 1px solid #1e2432; border-radius: 12px; }
QLabel#breadcrumb { font-size: 15px; font-weight: 700; color: #e6ecf5; }
QPushButton#ghostButton { background: transparent; border: 1px solid #28303f; color: #8b97aa; }
QPushButton#ghostButton:hover { color: #e6ecf5; border-color: #3a4a66; }
QPushButton#navButton {
  text-align: left; padding: 10px 14px; border: 1px solid transparent;
  border-radius: 8px; background: transparent; color: #8b95a7; font-size: 13px;
}
QPushButton#navButton:hover { background: #111826; color: #c6d4ea; }
QPushButton#navButton:checked { background: #14203a; border-color: #22406e; color: #cfe0ff; }
QLabel#brand { color: #f2b45c; font-size: 15px; font-weight: 700; letter-spacing: 1px; }
QLabel#muted { color: #8b95a7; font-size: 11.5px; }
QLabel#chip {
  padding: 3px 10px; border-radius: 9px; border: 1px solid #28303f;
  background: #0f141d; color: #8b95a7; font-size: 11.5px;
}
QLabel#chip[state="ok"] { border-color: #1d4a38; color: #a8e8c9; background: #0e1c17; }
QLabel#chip[state="warn"] { border-color: #4a3a1c; color: #f0cd9a; background: #1c1710; }
QLabel#chip[state="bad"] { border-color: #4d2a22; color: #f3b6a7; background: #1d1210; }
QGroupBox {
  border: 1px solid #1e2432; border-radius: 10px; margin-top: 12px;
  padding: 12px 10px 10px 10px; background: #0e1118;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #8b95a7; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
  background: #0c1119; border: 1px solid #28303f; border-radius: 6px;
  padding: 6px 8px; selection-background-color: #2f6fd0;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus { border-color: #2f6fd0; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QTextEdit:disabled, QPlainTextEdit:disabled {
  color: #5f6a7d; background: #0b0e14; border-color: #1e2432;
}
QPushButton {
  background: #161b26; border: 1px solid #28303f; border-radius: 6px;
  padding: 7px 12px; color: #e2e7f0;
}
QPushButton:hover { background: #1a2231; border-color: #3a4a66; }
QPushButton:disabled {
  color: #5f6a7d; background: #10141c; border-color: #1e2432;
}
QPushButton#primary {
  background: #2f6fd0; border-color: #3f80e0; color: #f2f7ff; font-weight: 600;
}
QPushButton#primary:hover { background: #3a7ce0; }
QTreeWidget, QListWidget, QTableWidget, QTableView {
  background: #0c1119; border: 1px solid #1e2432; border-radius: 8px;
  alternate-background-color: #0f141d; gridline-color: #1e2432;
}
QTreeWidget::item, QListWidget::item { padding: 3px; }
QTreeWidget::item:selected, QListWidget::item:selected, QTableView::item:selected {
  background: #1b2b47; color: #dbe9ff;
}
QTreeWidget::item:selected:active, QListWidget::item:selected:active,
QTableView::item:selected:active, QTableWidget::item:selected:active {
  background: #23406b; color: #f2f7ff;
}
QComboBox QAbstractItemView::item:selected {
  background: #1b2b47; color: #dbe9ff;
}
QTreeWidget:disabled, QListWidget:disabled, QTableWidget:disabled, QTableView:disabled {
  color: #5f6a7d; background: #0b0e14; border-color: #1e2432;
}
QHeaderView::section {
  background: #12161f; border: 0; border-bottom: 1px solid #1e2432;
  padding: 6px; color: #8b95a7;
}
QTabWidget::pane { border: 1px solid #1e2432; border-radius: 8px; }
QTabBar::tab { background: #12161f; padding: 7px 14px; border: 1px solid #1e2432; }
QTabBar::tab:selected { background: #14203a; color: #cfe0ff; }
QSplitter::handle { background: #1e2432; }
QStatusBar { background: #0d1119; border-top: 1px solid #1e2432; color: #8b95a7; }
QProgressBar { border: 1px solid #28303f; border-radius: 5px; background: #0c1119; text-align: center; }
QProgressBar::chunk { background: #2f6fd0; border-radius: 4px; }
QToolTip { background: #161b26; color: #e2e7f0; border: 1px solid #28303f; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2a3546; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #3a4a66; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2a3546; min-width: 28px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: #3a4a66; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QPushButton:focus, QCheckBox:focus {
  border: 2px solid #5ad7ff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus {
  border: 2px solid #5ad7ff;
}
QTreeWidget:focus, QListWidget:focus, QTableWidget:focus, QTableView:focus {
  border: 2px solid #5ad7ff;
}
QPushButton#navButton:focus, QPushButton#ghostButton:focus {
  background: #111826; border: 2px solid #5ad7ff; color: #e6ecf5;
}
QTabBar::tab:focus { border-color: #5ad7ff; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid #3a4a66; background: #0c1119; }
QCheckBox::indicator:checked { background: #2f6fd0; border-color: #5ad7ff; }
QCheckBox::indicator:disabled { background: #10141c; border-color: #2a3546; }
QTabBar::tab:hover { color: #e6ecf5; }
QSplitter::handle:hover { background: #2a3546; }
"""


def _mix(color_a: str, color_b: str, t: float) -> str:
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _scanline_gradient(top: str = "#04070f", bottom: str = "#0b1424",
                       lines: int = 110, tint: str = "#5ad7ff",
                       strength: float = 0.045) -> str:
    """生成不含图片的深空渐变 + 低透明水平扫描线。"""
    stops: list[str] = []
    for i in range(lines):
        t = i / lines
        base = _mix(top, bottom, t)
        line = _mix(base, tint, strength)
        stops.append(f"stop:{t:.5f} {line}")
        stops.append(f"stop:{min(t + 0.30 / lines, 1.0):.5f} {base}")
    return "qlineargradient(x1:0, y1:0, x2:0, y2:1, " + ", ".join(stops) + ")"


_SCANLINES = _scanline_gradient()

ATMOSPHERE_QSS = QSS + """
QMainWindow, QDialog { background: """ + _SCANLINES + """; }
QFrame#navRail {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #080d17, stop:1 #0a1322);
  border-right: 1px solid #3a2a17;
}
QFrame#commandBar {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #070c16, stop:0.55 #0a1220, stop:1 #0d1624);
  border-bottom: 1px solid #3a2a17;
}
QFrame#jobDock { background: #070c16; border-top: 1px solid #24384a; }
QFrame#card {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0a1220, stop:1 #0c1422);
  border: 1px solid #24384a;
}
QGroupBox { background: #0a121e; border: 1px solid #24384a; }
QPushButton#navButton:hover { background: #0d1a2b; color: #d7f0ff; }
QPushButton#navButton:checked {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #12303a, stop:1 #1c2930);
  border-color: #3f8fa3; color: #dff8ff;
}
QLabel#muted { color: #93a4b8; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
  background: #08111d; border: 1px solid #2a3f52;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus,
QPlainTextEdit:focus { border-color: #5ad7ff; }
QPushButton { background: #0d1624; border: 1px solid #2a3f52; }
QPushButton:hover { background: #132234; border-color: #3f8fa3; }
QPushButton#primary {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d9902f, stop:1 #b96f1c);
  border-color: #f0b45c; color: #171006;
}
QPushButton#primary:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e8a23d, stop:1 #ca7d24);
}
QTreeWidget, QListWidget, QTableWidget, QTableView {
  background: #08111d; border: 1px solid #24384a;
  alternate-background-color: #0c1624; gridline-color: #1b2d3d;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableView::item:selected {
  background: #173a46; color: #dff8ff;
}
QTreeWidget::item:selected:active, QListWidget::item:selected:active,
QTableView::item:selected:active, QTableWidget::item:selected:active {
  background: #1d4d5c; color: #f2fbff;
}
QComboBox QAbstractItemView::item:selected { background: #173a46; color: #dff8ff; }
QHeaderView::section {
  background: #0d1725; border-bottom: 1px solid #2a3f52; color: #9fb2c7;
}
QTabWidget::pane { border: 1px solid #24384a; }
QTabBar::tab { background: #0d1725; border: 1px solid #24384a; }
QTabBar::tab:selected {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #12303a, stop:1 #1c2930);
  color: #dff8ff;
}
QSplitter::handle { background: #24384a; }
QStatusBar { background: #080d17; border-top: 1px solid #3a2a17; color: #93a4b8; }
QProgressBar { border: 1px solid #2a3f52; background: #08111d; }
QProgressBar::chunk {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d9902f, stop:0.55 #5ad7ff, stop:1 #d9902f);
}
QToolTip { background: #101a28; border: 1px solid #3f8fa3; }
QCheckBox::indicator { border-color: #3a5468; background: #08111d; }
QCheckBox::indicator:checked { background: #d9902f; border-color: #f0b45c; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #2c4155; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #3f6076; }
"""


def set_atmosphere(on: bool) -> None:
    """切换无人深空氛围层；关闭时原样回到中性深色主题。"""
    app = QApplication.instance()
    if app is None:
        return
    app.setPalette(_palette(bool(on)))
    app.setStyleSheet(ATMOSPHERE_QSS if on else QSS)


def _font() -> QFont:
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Noto Sans CJK SC"):
        f = QFont(name, 10)
        if f.exactMatch() or QFont(name).family() == name:
            return f
    return QFont("Sans Serif", 10)


def apply(app: QApplication) -> None:
    from ..core import settings as settings_mod

    app.setStyle("Fusion")
    app.setFont(_font())
    try:
        on = bool(settings_mod.current().atmosphere)
    except Exception:                                        # noqa: BLE001
        on = bool(settings_mod.DEFAULTS.get("atmosphere", False))
    set_atmosphere(on)
