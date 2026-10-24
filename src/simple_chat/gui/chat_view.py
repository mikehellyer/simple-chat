"""The right-hand side: one machine's chat, and the box to type in."""
from __future__ import annotations

import html
import re
import time
from dataclasses import replace
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from simple_chat.core.store import DELIVERED, PENDING, StoredMessage
from simple_chat.gui import style

_URL = re.compile(r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+)")


class Composer(QPlainTextEdit):
    """Enter sends; Shift+Enter starts a new line."""

    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class ChatView(QWidget):
    send_requested = Signal(str, str)  # peer id, text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peer_id: Optional[str] = None
        self._messages: list[StoredMessage] = []
        self._by_id: dict[str, StoredMessage] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QLabel()
        self._header.setObjectName("chatHeader")
        self._header.setTextFormat(Qt.RichText)
        layout.addWidget(self._header)

        self._browser = QTextBrowser()
        self._browser.setObjectName("chat")
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._anchor)
        layout.addWidget(self._browser, stretch=1)

        bottom = QWidget()
        bottom.setObjectName("composerBar")
        row = QHBoxLayout(bottom)
        row.setContentsMargins(10, 8, 10, 10)
        self._composer = Composer()
        self._composer.setPlaceholderText("Type a message — Enter sends, Shift+Enter for a new line")
        self._composer.setFixedHeight(70)
        self._composer.submitted.connect(self._send)
        self._composer.textChanged.connect(self._update_button)
        row.addWidget(self._composer, stretch=1)
        self._send_button = QPushButton("Send")
        self._send_button.setObjectName("primary")
        self._send_button.setFixedHeight(70)
        self._send_button.clicked.connect(self._send)
        row.addWidget(self._send_button)
        layout.addWidget(bottom)

        self.show_peer(None, "", False, [])

    @property
    def peer_id(self) -> Optional[str]:
        return self._peer_id

    def show_peer(self, peer_id: Optional[str], name: str, online: bool, messages: list[StoredMessage],
                  detail: str = "") -> None:
        changed = peer_id != self._peer_id
        self._peer_id = peer_id
        self._messages = list(messages)
        self._by_id = {m.id: m for m in messages}
        self.set_online(name, online, detail)
        self._composer.setEnabled(peer_id is not None)
        self._update_button()
        self._render(scroll_to_end=True)
        if changed and peer_id is not None:
            self._composer.setFocus()

    def set_online(self, name: str, online: bool, detail: str = "") -> None:
        if self._peer_id is None:
            self._header.setText(f"<span style='color:{style.MUTED}'>No machine chosen</span>")
            return
        if online:
            state = f"<span style='color:{style.ONLINE}'>● online</span>"
        else:
            state = (f"<span style='color:{style.MUTED}'>○ offline — messages wait and are delivered "
                     "when it's back</span>")
        extra = f" <span style='color:{style.MUTED}'>&nbsp;{html.escape(detail)}</span>" if detail else ""
        self._header.setText(f"<b style='font-size:13pt'>{html.escape(name)}</b>&nbsp;&nbsp;{state}{extra}")

    def add_message(self, message: StoredMessage) -> None:
        if message.peer_id != self._peer_id or message.id in self._by_id:
            return
        self._messages.append(message)
        self._by_id[message.id] = message
        self._render(scroll_to_end=True)

    def mark_delivered(self, message_id: str) -> None:
        old = self._by_id.get(message_id)
        if old is None:
            return
        new = replace(old, status=DELIVERED)
        self._by_id[message_id] = new
        self._messages = [new if m.id == message_id else m for m in self._messages]
        self._render(scroll_to_end=False)

    def focus_composer(self) -> None:
        self._composer.setFocus()

    # --- internals

    def _send(self) -> None:
        text = self._composer.toPlainText().strip("\n")
        if self._peer_id is None or not text.strip():
            return
        self._composer.clear()
        self.send_requested.emit(self._peer_id, text)

    def _update_button(self) -> None:
        self._send_button.setEnabled(self._peer_id is not None and bool(self._composer.toPlainText().strip()))

    def _anchor(self, url: QUrl) -> None:
        if url.scheme() == "copy":
            message = self._by_id.get(url.path())
            if message is not None:
                QGuiApplication.clipboard().setText(message.text)
                self.window().statusBar().showMessage("Copied to the clipboard", 2000)
        else:
            QDesktopServices.openUrl(url)

    def _render(self, scroll_to_end: bool) -> None:
        bar = self._browser.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        old_value = bar.value()
        if self._peer_id is None:
            self._browser.setHtml(f"<p align='center' style='color:{style.MUTED}'><br><br>"
                                  "Pick a machine on the left to chat with it.<br><br>"
                                  "Machines running Simple-Chat on this network show up there by themselves.</p>")
            return
        if not self._messages:
            self._browser.setHtml(f"<p align='center' style='color:{style.MUTED}'><br><br>"
                                  "No messages yet. Say hello!</p>")
            return
        parts, last_day = [], None
        for m in self._messages:
            day = datetime.fromtimestamp(m.sent_at).date()
            if day != last_day:
                parts.append(f"<p align='center' style='color:{style.MUTED}; font-size:9pt; margin:10px'>"
                             f"{_day_label(day)}</p>")
                last_day = day
            parts.append(_bubble(m))
        self._browser.setHtml("".join(parts))
        if scroll_to_end or at_end:
            self._browser.moveCursor(QTextCursor.End)
            bar.setValue(bar.maximum())
        else:
            bar.setValue(old_value)


def _bubble(m: StoredMessage) -> str:
    when = datetime.fromtimestamp(m.sent_at).strftime("%H:%M")
    if m.outgoing:
        tick = "⏳ waiting" if m.status == PENDING else "✓ delivered"
        meta = f"{when} · {tick}"
        colour, align, text_colour = style.MINE, "right", style.MINE_TEXT
    else:
        meta = when
        colour, align, text_colour = style.THEIRS, "left", style.INK
    link_colour = "#ffffff" if m.outgoing else style.ACCENT
    body = _linkify(m.text, link_colour)
    copy = f"<a href='copy:{m.id}' style='color:{style.MUTED}; text-decoration:none'>copy</a>"
    return (
        f"<table width='100%' cellspacing='0' cellpadding='0' style='margin:3px 8px'><tr><td align='{align}'>"
        f"<table cellspacing='0' cellpadding='9' style='background:{colour}'><tr><td style='color:{text_colour}'>"
        f"{body}</td></tr></table>"
        f"<p align='{align}' style='margin:0; color:{style.MUTED}; font-size:8.5pt'>{meta} &nbsp; {copy}</p>"
        f"</td></tr></table>"
    )


def _linkify(text: str, colour: str) -> str:
    out, pos = [], 0
    for match in _URL.finditer(text):
        out.append(html.escape(text[pos:match.start()]))
        url = match.group(0).rstrip(".,;:!?)")
        href = url if url.startswith("http") else "http://" + url
        out.append(f"<a href='{html.escape(href, quote=True)}' style='color:{colour}'>{html.escape(url)}</a>")
        pos = match.start() + len(url)
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>").replace("  ", "&nbsp; ")


def _day_label(day) -> str:
    today = datetime.fromtimestamp(time.time()).date()
    delta = (today - day).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return f"{day:%A} {day.day} {day:%B %Y}"  # no %-d: Windows lacks it
