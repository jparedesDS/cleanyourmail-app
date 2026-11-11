"""The update helper script: quoted paths, PID wait, silent install, cleanup.

These tests never run ``cmd.exe`` or an installer. A fake launcher captures the
process arguments and the tests inspect the generated batch file instead.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from cleanyourmail_app.services import installer as installer_module
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
    """Record the launch and, by default, perform the helper's handshake."""

    def __init__(self, *, write_marker: bool = True) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.write_marker = write_marker

    def __call__(self, command: list[str], **kwargs: object) -> None:
        self.calls.append((command, kwargs))
        if self.write_marker:
            script = Path(str(kwargs["cwd"])) / command[-1]
            script.with_suffix(".started").write_text("started\n", encoding="utf-8")


def _read(script: Path) -> str:
    raw = script.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "the helper must not have a BOM"
    return raw.decode("utf-8")


def test_helper_waits_for_the_pid_and_quotes_every_path(updater_files):
    installer, app_exe = updater_files
    launcher = FakeLauncher()
    script = install_update(
        installer, app_exe, 4321, launcher=launcher, frozen=True
    )
    try:
        text = _read(script)

        assert text.startswith("@echo off")
        assert "chcp 65001" in text
        tasklist = (
            '"%SystemRoot%\\System32\\tasklist.exe" '
            '/FI "PID eq 4321" /NH >"%~dpn0.tasklist" 2>nul'
        )
        find = (
            '"%SystemRoot%\\System32\\find.exe" '
            '"4321" "%~dpn0.tasklist" >nul'
        )
        assert tasklist in text
        assert find in text
        assert '"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1' in text
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


def test_tasklist_and_find_failures_never_reach_the_installer(updater_files):
    installer, app_exe = updater_files
    script = install_update(
        installer, app_exe, 4321, launcher=FakeLauncher(), frozen=True
    )
    try:
        text = _read(script)
        tasklist = text.index('tasklist.exe')
        tasklist_guard = text.index('if errorlevel 1 goto tasklist_failed')
        missing_output = text.index(
            'if not exist "%~dpn0.tasklist" goto tasklist_failed'
        )
        find = text.index('find.exe')
        find_error = text.index('if errorlevel 2 goto tasklist_failed')
        not_found = text.index('if errorlevel 1 goto app_exited')
        install = text.index('start "" /wait')

        assert (
            tasklist
            < tasklist_guard
            < missing_output
            < find
            < find_error
            < not_found
            < install
        )
        assert ":tasklist_failed" in text
    finally:
        script.unlink(missing_ok=True)


def test_helper_writes_a_start_marker_before_waiting_and_honours_cancel(
    updater_files,
):
    installer, app_exe = updater_files
    script = install_update(
        installer, app_exe, 4321, launcher=FakeLauncher(), frozen=True
    )
    try:
        text = _read(script)
        first_cancel = text.index('if exist "%~dpn0.cancel" goto cancelled')
        preflight = text.index(f'if not exist "{installer}" goto missing_inputs')
        marker = text.index('>"%~dpn0.started" echo started')
        wait_loop = text.index(':wait_for_exit')
        loop_cancel = text.index(
            'if exist "%~dpn0.cancel" goto cancelled', first_cancel + 1
        )

        assert first_cancel < preflight < marker < wait_loop < loop_cancel
        assert 'del /f /q "%~dpn0.started"' in text
        assert 'del /f /q "%~dpn0.cancel"' in text
    finally:
        script.unlink(missing_ok=True)


def test_the_start_marker_is_detected_and_removed(updater_files):
    installer, app_exe = updater_files
    script = install_update(
        installer, app_exe, 4321, launcher=FakeLauncher(), frozen=True
    )
    try:
        assert script.is_file()
        assert not script.with_suffix(".started").exists()
        assert not script.with_suffix(".cancel").exists()
    finally:
        script.unlink(missing_ok=True)


def test_a_missing_start_marker_leaves_a_cancel_marker_and_raises(updater_files):
    installer, app_exe = updater_files
    launcher = FakeLauncher(write_marker=False)

    with pytest.raises(UpdateError):
        install_update(
            installer,
            app_exe,
            4321,
            launcher=launcher,
            frozen=True,
            start_timeout=0.05,
        )

    command, kwargs = launcher.calls[0]
    script = Path(str(kwargs["cwd"])) / command[-1]
    try:
        assert script.is_file(), "a late helper still needs its script"
        assert not script.with_suffix(".started").exists()
        assert script.with_suffix(".cancel").is_file()
    finally:
        script.unlink(missing_ok=True)
        script.with_suffix(".cancel").unlink(missing_ok=True)


def test_installer_is_deleted_only_after_a_successful_exit(updater_files):
    installer, app_exe = updater_files
    script = install_update(
        installer, app_exe, 99, launcher=FakeLauncher(), frozen=True
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
    script = install_update(
        installer, app_exe, 777, launcher=launcher, frozen=True
    )
    try:
        assert len(launcher.calls) == 1
        command, kwargs = launcher.calls[0]
        assert command == ["cmd.exe", "/d", "/c", script.name]
        assert kwargs == {
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            "cwd": str(script.parent),
        }
    finally:
        script.unlink(missing_ok=True)


def test_launcher_never_receives_a_metacharacter_script_path(
    updater_files, monkeypatch, tmp_path
):
    installer, app_exe = updater_files
    # Windows forbids "|" in a real file name, so inject the path: the point is
    # that the launcher must receive only the basename and the parent as cwd.
    special_dir = tmp_path / "amp & pipe | dir"
    real_script = tmp_path / "real-helper.cmd"
    script_path = special_dir / "helper.cmd"

    def make_script_file():
        descriptor = os.open(
            real_script,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        )
        return descriptor, str(script_path)

    monkeypatch.setattr(installer_module, "_make_script_file", make_script_file)
    monkeypatch.setattr(
        installer_module, "_wait_for_start_marker", lambda path, timeout: None
    )
    launcher = FakeLauncher(write_marker=False)
    install_update(
        installer, app_exe, 888, launcher=launcher, frozen=True
    )
    try:
        assert len(launcher.calls) == 1
        command, kwargs = launcher.calls[0]
        assert command == ["cmd.exe", "/d", "/c", "helper.cmd"]
        assert kwargs["cwd"] == str(special_dir)
        joined = " ".join(command)
        assert "&" not in joined
        assert "|" not in joined
        assert "amp & pipe | dir" not in joined
    finally:
        real_script.unlink(missing_ok=True)


def test_a_launcher_exception_removes_the_script_and_markers(updater_files):
    installer, app_exe = updater_files

    class ExplodingLauncher:
        def __init__(self) -> None:
            self.script: Path | None = None

        def __call__(self, command: list[str], **kwargs: object) -> None:
            self.script = Path(str(kwargs["cwd"])) / command[-1]
            self.script.with_suffix(".started").write_text(
                "partial\n", encoding="utf-8"
            )
            raise OSError("blocked by policy")

    launcher = ExplodingLauncher()
    with pytest.raises(UpdateError):
        install_update(installer, app_exe, 55, launcher=launcher, frozen=True)

    assert launcher.script is not None
    assert not launcher.script.exists()
    for suffix in (".started", ".cancel", ".tasklist"):
        assert not launcher.script.with_suffix(suffix).exists()


def test_a_unc_script_folder_is_refused_before_launch(
    updater_files, monkeypatch, tmp_path
):
    installer, app_exe = updater_files
    real_script = tmp_path / "real-helper.cmd"
    unc_script = Path(r"\\server\share\cleanyourmail-update-test.cmd")

    def make_script_file():
        descriptor = os.open(
            real_script,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        )
        return descriptor, str(unc_script)

    removed: list[Path] = []
    monkeypatch.setattr(installer_module, "_make_script_file", make_script_file)
    monkeypatch.setattr(
        installer_module, "_remove_file", lambda path: removed.append(path)
    )
    launcher = FakeLauncher(write_marker=False)
    try:
        with pytest.raises(UpdateError):
            install_update(installer, app_exe, 66, launcher=launcher, frozen=True)
    finally:
        real_script.unlink(missing_ok=True)

    assert launcher.calls == []
    assert removed == [unc_script]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (Path(r"\\server\share\folder"), True),
        (Path("//server/share/folder"), True),
        (Path(r"\\?\UNC\server\share"), True),
        (Path(r"\\?\C:\Temp"), False),
        (Path(r"C:\Temp"), False),
        (Path("folder"), False),
    ],
)
def test_unc_detection(path, expected):
    assert installer_module._is_unc_path(path) is expected


@pytest.mark.parametrize("timeout", [-1, True, "1", None])
def test_invalid_start_timeouts_are_refused(updater_files, timeout):
    installer, app_exe = updater_files

    with pytest.raises(ValueError):
        install_update(
            installer,
            app_exe,
            1,
            launcher=FakeLauncher(),
            frozen=True,
            start_timeout=timeout,
        )


def test_each_call_gets_a_unique_script_in_the_temp_folder(updater_files):
    installer, app_exe = updater_files
    first = install_update(
        installer, app_exe, 1, launcher=FakeLauncher(), frozen=True
    )
    second = install_update(
        installer, app_exe, 1, launcher=FakeLauncher(), frozen=True
    )
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
        percent_installer, app_exe, 2, launcher=FakeLauncher(), frozen=True
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
        install_update(installer, app_exe, 1, launcher=launcher)

    assert launcher.calls == []


def test_missing_paths_are_refused(updater_files, tmp_path):
    installer, app_exe = updater_files

    with pytest.raises(UpdateError):
        install_update(tmp_path / "missing.exe", app_exe, 1, frozen=True)
    with pytest.raises(UpdateError):
        install_update(installer, tmp_path / "missing-app.exe", 1, frozen=True)


@pytest.mark.parametrize("pid", [0, -1, True, False, "42", 1.5, None])
def test_invalid_pids_are_refused(updater_files, pid):
    installer, app_exe = updater_files

    with pytest.raises(ValueError):
        install_update(installer, app_exe, pid, frozen=True)


def test_control_characters_and_quotes_in_paths_are_refused(updater_files):
    installer, app_exe = updater_files

    with pytest.raises(ValueError):
        install_update(Path(f"{installer}\n"), app_exe, 1, frozen=True)
    with pytest.raises(ValueError):
        install_update(Path(f"{installer}\t"), app_exe, 1, frozen=True)
    with pytest.raises(ValueError):
        install_update(Path(f'{installer}"'), app_exe, 1, frozen=True)
