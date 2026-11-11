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
name cannot inject a batch variable. No log line ever includes account data.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
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

_SCRIPT_TEMPLATE = """@echo off
setlocal
chcp 65001 >nul
:wait_for_exit
tasklist /FI "PID eq {pid}" /NH | find "{pid}" >nul
if not errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto wait_for_exit
)
start "" /wait {installer} {switches}
set "CYM_EXITCODE=%ERRORLEVEL%"
if "%CYM_EXITCODE%"=="0" del /f /q {installer} >nul 2>&1
start "" {app_exe}
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
    frozen: bool = True,
) -> Path:
    """Write and start the temporary installer helper; return its script path.

    Args:
        installer: The downloaded, already verified installer executable.
        app_exe: The executable to start after the installer finishes.
        pid: The running app's process id; the helper waits for it to exit.
        launcher: Injection point for tests. Defaults to ``subprocess.Popen``.
        frozen: Must be true. An unpackaged development app must never replace
            itself, so this raises :class:`InstallerUnavailable` when false.

    Raises:
        InstallerUnavailable: The app is not frozen (not an installed build).
        UpdateError: A path is missing or the helper cannot be written/started.
        ValueError: The PID is invalid or a path contains control characters,
            newlines or a double quote, which cannot be safely quoted.
    """

    if not frozen:
        raise InstallerUnavailable(
            "Automatic updates are only available in the installed app."
        )
    if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 0xFFFFFFFF:
        raise ValueError("pid must be a positive 32-bit integer")

    installer_path = _checked_path(installer, "installer")
    app_path = _checked_path(app_exe, "app")
    if not installer_path.is_file():
        raise UpdateError("The downloaded installer is missing.")
    if not app_path.is_file():
        raise UpdateError("The app executable is missing.")

    script_path = _write_script(installer_path, app_path, pid)
    command = ["cmd.exe", "/c", str(script_path)]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    start = launcher if launcher is not None else subprocess.Popen
    try:
        start(command, creationflags=creationflags)
    except Exception as error:  # noqa: BLE001 - surfaced as an update failure
        _remove_file(script_path)
        raise UpdateError("The update helper could not be started.") from error
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


__all__ = ["INSTALLER_SWITCHES", "InstallerUnavailable", "install_update"]
