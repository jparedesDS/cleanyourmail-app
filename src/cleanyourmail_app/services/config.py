"""Create the sidecar's TOML and edit only the preferences it owns.

The CLI stays the single source of truth: ``ensure`` asks it for a config with
``init`` and never writes TOML from scratch. ``update_preferences`` then edits
the known ``[scan]``/``[policy]`` lines in place, preserving comments, the
account block and every unrelated section. ``validate`` returns the sidecar's
JSON so a page can show what the CLI thinks of its own config.

No secret lives here. The config only names the ``password_file``; the value is
written by ``services.secrets``.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from cleanyourmail_app.domain.models import Preferences
from cleanyourmail_app.domain.providers import Provider
from cleanyourmail_app.services.cli import CliClient

CONFIG_FILENAME = "cleanyourmail.toml"
OUTLOOK_HOST = "outlook.office365.com"

#: How far back the app asks the CLI to scan. This is the sidecar template's
#: default (one year); the wizard has no scan-window control, so the app owns
#: the value instead of exposing another knob.
SCAN_DAYS = 365

_SECTION_RE = re.compile(r"^[ \t]*\[(?P<name>[^\]\r\n]+)\][ \t]*(?:#.*)?$")
_ASSIGNMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z0-9_-]+)(?P<gap>[ \t]*=[ \t]*)(?P<value>.*)$"
)


class ConfigServiceError(RuntimeError):
    """The sidecar could not create, read or validate the config."""


def default_secret_path() -> Path:
    """``%USERPROFILE%/.secrets/cleanyourmail.txt``, the sidecar's default."""
    return Path.home() / ".secrets" / "cleanyourmail.txt"


class ConfigService:
    """Own the config path and the few values the app is allowed to change.

    ``app_data`` and ``secret_path`` are injectable so tests never touch the
    real profile or repository.
    """

    def __init__(
        self,
        cli: CliClient,
        app_data: str | os.PathLike[str],
        secret_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.cli = cli
        self.app_data = Path(app_data)
        self.secret_path = (
            Path(secret_path) if secret_path is not None else default_secret_path()
        )

    def config_path(self) -> Path:
        """The TOML path under the app-data directory."""
        return self.app_data / CONFIG_FILENAME

    def ensure(self, provider: Provider, email: str) -> Path:
        """Create the config through ``init`` once; keep any existing file.

        A second call returns the same path without running the sidecar, so a
        config edited by the CLI (or by a later app build) is never clobbered.
        """
        if not isinstance(provider, Provider):
            raise TypeError("ensure() needs a Provider value")
        cleaned = email.strip() if isinstance(email, str) else ""
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("ensure() needs a valid email address")

        path = self.config_path()
        if path.is_dir():
            raise ConfigServiceError(f"The config path is a directory: {path}")
        if path.exists():
            return path

        args = ["init", "--email", cleaned]
        if provider.id == "outlook":
            args.extend(["--host", OUTLOOK_HOST, "--auth", "xoauth2"])
        args.extend(["--path", str(path), "--secret-file", str(self.secret_path)])

        result = self.cli.run(args)
        if not result.get("ok"):
            raise ConfigServiceError(f"Cannot create {path}: {_detail(result)}")
        if not path.is_file():
            raise ConfigServiceError(
                f"The sidecar reported success but did not write {path}."
            )
        return path

    def update_preferences(self, preferences: Preferences) -> None:
        """Write the chosen policy into the existing TOML, line by line."""
        if not isinstance(preferences, Preferences):
            raise TypeError("update_preferences() needs a Preferences value")

        path = self.config_path()
        if not path.is_file():
            raise ConfigServiceError(
                f"There is no config at {path}; connect an account first."
            )

        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ConfigServiceError(f"Cannot read {path}: {exc}") from exc

        updated = _edit_config(text, preferences, path)
        _write_text_atomically(path, updated)

    def validate(self) -> dict[str, Any]:
        """Run the sidecar ``validate`` and return its JSON.

        Success returns the sidecar object untouched. A failure without JSON
        gets ``ok=False`` plus a readable ``error`` so the caller never has to
        parse stderr itself.
        """
        result = self.cli.run(["validate"], config_path=self.config_path())
        data = dict(result.get("data") or {})
        if not result.get("ok"):
            data.setdefault("ok", False)
            data.setdefault("error", _detail(result))
        return data


def _detail(result: dict[str, Any]) -> str:
    """A short, single-line reason from a failed sidecar result."""
    for key in ("stderr", "stdout"):
        text = result.get(key) or ""
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        if lines:
            return lines[-1][:500]
    return "the sidecar reported an error"


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _split_comment(value: str) -> tuple[str, str]:
    """Split a TOML value from a trailing comment, keeping the spacing."""
    index = value.find("#")
    if index < 0:
        return value.rstrip(), ""
    before = value[:index]
    spacing = before[len(before.rstrip()):]
    return before.rstrip(), spacing + value[index:]


def _edit_config(text: str, preferences: Preferences, path: Path) -> str:
    """Replace the known keys, keeping every other byte of the file.

    ``protect_starred`` maps to the sidecar's ``protect_flagged`` (IMAP's
    ``\\Flagged`` is what Gmail shows as a star) and ``max_moves`` maps to
    ``max_messages_per_run``. A missing key is an error: silently adding it
    would hide a config the app does not understand.
    """
    updates: dict[tuple[str, str], str] = {
        ("scan", "days"): str(SCAN_DAYS),
        ("policy", "min_age_days"): str(preferences.min_age_days),
        ("policy", "protect_answered"): _toml_bool(preferences.protect_answered),
        ("policy", "protect_flagged"): _toml_bool(preferences.protect_starred),
        ("policy", "max_messages_per_run"): str(preferences.max_moves),
        ("policy", "max_messages_per_group"): str(preferences.max_per_group),
    }

    found: set[tuple[str, str]] = set()
    section: str | None = None
    output: list[str] = []

    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        eol = line[len(body):]

        header = _SECTION_RE.match(body)
        if header:
            section = header.group("name").strip()
            output.append(line)
            continue

        assignment = _ASSIGNMENT_RE.match(body)
        if assignment and section is not None:
            key = assignment.group("key")
            wanted = updates.get((section, key))
            if wanted is not None:
                value, comment = _split_comment(assignment.group("value"))
                line = (
                    f"{assignment.group('indent')}{key}{assignment.group('gap')}"
                    f"{wanted}{comment}{eol}"
                )
                found.add((section, key))

        output.append(line)

    missing = [
        f"[{section_name}] {key}"
        for section_name, key in updates
        if (section_name, key) not in found
    ]
    if missing:
        joined = ", ".join(missing)
        raise ConfigServiceError(
            f"{path} is missing the keys the app writes: {joined}."
        )

    return "".join(output)


def _write_text_atomically(path: Path, text: str) -> None:
    """Write ``text`` next to ``path`` and replace the target in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
