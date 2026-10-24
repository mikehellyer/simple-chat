"""The left-hand side: every machine this one knows, online ones first."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from simple_chat.gui import style

_ROLE = Qt.UserRole + 1


@dataclass(frozen=True)
class PeerRow:
    id: str
    name: str
    online: bool
    unread: int
    host: str
    last_seen: float


class PeerList(QListWidget):
    peer_chosen = Signal(str)
    forget_requested = Signal(str)
    clear_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("peers")
        self.setItemDelegate(_PeerDelegate(self))
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.currentItemChanged.connect(self._changed)
        self._updating = False

    def set_rows(self, rows: list[PeerRow], current: Optional[str]) -> None:
        rows = sorted(rows, key=lambda r: (not r.online, r.name.lower()))
        self._updating = True
        self.clear()
        for row in rows:
            item = QListWidgetItem(row.name)
            item.setData(_ROLE, row)
            item.setToolTip(f"{row.name}\n{row.host or 'address not known yet'}")
            self.addItem(item)
            if row.id == current:
                self.setCurrentItem(item)
        self._updating = False

    def current_peer(self) -> Optional[str]:
        item = self.currentItem()
        return item.data(_ROLE).id if item else None

    def _changed(self, current, _previous) -> None:
        if not self._updating and current is not None:
            self.peer_chosen.emit(current.data(_ROLE).id)

    def _menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        row: PeerRow = item.data(_ROLE)
        menu = QMenu(self)
        menu.addAction("Clear this chat", lambda: self.clear_requested.emit(row.id))
        menu.addAction(f"Forget {row.name}", lambda: self.forget_requested.emit(row.id))
        menu.exec(self.viewport().mapToGlobal(pos))


class _PeerDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(200, 52)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row: PeerRow = index.data(_ROLE)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        selected = option.state & QStyle.State_Selected
        if selected:
            painter.fillRect(r, QColor(style.ACCENT))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(r, QColor(style.SHADE))
        ink = QColor("#ffffff") if selected else QColor(style.INK)
        muted = QColor("#dbe6ff") if selected else QColor(style.MUTED)

        # the online dot
        dot = QColor(style.ONLINE) if row.online else QColor(style.LINE)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(r.left() + 14, r.center().y() - 5, 10, 10)

        name_font = QFont(option.font)
        name_font.setBold(bool(row.unread))
        painter.setFont(name_font)
        painter.setPen(ink)
        badge_w = 0
        if row.unread:
            badge_w = 30
        text_rect = QRect(r.left() + 34, r.top() + 7, r.width() - 44 - badge_w, 20)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(row.name, Qt.ElideRight, text_rect.width()))
        small = QFont(option.font)
        small.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
        painter.setFont(small)
        painter.setPen(muted)
        painter.drawText(QRect(r.left() + 34, r.top() + 27, r.width() - 44, 18), Qt.AlignLeft | Qt.AlignVCenter,
                         "online" if row.online else last_seen_text(row.last_seen))

        if row.unread:
            badge = QRect(r.right() - 36, r.center().y() - 10, 26, 20)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ffffff") if selected else QColor(style.ACCENT))
            painter.drawRoundedRect(badge, 10, 10)
            painter.setPen(QColor(style.ACCENT) if selected else QColor("#ffffff"))
            bold = QFont(option.font)
            bold.setBold(True)
            bold.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.5))
            painter.setFont(bold)
            painter.drawText(badge, Qt.AlignCenter, str(row.unread) if row.unread < 100 else "99+")
        painter.restore()


def last_seen_text(last_seen: float, now: Optional[float] = None) -> str:
    if not last_seen:
        return "offline"
    ago = (now or time.time()) - last_seen
    if ago < 120:
        return "offline · seen just now"
    if ago < 3600:
        return f"offline · seen {int(ago // 60)} min ago"
    if ago < 86400:
        hours = int(ago // 3600)
        return f"offline · seen {hours} hour{'s' if hours != 1 else ''} ago"
    days = int(ago // 86400)
    return f"offline · seen {days} day{'s' if days != 1 else ''} ago"
