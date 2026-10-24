"""The main window: machines on the left, the chat on the right, the
tray icon, menus, and the update banner."""
from __future__ import annotations

import html
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from simple_chat import __version__
from simple_chat.core.self_update import download_asset, find_asset_for_this_platform, launch_installer
from simple_chat.core.settings import SettingsStore
from simple_chat.core.store import ChatStore, StoredMessage
from simple_chat.core.updater import check_for_update
from simple_chat.gui.chat_view import ChatView
from simple_chat.gui.peer_list import PeerList, PeerRow, last_seen_text
from simple_chat.gui.update_banner import UpdateBanner
from simple_chat.gui.workers import BackgroundRunner
from simple_chat.net.node import ChatNode

UPDATE_OWNER = "mikehellyer"
UPDATE_REPO = "simple-chat"
BACKGROUND_JOIN_TIMEOUT_MS = 3000
ICON_PATH = Path(__file__).parent / "resources" / "icon.png"


class MainWindow(QMainWindow):
    def __init__(self, settings: SettingsStore, store: ChatStore, profile: str = ""):
        super().__init__()
        self._settings = settings
        self._store = store
        self._profile = profile
        self._runner = BackgroundRunner(self)
        self._pending_update = None
        self._quitting = False
        self._told_about_tray = False
        self._notify_peer = None  # the chat the last notification was about
        s = settings.settings

        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(900, 620)
        if s.geometry:
            self.restoreGeometry(QByteArray.fromHex(s.geometry.encode()))

        self._node = ChatNode(store, s.node_id, s.name, parent=self)
        self._node.peers_changed.connect(self._refresh_peers)
        self._node.message_received.connect(self._on_received)
        self._node.message_delivered.connect(self._on_delivered)
        self._node.status.connect(lambda text: self.statusBar().showMessage(text, 15000))

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._update_banner = UpdateBanner()
        self._update_banner.update_clicked.connect(self._start_update)
        layout.addWidget(self._update_banner)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        self._me = QLabel()
        self._me.setObjectName("me")
        self._me.setTextFormat(Qt.RichText)
        self._me.setWordWrap(True)
        left_layout.addWidget(self._me)
        self._peers = PeerList()
        self._peers.peer_chosen.connect(self._open_peer)
        self._peers.forget_requested.connect(self._forget)
        self._peers.clear_requested.connect(self._clear)
        left_layout.addWidget(self._peers, stretch=1)
        splitter.addWidget(left)
        self._chat = ChatView()
        self._chat.send_requested.connect(self._send)
        splitter.addWidget(self._chat)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 650])
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

        self._build_menus()
        self._build_tray()

        if not self._node.start():
            QMessageBox.warning(self, "Simple-Chat", "Simple-Chat couldn't open a network port, so it can't "
                                "send or receive messages. Is something blocking it?")
        self._node.set_manual_hosts(s.manual_hosts)
        self._update_me()
        self._refresh_peers()
        if s.last_peer and store.peer(s.last_peer):
            self._open_peer(s.last_peer)

        # "last seen" texts age, so the list is redrawn now and then
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._peers.viewport().update)
        self._tick.start(30_000)
        QTimer.singleShot(3000, self._check_for_updates)

    # --- building

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("Change my name…", self._rename)
        file_menu.addAction("Add a machine by address…", self._add_by_address)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.quit)
        file_menu.addAction(quit_action)

        options = self.menuBar().addMenu("&Options")
        self._tray_option = QAction("Keep running in the tray when the window is closed", self, checkable=True)
        self._tray_option.setChecked(self._settings.settings.close_to_tray)
        self._tray_option.toggled.connect(lambda on: self._settings.update(close_to_tray=on))
        options.addAction(self._tray_option)
        notify = QAction("Notify me of new messages", self, checkable=True)
        notify.setChecked(self._settings.settings.notify)
        notify.toggled.connect(lambda on: self._settings.update(notify=on))
        options.addAction(notify)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("This machine's addresses", self._show_addresses)
        help_menu.addAction("Check for updates", lambda: self._check_for_updates(tell=True))
        help_menu.addAction("About Simple-Chat", self._about)

    def _build_tray(self) -> None:
        self._tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QSystemTrayIcon(QIcon(str(ICON_PATH)), self)
        menu = QMenu(self)
        menu.addAction("Open Simple-Chat", self.bring_to_front)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._tray_activated)
        self._tray.messageClicked.connect(self.bring_to_front)
        self._tray.show()

    # --- machines

    def _update_me(self) -> None:
        addresses = ", ".join(self._node.local_addresses()) or "no network"
        self._me.setText(f"<b>{html.escape(self._node.name)}</b> <span style='color:#7a7a80'>(this machine)"
                         f"<br>{html.escape(addresses)}</span>")

    def _refresh_peers(self) -> None:
        unread = self._store.unread_counts()
        rows = [PeerRow(p.id, p.name, self._node.is_online(p.id), unread.get(p.id, 0), p.host, p.last_seen)
                for p in self._store.peers()]
        self._peers.set_rows(rows, self._chat.peer_id)
        if self._chat.peer_id:
            peer = self._store.peer(self._chat.peer_id)
            if peer:
                self._chat.set_online(peer.name, self._node.is_online(peer.id), self._peer_detail(peer))
        self._update_title(sum(unread.values()))

    def _peer_detail(self, peer) -> str:
        if self._node.is_online(peer.id):
            return peer.host
        return last_seen_text(peer.last_seen).removeprefix("offline · ").removeprefix("offline")

    def _open_peer(self, peer_id: str) -> None:
        peer = self._store.peer(peer_id)
        if peer is None:
            return
        self._store.mark_read(peer_id)
        self._chat.show_peer(peer_id, peer.name, self._node.is_online(peer_id), self._store.conversation(peer_id),
                             self._peer_detail(peer))
        self._settings.update(last_peer=peer_id)
        self._refresh_peers()

    def _forget(self, peer_id: str) -> None:
        peer = self._store.peer(peer_id)
        if peer is None:
            return
        answer = QMessageBox.question(self, "Forget machine", f"Forget {peer.name} and delete your chat with it?\n\n"
                                      "If it's still running Simple-Chat it will come back when it's next seen.")
        if answer != QMessageBox.Yes:
            return
        self._store.forget_peer(peer_id)
        if self._chat.peer_id == peer_id:
            self._chat.show_peer(None, "", False, [])
        self._refresh_peers()

    def _clear(self, peer_id: str) -> None:
        peer = self._store.peer(peer_id)
        if peer is None:
            return
        if QMessageBox.question(self, "Clear chat", f"Delete every message in your chat with {peer.name}?\n\n"
                                "This only clears it on this machine.") != QMessageBox.Yes:
            return
        self._store.clear_conversation(peer_id)
        if self._chat.peer_id == peer_id:
            self._open_peer(peer_id)

    def _rename(self) -> None:
        name, ok = QInputDialog.getText(self, "Change my name", "The name other machines see for this one:",
                                        text=self._node.name)
        name = " ".join(name.split())[:60]
        if ok and name:
            self._settings.update(name=name)
            self._node.set_name(name)
            self._update_me()

    def _add_by_address(self) -> None:
        host, ok = QInputDialog.getText(
            self, "Add a machine by address",
            "Machines on this network normally appear by themselves. If one doesn't (it's on another\n"
            "network, or a router blocks broadcasts), type its IP address or name here — e.g. 192.168.1.20.\n"
            "It needs Simple-Chat running too.")
        host = host.strip()
        if not ok or not host:
            return
        hosts = self._settings.settings.manual_hosts
        if host not in hosts:
            hosts = hosts + [host]
            self._settings.update(manual_hosts=hosts)
        self._node.set_manual_hosts(hosts)
        self.statusBar().showMessage(f"Asking {host} to say hello…", 8000)

    def _show_addresses(self) -> None:
        addresses = "<br>".join(html.escape(a) for a in self._node.local_addresses()) or "No network connection"
        discovery = ("Looking for other machines automatically." if self._node.discovery_ok else
                     "Can't look for other machines automatically here — add them by address.")
        QMessageBox.information(self, "This machine's addresses",
                                f"<b>{html.escape(self._node.name)}</b><br><br>{addresses}<br><br>"
                                f"Messages arrive on TCP port {self._node.port}.<br>{discovery}")

    # --- messages

    def _send(self, peer_id: str, text: str) -> None:
        message = self._node.send(peer_id, text)
        self._chat.add_message(message)

    def _on_received(self, message: StoredMessage) -> None:
        looking = self._chat.peer_id == message.peer_id and self.isVisible() and self.isActiveWindow()
        if self._chat.peer_id == message.peer_id:
            self._chat.add_message(message)
        if looking:
            self._store.mark_read(message.peer_id)
        else:
            self._notify(message)
        self._refresh_peers()

    def _on_delivered(self, message_id: str, peer_id: str) -> None:
        if self._chat.peer_id == peer_id:
            self._chat.mark_delivered(message_id)

    def _notify(self, message: StoredMessage) -> None:
        QApplication.alert(self)
        if not self._settings.settings.notify or self._tray is None:
            return
        peer = self._store.peer(message.peer_id)
        text = message.text if len(message.text) < 200 else message.text[:200] + "…"
        self._notify_peer = message.peer_id
        self._tray.showMessage(peer.name if peer else "New message", text, QIcon(str(ICON_PATH)), 6000)

    def _update_title(self, unread: int) -> None:
        title = "Simple-Chat" + (f" — {self._profile}" if self._profile else "")
        if unread:
            title = f"({unread}) {title}"
        self.setWindowTitle(title)
        if self._tray is not None:
            self._tray.setToolTip(f"Simple-Chat — {unread} unread" if unread else "Simple-Chat")

    def changeEvent(self, event) -> None:
        # coming back to the window reads the open chat
        if event.type() == event.Type.ActivationChange and self.isActiveWindow() and self._chat.peer_id:
            if self._store.unread_counts().get(self._chat.peer_id):
                self._store.mark_read(self._chat.peer_id)
                self._refresh_peers()
        super().changeEvent(event)

    # --- showing, hiding and quitting

    def bring_to_front(self) -> None:
        peer_id = self._notify_peer
        if peer_id and self._store.unread_counts().get(peer_id):
            self._open_peer(peer_id)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._chat.focus_composer()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and self.isActiveWindow():
                self.hide()
            else:
                self.bring_to_front()

    def quit(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:
        if not self._quitting and self._tray is not None and self._settings.settings.close_to_tray:
            self._save_window()
            self.hide()
            event.ignore()
            if not self._told_about_tray:
                self._told_about_tray = True
                self._tray.showMessage("Simple-Chat is still running",
                                       "Messages will still arrive. Quit from the tray icon's menu.",
                                       QIcon(str(ICON_PATH)), 4000)
            return
        self._save_window()
        self._node.stop()
        self._runner.shutdown(BACKGROUND_JOIN_TIMEOUT_MS)
        if self._tray is not None:
            self._tray.hide()
        super().closeEvent(event)
        QApplication.quit()

    def _save_window(self) -> None:
        self._settings.update(geometry=bytes(self.saveGeometry().toHex()).decode())

    # --- about & updates

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About Simple-Chat",
            f"<b>Simple-Chat</b> v{__version__}<br><br>"
            "Pass messages between your own computers on the same network — no accounts, no internet, "
            "no server. Machines running Simple-Chat find each other by themselves.<br><br>"
            "By Mike Hellyer, built with Claude Code.",
        )

    def _check_for_updates(self, tell: bool = False) -> None:
        self._runner.run(
            lambda: check_for_update(__version__, UPDATE_OWNER, UPDATE_REPO),
            lambda info: self._on_update_checked(info, tell),
            lambda error: None,
        )

    def _on_update_checked(self, info, tell: bool = False) -> None:
        if info:
            self._pending_update = info
            self._update_banner.announce(info.version)
        elif tell:
            self.statusBar().showMessage(f"Simple-Chat v{__version__} is the latest version", 5000)

    def _start_update(self) -> None:
        if self._pending_update is None:
            return
        asset_url = find_asset_for_this_platform(self._pending_update.assets)
        if asset_url is None:
            self._update_banner.set_status(f"No installer for this platform — see {self._pending_update.url}")
            return
        self._update_banner.set_busy(True, "Downloading…")
        self._runner.run(lambda: download_asset(asset_url), self._on_update_downloaded, lambda error: self._on_update_downloaded(None))

    def _on_update_downloaded(self, path) -> None:
        if path is None:
            self._update_banner.set_status("Couldn't download the update — try again")
            self._update_banner.set_busy(False)
            return
        try:
            process = launch_installer(path)
        except OSError:
            self._update_banner.set_status(f"Downloaded to {path} — open it manually")
            self._update_banner.set_busy(False)
            return

        self._update_banner.set_status("Installer launched — closing to finish…")
        if sys.platform not in ("win32", "darwin") and process is not None:
            # Linux: wait for pkexec/apt to finish before quitting — quitting
            # immediately can kill its password prompt before it's answered.
            self._runner.run(lambda: (path, self._wait_for_installer(process)), self._on_installer_finished)
        else:
            QTimer.singleShot(1500, self.quit)

    @staticmethod
    def _wait_for_installer(process) -> tuple[int, str]:
        returncode = process.wait()
        stderr_text = process.stderr.read().strip() if process.stderr is not None else ""
        return returncode, stderr_text

    def _on_installer_finished(self, result) -> None:
        path, (returncode, stderr_text) = result
        if returncode == 0:
            self.quit()
            return
        detail = f": {stderr_text}" if stderr_text else f" (exit code {returncode})"
        self._update_banner.set_status(f"Update didn't install{detail} — installer is at {path}")
        self._update_banner.set_busy(False)
