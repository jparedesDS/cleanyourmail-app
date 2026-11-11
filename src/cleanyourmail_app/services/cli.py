"""The only bridge to the frozen CleanYourMail CLI sidecar.

The app never implements IMAP, planning or moves: it runs ``cym-cli.exe``
(CleanYourMail 1.3.0, pinned) and reads its JSON. Two rules hold everywhere in
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
import re
import subprocess
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cleanyourmail_app.domain.models import CATEGORIES, MODES

SIDECAR_ENV = "CYM_CLI"
SIDECAR_DIR = Path("resources") / "cli"
SIDECAR_NAMES = ("cym-cli.exe", "cym-cli")

#: A local ``--version`` must answer almost instantly. A hung sidecar must not
#: freeze the header for the generic 30-second command ceiling.
VERSION_TIMEOUT = 5

#: The sidecar the app is built and tested against. A different version may
#: change the JSON contract or the safety rules, so the app verifies this
#: before it writes a config or asks for mail changes.
EXPECTED_CLI_VERSION = "CleanYourMail 1.3.0"

#: A header scan of a year's mail can take minutes on a large mailbox. The
#: page always runs it off the UI thread, so a generous ceiling is safe.
SCAN_TIMEOUT = 900

#: An apply may move thousands of messages (``max_moves`` can reach 5000), so
#: the generic two-minute ceiling is too short. A timeout means the outcome is
#: unknown: the page closes the gate rather than assuming nothing moved.
APPLY_TIMEOUT = 1800

#: Undo verifies every message identity before moving it back, which is slower
#: than the summary calls but bounded by the run being restored.
UNDO_TIMEOUT = 900


class CliError(RuntimeError):
    """The sidecar is missing, cannot be started or did not answer."""


class CliVersionMismatch(CliError):
    """The sidecar answered, but not with the pinned 1.3.0 contract."""


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


#: A journal run id is opaque, but it is one argv word: letters, digits and a
#: small punctuation set. Rejecting spaces and a leading dash keeps a value from
#: turning into an option the sidecar would parse instead of an id.
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _plan_path(value: object) -> str:
    """A non-empty plan path as one argv word, or ``ValueError``."""
    if isinstance(value, (str, os.PathLike)) and not isinstance(value, bytes):
        text = os.fspath(value)
    else:
        raise ValueError("plan_path must be a path")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("plan_path must not be empty")
    return text


def _run(value: object) -> str:
    """A journal run id that cannot be mistaken for a flag."""
    if not isinstance(value, str) or not _RUN_ID.fullmatch(value.strip()):
        raise ValueError("run must be a journal run id")
    return value.strip()


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
        #: A verified version line; success is cached so the wizard runs
        #: ``--version`` once, while a failure is retried on the next save.
        self._verified_version: str | None = None

    def run(
        self,
        args: list[str],
        *,
        config_path: Path | None = None,
        timeout: int = 120,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Run ``args`` on the sidecar and return ``{ok, exit_code, data, stdout, stderr}``.

        Without ``cancel_event`` the existing ``subprocess.run`` path is used
        unchanged. With an event, the child is polled every 200 ms; setting the
        event terminates it (and kills it after a short grace) and returns
        ``{ok: False, cancelled: True, exit_code: -1}`` instead of pretending
        the command failed on its own.
        """
        argv = [*self.command, *args, "--json"]
        if config_path is not None:
            argv.extend(["--config", str(config_path)])

        if cancel_event is None:
            completed = self._execute(argv, timeout)
            return self._normalize(completed.returncode, completed.stdout, completed.stderr)

        return self._run_cancellable(argv, timeout, cancel_event)

    @staticmethod
    def _normalize(
        returncode: int, stdout: str, stderr: str, *, cancelled: bool = False
    ) -> dict[str, Any]:
        data = _parse_json(stdout)
        result: dict[str, Any] = {
            "ok": returncode == 0 and data.get("ok", True) is not False,
            "exit_code": returncode,
            "data": data,
            "stdout": stdout,
            "stderr": stderr,
        }
        if cancelled:
            result["cancelled"] = True
        return result

    def _run_cancellable(
        self, argv: list[str], timeout: int, cancel_event: threading.Event
    ) -> dict[str, Any]:
        """Run with a poll loop so Cancel can stop the sidecar promptly."""
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.env,
                **_spawn_flags(),
            )
        except FileNotFoundError as exc:
            raise CliError(
                f"Cannot start the CleanYourMail sidecar: {self.command[0]}"
            ) from exc
        except OSError as exc:
            raise CliError(f"Cannot start the CleanYourMail sidecar: {exc}") from exc

        deadline = time.monotonic() + timeout
        while True:
            if cancel_event.is_set():
                stdout, stderr = _stop_process(process)
                return self._normalize(-1, stdout, stderr, cancelled=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise CliError(
                    f"The CleanYourMail sidecar did not answer within {timeout} seconds."
                )
            try:
                stdout, stderr = process.communicate(timeout=min(0.2, remaining))
            except subprocess.TimeoutExpired:
                continue
            return self._normalize(process.returncode, stdout, stderr)

    # -- typed helpers ------------------------------------------------------
    #
    # The wizard never builds argv itself. These helpers mirror the frozen
    # 1.3.0 commands and keep the ``--json`` flag in one place; each returns
    # the same ``{ok, exit_code, data, stdout, stderr}`` shape as ``run`` and
    # never raises for a failed command.

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

    def apply(
        self,
        plan_path: str | Path,
        limit: int,
        *,
        config_path: Path | None = None,
        timeout: int = APPLY_TIMEOUT,
    ) -> dict[str, Any]:
        """Move at most ``limit`` messages from a reviewed plan.

        ``--action move`` is always explicit: even a plan that also carries
        unsubscribe actions cannot make this call send one. ``--yes`` is the
        app's confirmation, which the page asks for before it gets here. A
        timeout is not a safe "nothing happened" signal; the caller must close
        its gate because the sidecar may already have moved messages.
        """
        return self.run(
            [
                "apply",
                _plan_path(plan_path),
                "--yes",
                "--action",
                "move",
                "--limit",
                str(_positive(limit, "limit")),
            ],
            config_path=config_path,
            timeout=timeout,
        )

    def journal(
        self,
        limit: int = 20,
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        """Read the newest ``limit`` journal runs.

        The summary carries a run id, timestamp, counts and the account; it
        never contains message ids, so no redaction is needed for the dialog.
        """
        return self.run(
            ["journal", "--limit", str(_positive(limit, "limit"))],
            config_path=config_path,
        )

    def undo(
        self,
        run: str,
        *,
        config_path: Path | None = None,
        timeout: int = UNDO_TIMEOUT,
    ) -> dict[str, Any]:
        """Ask the sidecar to restore one journal run, after its own checks."""
        return self.run(
            ["undo", "--run", _run(run), "--yes"],
            config_path=config_path,
            timeout=timeout,
        )

    def version(self) -> str:
        """Return the sidecar's version line, e.g. ``CleanYourMail 1.3.0``."""
        completed = self._execute([*self.command, "--version"], VERSION_TIMEOUT)
        text = completed.stdout.lstrip("\ufeff").strip()
        if completed.returncode != 0 or not text:
            detail = (completed.stderr or completed.stdout).strip() or "no output"
            raise CliError(f"Cannot read the CleanYourMail version: {detail}")
        return text.splitlines()[0].strip()

    @property
    def cached_version(self) -> str | None:
        """The verified version, when a connection test already read it."""
        return self._verified_version

    def verify_version(
        self, expected: str = EXPECTED_CLI_VERSION
    ) -> str:
        """Fail closed unless the sidecar is the pinned CleanYourMail build.

        A successful check is cached; a failure is raised and not cached, so a
        missing helper can be fixed and retried without restarting the app.
        """
        if self._verified_version == expected:
            return self._verified_version
        actual = self.version()
        if actual != expected:
            raise CliVersionMismatch(
                f"The CleanYourMail helper is {actual!r}; this app needs "
                f"{expected!r}. Reinstall CleanYourMail."
            )
        self._verified_version = actual
        return actual

    def print_version(self) -> str:
        """Return the raw sidecar version line for diagnostics and smoke tests."""
        return self.version()

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


def _stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Terminate a cancelled child, then kill it after a short grace period."""
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            return process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        return "", ""
