"""Locate and call the CleanYourMail CLI. The CLI remains the source of truth."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class CliError(RuntimeError):
    pass


def _candidate(path: str | os.PathLike[str]) -> Path | None:
    raw = Path(path).expanduser()
    if raw.is_dir():
        raw = raw / "tools" / "mail.py"
    try:
        resolved = raw.resolve()
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def find_cli(explicit: str | None = None, app_root: Path | None = None) -> Path | None:
    app_root = app_root or Path(__file__).resolve().parents[1]
    candidates: list[str | os.PathLike[str]] = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("CYM_CLI")
    if env:
        candidates.append(env)
    candidates.extend([
        app_root.parent / "cleanyourmail" / "tools" / "mail.py",
        app_root.parent / "clean-your-mail" / "tools" / "mail.py",
        app_root / "cleanyourmail" / "tools" / "mail.py",
        app_root / "vendor" / "cleanyourmail" / "tools" / "mail.py",
    ])
    for candidate in candidates:
        found = _candidate(candidate)
        if found is not None:
            return found
    return None


def run(
    command: list[str],
    *,
    cli_path: Path,
    config_path: Path,
    password: str | None = None,
    timeout: int = 120,
    require_config: bool = True,
) -> dict[str, Any]:
    if not cli_path.is_file():
        raise CliError("CleanYourMail CLI not found. Set the path to tools/mail.py.")
    config_path = config_path.expanduser()
    if require_config and not config_path.is_file():
        raise CliError(f"Config file not found: {config_path}")
    cmd = [
        sys.executable,
        str(cli_path),
        *command,
        "--config",
        str(config_path),
        "--json",
    ]
    env = os.environ.copy()
    if password:
        env["CYM_PASSWORD"] = password
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cli_path.parent.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CliError(f"The CLI timed out after {timeout}s.") from error
    except OSError as error:
        raise CliError(f"Could not start the CLI: {error}") from error

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    payload: Any = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except ValueError:
            payload = None
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "data": payload,
        "stdout": stdout[:6000] if payload is None else "",
        "stderr": stderr[:4000],
    }
