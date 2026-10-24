"""The look: calm greys with a blue accent; your own messages in blue
bubbles on the right, theirs in grey on the left."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

INK = "#1d1d1f"
MUTED = "#7a7a80"
LINE = "#d9d9de"
PAPER = "#ffffff"
SHADE = "#f2f3f6"
ACCENT = "#2f6fed"
ONLINE = "#2fb35a"
MINE = ACCENT
MINE_TEXT = "#ffffff"
THEIRS = "#e9eaef"

STYLE = f"""
QWidget {{ color: {INK}; font-size: 10.5pt; }}
QMainWindow, QSplitter {{ background: {SHADE}; }}
QListWidget#peers {{ background: {PAPER}; border: none; border-right: 1px solid {LINE}; outline: none; }}
QLabel#me {{ background: {PAPER}; border-right: 1px solid {LINE}; border-bottom: 1px solid {LINE}; padding: 12px; }}
QLabel#chatHeader {{ background: {PAPER}; border-bottom: 1px solid {LINE}; padding: 12px 14px; }}
QTextBrowser#chat {{ background: {PAPER}; border: none; }}
QWidget#composerBar {{ background: {PAPER}; border-top: 1px solid {LINE}; }}
QPlainTextEdit, QLineEdit {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 8px; }}
QPlainTextEdit:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QPushButton {{ background: {PAPER}; border: 1px solid {LINE}; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; border-radius: 8px;
    padding: 6px 20px; font-weight: 600; }}
QPushButton#primary:disabled {{ background: #a9c1f5; }}
QPushButton#scan {{ border: none; border-top: 1px solid {LINE}; border-right: 1px solid {LINE};
    border-radius: 0; padding: 10px; color: {ACCENT}; font-weight: 600; }}
QPushButton#scan:hover {{ background: {SHADE}; }}
QStatusBar {{ background: {PAPER}; color: {MUTED}; border-top: 1px solid {LINE}; }}
QMenuBar {{ background: {PAPER}; border-bottom: 1px solid {LINE}; }}
QMenuBar::item {{ background: transparent; color: {INK}; padding: 4px 10px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {ACCENT}; color: white; border-radius: 4px; }}
QMenu {{ background: {PAPER}; color: {INK}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 5px 28px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
QToolTip {{ background: {PAPER}; color: {INK}; border: 1px solid {LINE}; padding: 4px; }}
QCheckBox {{ background: transparent; }}
"""


def apply(app: QApplication) -> None:
    """A light look whatever the desktop's theme, so the bubbles always
    read the same."""
    app.setStyle(QStyleFactory.create("Fusion"))
    palette = QPalette()
    for role, colour in ((QPalette.Window, SHADE), (QPalette.Base, PAPER), (QPalette.AlternateBase, SHADE),
                         (QPalette.Text, INK), (QPalette.WindowText, INK), (QPalette.Button, PAPER),
                         (QPalette.ButtonText, INK), (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#ffffff"),
                         (QPalette.ToolTipBase, PAPER), (QPalette.ToolTipText, INK), (QPalette.PlaceholderText, MUTED),
                         (QPalette.Link, ACCENT)):
        palette.setColor(role, QColor(colour))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
