"""Application entry point: build the local services and show the wizard.

Qt is imported inside :func:`main` so ``python -m cleanyourmail_app --version``
and the pure service tests never pay for loading the GUI stack. Nothing here
touches the network, and no secret is read or passed: the sidecar owns the
account credentials.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.cli import (
    SIDECAR_DIR,
    SIDECAR_NAMES,
    CliClient,
    find_sidecar,
)
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.services.installer import install_update
from cleanyourmail_app.services.settings import SettingsStore, default_settings_path
from cleanyourmail_app.services.updates import check_for_update, download_update
from cleanyourmail_app.version import __version__

APP_NAME = "CleanYourMail"


def app_root() -> Path:
    """Where bundled resources live: ``sys._MEIPASS`` when frozen, else repo."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parents[2]


def app_data_path() -> Path:
    """``%APPDATA%/cleanyourmail-app`` — the config and settings folder."""
    return default_settings_path().parent


def sidecar_command(root: Path) -> list[str]:
    """Use a found sidecar; otherwise name the path we expected, for the error."""
    found = find_sidecar(root)
    if found is not None:
        return [str(found)]
    return [str(root / SIDECAR_DIR / SIDECAR_NAMES[0])]


def build_services(settings: SettingsStore, translator: Translator) -> AppServices:
    """Wire the sidecar client, config writer, settings store and translator."""
    cli = CliClient(sidecar_command(app_root()))
    config = ConfigService(cli, app_data_path())
    return AppServices(cli=cli, config=config, settings=settings, translator=translator)


def install_downloaded_update(installer: str | os.PathLike[str]) -> Path:
    """Adapter for the window: install the verified file for this process."""
    return install_update(
        Path(installer),
        Path(sys.executable),
        os.getpid(),
        frozen=getattr(sys, "frozen", False),
    )


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from cleanyourmail_app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)

    settings = SettingsStore()
    stored = settings.load()
    # The translator loads both catalogs eagerly; a packaging error surfaces
    # here at startup rather than halfway through the wizard.
    translator = Translator(stored.preferences.language)
    services = build_services(settings, translator)

    window = MainWindow(
        settings,
        translator,
        services,
        update_checker=check_for_update,
        update_downloader=download_update,
        update_installer=install_downloaded_update,
    )
    window.show()
    return app.exec()
