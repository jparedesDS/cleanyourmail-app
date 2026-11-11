"""SettingsStore: a small JSON file that never holds a secret."""

from __future__ import annotations

import json
import os

import pytest

from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.services.settings import SettingsStore, default_settings_path

SECRET_MARKERS = ("password", "secret", "token", "credential", "refresh")


def _secret_free(payload: object) -> bool:
    """True when no key or value at any depth mentions a secret."""
    text = json.dumps(payload).lower()
    return not any(marker in text for marker in SECRET_MARKERS)


def test_default_path_is_under_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert default_settings_path() == tmp_path / "cleanyourmail-app" / "settings.json"


def test_default_path_is_used_when_no_path_is_given(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert SettingsStore().path == tmp_path / "cleanyourmail-app" / "settings.json"


def test_explicit_path_overrides_the_default(tmp_path):
    target = tmp_path / "elsewhere" / "settings.json"
    assert SettingsStore(target).path == target
    assert SettingsStore(str(target)).path == target


def test_load_without_a_file_returns_defaults(tmp_path):
    settings = SettingsStore(tmp_path / "settings.json").load()
    assert settings.provider == "custom"
    assert settings.email == ""
    assert settings.preferences == Preferences()


def test_save_writes_json_and_load_round_trips(tmp_path):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)
    expected = AppSettings(
        provider="fastmail",
        email="me@fastmail.com",
        preferences=Preferences(categories=["newsletter"], mode="archive", language="es"),
        last_update_check=1_760_000_000,
    )

    store.save(expected)

    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8")) == expected.to_dict()
    assert store.load() == expected


def test_save_creates_the_parent_directory(tmp_path):
    target = tmp_path / "nested" / "deeper" / "settings.json"
    SettingsStore(target).save(AppSettings(provider="gmail", email="me@gmail.com"))
    assert target.is_file()


def test_save_replaces_an_existing_file(tmp_path):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)
    store.save(AppSettings(provider="gmail", email="first@gmail.com"))
    store.save(AppSettings(provider="yahoo", email="second@yahoo.com"))
    assert store.load().email == "second@yahoo.com"


def test_save_is_atomic_and_leaves_no_temporary_files(tmp_path):
    target = tmp_path / "settings.json"
    SettingsStore(target).save(AppSettings(provider="gmail", email="me@gmail.com"))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["settings.json"]


def test_save_failure_keeps_the_previous_file(tmp_path):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)
    first = AppSettings(provider="gmail", email="me@gmail.com")
    store.save(first)

    # A directory at the target makes the final replace fail.
    target.unlink()
    target.mkdir()
    with pytest.raises(OSError):
        store.save(AppSettings(provider="yahoo", email="me@yahoo.com"))

    assert target.is_dir()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["settings.json"]


def test_corrupt_json_returns_defaults(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{not json", encoding="utf-8")
    assert SettingsStore(target).load() == AppSettings(provider="custom", email="")


def test_non_object_json_returns_defaults(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("[]", encoding="utf-8")
    assert SettingsStore(target).load().provider == "custom"


def test_invalid_values_return_defaults(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"provider": "gmail", "preferences": {"max_moves": 0}}))
    assert SettingsStore(target).load() == AppSettings(provider="custom", email="")


def test_unknown_and_secret_keys_are_ignored_and_never_rewritten(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "provider": "gmail",
                "email": "me@gmail.com",
                "password": "hunter2",
                "refresh_token": "hunter2",
                "preferences": {"mode": "archive", "secret": "hunter2"},
            }
        ),
        encoding="utf-8",
    )
    store = SettingsStore(target)
    loaded = store.load()

    assert loaded.provider == "gmail"
    assert loaded.preferences.mode == "archive"
    assert _secret_free(loaded.to_dict())
    assert "hunter2" not in json.dumps(loaded.to_dict())

    store.save(loaded)
    raw = target.read_text(encoding="utf-8")
    assert "hunter2" not in raw
    assert "password" not in raw.lower()
    assert "secret" not in raw.lower()
    assert "token" not in raw.lower()


def test_saved_file_contains_no_secret_marker(tmp_path):
    target = tmp_path / "settings.json"
    SettingsStore(target).save(
        AppSettings(provider="proton", email="me@proton.me", preferences=Preferences())
    )
    assert _secret_free(json.loads(target.read_text(encoding="utf-8")))


def test_load_preferences_reads_only_the_preferences(tmp_path):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)
    store.save(
        AppSettings(
            provider="gmail",
            email="me@gmail.com",
            preferences=Preferences(mode="archive", language="es"),
        )
    )
    assert store.load_preferences() == Preferences(mode="archive", language="es")


def test_load_preferences_without_a_file_returns_defaults(tmp_path):
    assert SettingsStore(tmp_path / "settings.json").load_preferences() == Preferences()


def test_update_preferences_keeps_provider_email_and_last_update_check(tmp_path):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)
    store.save(
        AppSettings(
            provider="icloud",
            email="me@icloud.com",
            last_update_check=1_760_000_000,
        )
    )

    store.update_preferences(Preferences(mode="archive", max_moves=10, language="es"))

    loaded = store.load()
    assert loaded.provider == "icloud"
    assert loaded.email == "me@icloud.com"
    assert loaded.last_update_check == 1_760_000_000
    assert loaded.preferences == Preferences(mode="archive", max_moves=10, language="es")


def test_update_preferences_writes_the_file_when_none_exists(tmp_path):
    target = tmp_path / "settings.json"
    SettingsStore(target).update_preferences(Preferences(mode="archive"))
    assert target.is_file()
    assert SettingsStore(target).load_preferences().mode == "archive"


def test_update_last_update_check_preserves_every_other_field(tmp_path):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)
    store.save(
        AppSettings(
            provider="gmail",
            email="me@gmail.com",
            preferences=Preferences(
                categories=["newsletter", "spam"],
                mode="archive",
                max_moves=25,
                language="es",
            ),
        )
    )

    store.update_last_update_check(1_760_000_123)

    loaded = store.load()
    assert loaded.last_update_check == 1_760_000_123
    assert loaded.provider == "gmail"
    assert loaded.email == "me@gmail.com"
    assert loaded.preferences == Preferences(
        categories=["newsletter", "spam"],
        mode="archive",
        max_moves=25,
        language="es",
    )


def test_update_last_update_check_creates_a_missing_file(tmp_path):
    target = tmp_path / "settings.json"
    SettingsStore(target).update_last_update_check(42)

    assert target.is_file()
    loaded = SettingsStore(target).load()
    assert loaded.last_update_check == 42
    assert loaded.provider == "custom"
    assert loaded.email == ""


def test_update_last_update_check_does_not_overwrite_a_corrupt_file(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{not json", encoding="utf-8")
    before = target.read_bytes()

    SettingsStore(target).update_last_update_check(99)

    assert target.read_bytes() == before


def test_update_last_update_check_does_not_overwrite_invalid_settings(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps({"provider": "gmail", "preferences": {"max_moves": 0}}),
        encoding="utf-8",
    )
    before = target.read_bytes()

    SettingsStore(target).update_last_update_check(99)

    assert target.read_bytes() == before


@pytest.mark.parametrize("timestamp", [-1, True, False, "42", 1.5, None])
def test_update_last_update_check_rejects_an_invalid_timestamp(
    tmp_path, timestamp
):
    target = tmp_path / "settings.json"
    store = SettingsStore(target)

    with pytest.raises(ValueError):
        store.update_last_update_check(timestamp)

    assert not target.exists()


def test_settings_file_is_utf8_and_ends_with_a_newline(tmp_path):
    target = tmp_path / "settings.json"
    SettingsStore(target).save(AppSettings(provider="gmail", email="me@gmail.com"))
    raw = target.read_bytes()
    assert raw.endswith(b"\n")
    assert "me@gmail.com" in raw.decode("utf-8")


def test_os_replace_is_used_not_a_direct_write(tmp_path, monkeypatch):
    """The final step must be ``os.replace`` so a reader never sees half a file."""
    target = tmp_path / "settings.json"
    calls = []
    real_replace = os.replace

    def tracking_replace(source, destination):
        calls.append((source, destination))
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", tracking_replace)
    SettingsStore(target).save(AppSettings(provider="gmail", email="me@gmail.com"))

    assert len(calls) == 1
    source, destination = calls[0]
    assert os.path.dirname(str(source)) == str(tmp_path)
    assert str(destination) == str(target)
    assert not os.path.exists(source)
