"""The window, offscreen: a message typed in one window turns up in the other's."""
import time

import pytest
from PySide6.QtWidgets import QApplication

from simple_chat.core.settings import SettingsStore
from simple_chat.core.store import ChatStore
from simple_chat.gui import chat_view
from simple_chat.gui.main_window import MainWindow
from simple_chat.gui.peer_list import last_seen_text


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def spin(until, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return False


def test_two_windows_chat(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_check_for_updates", lambda self, tell=False: None)
    windows = []
    for name in ("alpha", "beta"):
        settings = SettingsStore(tmp_path / f"{name}.json")
        settings.update(name=name.title(), close_to_tray=False)
        windows.append(MainWindow(settings, ChatStore(), name))
    a, b = windows
    try:
        # introduce them directly (broadcasts may not route in a test box)
        a._node._hear(b._node.node_id, "Beta", "127.0.0.1", b._node.port)
        b._node._hear(a._node.node_id, "Alpha", "127.0.0.1", a._node.port)
        a._open_peer(b._node.node_id)
        a._chat._composer.setPlainText("see https://example.com/x, ok")
        a._chat._send()
        assert spin(lambda: b._store.unread_counts().get(a._node.node_id) == 1)
        assert spin(lambda: "delivered" in a._chat._browser.toPlainText())
        assert b.windowTitle().startswith("(1)")
        b._open_peer(a._node.node_id)
        assert "example.com" in b._chat._browser.toHtml()
        assert not b._store.unread_counts()
    finally:
        for w in windows:
            w.quit()


def test_linkify_escapes_and_links():
    out = chat_view._linkify("<b>hi</b> www.x.org.\nnext", "#fff")
    assert "&lt;b&gt;" in out and "href='http://www.x.org'" in out and "<br>" in out and "x.org</a>." in out


def test_last_seen_text():
    assert last_seen_text(0) == "offline"
    assert last_seen_text(1000, now=1030) == "offline · seen just now"
    assert last_seen_text(1000, now=1000 + 7200) == "offline · seen 2 hours ago"
