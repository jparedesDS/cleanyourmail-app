"""The only bridge to the frozen CleanYourMail CLI sidecar.

The app never implements IMAP, planning or moves: it runs ``cym-cli.exe``
(CleanYourMail 1.2.2, pinned) and reads its JSON. Two rules hold everywhere in
this module:

- No secret is passed in ``argv``. The app writes app passwords to the sidecar's
  ``password_file`` itself; the sidecar owns the Outlook refresh token.
- Nothing here logs arguments, stdout or stderr. Callers get them back as data
  and decide what to show.

``run`` always appends ``--json`` (plus ``--config <path>`` when given) and never
raises for a non-zero sidecar exit: a failed command is a result with
``ok=False`` and the sidecar's message. ``CliError`` is reserved for a sidecar
that cannot be started or does not answer at all.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cleanyourmail_app.domain.models import CATEGORIES, MODES

SIDECAR_ENV = "CYM_CLI"
SIDECAR_DIR = Path("resources") / "cli"
SIDECAR_NAMES = ("cym-cli.exe", "cym-cli")

#: A header scan of a year's mail can take minutes on a large mailbox. The
#: page always runs it off the UI thread, so a generous ceiling is safe.
SCAN_TIMEOUT = 900


class CliError(RuntimeError):
    """The sidecar is missing, cannot be started or did not answer."""


def find_sidecar(app_root: Path, explicit: str | None = None) -> Path | None:
    """Locate the sidecar: ``explicit``, then ``CYM_CLI``, then the bundled exe.

    A candidate that does not exist is skipped, so a stale ``CYM_CLI`` still
    falls back to the copy shipped next to the app. Returns ``None`` when no
    sidecar is available.
    """
    candidates: list[Path] = []
    for value in (explicit, os.environ.get(SIDECAR_ENV)):
        if value:
            candidates.append(Path(os.path.expanduser(value)))
    candidates.extend(Path(app_root) / SIDECAR_DIR / name for name in SIDECAR_NAMES)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _parse_json(text: str) -> dict[str, Any]:
    """Return the last JSON object in the output, or ``{}`` when there is none.

    The sidecar prints one object for ``--json``; older builds may add a
    progress line, so plain parsing is tried first and then a line scan.
    """
    text = text.lstrip("\ufeff").strip()
    if not text:
        return {}
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
    return parsed if isinstance(parsed, dict) else {}


def _positive(value: object, name: str) -> int:
    """A whole number of at least one, or ``ValueError`` for a bad call."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


class CliClient:
    """Run one sidecar executable and normalize its JSON contract."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
        if not command:
            raise ValueError("CliClient needs a command")
        self.command = [str(part) for part in command]
        # The sidecar inherits the user's environment (its own ``password_env``
        # and OAuth store settings live there); ``env`` only overrides values.
        self.env = dict(os.environ)
        if env:
            self.env.update({str(key): str(value) for key, value in env.items()})

    def run(
        self,
        args: list[str],
        *,
        config_path: Path | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        """Run ``args`` on the sidecar and return ``{ok, exit_code, data, stdout, stderr}``."""
        argv = [*self.command, *args, "--json"]
        if config_path is not None:
            argv.extend(["--config", str(config_path)])

        completed = self._execute(argv, timeout)
        data = _parse_json(completed.stdout)
        return {
            "ok": completed.returncode == 0 and data.get("ok", True) is not False,
            "exit_code": completed.returncode,
            "data": data,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    # -- typed helpers ------------------------------------------------------
    #
    # The wizard never builds argv itself. These three helpers mirror the
    # frozen 1.2.2 commands and keep the ``--json`` flag in one place; each
    # returns the same ``{ok, exit_code, data, stdout, stderr}`` shape as
    # ``run`` and never raises for a failed command.

    def scan(
        self,
        days: int,
        *,
        config_path: Path | None = None,
        timeout: int = SCAN_TIMEOUT,
    ) -> dict[str, Any]:
        """Cache headers from the last ``days`` days (read-only)."""
        return self.run(
            ["scan", "--days", str(_positive(days, "days"))],
            config_path=config_path,
            timeout=timeout,
        )

    def report(
        self,
        top: int = 30,
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        """Summarize the cache: categories, totals and sender groups."""
        return self.run(
            ["report", "--top", str(_positive(top, "top"))],
            config_path=config_path,
        )

    def plan(
        self,
        mode: str,
        categories: Iterable[str] = CATEGORIES,
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        """Write ``plan.json`` from the cache without changing any message.

        ``mode`` is ``folders`` (the reversible move) or ``archive`` (Gmail's
        Inbox label). Every accepted category becomes one ``--category`` flag;
        duplicates are dropped so the sidecar sees each class once.
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of: {', '.join(MODES)}")
        selected: list[str] = []
        for category in categories:
            if category not in CATEGORIES:
                raise ValueError(f"categories must be a subset of: {', '.join(CATEGORIES)}")
            if category not in selected:
                selected.append(category)

        args = ["plan", "--mode", mode]
        for category in selected:
            args.extend(["--category", category])
        return self.run(args, config_path=config_path)

    def version(self) -> str:
        """Return the sidecar's version line, e.g. ``CleanYourMail 1.2.2``."""
        completed = self._execute([*self.command, "--version"], 30)
        text = completed.stdout.lstrip("\ufeff").strip()
        if completed.returncode != 0 or not text:
            detail = (completed.stderr or completed.stdout).strip() or "no output"
            raise CliError(f"Cannot read the CleanYourMail version: {detail}")
        return text.splitlines()[0].strip()

    def _execute(self, argv: list[str], timeout: int) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=self.env,
                **_spawn_flags(),
            )
        except subprocess.TimeoutExpired as exc:
            raise CliError(
                f"The CleanYourMail sidecar did not answer within {timeout} seconds."
            ) from exc
        except FileNotFoundError as exc:
            raise CliError(
                f"Cannot start the CleanYourMail sidecar: {self.command[0]}"
            ) from exc
        except OSError as exc:
            raise CliError(f"Cannot start the CleanYourMail sidecar: {exc}") from exc


def _spawn_flags() -> dict[str, Any]:
    """Hide the console window a sidecar would otherwise flash on Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
