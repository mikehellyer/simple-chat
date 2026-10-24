"""Persisted user preferences, and this machine's identity."""
from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir

from simple_chat.core.protocol import new_id


@dataclass
class Settings:
    # This machine's identity on the network. Made once, on first run, so
    # other machines know it's the same one even if its name or address
    # changes.
    node_id: str = ""
    # The name other machines see. The computer's hostname to start with.
    name: str = ""
    # The window's size and place, as Qt's saveGeometry() gives it (hex).
    geometry: str = ""
    # The chat open when the app was last closed.
    last_peer: str = ""
    # Closing the window leaves the app running in the system tray, so
    # messages still arrive. Quit from the tray menu or File → Quit.
    close_to_tray: bool = True
    # Pop up a desktop notification when a message arrives and the window
    # isn't in front.
    notify: bool = True
    # Machines added by address because broadcasts don't reach them
    # (another subnet, a VPN). Each is asked "are you there?" regularly.
    manual_hosts: list = field(default_factory=list)
    # The encryption key made from the shared passphrase (hex), or "" for
    # none. The passphrase itself is never saved.
    network_key: str = ""


def default_config_path(profile: str = "") -> Path:
    """`profile` gives a second copy of the app on one machine its own
    identity (Simple-Chat --profile test)."""
    base = Path(user_config_dir("Simple-Chat"))
    return base / (f"settings-{profile}.json" if profile else "settings.json")


class SettingsStore:
    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or default_config_path()
        self.settings = Settings()
        self.load()
        changed = False
        if not self.settings.node_id:
            self.settings.node_id = new_id()
            changed = True
        if not self.settings.name.strip():
            self.settings.name = socket.gethostname().split(".")[0] or "My computer"
            changed = True
        if changed:
            self.save()

    def update(self, **changes) -> None:
        for name, value in changes.items():
            if not hasattr(self.settings, name):
                raise AttributeError(name)
            setattr(self.settings, name, value)
        self.save()

    def load(self) -> None:
        try:
            data = json.loads(self._config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        defaults = Settings()
        for f in fields(Settings):
            if f.name not in data:
                continue
            value, default = data[f.name], getattr(defaults, f.name)
            if type(value) is not type(default):
                continue
            if f.name == "manual_hosts":
                value = [h.strip() for h in value if isinstance(h, str) and h.strip()]
            setattr(self.settings, f.name, value)

    def save(self) -> None:
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._config_path.write_text(json.dumps(asdict(self.settings), indent=2))
            # it holds the encryption key: readable by this user only
            # (a no-op on Windows, where the user's profile is private)
            os.chmod(self._config_path, 0o600)
        except OSError:
            pass
