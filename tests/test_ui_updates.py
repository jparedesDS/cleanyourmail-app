"""The header Updates button, the banner and the download/install flow.

Every service is injected. The tests never touch the network, never start an
installer and never quit the real application: the checker, downloader, installer
and quit method are all fakes or monkeypatches.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from cleanyourmail_app import version
from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.services.installer import InstallerUnavailable
from cleanyourmail_app.services.updates import RELEASES_PAGE, UpdateError, UpdateInfo
from cleanyourmail_app.ui import main_window as main_window_module
from cleanyourmail_app.ui.main_window import MainWindow

RELEASE_BASE = (
    "https://github.com/jparedesDS/cleanyourmail-app/releases/download"
)


def _info(*, assets: bool = True, version: str = "9.9.9") -> UpdateInfo:
    installer_url = (
        f"{RELEASE_BASE}/v{version}/CleanYourMail-Setup-{version}.exe"
    )
    return UpdateInfo(
        version=version,
        tag=f"v{version}",
        installer_url=installer_url if assets else "",
        checksum_url=f"{installer_url}.sha256" if assets else "",
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
        return (
            not window._update_check_worker.active
            and window.update_banner.isVisible()
            and fragment in window.update_banner_label.text()
        )

    qtbot.waitUntil(visible, timeout=3000)


def test_without_a_checker_there_is_no_button_and_no_startup_check(
    qtbot, app_services
):
    window = _window(qtbot, app_services)

    assert not window.update_button.isVisible()
    assert not window.update_banner.isVisible()
    assert window._update_startup_timer is None
    window._maybe_check_updates()


def test_a_checker_schedules_one_parented_startup_check(qtbot, app_services):
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: None,
    )

    timer = window._update_startup_timer
    assert timer is not None
    assert timer.parent() is window
    assert timer.isSingleShot()
    assert timer.isActive()
    assert 0 < timer.remainingTime() <= 1500
    assert window.update_button.isVisible()


def test_close_waits_for_an_active_check_and_stops_both_workers(
    qtbot, app_services, monkeypatch
):
    app_services.settings.save(AppSettings(last_update_check=int(time.time())))
    started = threading.Event()
    release = threading.Event()

    def checker(current: str) -> UpdateInfo | None:
        started.set()
        release.wait(5)
        return None

    window = _window(qtbot, app_services, update_checker=checker)
    window._on_updates_clicked()
    qtbot.waitUntil(started.is_set, timeout=3000)

    calls: list[str] = []
    real_check_shutdown = window._update_check_worker.shutdown
    real_download_shutdown = window._update_download_worker.shutdown

    def check_shutdown(timeout: float = 5.0) -> None:
        calls.append("check")
        real_check_shutdown(timeout)

    def download_shutdown(timeout: float = 5.0) -> None:
        calls.append("download")
        real_download_shutdown(timeout)

    monkeypatch.setattr(
        window._update_check_worker, "shutdown", check_shutdown
    )
    monkeypatch.setattr(
        window._update_download_worker, "shutdown", download_shutdown
    )
    timer = threading.Timer(0.1, release.set)
    timer.daemon = True
    timer.start()
    try:
        assert window.close()
    finally:
        release.set()
        timer.join(1)

    assert calls == ["check", "download"]
    assert not window._update_check_worker.active
    thread = window._update_check_worker._thread
    assert thread is not None and not thread.is_alive()


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
    assert window.update_github_button.isVisible()
    assert window.update_github_button.text() == "Open GitHub"
    assert window.update_github_button.geometry().right() <= banner.width()
    assert window.update_open_button.geometry().right() <= banner.width()
    assert window.update_later_button.geometry().right() <= banner.width()


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
    assert window.update_github_button.text() == "Open GitHub"
    assert window.update_github_button.isVisible()
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
    assert not window.update_github_button.isVisible()
    window.update_open_button.click()
    assert opened == [RELEASES_PAGE]


def test_the_secondary_open_github_action_opens_the_release_page(
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
        update_checker=lambda current: _info(),
        update_downloader=lambda info: Path("unused.exe"),
        update_installer=lambda path: None,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    assert window.update_github_button.isVisible()
    window.update_github_button.click()
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
    assert window.update_github_button.isHidden()
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
    assert not window.update_github_button.isVisible()


def test_automatic_check_failure_is_silent(qtbot, app_services):
    def checker(current: str) -> UpdateInfo | None:
        raise UpdateError("offline")

    window = _window(qtbot, app_services, update_checker=checker)
    with qtbot.waitSignal(window._update_check_worker.finished, timeout=3000):
        window._maybe_check_updates()
    qtbot.wait(50)

    assert not window.update_banner.isVisible()


def test_automatic_check_is_skipped_within_six_hours(qtbot, app_services):
    stamp = int(time.time())
    app_services.settings.save(AppSettings(last_update_check=stamp))
    calls: list[str] = []

    def checker(current: str) -> UpdateInfo | None:
        calls.append(current)
        return None

    window = _window(qtbot, app_services, update_checker=checker)
    window._maybe_check_updates()
    qtbot.wait(100)
    assert calls == []

    # The header button checks on demand, ignoring the throttle, but it must
    # not move the automatic-check timestamp.
    window.update_button.click()
    qtbot.waitUntil(lambda: calls == [version.__version__], timeout=3000)
    assert app_services.settings.load().last_update_check == stamp


def test_automatic_check_updates_the_timestamp_without_losing_settings(
    qtbot, app_services
):
    app_services.settings.save(
        AppSettings(
            provider="gmail",
            email="me@gmail.com",
            preferences=Preferences(
                categories=["newsletter"],
                mode="archive",
                language="es",
            ),
        )
    )
    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: None,
    )
    with qtbot.waitSignal(window._update_check_worker.finished, timeout=3000):
        window._maybe_check_updates()

    stored = app_services.settings.load()
    assert stored.last_update_check > 0
    assert stored.provider == "gmail"
    assert stored.email == "me@gmail.com"
    assert stored.preferences == Preferences(
        categories=["newsletter"],
        mode="archive",
        language="es",
    )


def test_installer_without_a_downloader_opens_github(
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
        update_checker=lambda current: _info(),
        update_installer=lambda path: None,
    )
    window._on_updates_clicked()
    _wait_banner(qtbot, window)

    assert window.update_open_button.text() == "Open GitHub"
    assert not window.update_github_button.isVisible()
    window.update_open_button.click()
    assert opened == [RELEASES_PAGE]


@pytest.mark.parametrize("second", ["newer", "failure"])
def test_a_check_result_cannot_cancel_a_confirmed_download(
    qtbot, app_services, monkeypatch, tmp_path, second
):
    checker_release = threading.Event()
    checker_started = threading.Event()
    checker_calls = 0

    def checker(current: str) -> UpdateInfo:
        nonlocal checker_calls
        checker_calls += 1
        if checker_calls == 1:
            return _info()
        checker_started.set()
        checker_release.wait(5)
        if second == "failure":
            raise UpdateError("offline")
        return _info(version="10.0.0")

    downloaded = tmp_path / "CleanYourMail-Setup-9.9.9.exe"
    downloaded.write_bytes(b"MZ")
    download_started = threading.Event()
    download_release = threading.Event()
    downloads: list[UpdateInfo] = []
    installs: list[object] = []
    quits: list[bool] = []

    def downloader(info: UpdateInfo) -> Path:
        downloads.append(info)
        download_started.set()
        download_release.wait(5)
        return downloaded

    window = _window(
        qtbot,
        app_services,
        update_checker=checker,
        update_downloader=downloader,
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(window, "_quit_for_update", lambda: quits.append(True))
    try:
        window._on_updates_clicked()
        _wait_banner(qtbot, window, "CleanYourMail 9.9.9 is available.")

        window._on_updates_clicked()
        qtbot.waitUntil(checker_started.is_set, timeout=3000)
        assert window._update_check_worker.active
        assert not window.update_open_button.isEnabled()
        assert window.update_later_button.isEnabled()

        info = window._update_info
        assert info is not None
        window._start_update_download(info)
        qtbot.waitUntil(download_started.is_set, timeout=3000)
        assert window._update_state == "downloading"

        checker_release.set()
        qtbot.waitUntil(
            lambda: not window._update_check_worker.active, timeout=3000
        )
        qtbot.wait(50)

        # Neither a newer release nor a failed check may replace the download
        # state once the person has confirmed the install.
        assert window._update_state == "downloading"
        assert window.update_banner_label.text() == "Downloading update…"
        assert window._update_version == "9.9.9"
        assert not window.update_open_button.isEnabled()
        assert not window.update_later_button.isEnabled()

        download_release.set()
        qtbot.waitUntil(lambda: installs == [downloaded], timeout=3000)
        qtbot.waitUntil(lambda: quits == [True], timeout=3000)
        assert len(downloads) == 1
        assert len(installs) == 1
    finally:
        checker_release.set()
        download_release.set()


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
    assert window.update_github_button.text() == "Abrir GitHub"
    assert window.update_github_button.isVisible()
    assert window.update_later_button.text() == "Más tarde"


def test_install_waits_for_a_busy_review_page(
    qtbot, app_services, monkeypatch
):
    downloads: list[UpdateInfo] = []
    installs: list[object] = []
    questions: list[object] = []

    def question(*args, **kwargs):
        questions.append(args)
        return QMessageBox.StandardButton.Yes

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=lambda info: downloads.append(info),
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(main_window_module.QMessageBox, "question", question)
    window._on_updates_clicked()
    _wait_banner(qtbot, window)
    monkeypatch.setattr(window.review_page, "is_busy", lambda: True)

    window.update_open_button.click()
    _wait_banner(
        qtbot,
        window,
        "Wait for the current mailbox action to finish before updating.",
    )

    assert questions == []
    assert downloads == []
    assert installs == []
    assert window._update_state == "available"
    assert window.update_open_button.text() == "Install update"


def test_a_confirmed_download_blocks_the_whole_window(
    qtbot, app_services, monkeypatch, tmp_path
):
    downloaded = tmp_path / "CleanYourMail-Setup-9.9.9.exe"
    downloaded.write_bytes(b"MZ")
    download_started = threading.Event()
    download_release = threading.Event()
    installs: list[object] = []
    quits: list[bool] = []

    def downloader(info: UpdateInfo) -> Path:
        download_started.set()
        download_release.wait(5)
        return downloaded

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=downloader,
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(window, "_quit_for_update", lambda: quits.append(True))
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        window._on_updates_clicked()
        _wait_banner(qtbot, window)
        window.update_open_button.click()
        qtbot.waitUntil(download_started.is_set, timeout=3000)

        assert window._update_state == "downloading"
        assert window._update_ui_blocked
        assert not window.centralWidget().isEnabled()
        assert not window.update_button.isEnabled()
        assert not window.feedback_button.isEnabled()
        assert not window.language_combo.isEnabled()
        assert not window.update_open_button.isEnabled()
        assert not window.update_later_button.isEnabled()
        assert window.update_github_button.isHidden()

        download_release.set()
        qtbot.waitUntil(lambda: quits == [True], timeout=3000)
        assert installs == [downloaded]
    finally:
        download_release.set()


def test_download_finishing_while_review_busy_does_not_install_or_quit(
    qtbot, app_services, monkeypatch, tmp_path
):
    downloaded = tmp_path / "CleanYourMail-Setup-9.9.9.exe"
    downloaded.write_bytes(b"MZ")
    download_started = threading.Event()
    download_release = threading.Event()
    installs: list[object] = []
    quits: list[bool] = []

    def downloader(info: UpdateInfo) -> Path:
        download_started.set()
        download_release.wait(5)
        return downloaded

    window = _window(
        qtbot,
        app_services,
        update_checker=lambda current: _info(),
        update_downloader=downloader,
        update_installer=lambda path: installs.append(path),
    )
    monkeypatch.setattr(window, "_quit_for_update", lambda: quits.append(True))
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    try:
        window._on_updates_clicked()
        _wait_banner(qtbot, window)
        window.update_open_button.click()
        qtbot.waitUntil(download_started.is_set, timeout=3000)

        # The confirmation is already answered. A mailbox action starts while
        # the download is still in flight; the finishing download must not
        # install or quit over it.
        monkeypatch.setattr(window.review_page, "is_busy", lambda: True)
        download_release.set()
        _wait_banner(
            qtbot,
            window,
            "Wait for the current mailbox action to finish before updating.",
        )

        assert installs == []
        assert quits == []
        assert window._update_state == "available"
        assert not window._update_ui_blocked
        assert window.centralWidget().isEnabled()
        assert window.update_open_button.isEnabled()
        assert window.update_github_button.isVisible()
    finally:
        download_release.set()


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
        "The update could not be downloaded or verified. "
        "Check your connection and try again.",
    )

    assert window.update_open_button.isEnabled()
    assert window.update_github_button.isVisible()
    assert window.update_github_button.isEnabled()
    assert window.update_later_button.isEnabled()
    assert window.update_open_button.text() == "Install update"
    assert window.centralWidget().isEnabled()
    assert installs == []


def test_close_uses_one_total_deadline_for_both_update_workers(
    qtbot, app_services, monkeypatch
):
    calls: list[float] = []

    class SlowWorker:
        def shutdown(self, timeout: float = 5.0) -> None:
            calls.append(timeout)
            time.sleep(timeout)

    window = _window(qtbot, app_services)
    monkeypatch.setattr(
        main_window_module, "UPDATE_SHUTDOWN_TIMEOUT_SECONDS", 0.2
    )
    monkeypatch.setattr(window, "_update_check_worker", SlowWorker())
    monkeypatch.setattr(window, "_update_download_worker", SlowWorker())

    started = time.monotonic()
    window._shutdown_update_workers()
    elapsed = time.monotonic() - started

    assert 1 <= len(calls) <= 2
    assert elapsed < 0.4, "shutdown must not wait 5 s per worker"
    assert calls[0] <= 0.2
    if len(calls) == 2:
        assert calls[1] <= 0.05


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
    assert window.centralWidget().isEnabled()
    assert not window._update_ui_blocked
