import sys

from simple_chat import __version__


def self_test() -> int:
    """`Simple-Chat --self-test`: checks a built app has everything it
    needs bundled (the release workflow runs this on each OS). Exit code
    0 if so."""
    checks = {}
    try:
        from simple_chat.core import protocol

        m = protocol.ChatMessage("m1", "n1", "Test", 1, "hi\nthere")
        checks["protocol"] = protocol.decode_line(protocol.encode_message(m).strip()) == m
    except Exception:
        checks["protocol"] = False
    try:
        from simple_chat.core.store import ChatStore

        store = ChatStore()
        store.add_outgoing("m1", "p1", "hi", 1.0)
        checks["message store"] = len(store.pending_for("p1")) == 1
    except Exception:
        checks["message store"] = False
    try:
        from PySide6.QtNetwork import QHostAddress  # noqa: F401  (needs no display)

        checks["networking"] = QHostAddress("192.168.1.1").toIPv4Address() == 3232235777
    except Exception:
        checks["networking"] = False
    try:
        from simple_chat.core.crypto import Channel

        channel = Channel(bytes(32))
        checks["encryption"] = channel.open_line(channel.seal_line(b"hi\n").rstrip(b"\n")) == b"hi"
    except Exception:
        checks["encryption"] = False
    try:
        import certifi  # noqa: F401

        checks["certificates"] = True
    except Exception:
        checks["certificates"] = False
    report = ", ".join(f"{name}: {'ok' if ok else 'MISSING'}" for name, ok in checks.items())
    try:
        print(f"Simple-Chat {__version__} self-test — {report}", flush=True)
    except (AttributeError, OSError):  # no console (Windows GUI build)
        pass
    return 0 if all(checks.values()) else 1


def _profile() -> str:
    """`--profile NAME` runs a separate copy with its own identity and
    chats — for trying two "machines" on one computer."""
    if "--profile" in sys.argv:
        i = sys.argv.index("--profile")
        if i + 1 < len(sys.argv):
            return "".join(ch for ch in sys.argv[i + 1] if ch.isalnum())[:20]
    return ""


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    # Qt is imported only now, so --self-test runs even where there's no
    # display or graphics libraries (the release workflow's build machines).
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from simple_chat.core.diagnostics import enable_app_log, enable_crash_log, log_event
    from simple_chat.core.settings import SettingsStore, default_config_path
    from simple_chat.core.store import ChatStore, default_path
    from simple_chat.gui import style
    from simple_chat.gui.main_window import MainWindow

    profile = _profile()
    enable_app_log(__version__)
    enable_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName("Simple-Chat")
    app.setDesktopFileName("simple-chat")
    app.setQuitOnLastWindowClosed(False)  # it lives on in the tray

    # One copy per profile: starting it again just brings the running one
    # to the front (it may be hidden in the tray).
    key = "simple-chat-" + (profile or "main")
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(500):
        probe.write(b"show\n")
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(key)  # a stale one left by a crash
    server = QLocalServer()
    server.listen(key)

    style.apply(app)
    settings = SettingsStore(default_config_path(profile))
    store = ChatStore(default_path(profile))
    window = MainWindow(settings, store, profile)
    server.newConnection.connect(window.bring_to_front)
    # --hidden (from "Start when I log in") goes straight to the tray —
    # unless there's no tray to go to, when the window has to show
    if "--hidden" not in sys.argv or not window.has_tray:
        window.show()
    code = app.exec()
    store.close()
    log_event(f"event loop finished (code {code})")
    return code


if __name__ == "__main__":
    sys.exit(main())
