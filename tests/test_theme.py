import os
import pytest

@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_theme_applies_nms_style(qapp):
    from PySide6.QtGui import QPalette
    from starforge.app import theme

    theme.apply(qapp)
    assert qapp.styleSheet() == theme.ATMOSPHERE_QSS
    assert "qlineargradient" in qapp.styleSheet()
    assert qapp.palette().color(QPalette.Window).name() == "#060a14"
