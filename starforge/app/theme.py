"""原生界面主题：Qt Widgets 深色 + NMS 风格的橙/青点缀。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------- 设计 token
# 统一间距/字号/圆角，全部使用“逻辑像素”；Qt 会随 DPR 自动缩放。
# 页面与全局组件只引用这些常量，避免各自硬编码 4/8/12/16 与 11.5/13/15px。
SPACE_XXS = 2
SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16
SPACE_XL = 24

RADIUS_S = 6
RADIUS_M = 8
RADIUS_L = 12

FONT_CAPTION = 11.5      # 次要说明、状态标签
FONT_SMALL = 12.5        # 紧凑按钮、列表行
FONT_BODY = 13           # 正文 / 表单
FONT_SECTION = 15        # 区块标题
FONT_TITLE = 18          # 页面标题
FONT_BRAND = 15          # 品牌名
FONT_POINT = 10          # QApplication 默认字体（pt，随 DPI 缩放）

RAIL_WIDTH = 196         # 左侧工作区导航宽度：1180×760 下仍给内容留足宽度
COMMAND_BAR_MARGIN = (SPACE_L, SPACE_S, SPACE_L, SPACE_S)
CONTEXT_BAR_MARGIN = (SPACE_L, SPACE_XS, SPACE_L, SPACE_XS)
PAGE_MARGIN = (SPACE_M, SPACE_M, SPACE_M, SPACE_M)
PAGE_GAP = SPACE_S
SCROLL_MARGIN = (SPACE_M, SPACE_M, SPACE_M, SPACE_L)
DOCK_BUTTON_HEIGHT = 26

# 卡片 / 表单 / 主次操作统一 token：页面与全局组件只引用这里。
CARD_PADDING = SPACE_M
CARD_SPACING = SPACE_S
CARD_RADIUS = RADIUS_L
CONTROL_RADIUS = RADIUS_S
CONTROL_HEIGHT = 30
STATUS_CHIP_RADIUS = 10
NAV_ITEM_HEIGHT = 32
NAV_SUB_HEIGHT = 28
CONTEXT_BAR_HEIGHT = 40


def scale(widget, value: float) -> int:
    """把逻辑尺寸换算成设备像素（用于 QPixmap/QPainter，不用于布局尺寸）。"""
    try:
        ratio = widget.devicePixelRatioF() or 1.0
    except Exception:                                        # noqa: BLE001
        ratio = 1.0
    return max(1, round(float(value) * float(ratio)))


def icon_size(widget, base: int = 16) -> int:
    """图标设备像素尺寸（高分屏下更大），配合 setDevicePixelRatio 使用。"""
    return scale(widget, base)


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
QLabel#navSection {
  color: #5f6a7d; font-size: 10.5px; font-weight: 600;
  padding: 10px 6px 2px 6px;
}
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
QPushButton#primary, QPushButton#primaryButton {
  background: #2f6fd0; border-color: #3f80e0; color: #f2f7ff; font-weight: 600;
}
QPushButton#primary:hover, QPushButton#primaryButton:hover { background: #3a7ce0; }
QPushButton#primary:disabled, QPushButton#primaryButton:disabled {
  background: #1a1f29; border-color: #28303f; color: #5f6a7d;
}
QPushButton#dangerButton {
  background: #2a1514; border: 1px solid #6b2f28; color: #ffc9c0; font-weight: 600;
}
QPushButton#dangerButton:hover { background: #3a1b18; border-color: #a5483c; }
QPushButton#dangerButton:disabled {
  background: #171112; border-color: #2c2223; color: #6b5a58;
}
QTreeWidget, QListWidget, QTableWidget, QTableView {
  background: #0c1119; border: 1px solid #1e2432; border-radius: 8px;
  alternate-background-color: #0f141d; gridline-color: #1e2432;
}
QTreeWidget::item, QListWidget::item { padding: 3px; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #141d2a; color: #e6ecf5; }
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

# 统一排版规则：全局组件通过 objectName 引用，避免在页面里各写一套字号。
QSS += f"""
QLabel#pageTitle {{ font-size: {FONT_TITLE}px; font-weight: 700; color: #e6ecf5; }}
QLabel#cardTitle {{ font-size: {FONT_SECTION - 1}px; font-weight: 700; color: #e6ecf5; }}
QLabel#sectionTitle {{ font-size: {FONT_SECTION}px; font-weight: 700; color: #e6ecf5; }}
QLabel#sectionHint {{ color: #8b95a7; font-size: {FONT_CAPTION}px; }}
QPushButton#dockButton {{
  padding: 3px 10px; font-size: {FONT_SMALL}px; border-radius: {RADIUS_S - 1}px;
}}
QPushButton#dangerButton[dock="true"] {{
  padding: 3px 10px; font-size: {FONT_SMALL}px; border-radius: {RADIUS_S - 1}px;
}}
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}
QToolTip {{ padding: {SPACE_XS}px {SPACE_S}px; }}
QTabBar::tab {{ min-height: 18px; }}
QListWidget::item, QTreeWidget::item {{ padding: 3px 5px; }}

/* ---------- 工作区二级导航（全局壳层） ---------- */
QFrame#workspaceNav {{ background: transparent; }}
QPushButton#workspaceButton {{
  text-align: left; padding: 9px 12px; border: 1px solid transparent;
  border-radius: {RADIUS_M}px; background: transparent; color: #9fb0c4;
  font-size: {FONT_SECTION}px; font-weight: 700;
  min-height: {NAV_ITEM_HEIGHT}px;
}}
QPushButton#workspaceButton:hover {{ background: #111826; color: #e6ecf5; }}
QPushButton#workspaceButton:checked {{
  background: #13202e; border-color: #2d5260; color: #eafcff;
}}
QWidget#subNav {{ background: transparent; }}
QPushButton#subNavButton {{
  text-align: left; padding: 5px 10px 5px 18px; border: 0;
  border-left: 2px solid transparent; border-radius: 0;
  background: transparent; color: #8fa2b8; font-size: {FONT_SMALL}px;
  min-height: {NAV_SUB_HEIGHT}px;
}}
QPushButton#subNavButton:hover {{ color: #e6ecf5; background: #101927; }}
QPushButton#subNavButton:checked {{
  color: #eafcff; background: #10202c; border-left: 2px solid #5ad7ff;
  font-weight: 600;
}}
QPushButton#workspaceButton:focus, QPushButton#subNavButton:focus {{
  border: 2px solid #5ad7ff;
}}
QLabel#workspaceClaim {{
  color: #9fb0c4; font-size: {FONT_SMALL}px;
}}
QFrame#contextBar {{
  background: #0b1119; border-bottom: 1px solid #1e2432;
}}
QLabel#nextStepLabel {{ color: #6f879b; font-size: {FONT_CAPTION}px; }}
QPushButton#nextStepButton {{
  padding: 4px 10px; font-size: {FONT_SMALL}px;
  border-radius: {RADIUS_S}px; color: #cfe0ff; border-color: #2d4a6a;
  background: #101a28;
}}
QPushButton#nextStepButton:hover {{ background: #16263a; border-color: #3f8fa3; }}
QPushButton#emptyAction {{
  border-color: #2d5260; color: #cfe0ff; background: #101a28;
}}
QPushButton#emptyAction:hover {{ background: #16263a; border-color: #3f8fa3; }}

/* ---------- 顶部状态条：四个可点击 chip ---------- */
QPushButton#statusChip {{
  padding: 3px 10px; border-radius: {STATUS_CHIP_RADIUS}px;
  border: 1px solid #28303f; background: #0f141d; color: #8b95a7;
  font-size: {FONT_CAPTION}px; min-height: 20px;
}}
QPushButton#statusChip:hover {{ color: #e6ecf5; border-color: #3f8fa3; }}
QPushButton#statusChip[state="ok"] {{
  border-color: #1d4a38; color: #a8e8c9; background: #0e1c17;
}}
QPushButton#statusChip[state="warn"] {{
  border-color: #4a3a1c; color: #f0cd9a; background: #1c1710;
}}
QPushButton#statusChip[state="bad"] {{
  border-color: #4d2a22; color: #f3b6a7; background: #1d1210;
}}
QPushButton#statusChip:focus {{ border: 2px solid #5ad7ff; }}

/* ---------- 上手向导 ---------- */
QDialog#onboardingDialog {{ background: #0a0c11; }}
QLabel#onboardingTitle {{ font-size: {FONT_TITLE}px; font-weight: 700; color: #e6ecf5; }}
QLabel#onboardingHint {{ color: #8b95a7; font-size: {FONT_SMALL}px; }}
QLabel#onboardingStep {{
  color: #6f879b; font-size: {FONT_SMALL}px; padding: 7px 8px;
  border-left: 2px solid transparent;
}}
QLabel#onboardingStep[state="active"] {{
  color: #eafcff; border-left: 2px solid #5ad7ff; background: #101c28;
  font-weight: 600;
}}
QLabel#onboardingStep[state="done"] {{ color: #a8e8c9; border-left-color: #1d4a38; }}
QLabel#onboardingStatus {{ color: #cfe0ff; font-size: {FONT_BODY}px; }}
QLabel#onboardingStatus[state="bad"] {{ color: #f0cd9a; }}
QLabel#onboardingStatus[state="ok"] {{ color: #a8e8c9; }}

/* 卡片被“下一步”定位时短暂高亮，帮助用户找到落点。 */
QFrame#card[spotlight="true"] {{
  border: 1px solid #5ad7ff;
}}

/* token 落地：卡片/表单/按钮共用同一套圆角，后续页面只引用 token。 */
QFrame#card {{ border-radius: {CARD_RADIUS}px; }}
QGroupBox {{ border-radius: {RADIUS_M}px; }}
QPushButton {{ border-radius: {CONTROL_RADIUS}px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
  border-radius: {CONTROL_RADIUS}px;
}}
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
QPushButton#workspaceButton:hover { background: #0d1a2b; color: #d7f0ff; }
QPushButton#workspaceButton:checked {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #12303a, stop:1 #1c2930);
  border-color: #3f8fa3; color: #dff8ff;
}
QPushButton#subNavButton:hover { background: #0d1a2b; color: #d7f0ff; }
QPushButton#subNavButton:checked {
  background: #10202c; border-left: 2px solid #5ad7ff; color: #dff8ff;
}
QFrame#contextBar {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #080d17, stop:1 #0b1422);
  border-bottom: 1px solid #24384a;
}
QPushButton#statusChip {
  background: #08111d; border-color: #2a3f52; color: #9fb2c7;
}
QPushButton#statusChip:hover { border-color: #3f8fa3; color: #eafcff; }
QLabel#muted { color: #93a4b8; }
QLabel#navSection {
  color: #6f879b; font-size: 10.5px; font-weight: 600;
  padding: 10px 6px 2px 6px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
  background: #08111d; border: 1px solid #2a3f52;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus,
QPlainTextEdit:focus { border-color: #5ad7ff; }
QPushButton { background: #0d1624; border: 1px solid #2a3f52; }
QPushButton:hover { background: #132234; border-color: #3f8fa3; }
QPushButton#primary, QPushButton#primaryButton {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d9902f, stop:1 #b96f1c);
  border-color: #f0b45c; color: #171006; font-weight: 700;
}
QPushButton#primary:hover, QPushButton#primaryButton:hover {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e8a23d, stop:1 #ca7d24);
}
QPushButton#primary:disabled, QPushButton#primaryButton:disabled {
  background: #1a1f29; border-color: #2a3546; color: #5f6a7d;
}
QPushButton#dangerButton {
  background: #2a1514; border: 1px solid #8a3d32; color: #ffd4cc;
}
QPushButton#dangerButton:hover { background: #3a1b18; border-color: #c45444; }
QTreeWidget, QListWidget, QTableWidget, QTableView {
  background: #08111d; border: 1px solid #24384a;
  alternate-background-color: #0c1624; gridline-color: #1b2d3d;
}
QTreeWidget::item:hover, QListWidget::item:hover {
  background: #102535; color: #eafcff;
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
            f.setPointSize(FONT_POINT)
            f.setStyleStrategy(QFont.PreferAntialias)
            return f
    fallback = QFont("Sans Serif", FONT_POINT)
    fallback.setStyleStrategy(QFont.PreferAntialias)
    return fallback


def apply(app: QApplication) -> None:
    """统一使用无人深空氛围；不再提供单独的界面切换项。"""
    app.setStyle("Fusion")
    app.setFont(_font())
    set_atmosphere(True)
