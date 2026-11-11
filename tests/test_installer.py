"""The update helper script: quoted paths, PID wait, silent install, cleanup.

These tests never run ``cmd.exe`` or an installer. A fake launcher captures the
process arguments and the tests inspect the generated batch file instead.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from cleanyourmail_app.services.installer import (
    INSTALLER_SWITCHES,
    InstallerUnavailable,
    install_update,
)
from cleanyourmail_app.services.updates import UpdateError


@pytest.fixture
def updater_files(tmp_path) -> tuple[Path, Path]:
    installer = tmp_path / "Café Folder" / "CleanYourMail-Setup-0.6.0.exe"
    app_exe = tmp_path / "Program Files" / "CleanYourMail.exe"
    installer.parent.mkdir()
    installer.write_bytes(b"MZ installer")
    app_exe.parent.mkdir()
    app_exe.write_bytes(b"MZ app")
    return installer, app_exe


class FakeLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> None:
        self.calls.append((command, kwargs))


def _read(script: Path) -> str:
    raw = script.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "the helper must not have a BOM"
    return raw.decode("utf-8")


def test_helper_waits_for_the_pid_and_quotes_every_path(updater_files):
    installer, app_exe = updater_files
    launcher = FakeLauncher()
    script = install_update(installer, app_exe, 4321, launcher=launcher)
    try:
        text = _read(script)

        assert text.startswith("@echo off")
        assert "chcp 65001" in text
        assert 'tasklist /FI "PID eq 4321" /NH | find "4321"' in text
        assert "ping -n 2 127.0.0.1" in text
        assert 'goto wait_for_exit' in text
        assert (
            f'start "" /wait "{installer}" '
            "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER"
        ) in text
        assert 'set "CYM_EXITCODE=%ERRORLEVEL%"' in text
        assert (
            f'if "%CYM_EXITCODE%"=="0" del /f /q "{installer}"'
        ) in text
        assert f'start "" "{app_exe}"' in text
        assert 'del /f /q "%~f0"' in text
        assert "\r\n" in text
        for switch in INSTALLER_SWITCHES:
            assert switch in text
    finally:
        script.unlink(missing_ok=True)


def test_installer_is_deleted_only_after_a_successful_exit(updater_files):
    installer, app_exe = updater_files
    script = install_update(
        installer, app_exe, 99, launcher=FakeLauncher()
    )
    try:
        text = _read(script)
        success_condition = text.index(
            f'if "%CYM_EXITCODE%"=="0" del /f /q "{installer}"'
        )
        restart = text.index(f'start "" "{app_exe}"')
        self_delete = text.index('del /f /q "%~f0"')

        assert success_condition < restart < self_delete
        assert text.count(f'del /f /q "{installer}"') == 1
    finally:
        script.unlink(missing_ok=True)


def test_launcher_starts_cmd_without_a_console_window(updater_files):
    installer, app_exe = updater_files
    launcher = FakeLauncher()
    script = install_update(installer, app_exe, 777, launcher=launcher)
    try:
        assert len(launcher.calls) == 1
        command, kwargs = launcher.calls[0]
        assert command == ["cmd.exe", "/c", str(script)]
        assert kwargs == {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)
        }
    finally:
        script.unlink(missing_ok=True)


def test_each_call_gets_a_unique_script_in_the_temp_folder(updater_files):
    installer, app_exe = updater_files
    first = install_update(installer, app_exe, 1, launcher=FakeLauncher())
    second = install_update(installer, app_exe, 1, launcher=FakeLauncher())
    try:
        assert first != second
        assert first.parent == Path(tempfile.gettempdir())
        assert first.suffix == ".cmd"
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)


def test_percent_in_a_path_is_escaped_for_batch(updater_files):
    installer, app_exe = updater_files
    percent_installer = installer.with_name("100% update.exe")
    percent_installer.write_bytes(b"MZ")
    script = install_update(
        percent_installer, app_exe, 2, launcher=FakeLauncher()
    )
    try:
        text = _read(script)
        assert "100%% update.exe" in text
        assert "100% update.exe" not in text
    finally:
        script.unlink(missing_ok=True)


def test_an_unfrozen_app_refuses_to_install(updater_files):
    installer, app_exe = updater_files
    launcher = FakeLauncher()

    with pytest.raises(InstallerUnavailable):
        install_update(
            installer, app_exe, 1, launcher=launcher, frozen=False
        )

    assert launcher.calls == []


def test_missing_paths_are_refused(updater_files, tmp_path):
    installer, app_exe = updater_files

    with pytest.raises(UpdateError):
        install_update(tmp_path / "missing.exe", app_exe, 1)
    with pytest.raises(UpdateError):
        install_update(installer, tmp_path / "missing-app.exe", 1)


@pytest.mark.parametrize("pid", [0, -1, True, False, "42", 1.5, None])
def test_invalid_pids_are_refused(updater_files, pid):
    installer, app_exe = updater_files

    with pytest.raises(ValueError):
        install_update(installer, app_exe, pid)


def test_control_characters_and_quotes_in_paths_are_refused(updater_files):
    installer, app_exe = updater_files

    with pytest.raises(ValueError):
        install_update(Path(f"{installer}\n"), app_exe, 1)
    with pytest.raises(ValueError):
        install_update(Path(f"{installer}\t"), app_exe, 1)
    with pytest.raises(ValueError):
        install_update(Path(f'{installer}"'), app_exe, 1)
