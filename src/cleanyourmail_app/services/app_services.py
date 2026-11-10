"""The services one running app shares across every wizard page.

The window owns one of these instead of building a CLI client, a config writer
and a settings store per page. Keeping them in one dataclass also makes the
dependency explicit: a page receives exactly what it may use, and tests pass
temporary paths without touching the user profile.

No secret is part of this object. The app password lives in the sidecar's
``password_file`` and is written by ``services.secrets``.
"""

from __future__ import annotations

from dataclasses import dataclass

from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.cli import CliClient
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.services.settings import SettingsStore


@dataclass
class AppServices:
    """Everything the wizard needs to talk to the sidecar and local state."""

    cli: CliClient
    config: ConfigService
    settings: SettingsStore
    translator: Translator
