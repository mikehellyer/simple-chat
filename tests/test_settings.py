from simple_chat.core.settings import SettingsStore


def test_identity_made_once_and_kept(tmp_path):
    path = tmp_path / "settings.json"
    first = SettingsStore(path).settings
    assert first.node_id and first.name
    again = SettingsStore(path).settings
    assert again.node_id == first.node_id


def test_bad_values_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"name": 5, "close_to_tray": false, "manual_hosts": ["pi.local", 3, "  "]}')
    s = SettingsStore(path).settings
    assert s.name != 5 and s.close_to_tray is False
    assert s.manual_hosts == ["pi.local"]
