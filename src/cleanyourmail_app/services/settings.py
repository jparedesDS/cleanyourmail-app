"""Local, non-secret application settings.

The store is one JSON file in ``%APPDATA%\\cleanyourmail-app\\settings.json``.
It holds the chosen provider, the email address, ``Preferences`` and the time
of the last automatic update check only: never a password, token or refresh
token. The app passwords and the Outlook refresh token belong to the sidecar
(see ``services/cli.py``).

Writes are atomic: the new JSON is written to a temporary file next to the
target, flushed to disk, then ``os.replace``d over it. A crash therefore leaves
either the old file or the new one, never a truncated settings file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from cleanyourmail_app.domain.models import AppSettings, Preferences

APP_DIR_NAME = "cleanyourmail-app"
SETTINGS_FILENAME = "settings.json"


def default_settings_path() -> Path:
    """``%APPDATA%/cleanyourmail-app/settings.json``.

    ``%APPDATA%`` is always set on Windows; the home-directory fallback keeps
    tests and development on other systems working.
    """
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / APP_DIR_NAME / SETTINGS_FILENAME


class SettingsStore:
    """Read and write ``AppSettings`` as one small JSON file.

    ``path`` is injectable so tests never touch the real user profile.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self) -> AppSettings:
        """Return the stored settings, or safe defaults when there are none.

        A missing, unreadable, corrupt or outdated file is not fatal: the wizard
        opens on the first page with defaults instead of crashing.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return _defaults()

        try:
            payload: Any = json.loads(text.lstrip("\ufeff"))
        except ValueError:
            return _defaults()

        try:
            return AppSettings.from_dict(payload)
        except (TypeError, ValueError):
            return _defaults()

    def save(self, settings: AppSettings) -> None:
        """Write ``settings`` atomically, creating the directory if needed."""
        if not isinstance(settings, AppSettings):
            raise TypeError("save() needs an AppSettings value")

        text = json.dumps(
            settings.to_dict(),
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ) + "\n"

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def load_preferences(self) -> Preferences:
        """Convenience for pages that only care about the checkboxes."""
        return self.load().preferences

    def update_preferences(self, preferences: Preferences) -> None:
        """Replace the preferences, leaving the other stored fields untouched."""
        if not isinstance(preferences, Preferences):
            raise TypeError("update_preferences() needs a Preferences value")
        current = self.load()
        self.save(
            AppSettings(
                provider=current.provider,
                email=current.email,
                preferences=preferences,
                last_update_check=current.last_update_check,
            )
        )


def _defaults() -> AppSettings:
    return AppSettings(provider="custom", email="")
