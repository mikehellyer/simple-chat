"""Scanning the local network for machines running Simple-Chat.

Normally machines find each other by broadcast, but some routers, Wi-Fi
"isolation" settings and firewalls drop broadcasts. The scan knocks on
every address on this machine's networks two ways:

- a UDP "hello" to the discovery port, which any copy that hears it
  answers with an announcement (handled by ChatNode as usual), and
- a TCP connection to the usual message port with a "who" line, which
  gets through where UDP is blocked.

Either way an answer reaches ChatNode._hear, which remembers the
machine; the scan just listens to ChatNode.peer_heard to report who
turned up.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface, QTcpSocket

from simple_chat.core import protocol
from simple_chat.core.protocol import Announce, LineReader
from simple_chat.core.subnets import scan_targets

PARALLEL = 64
PROBE_TIMEOUT_MS = 1500
# Time left for UDP answers after the last TCP probe ends.
GRACE_MS = 1500


def local_networks() -> list[tuple[str, int]]:
    """(address, prefix length) for each IPv4 network this machine is on."""
    found = []
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not (flags & QNetworkInterface.IsUp and flags & QNetworkInterface.IsRunning) or flags & QNetworkInterface.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            if entry.ip().protocol() == QAbstractSocket.IPv4Protocol:
                found.append((entry.ip().toString(), entry.prefixLength()))
    return found


class NetworkScanner(QObject):
    progress = Signal(int, int)  # addresses done, total
    # {peer id: address} of every machine heard from during the scan
    finished = Signal(dict)

    def __init__(self, node, targets: list[str] | None = None, port: int = protocol.PREFERRED_MESSAGE_PORT,
                 parent=None):
        super().__init__(parent or node)
        self._node = node
        self._targets = scan_targets(local_networks()) if targets is None else list(targets)
        self._port = port
        self._queue = list(self._targets)
        self._active: set[_Probe] = set()
        self._done = 0
        self._found: dict[str, str] = {}
        self._running = False
        self._grace = QTimer(self)
        self._grace.setSingleShot(True)
        self._grace.setInterval(GRACE_MS)
        self._grace.timeout.connect(self._finish)

    @property
    def total(self) -> int:
        return len(self._targets)

    def start(self) -> None:
        self._running = True
        self._node.peer_heard.connect(self._heard)
        for host in self._targets:
            self._node.say_hello(QHostAddress(host))
        self.progress.emit(0, self.total)
        self._fill()

    def cancel(self) -> None:
        if not self._running:
            return
        self._queue.clear()
        for probe in list(self._active):
            probe.stop()
        self._finish()

    @Slot(str, str)
    def _heard(self, peer_id: str, host: str) -> None:
        self._found[peer_id] = host

    def _fill(self) -> None:
        while self._running and self._queue and len(self._active) < PARALLEL:
            probe = _Probe(self, self._queue.pop(0), self._port)
            self._active.add(probe)
            probe.start()
        if self._running and not self._queue and not self._active and not self._grace.isActive():
            self._grace.start()

    def _probe_done(self, probe: "_Probe") -> None:
        if probe not in self._active:
            return
        self._active.discard(probe)
        self._done += 1
        if self._running:
            self.progress.emit(self._done, self.total)
            self._fill()

    def _answered(self, announce: Announce, host: str) -> None:
        self._node._hear(announce.node_id, announce.name, host, announce.port)

    @Slot()
    def _finish(self) -> None:
        if not self._running:
            return
        self._running = False
        self._grace.stop()
        self._node.peer_heard.disconnect(self._heard)
        self.finished.emit(dict(self._found))


class _Probe(QObject):
    """One TCP knock: connect, ask "who", read the announcement."""

    def __init__(self, scanner: NetworkScanner, host: str, port: int):
        super().__init__(scanner)
        self._scanner = scanner
        self._host, self._port = host, port
        self._reader = LineReader()
        self._stopped = False
        self._socket = QTcpSocket(self)
        self._socket.connected.connect(lambda: self._socket.write(protocol.encode_who()))
        self._socket.readyRead.connect(self._read)
        self._socket.errorOccurred.connect(self.stop)
        self._socket.disconnected.connect(self.stop)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PROBE_TIMEOUT_MS)
        self._timer.timeout.connect(self.stop)

    def start(self) -> None:
        self._timer.start()
        self._socket.connectToHost(self._host, self._port)

    @Slot()
    def _read(self) -> None:
        for line in self._reader.feed(bytes(self._socket.readAll())):
            answer = protocol.decode_line(line)
            if isinstance(answer, Announce):
                self._scanner._answered(answer, self._host)
                self.stop()
                return
        if self._reader.broken:
            self.stop()

    @Slot()
    def stop(self, *_args) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._timer.stop()
        self._socket.abort()
        self._scanner._probe_done(self)
        self.deleteLater()
