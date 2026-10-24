"""Starting Simple-Chat when you log in, so messages arrive without
having to remember to open it.

Each system has its own place for this, all per-user (no admin rights):

- Linux (and the Pi): a .desktop file in ~/.config/autostart.
- macOS: a LaunchAgent plist in ~/Library/LaunchAgents.
- Windows: a value under HKCU\\...\\CurrentVersion\\Run.

The app starts with --hidden, straight into the tray. Whether it's on is
read back from the system itself rather than remembered in settings, so
the menu tick is always the truth.
"""
from __future__ import annotations

import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "Simple-Chat"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_LAUNCH_LABEL = "uk.hellyer.simplechat"


def launch_command(profile: str = "") -> list[str]:
    """How to start this copy of the app, as it's running now: the
    installed program, or Python and the module when run from source."""
    if getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        command = [sys.executable, "-m", "simple_chat.app"]
    command.append("--hidden")
    if profile:
        command += ["--profile", profile]
    return command


def _entry_name(profile: str) -> str:
    return APP_NAME + (f"-{profile}" if profile else "")


class Autostart:
    def __init__(self, profile: str = "", platform: Optional[str] = None, home: Optional[Path] = None,
                 registry=None):
        """platform, home and registry are for tests; registry stands in
        for winreg (get/set/delete of one value)."""
        self._profile = profile
        self._platform = platform or sys.platform
        self._home = home or Path.home()
        self._registry = registry

    @property
    def supported(self) -> bool:
        return self._platform.startswith(("linux", "darwin", "win32"))

    def is_enabled(self) -> bool:
        try:
            if self._platform == "win32":
                return self._reg().get(_entry_name(self._profile)) is not None
            return self._file().exists()
        except OSError:
            return False

    def set_enabled(self, on: bool, command: Optional[list[str]] = None) -> None:
        """Raises OSError if the system refused."""
        if on:
            self._write(command or launch_command(self._profile))
        else:
            self._remove()

    def refresh(self) -> None:
        """Re-point an existing entry at this copy (it may have moved, or
        been run from somewhere else). Never raises."""
        try:
            if self.is_enabled():
                self._write(launch_command(self._profile))
        except OSError:
            pass

    # --- per system

    def _file(self) -> Path:
        name = _entry_name(self._profile).lower()
        if self._platform == "darwin":
            label = _LAUNCH_LABEL + (f".{self._profile}" if self._profile else "")
            return self._home / "Library" / "LaunchAgents" / f"{label}.plist"
        return self._home / ".config" / "autostart" / f"{name}.desktop"

    def _write(self, command: list[str]) -> None:
        if self._platform == "win32":
            self._reg().set(_entry_name(self._profile), _windows_command_line(command))
            return
        path = self._file()
        path.parent.mkdir(parents=True, exist_ok=True)
        if self._platform == "darwin":
            label = path.stem
            path.write_bytes(plistlib.dumps({
                "Label": label, "ProgramArguments": command, "RunAtLoad": True, "ProcessType": "Interactive",
            }))
        else:
            path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={APP_NAME}\n"
                "Comment=Pass messages between your computers on the local network\n"
                f"Exec={' '.join(_desktop_quote(part) for part in command)}\n"
                # skipped quietly if the app has been uninstalled
                f"TryExec={_desktop_quote(command[0])}\n"
                "Icon=simple-chat\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )

    def _remove(self) -> None:
        if self._platform == "win32":
            self._reg().delete(_entry_name(self._profile))
            return
        try:
            self._file().unlink()
        except FileNotFoundError:
            pass

    def _reg(self):
        if self._registry is None:
            self._registry = _WindowsRunKey()
        return self._registry


def _desktop_quote(arg: str) -> str:
    """Quoting for a .desktop Exec line (close to shell quoting, but %
    must be doubled)."""
    return shlex.quote(arg).replace("%", "%%")


def _windows_command_line(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


class _WindowsRunKey:
    """HKCU\\...\\Run, one value at a time."""

    def get(self, name: str) -> Optional[str]:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None

    def set(self, name: str, value: str) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass
