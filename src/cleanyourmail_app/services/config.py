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
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from cleanyourmail_app.domain.models import Preferences
from cleanyourmail_app.domain.providers import Provider
from cleanyourmail_app.services.cli import CliClient

CONFIG_FILENAME = "cleanyourmail.toml"
OUTLOOK_HOST = "outlook.office365.com"

#: Proton Bridge's sidecar preset. ``ensure`` leaves the host out of ``init``
#: so the 1143/STARTTLS preset survives, but the existing-config check still
#: knows which host this provider must have.
PROTON_HOST = "127.0.0.1"

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


class ConfigMismatchError(ConfigServiceError):
    """The existing TOML belongs to another account or IMAP host.

    The app must never write this account's secret into the previous account's
    ``password_file``. The caller can either stop or explicitly replace the
    connection with ``ensure(..., replace=True)``.
    """

    def __init__(
        self,
        message: str,
        *,
        existing_email: str = "",
        existing_host: str = "",
    ) -> None:
        super().__init__(message)
        self.existing_email = existing_email
        self.existing_host = existing_host


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

    def ensure(
        self,
        provider: Provider,
        email: str,
        host: str | None = None,
        port: int = 993,
        ssl: bool = True,
        replace: bool = False,
    ) -> Path:
        """Create the config through ``init`` once; keep any existing file.

        A second call for the same account returns the same path without
        running the sidecar, so a config edited by the CLI (or by a later app
        build) is never clobbered. A file that belongs to another email or IMAP
        host raises ``ConfigMismatchError`` unless ``replace`` is true; writing
        a secret into another account's ``password_file`` would be unsafe.

        ``host`` is for Custom IMAP, where the sidecar has no preset and its
        template default is ``imap.example.com``. Known domains already get a
        preset from the sidecar (Gmail, Yahoo, iCloud, Fastmail and Proton,
        including Proton's 1143/STARTTLS); passing an explicit host there
        replaces that preset with the 993/TLS template, so callers should only
        pass one when there is no preset to protect.

        ``port`` and ``ssl`` exist so a page can state what it wants, but the
        pinned sidecar's ``init`` has no flag for them: the template default is
        993/TLS (a provider preset such as Proton's may differ), so any other
        requested value is rejected instead of being silently ignored.

        ``replace`` maps to ``init --force``: it is only used after the person
        explicitly confirms replacing a different existing connection.
        """
        if not isinstance(provider, Provider):
            raise TypeError("ensure() needs a Provider value")
        cleaned = email.strip() if isinstance(email, str) else ""
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("ensure() needs a valid email address")

        cleaned_host = _clean_host(host)
        if provider.id == "custom" and cleaned_host is None:
            raise ValueError("ensure() needs a host for a custom IMAP provider")
        _require_supported_tls(port, ssl)

        path = self.config_path()
        if path.is_dir():
            raise ConfigServiceError(f"The config path is a directory: {path}")
        if path.exists() and not replace:
            self._require_same_account(path, cleaned, provider, cleaned_host)
            return path

        args = ["init", "--email", cleaned]
        if provider.id == "outlook":
            args.extend(["--host", OUTLOOK_HOST, "--auth", "xoauth2"])
        elif cleaned_host is not None:
            args.extend(["--host", cleaned_host])
        args.extend(["--path", str(path), "--secret-file", str(self.secret_path)])
        if replace:
            args.append("--force")

        result = self.cli.run(args)
        if not result.get("ok"):
            raise ConfigServiceError(f"Cannot create {path}: {_detail(result)}")
        if not path.is_file():
            raise ConfigServiceError(
                f"The sidecar reported success but did not write {path}."
            )
        return path

    def _require_same_account(
        self,
        path: Path,
        email: str,
        provider: Provider,
        requested_host: str | None,
    ) -> None:
        """Raise ``ConfigMismatchError`` when the TOML is another connection."""
        existing = self._read_account(path)
        existing_email = existing.get("existing_email", "")
        existing_host = existing.get("existing_host", "")

        same_email = existing_email.strip().lower() == email.strip().lower()
        if provider.id == "outlook":
            wanted_host: str | None = OUTLOOK_HOST
        elif provider.id == "proton":
            wanted_host = PROTON_HOST
        else:
            wanted_host = requested_host
        same_host = (
            wanted_host is None
            or existing_host.strip().lower() == wanted_host.strip().lower()
        )
        if same_email and same_host:
            return

        reason = "another account" if not same_email else "another IMAP server"
        raise ConfigMismatchError(
            f"{path} belongs to {reason} ({existing_email or 'unknown'}).",
            existing_email=existing_email,
            existing_host=existing_host,
        )

    @staticmethod
    def _read_account(path: Path) -> dict[str, str]:
        """The account email/host from an existing TOML, best-effort."""
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError, UnicodeError) as exc:
            raise ConfigServiceError(f"Cannot read {path}: {exc}") from exc
        account = data.get("account")
        if not isinstance(account, dict):
            raise ConfigServiceError(f"{path} has no [account] table.")
        return {
            "existing_email": str(account.get("email") or ""),
            "existing_host": str(account.get("imap_host") or ""),
        }

    def password_file(self) -> Path:
        """The ``password_file`` the existing TOML names.

        Falls back to ``secret_path`` when the config is missing or has no
        usable value. ``~`` is expanded. The pinned sidecar resolves a relative
        ``password_file`` against its current working directory, which it
        inherits from this app, so the app resolves it the same way instead of
        guessing a path next to the config.
        """
        try:
            with self.config_path().open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError, UnicodeError):
            return self.secret_path
        account = data.get("account")
        if not isinstance(account, dict):
            return self.secret_path
        value = account.get("password_file")
        if not isinstance(value, str) or not value.strip():
            return self.secret_path
        candidate = Path(os.path.expanduser(value.strip()))
        if not candidate.is_absolute():
            # Match the pinned sidecar: ``resolve_secret`` reads the path as
            # given, so a relative value is relative to the shared process cwd.
            candidate = Path.cwd() / candidate
        return candidate

    def state_dir(self) -> Path:
        """The CLI state folder this config uses, without reading the cache.

        Precedence: the top-level ``state_dir`` key the pinned CLI accepts,
        then ``CYM_STATE_DIR``, then the per-user default
        (``%LOCALAPPDATA%\\CleanYourMail`` on Windows). ``[account] state_dir``
        is not a CLI key and is deliberately ignored.
        """
        try:
            with self.config_path().open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError, UnicodeError):
            data = {}
        value = data.get("state_dir")
        if isinstance(value, str) and value.strip():
            return _resolve_state_path(value.strip(), Path.cwd())

        override = os.environ.get("CYM_STATE_DIR", "").strip()
        if override:
            return _resolve_state_path(override, Path.cwd())

        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA", "")
            root = Path(os.path.expanduser(base)) if base else (
                Path.home() / "AppData" / "Local"
            )
            return root / "CleanYourMail"

        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "CleanYourMail"
        base = os.environ.get("XDG_STATE_HOME", "").strip()
        root = Path(os.path.expanduser(base)) if base else (
            Path.home() / ".local" / "state"
        )
        return root / "cleanyourmail"

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


def _resolve_state_path(value: str, base: Path) -> Path:
    """Expand ``~``/environment variables and resolve against ``base``."""
    candidate = Path(os.path.expanduser(os.path.expandvars(value)))
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate


def _clean_host(host: str | None) -> str | None:
    """A usable IMAP host name, or ``None`` when the caller passed nothing.

    ``init --host`` takes a bare host: a value with whitespace or a URL scheme
    would become a broken TOML entry, so it is rejected rather than trimmed
    into something surprising.
    """
    if host is None:
        return None
    if not isinstance(host, str):
        raise ValueError("ensure() needs the IMAP host as text")
    cleaned = host.strip()
    if not cleaned:
        return None
    if any(character.isspace() for character in cleaned):
        raise ValueError("ensure() needs a host name without spaces")
    if "://" in cleaned:
        raise ValueError("ensure() needs a bare host name, not a URL")
    return cleaned


def _require_supported_tls(port: int, ssl: bool) -> None:
    """Reject a port/TLS pair the pinned sidecar cannot write."""
    try:
        wanted_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ConfigServiceError(
            "The sidecar's init has no --port flag; CleanYourMail writes port 993."
        ) from exc
    if wanted_port != 993:
        raise ConfigServiceError(
            "The sidecar's init has no --port flag; CleanYourMail writes port 993 "
            "with TLS. A different port needs a later sidecar release."
        )
    if ssl is not True:
        raise ConfigServiceError(
            "The sidecar's init has no --ssl flag; CleanYourMail writes TLS on "
            "port 993. Plain-text IMAP needs a later sidecar release."
        )


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
