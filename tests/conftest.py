"""Shared pytest setup, including a headless Qt platform.

Qt must be told to use the offscreen platform *before* PySide6 is imported, so
the variable is set at module import time. Windows CI has no interactive
desktop session; a real platform plugin would fail there.

The fixtures below build a throw-away ``SettingsStore`` and ``AppServices`` so
no UI test reads or writes the real user profile.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.cli import CliClient
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.services.settings import SettingsStore


@pytest.fixture
def translator() -> Translator:
    return Translator("en")


@pytest.fixture
def settings_store(tmp_path) -> SettingsStore:
    return SettingsStore(tmp_path / "settings.json")


@pytest.fixture
def app_services(tmp_path, translator, settings_store) -> AppServices:
    """Services wired to temporary paths; the sidecar is never executed."""
    cli = CliClient([sys.executable, str(tmp_path / "fake-cli.py")])
    config = ConfigService(cli, tmp_path / "appdata", tmp_path / "secret.txt")
    return AppServices(
        cli=cli,
        config=config,
        settings=settings_store,
        translator=translator,
    )
