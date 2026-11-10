"""save_app_password: an app password in its own owner-only file, never logged."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

import cleanyourmail_app.services.secrets as secrets
from cleanyourmail_app.services.secrets import save_app_password

SENTINEL = "sentinel-app-password-1234"


def test_writes_exactly_the_value_without_a_trailing_newline(tmp_path: Path):
    target = tmp_path / ".secrets" / "cleanyourmail.txt"

    assert save_app_password(target, SENTINEL) is None

    assert target.read_bytes() == SENTINEL.encode("utf-8")
    assert target.read_text(encoding="utf-8") == SENTINEL


def test_writes_whitespace_inside_the_value_verbatim(tmp_path: Path):
    target = tmp_path / "cleanyourmail.txt"
    value = "  abcd efgh ijkl mnop  "

    save_app_password(target, value)

    assert target.read_bytes() == value.encode("utf-8")


def test_creates_the_parent_directory(tmp_path: Path):
    target = tmp_path / "nested" / "deeper" / "cleanyourmail.txt"

    save_app_password(target, SENTINEL)

    assert target.is_file()


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
def test_posix_mode_is_0600(tmp_path: Path):
    target = tmp_path / "cleanyourmail.txt"

    save_app_password(target, SENTINEL)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
def test_posix_mode_narrows_an_existing_wide_file(tmp_path: Path):
    target = tmp_path / "cleanyourmail.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o644)

    save_app_password(target, SENTINEL)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("value", ["", " ", "\t", "\r\n  \t "])
def test_rejects_empty_and_whitespace_values(tmp_path: Path, value: str):
    target = tmp_path / "cleanyourmail.txt"

    with pytest.raises(ValueError):
        save_app_password(target, value)

    assert not target.exists()


def test_rejects_a_directory_target(tmp_path: Path):
    target = tmp_path / "cleanyourmail.txt"
    target.mkdir()

    with pytest.raises(IsADirectoryError):
        save_app_password(target, SENTINEL)

    assert target.is_dir()


def test_replaces_an_existing_file_atomically(tmp_path: Path, monkeypatch):
    target = tmp_path / "cleanyourmail.txt"
    target.write_text("old-password", encoding="utf-8")
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def tracking_replace(source, destination):
        calls.append((str(source), str(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", tracking_replace)

    save_app_password(target, SENTINEL)

    assert target.read_text(encoding="utf-8") == SENTINEL
    assert len(calls) == 1
    source, destination = calls[0]
    assert os.path.dirname(source) == str(tmp_path)
    assert destination == str(target)
    assert not os.path.exists(source)
    assert sorted(path.name for path in tmp_path.iterdir()) == [target.name]


def test_a_failed_replace_keeps_the_old_file_and_removes_the_temp(
    tmp_path: Path, monkeypatch
):
    target = tmp_path / "cleanyourmail.txt"
    target.write_text("old-password", encoding="utf-8")

    def failing_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="replace failed") as error:
        save_app_password(target, SENTINEL)

    assert SENTINEL not in str(error.value)
    assert target.read_text(encoding="utf-8") == "old-password"
    assert sorted(path.name for path in tmp_path.iterdir()) == [target.name]


def test_the_secret_never_appears_in_logs_or_the_result(tmp_path: Path, caplog):
    target = tmp_path / "cleanyourmail.txt"

    with caplog.at_level(logging.DEBUG):
        result = save_app_password(target, SENTINEL)

    assert result is None
    assert SENTINEL not in caplog.text
    assert SENTINEL not in repr(result)
    assert SENTINEL not in str(target)


@pytest.mark.skipif(os.name != "nt", reason="the ACL step only runs on Windows")
def test_a_windows_acl_failure_is_best_effort(tmp_path: Path, monkeypatch):
    def boom(path):
        raise OSError("icacls is not available")

    monkeypatch.setattr(secrets, "_restrict_windows_acl", boom)
    target = tmp_path / "cleanyourmail.txt"

    save_app_password(target, SENTINEL)

    assert target.read_text(encoding="utf-8") == SENTINEL
