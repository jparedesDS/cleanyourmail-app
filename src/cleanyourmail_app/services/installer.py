"""Build and start the small Windows helper that installs an update.

The app cannot replace its own executable while it is running. After the person
confirms an update, the app writes a unique ``.cmd`` file in the temporary
folder, starts it without a console, and quits. The helper waits for this PID to
exit, runs the verified Inno Setup installer silently for the current user,
deletes the installer only when the installer succeeded, and starts the newly
installed app.

This module only builds and launches the helper; it never downloads anything and
never installs without the confirmation handled by the window. Paths are quoted,
control characters are refused, and every literal ``%`` is escaped so a folder
name cannot inject a batch variable. A UNC temp folder is refused before the
window quits, the batch file uses the System32 tools by absolute path, and a
tasklist or find failure stops the helper instead of assuming the app exited. No
log line ever includes account data.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cleanyourmail_app.services.updates import UpdateError

#: Inno Setup switches: no wizard, no message boxes, no restart, current user.
INSTALLER_SWITCHES: tuple[str, ...] = (
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/CURRENTUSER",
)

#: How long the app waits for the helper's start marker before giving up.
DEFAULT_START_TIMEOUT_SECONDS = 5.0

#: The helper writes this marker after its preflight and before waiting for the
#: app PID. Its absence means the helper may never have run, so the app must
#: stay open. A cancel marker makes a late start exit without installing.
_SCRIPT_TEMPLATE = """@echo off
setlocal
chcp 65001 >nul
if exist "%~dpn0.cancel" goto cancelled
if not exist {installer} goto missing_inputs
if not exist {app_exe} goto missing_inputs
>"%~dpn0.started" echo started

:wait_for_exit
if exist "%~dpn0.cancel" goto cancelled
"%SystemRoot%\\System32\\tasklist.exe" /FI "PID eq {pid}" /NH >"%~dpn0.tasklist" 2>nul
if errorlevel 1 goto tasklist_failed
if not exist "%~dpn0.tasklist" goto tasklist_failed
"%SystemRoot%\\System32\\find.exe" "{pid}" "%~dpn0.tasklist" >nul
if errorlevel 2 goto tasklist_failed
if errorlevel 1 goto app_exited
"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1 >nul
goto wait_for_exit

:app_exited
del /f /q "%~dpn0.tasklist" >nul 2>&1
start "" /wait {installer} {switches}
set "CYM_EXITCODE=%ERRORLEVEL%"
if "%CYM_EXITCODE%"=="0" del /f /q {installer} >nul 2>&1
start "" {app_exe}
goto cleanup

:tasklist_failed
del /f /q "%~dpn0.tasklist" >nul 2>&1

:cancelled
:missing_inputs
:cleanup
del /f /q "%~dpn0.started" >nul 2>&1
del /f /q "%~dpn0.cancel" >nul 2>&1
del /f /q "%~f0" >nul 2>&1
"""

Launcher = Callable[..., Any]


class InstallerUnavailable(UpdateError):
    """Automatic installation is not possible in this build or layout."""


def install_update(
    installer: str | os.PathLike[str],
    app_exe: str | os.PathLike[str],
    pid: int,
    *,
    launcher: Launcher | None = None,
    frozen: bool = False,
    start_timeout: float = DEFAULT_START_TIMEOUT_SECONDS,
) -> Path:
    """Write and start the temporary installer helper; return its script path.

    The helper writes a ``.started`` marker after checking its inputs and before
    waiting for this PID. Only when that marker appears may the window quit:
    ``Popen`` returning a process only proves that ``cmd.exe`` was created, not
    that the batch file ran. If the marker does not appear within
    ``start_timeout``, a ``.cancel`` marker is left behind so a helper that
    starts late exits without installing, and :class:`UpdateError` is raised.

    Args:
        installer: The downloaded, already verified installer executable.
        app_exe: The executable to start after the installer finishes.
        pid: The running app's process id; the helper waits for it to exit.
        launcher: Injection point for tests. Defaults to ``subprocess.Popen``.
        frozen: Callers must opt in with a true value. An unpackaged development
            app must never replace itself, so the default refuses with
            :class:`InstallerUnavailable`.
        start_timeout: Seconds to wait for the helper's start marker.

    Raises:
        InstallerUnavailable: The app is not frozen (not an installed build).
        UpdateError: A path is missing, the temp folder is a UNC path, or the
            helper cannot be written, started or verified as running.
        ValueError: The PID, timeout or a path is invalid.
    """

    if not frozen:
        raise InstallerUnavailable(
            "Automatic updates are only available in the installed app."
        )
    if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 0xFFFFFFFF:
        raise ValueError("pid must be a positive 32-bit integer")
    if (
        isinstance(start_timeout, bool)
        or not isinstance(start_timeout, (int, float))
        or start_timeout < 0
    ):
        raise ValueError("start_timeout must be a non-negative number")

    installer_path = _checked_path(installer, "installer")
    app_path = _checked_path(app_exe, "app")
    if not installer_path.is_file():
        raise UpdateError("The downloaded installer is missing.")
    if not app_path.is_file():
        raise UpdateError("The app executable is missing.")

    script_path = _write_script(installer_path, app_path, pid)
    if _is_unc_path(script_path.parent):
        # ``cmd.exe`` cannot use a UNC working directory; it falls back to the
        # Windows directory and cannot find the basename script. Refuse while
        # the app is still running.
        _remove_file(script_path)
        raise UpdateError("The update helper cannot run from a network folder.")

    # ``cmd.exe /c`` reparses its command line. Pass only the generated
    # basename and set the parent as cwd so a temp directory containing ``&``
    # or ``|`` cannot become a second command.
    command = ["cmd.exe", "/d", "/c", script_path.name]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    start = launcher if launcher is not None else subprocess.Popen
    try:
        start(
            command,
            creationflags=creationflags,
            cwd=str(script_path.parent),
        )
    except Exception as error:  # noqa: BLE001 - surfaced as an update failure
        _remove_start_markers(script_path)
        _remove_file(script_path)
        raise UpdateError("The update helper could not be started.") from error

    _wait_for_start_marker(script_path, float(start_timeout))
    return script_path


def _checked_path(value: str | os.PathLike[str], role: str) -> Path:
    """Return a path that can be quoted safely in a batch file."""

    try:
        path = Path(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"the {role} path is invalid") from error
    text = str(path)
    if not text:
        raise ValueError(f"the {role} path is empty")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        raise ValueError(f"the {role} path contains a control character")
    if '"' in text:
        raise ValueError(f"the {role} path contains a double quote")
    return path


def _write_script(installer: Path, app_exe: Path, pid: int) -> Path:
    """Create a unique UTF-8 (no BOM) helper script in the temp folder."""

    text = _SCRIPT_TEMPLATE.format(
        pid=pid,
        installer=_quote(str(installer)),
        app_exe=_quote(str(app_exe)),
        switches=" ".join(INSTALLER_SWITCHES),
    )
    descriptor, name = _make_script_file()
    script_path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.replace("\n", "\r\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        _remove_file(script_path)
        raise UpdateError("The update helper could not be written.") from error
    return script_path


def _is_unc_path(path: Path) -> bool:
    """True for a network share or an extended UNC path."""

    text = str(path)
    if text.startswith("\\\\?\\"):
        return text[4:].upper().startswith("UNC\\")
    return text.startswith(("\\\\", "//"))


def _start_marker(script_path: Path) -> Path:
    return script_path.with_suffix(".started")


def _cancel_marker(script_path: Path) -> Path:
    return script_path.with_suffix(".cancel")


def _wait_for_start_marker(script_path: Path, timeout: float) -> None:
    """Wait for the helper's handshake; on timeout leave a cancel marker."""

    started = _start_marker(script_path)
    deadline = time.monotonic() + timeout
    while True:
        if started.is_file():
            _remove_file(started)
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))

    # Re-check once: the marker may have appeared while the loop was exiting.
    if started.is_file():
        _remove_file(started)
        return

    try:
        _cancel_marker(script_path).write_text("cancelled\n", encoding="utf-8")
    except OSError:
        pass
    raise UpdateError("The update helper did not start in time.")


def _remove_start_markers(script_path: Path) -> None:
    for suffix in (".started", ".cancel", ".tasklist"):
        _remove_file(script_path.with_suffix(suffix))


def _make_script_file() -> tuple[int, str]:
    try:
        return tempfile.mkstemp(
            prefix="cleanyourmail-update-",
            suffix=".cmd",
            text=False,
        )
    except OSError as error:
        raise UpdateError("The update helper could not be written.") from error


def _quote(value: str) -> str:
    """Quote one literal path and neutralise batch percent expansion."""

    return f'"{value.replace("%", "%%")}"'


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


__all__ = [
    "DEFAULT_START_TIMEOUT_SECONDS",
    "INSTALLER_SWITCHES",
    "InstallerUnavailable",
    "install_update",
]
