"""Options → Encryption passphrase: set, change or turn off the shared
passphrase."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from simple_chat.core.crypto import MIN_PASSPHRASE
from simple_chat.gui import style

# What the dialog was closed with.
SET, TURN_OFF = "set", "off"


class PassphraseDialog(QDialog):
    def __init__(self, current_fingerprint: Optional[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Encryption passphrase")
        self.setMinimumWidth(460)
        self.action: Optional[str] = None
        self.passphrase = ""

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Type the <b>same passphrase on each of your machines</b>. Everything Simple-Chat sends is then "
            "encrypted with it, and only machines with the same passphrase can see this one, read its "
            "messages or send it any.<br><br>"
            "Machines with a different passphrase (or none) disappear from the list until you set the same "
            "one on them. The passphrase itself isn't saved, only a key made from it.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        layout.addWidget(intro)

        if current_fingerprint:
            status = (f"<span style='color:{style.ONLINE}'>🔒 Encryption is on.</span> Check code: "
                      f"<b>{current_fingerprint}</b> — every machine with the same passphrase shows the same code.")
        else:
            status = f"<span style='color:{style.MUTED}'>Encryption is off: messages go as plain text.</span>"
        status_label = QLabel(status)
        status_label.setWordWrap(True)
        status_label.setTextFormat(Qt.RichText)
        status_label.setStyleSheet("margin: 8px 0;")
        layout.addWidget(status_label)

        self._first = QLineEdit()
        self._first.setPlaceholderText(f"New passphrase (at least {MIN_PASSPHRASE} characters)")
        self._first.setEchoMode(QLineEdit.Password)
        self._second = QLineEdit()
        self._second.setPlaceholderText("Type it again")
        self._second.setEchoMode(QLineEdit.Password)
        show = QCheckBox("Show passphrase")
        show.toggled.connect(self._show)
        for widget in (self._first, self._second, show):
            layout.addWidget(widget)
        self._problem = QLabel()
        self._problem.setStyleSheet("color: #c0392b;")
        layout.addWidget(self._problem)

        buttons = QDialogButtonBox()
        self._save = buttons.addButton("Set passphrase" if not current_fingerprint else "Change passphrase",
                                       QDialogButtonBox.AcceptRole)
        self._save.setObjectName("primary")
        self._save.clicked.connect(self._accept_set)
        if current_fingerprint:
            off = QPushButton("Turn encryption off")
            off.clicked.connect(self._turn_off)
            buttons.addButton(off, QDialogButtonBox.DestructiveRole)
        buttons.addButton(QDialogButtonBox.Cancel).clicked.connect(self.reject)
        layout.addWidget(buttons)
        for field in (self._first, self._second):
            field.textChanged.connect(self._check)
            field.returnPressed.connect(self._accept_set)
        self._check()

    def _show(self, on: bool) -> None:
        mode = QLineEdit.Normal if on else QLineEdit.Password
        self._first.setEchoMode(mode)
        self._second.setEchoMode(mode)

    def _problem_text(self) -> str:
        first, second = self._first.text(), self._second.text()
        if not first:
            return ""
        if len(first) < MIN_PASSPHRASE:
            return f"At least {MIN_PASSPHRASE} characters, please — longer is safer."
        if second and first != second:
            return "The two don't match."
        return ""

    def _check(self) -> None:
        problem = self._problem_text()
        self._problem.setText(problem)
        self._save.setEnabled(not problem and bool(self._first.text()) and self._first.text() == self._second.text())

    def _accept_set(self) -> None:
        if not self._save.isEnabled():
            return
        self.action, self.passphrase = SET, self._first.text()
        self.accept()

    def _turn_off(self) -> None:
        self.action = TURN_OFF
        self.accept()
