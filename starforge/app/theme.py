"""原生界面主题：Qt Widgets 深色 + NMS 风格的橙/青点缀。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


def _palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#0a0c11"))
    p.setColor(QPalette.WindowText, QColor("#e2e7f0"))
    p.setColor(QPalette.Base, QColor("#0e1118"))
    p.setColor(QPalette.AlternateBase, QColor("#12161f"))
    p.setColor(QPalette.ToolTipBase, QColor("#161b26"))
    p.setColor(QPalette.ToolTipText, QColor("#e2e7f0"))
    p.setColor(QPalette.Text, QColor("#e2e7f0"))
    p.setColor(QPalette.Button, QColor("#161b26"))
    p.setColor(QPalette.ButtonText, QColor("#e2e7f0"))
    p.setColor(QPalette.BrightText, QColor("#ff5c5c"))
    p.setColor(QPalette.Link, QColor("#6aa9ff"))
    p.setColor(QPalette.Highlight, QColor("#2f6fd0"))
    p.setColor(QPalette.HighlightedText, QColor("#f2f7ff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#5f6a7d"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5f6a7d"))
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
QPushButton {
  background: #161b26; border: 1px solid #28303f; border-radius: 6px;
  padding: 7px 12px; color: #e2e7f0;
}
QPushButton:hover { background: #1a2231; border-color: #3a4a66; }
QPushButton:disabled { color: #5f6a7d; background: #10141c; }
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
"""


def _font() -> QFont:
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Noto Sans CJK SC"):
        f = QFont(name, 10)
        if f.exactMatch() or QFont(name).family() == name:
            return f
    return QFont("Sans Serif", 10)


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setFont(_font())
    app.setStyleSheet(QSS)
