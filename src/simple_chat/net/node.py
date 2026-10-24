"""This machine on the network: finding the others and passing messages.

Everything here runs on the GUI thread, driven by Qt's own socket
events — there are no threads to hand results back from. See
core/protocol.py for what goes over the wire.
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import (
    QAbstractSocket,
    QHostAddress,
    QHostInfo,
    QNetworkInterface,
    QTcpServer,
    QTcpSocket,
    QUdpSocket,
)

from simple_chat.core import protocol
from simple_chat.core.protocol import Ack, Announce, ChatMessage, LineReader
from simple_chat.core.store import ChatStore, StoredMessage

ANNOUNCE_EVERY_MS = 5000
# A machine not heard from for this long is shown as offline.
OFFLINE_AFTER_SECONDS = 16
CONNECT_TIMEOUT_MS = 8000
# An incoming connection that's said nothing for this long is closed.
IDLE_TIMEOUT_MS = 60_000


class ChatNode(QObject):
    # a machine appeared, went away, or changed its name
    peers_changed = Signal()
    message_received = Signal(object)  # StoredMessage
    message_delivered = Signal(str, str)  # message id, peer id
    # a line for the status bar
    status = Signal(str)

    def __init__(self, store: ChatStore, node_id: str, name: str, discovery_port: int = protocol.DISCOVERY_PORT,
                 message_port: int = protocol.PREFERRED_MESSAGE_PORT, parent=None):
        super().__init__(parent)
        self._store = store
        self.node_id = node_id
        self.name = name
        self._discovery_port = discovery_port
        self._preferred_port = message_port
        self._heard: dict[str, float] = {}  # peer id → time.monotonic() last heard
        self._senders: dict[str, _Sender] = {}
        self._incoming: set[_Incoming] = set()
        self._manual_hosts: list[str] = []
        self._resolved: dict[str, QHostAddress] = {}
        self.discovery_ok = False

        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept)
        self._udp = QUdpSocket(self)
        self._udp.readyRead.connect(self._read_datagrams)

        self._announce_timer = QTimer(self)
        self._announce_timer.setInterval(ANNOUNCE_EVERY_MS)
        self._announce_timer.timeout.connect(self._announce_round)
        self._soon = QTimer(self)  # an extra announcement, coalesced
        self._soon.setSingleShot(True)
        self._soon.setInterval(250)
        self._soon.timeout.connect(lambda: self._broadcast(hello=False))
        self._online_check = QTimer(self)
        self._online_check.setInterval(2000)
        self._online_check.timeout.connect(self._check_online)
        self._was_online: set[str] = set()

    # --- life cycle

    def start(self) -> bool:
        """False if no TCP port could be opened at all (nothing works
        then); discovery failing on its own only limits finding machines."""
        if not self._server.listen(QHostAddress.AnyIPv4, self._preferred_port):
            if not self._server.listen(QHostAddress.AnyIPv4, 0):
                self.status.emit(f"Can't listen for messages: {self._server.errorString()}")
                return False
        self.discovery_ok = self._udp.bind(
            QHostAddress.AnyIPv4, self._discovery_port,
            QAbstractSocket.ShareAddress | QAbstractSocket.ReuseAddressHint,
        )
        if not self.discovery_ok:
            self.status.emit(f"Can't look for other machines (UDP port {self._discovery_port}): "
                             f"{self._udp.errorString()} — add them by address instead")
        self._announce_timer.start()
        self._online_check.start()
        self._broadcast(hello=True)
        self._ping_manual_hosts()
        return True

    def stop(self) -> None:
        self._announce_timer.stop()
        self._online_check.stop()
        self._server.close()
        self._udp.close()
        for sender in list(self._senders.values()):
            sender.abort()
        for incoming in list(self._incoming):
            incoming.close()

    @property
    def port(self) -> int:
        return self._server.serverPort()

    def set_name(self, name: str) -> None:
        self.name = name
        self._soon.start()

    def set_manual_hosts(self, hosts: list[str]) -> None:
        self._manual_hosts = list(hosts)
        self._ping_manual_hosts()

    def is_online(self, peer_id: str) -> bool:
        heard = self._heard.get(peer_id)
        return heard is not None and time.monotonic() - heard < OFFLINE_AFTER_SECONDS

    def local_addresses(self) -> list[str]:
        return [address.toString() for address in _ipv4_entries(lambda e: e.ip())]

    # --- sending

    def send(self, peer_id: str, text: str) -> StoredMessage:
        """Stores the message as pending and sends it now if the machine
        is about, or as soon as it's next seen."""
        message = self._store.add_outgoing(protocol.new_id(), peer_id, text, time.time())
        self.flush(peer_id)
        return message

    def flush(self, peer_id: str) -> None:
        """Try to deliver everything still waiting for this machine."""
        if not self.is_online(peer_id) or not self._store.pending_for(peer_id):
            return
        sender = self._senders.get(peer_id)
        if sender is None:
            peer = self._store.peer(peer_id)
            if peer is None or not peer.host or not peer.port:
                return
            sender = _Sender(self, peer_id, peer.host, peer.port)
            self._senders[peer_id] = sender
            sender.start()
        else:
            sender.send_pending()

    def _wire_message(self, stored: StoredMessage) -> bytes:
        return protocol.encode_message(ChatMessage(
            stored.id, self.node_id, self.name, self.port, stored.text, stored.sent_at))

    def _acked(self, message_id: str) -> None:
        peer_id = self._store.mark_delivered(message_id)
        if peer_id is not None:
            self.message_delivered.emit(message_id, peer_id)

    def _sender_done(self, sender: "_Sender") -> None:
        if self._senders.get(sender.peer_id) is sender:
            del self._senders[sender.peer_id]
        # anything queued while it was closing goes in a fresh connection
        if sender.succeeded:
            QTimer.singleShot(0, lambda peer_id=sender.peer_id: self.flush(peer_id))

    # --- receiving

    @Slot()
    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._incoming.add(_Incoming(self, socket))

    def _received(self, message: ChatMessage, host: str) -> bytes:
        """Handles one incoming chat message; returns the ack to send."""
        self._hear(message.sender_id, message.sender_name, host, message.sender_port)
        stored = self._store.add_incoming(message.id, message.sender_id, message.text, message.sent_at)
        if stored is not None:
            self.message_received.emit(stored)
        return protocol.encode_ack(Ack(message.id))

    # --- discovery

    def _hear(self, peer_id: str, name: str, host: str, port: int) -> None:
        if peer_id == self.node_id:
            return
        known = self._store.peer(peer_id)
        was_online = self.is_online(peer_id)
        self._heard[peer_id] = time.monotonic()
        if known is None or (known.name, known.host, known.port) != (name, host, port) or time.time() - known.last_seen > 60:
            self._store.remember_peer(peer_id, name, host, port)
        if known is None or known.name != name or not was_online:
            self._was_online.add(peer_id)
            self.peers_changed.emit()
        if not was_online or known is None or (known.host, known.port) != (host, port):
            self.flush(peer_id)

    @Slot()
    def _read_datagrams(self) -> None:
        while self._udp.hasPendingDatagrams():
            datagram = self._udp.receiveDatagram()
            announce = protocol.decode_announce(bytes(datagram.data()))
            if announce is None or announce.node_id == self.node_id:
                continue
            host = _plain_ipv4(datagram.senderAddress())
            sender = QHostAddress(host)
            is_new = not self.is_online(announce.node_id)
            self._hear(announce.node_id, announce.name, host, announce.port)
            if announce.hello or is_new:
                # answer directly (it may be on another subnet), and to
                # everyone, since a second copy on the same computer
                # won't get a direct reply to a shared port
                self._send_announce(sender, hello=False)
                self._soon.start()

    def _announce_round(self) -> None:
        self._broadcast(hello=False)
        self._ping_manual_hosts()

    def _broadcast(self, hello: bool) -> None:
        if not self.discovery_ok:
            return
        for address in self._broadcast_targets():
            self._send_announce(address, hello)

    def _broadcast_targets(self) -> list[QHostAddress]:
        """Each network's own broadcast address (some routers and VPNs
        drop 255.255.255.255), plus 255.255.255.255 if there's a network."""
        targets = {a.toString(): a for a in _ipv4_entries(lambda e: e.broadcast())}
        if targets:
            targets["255.255.255.255"] = QHostAddress(QHostAddress.Broadcast)
        return list(targets.values())

    def _send_announce(self, address: QHostAddress, hello: bool) -> None:
        data = protocol.encode_announce(Announce(self.node_id, self.name, self.port, hello))
        self._udp.writeDatagram(data, address, self._discovery_port)

    def _ping_manual_hosts(self) -> None:
        if not self.discovery_ok:
            return
        for host in self._manual_hosts:
            address = QHostAddress(host)
            if not address.isNull():
                self._send_announce(address, hello=True)
            elif host in self._resolved:
                self._send_announce(self._resolved[host], hello=True)
                QHostInfo.lookupHost(host, self._host_looked_up)  # it may have moved
            else:
                QHostInfo.lookupHost(host, self._host_looked_up)

    @Slot(QHostInfo)
    def _host_looked_up(self, info: QHostInfo) -> None:
        addresses = [a for a in info.addresses() if a.protocol() == QAbstractSocket.IPv4Protocol]
        if not addresses or info.hostName() not in self._manual_hosts:
            return
        first_time = info.hostName() not in self._resolved
        self._resolved[info.hostName()] = addresses[0]
        if first_time:
            self._send_announce(addresses[0], hello=True)

    def _check_online(self) -> None:
        online = {peer_id for peer_id in self._heard if self.is_online(peer_id)}
        if online != self._was_online:
            self._was_online = online
            self.peers_changed.emit()


class _Sender(QObject):
    """One outgoing connection to a machine: writes everything pending,
    marks each message delivered as its ack comes back, and hangs up
    once nothing is outstanding."""

    def __init__(self, node: ChatNode, peer_id: str, host: str, port: int):
        super().__init__(node)
        self._node = node
        self.peer_id = peer_id
        self.succeeded = False
        self._outstanding: set[str] = set()
        self._reader = LineReader()
        self._finished = False
        self._socket = QTcpSocket(self)
        self._socket.connected.connect(self._connected)
        self._socket.readyRead.connect(self._read)
        self._socket.disconnected.connect(self._finish)
        self._socket.errorOccurred.connect(self._error)
        self._host, self._port = host, port
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(CONNECT_TIMEOUT_MS)
        self._timeout.timeout.connect(self.abort)

    def start(self) -> None:
        self._timeout.start()
        self._socket.connectToHost(self._host, self._port)

    def send_pending(self) -> None:
        if self._socket.state() != QAbstractSocket.ConnectedState:
            return  # _connected() sends them
        for stored in self._node._store.pending_for(self.peer_id):
            if stored.id not in self._outstanding:
                self._outstanding.add(stored.id)
                self._socket.write(self._node._wire_message(stored))
        if self._outstanding:
            self._timeout.start()

    @Slot()
    def _connected(self) -> None:
        self.send_pending()
        if not self._outstanding:
            self._socket.disconnectFromHost()

    @Slot()
    def _read(self) -> None:
        for line in self._reader.feed(bytes(self._socket.readAll())):
            reply = protocol.decode_line(line)
            if isinstance(reply, Ack) and reply.id in self._outstanding:
                self._outstanding.discard(reply.id)
                self.succeeded = True
                self._node._acked(reply.id)
        if self._reader.broken:
            self.abort()
        elif not self._outstanding:
            self._timeout.stop()
            self._socket.disconnectFromHost()

    @Slot()
    def _error(self, _error=None) -> None:
        self._finish()

    def abort(self) -> None:
        self._socket.abort()
        self._finish()

    @Slot()
    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._timeout.stop()
        self._node._sender_done(self)
        self.deleteLater()


class _Incoming(QObject):
    """One connection from another machine sending us messages."""

    def __init__(self, node: ChatNode, socket: QTcpSocket):
        super().__init__(node)
        self._node = node
        self._socket = socket
        socket.setParent(self)
        self._reader = LineReader()
        self._host = _plain_ipv4(socket.peerAddress())
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_TIMEOUT_MS)
        self._idle.timeout.connect(self.close)
        self._idle.start()
        socket.readyRead.connect(self._read)
        socket.disconnected.connect(self.close)
        self._closed = False
        if socket.bytesAvailable():
            self._read()

    @Slot()
    def _read(self) -> None:
        self._idle.start()
        for line in self._reader.feed(bytes(self._socket.readAll())):
            message = protocol.decode_line(line)
            if isinstance(message, ChatMessage):
                self._socket.write(self._node._received(message, self._host))
        if self._reader.broken:
            self.close()

    @Slot()
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._idle.stop()
        self._socket.disconnectFromHost()
        self._node._incoming.discard(self)
        self.deleteLater()


def _plain_ipv4(address: QHostAddress) -> str:
    """"192.168.1.5" rather than "::ffff:192.168.1.5"."""
    ipv4 = address.toIPv4Address()  # 0 when it isn't one
    return QHostAddress(ipv4).toString() if ipv4 else address.toString()


def _ipv4_entries(pick) -> list[QHostAddress]:
    """`pick(entry)` for each IPv4 address on an interface that's up and
    not loopback; null results are skipped."""
    found = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not (flags & QNetworkInterface.IsUp and flags & QNetworkInterface.IsRunning) or flags & QNetworkInterface.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            if entry.ip().protocol() != QAbstractSocket.IPv4Protocol:
                continue
            address = pick(entry)
            if not address.isNull():
                found.append(address)
    return found
