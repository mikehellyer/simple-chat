import plistlib
import sys

import pytest

from simple_chat.core import autostart
from simple_chat.core.autostart import Autostart

COMMAND = ["/opt/simple-chat/Simple-Chat", "--hidden"]


class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_linux_desktop_file(tmp_path):
    a = Autostart(platform="linux", home=tmp_path)
    assert a.supported and not a.is_enabled()
    a.set_enabled(True, COMMAND)
    path = tmp_path / ".config" / "autostart" / "simple-chat.desktop"
    text = path.read_text()
    assert "Exec=/opt/simple-chat/Simple-Chat --hidden\n" in text
    assert "TryExec=/opt/simple-chat/Simple-Chat\n" in text
    assert a.is_enabled()
    a.set_enabled(False)
    assert not path.exists() and not a.is_enabled()
    a.set_enabled(False)  # already off: fine


def test_linux_quotes_awkward_paths(tmp_path):
    a = Autostart(platform="linux", home=tmp_path)
    a.set_enabled(True, ["/home/mike/My Apps/100% chat", "--hidden"])
    text = (tmp_path / ".config" / "autostart" / "simple-chat.desktop").read_text()
    assert "Exec='/home/mike/My Apps/100%% chat' --hidden" in text


def test_profiles_get_their_own_entry(tmp_path):
    main, test = Autostart(platform="linux", home=tmp_path), Autostart("test", platform="linux", home=tmp_path)
    test.set_enabled(True, COMMAND + ["--profile", "test"])
    assert test.is_enabled() and not main.is_enabled()


def test_macos_launch_agent(tmp_path):
    a = Autostart(platform="darwin", home=tmp_path)
    a.set_enabled(True, ["/Applications/Simple-Chat.app/Contents/MacOS/Simple-Chat", "--hidden"])
    path = tmp_path / "Library" / "LaunchAgents" / "uk.hellyer.simplechat.plist"
    plist = plistlib.loads(path.read_bytes())
    assert plist["RunAtLoad"] is True and plist["Label"] == "uk.hellyer.simplechat"
    assert plist["ProgramArguments"][-1] == "--hidden"
    a.set_enabled(False)
    assert not path.exists()


def test_windows_run_key():
    reg = FakeRegistry()
    a = Autostart(platform="win32", registry=reg)
    a.set_enabled(True, [r"C:\Program Files\Simple-Chat\Simple-Chat.exe", "--hidden"])
    assert reg.values == {"Simple-Chat": r'"C:\Program Files\Simple-Chat\Simple-Chat.exe" --hidden'}
    assert a.is_enabled()
    a.set_enabled(False)
    assert reg.values == {} and not a.is_enabled()


def test_refresh_repoints_only_when_on(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "launch_command", lambda profile="": ["/new/place/Simple-Chat", "--hidden"])
    a = Autostart(platform="linux", home=tmp_path)
    a.refresh()
    assert not a.is_enabled()
    a.set_enabled(True, COMMAND)
    a.refresh()
    assert "Exec=/new/place/Simple-Chat --hidden" in (tmp_path / ".config/autostart/simple-chat.desktop").read_text()


def test_launch_command_from_source_and_frozen(monkeypatch):
    assert autostart.launch_command() == [sys.executable, "-m", "simple_chat.app", "--hidden"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.launch_command("test") == [sys.executable, "--hidden", "--profile", "test"]
