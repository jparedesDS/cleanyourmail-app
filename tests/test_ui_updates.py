"""The header Updates button, the banner and the download/install flow.

Every service is injected. The tests never touch the network, never start an
installer and never quit the real application: the checker, downloader, installer
and quit method are all fakes or monkeypatches.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from cleanyourmail_app import version
from cleanyourmail_app.domain.models import AppSettings
from cleanyourmail_app.services.installer import InstallerUnavailable
from cleanyourmail_app.services.updates import RELEASES_PAGE, UpdateError, UpdateInfo
from cleanyourmail_app.ui import main_window as main_window_module
from cleanyourmail_app.ui.main_window import MainWindow

INSTALLER_URL = (
    "https://github.com/jparedesDS/cleanyourmail-app/releases/download/"
    "v9.9.9/CleanYourMail-Setup-9.9.9.exe"
)
CHECKSUM_URL = f"{INSTALLER_URL}.sha256"


def _info(*, assets: bool = True) -> UpdateInfo:
    return UpdateInfo(
        version="9.9.9",
        tag="v9.9.9",
        installer_url=INSTALLER_URL if assets else "",
        checksum_url=CHECKSUM_URL if assets else "",
    )


def _window(
    qtbot, app_services, **kwargs: object
) -> MainWindow:
    window = MainWindow(
        app_services.settings,
        app_services.translator,
        app_services,
        **kwargs,
    )
    qtbot.addWidget(window)
    window.show()
    return window


def _wait_banner(qtbot, window: MainWindow, fragment: str = "") -> None:
    def visible() -> bool:
        return window.update_banner.isVisible() and fragment in (
            window.update_banner_label.text()
        )

    qtbot.waitUntil(visible, timeout=3000)


def test_without_a_checker_there_is_no_button_and_no_startup_check(
    qtbot, app_services, monkeypatch
):
    scheduled: list[int] = []

    class FakeTimer:
        @staticmethod
        def singleShot(milliseconds: int, callback: object) -> None:
            scheduled.append(milliseconds)

    monkeypatch.setattr(main_window_module, "QTimer", FakeTimer)
    window = _window(qtbot, app_services)

    assert not window.update_button.isVisible()
    assert not window.update_banner.isVisible()
    window._maybe_check_updates()
    assert scheduled == []


def test_a_checker_schedules_one_startup_check(qtbot, app_services, monkeypatch):
    scheduled: list[int] = []

    class FakeTimer:
        @staticmethod
        def singleShot(milliseconds: int, callback: object) -> None:
            scheduled.append(milliseconds)

    monkeypatch.setattr(main_window_module, "QTimer", FakeTimer)
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: None,
    )

    assert scheduled == [1500]
    assert window.update_button.isVisible()


def test_the_banner_fits_the_minimum_window_without_covering_the_stack(
    qtbot, app_services
):
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=lambda info: Path("unused.exe"),
        update_installer=lambda path: None,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)
    window.resize(900, 620)
    qtbot.wait(50)

    banner = window.update_banner.geometry()
    assert banner.width() <= window.centralWidget().width()
    assert banner.bottom() < window.stack.geometry().top()
    assert window.stack.height() > 0


def test_a_newer_version_shows_the_banner_and_later_hides_it(qtbot, app_services):
    seen: list[str] = []

    def checker(current: str) -> UpdateInfo:
        seen.append(current)
        return _info()

    window = _window(
        qtbot,
        app_services,
        update_checker=checker,
        update_downloader=lambda info: Path("unused.exe"),
        update_installer=lambda path: None,
    )
    window._maybe_check_updates()
    _wait_banner(qtbot, window, "CleanYourMail 9.9.9 is available.")

    assert seen == [version.__version__]
    assert window.update_open_button.text() == "Install update"
    assert window.update_later_button.text() == "Later"
    assert window.update_button.accessibleName() == "Updates"
    assert window.update_button.toolTip() == "Check for updates"

    window.update_later_button.click()
    assert not window.update_banner.isVisible()


def test_without_installer_assets_the_primary_action_opens_github(
    qtbot, app_services, monkeypatch
):
    opened: list[str] = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url: object) -> None:
            opened.append(url.toString())

    monkeypatch.setattr(main_window_module, "QDesktopServices", FakeDesktop)
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(assets=False),
        update_installer=lambda path: None,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    assert window.update_open_button.text() == "Open GitHub"
    window.update_open_button.click()
    assert opened == [RELEASES_PAGE]


def test_manual_check_reports_up_to_date(qtbot, app_services):
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: None,
    )
    window.update_button.click()
    _wait_banner(qtbot, window, "You're up to date.")

    assert window.update_open_button.isHidden()
    assert window.update_later_button.isVisible()


def test_manual_check_failure_is_localized_and_visible(qtbot, app_services):
    def checker(current: str) -> UpdateInfo | None:
        raise UpdateError("offline")

    window = _window(qtbot, app_services, update_checker=checker)
    window.update_button.click()
    _wait_banner(
        qtbot, window, "Could not check for updates. Check your connection."
    )

    assert window.update_open_button.text() == "Open GitHub"
    assert window.update_open_button.isVisible()


def test_automatic_check_failure_is_silent(qtbot, app_services):
    def checker(current: str) -> UpdateInfo | None:
        raise UpdateError("offline")

    window = _window(qtbot, app_services, update_checker=checker)
    with qtbot.waitSignal(window._update_check_worker.finished, timeout=3000):
        window._maybe_check_updates()
    qtbot.wait(50)

    assert not window.update_banner.isVisible()


def test_automatic_check_is_skipped_within_six_hours(qtbot, app_services):
    app_services.settings.save(AppSettings(last_update_check=int(time.time())))
    calls: list[str] = []

    def checker(current: str) -> UpdateInfo | None:
        calls.append(current)
        return None

    window = _window(qtbot, app_services, update_checker=checker)
    window._maybe_check_updates()
    qtbot.wait(100)
    assert calls == []

    # The header button checks on demand, ignoring the throttle.
    window.update_button.click()
    qtbot.waitUntil(lambda: calls == [version.__version__], timeout=3000)


def test_spanish_retranslation_keeps_the_pending_version(qtbot, app_services):
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=lambda info: Path("unused.exe"),
        update_installer=lambda path: None,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window, "CleanYourMail 9.9.9 is available.")

    window.set_language("es")

    assert window.update_button.text() == "Actualizaciones"
    assert (
        window.update_banner_label.text()
        == "CleanYourMail 9.9.9 está disponible."
    )
    assert window.update_open_button.text() == "Instalar actualización"
    assert window.update_later_button.text() == "Más tarde"


def test_confirmation_no_does_not_download_or_install(
    qtbot, app_services, monkeypatch
):
    downloads: list[UpdateInfo] = []
    installs: list[object] = []

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=lambda info: downloads.append(info),
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    window.update_open_button.click()

    assert downloads == []
    assert installs == []


def test_confirmation_yes_downloads_installs_and_quits_once(
    qtbot, app_services, monkeypatch, tmp_path
):
    downloaded = tmp_path / "CleanYourMail-Setup-9.9.9.exe"
    downloaded.write_bytes(b"MZ")
    downloads: list[UpdateInfo] = []
    installs: list[object] = []
    questions: list[str] = []
    quits: list[bool] = []

    def downloader(info: UpdateInfo) -> Path:
        downloads.append(info)
        return downloaded

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=downloader,
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(window, "_quit_for_update", lambda: quits.append(True))

    def question(parent, title, text, *args, **kwargs):
        questions.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(main_window_module.QMessageBox, "question", question)
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    window.update_open_button.click()
    qtbot.waitUntil(lambda: installs == [downloaded], timeout=3000)
    qtbot.waitUntil(lambda: quits == [True], timeout=3000)

    assert questions == [
        "Install 9.9.9 now? The app will close and restart."
    ]
    assert len(downloads) == 1
    assert len(installs) == 1
    assert len(quits) == 1


def test_download_failure_is_localized_and_re_enables_the_banner(
    qtbot, app_services, monkeypatch
):
    installs: list[object] = []

    def downloader(info: UpdateInfo) -> Path:
        raise UpdateError("offline")

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=downloader,
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    window.update_open_button.click()
    _wait_banner(
        qtbot,
        window,
        "The update could not be downloaded. Check your connection and try again.",
    )

    assert window.update_open_button.isEnabled()
    assert window.update_later_button.isEnabled()
    assert window.update_open_button.text() == "Install update"
    assert installs == []


def test_an_unfrozen_installer_failure_offers_github_and_keeps_the_app_open(
    qtbot, app_services, monkeypatch
):
    quits: list[bool] = []

    def installer(path: object) -> None:
        raise InstallerUnavailable("not frozen")

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=lambda info: Path("unused.exe"),
        update_installer=installer,
    )
    monkeypatch.setattr(window, "_quit_for_update", lambda: quits.append(True))
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    window.update_open_button.click()
    _wait_banner(
        qtbot,
        window,
        "Automatic updates are available in the installed app. "
        "Open GitHub instead.",
    )

    assert quits == []
    assert window.update_open_button.text() == "Open GitHub"
    assert window.update_open_button.isEnabled()
