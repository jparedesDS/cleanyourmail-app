"""The wizard shell: one window, a progress rail and stacked pages.

``MainWindow`` is the only object that knows the step order. Pages report what
happened through signals; the shell resolves ids, remembers the account it was
handed and moves the rail forward. The Connect page receives the provider/email
pair from the provider page; a successful connection advances to Preferences,
which writes the policy before asking for the Review page. Review reloads on
arrival so it never shows a plan built from stale preferences; a page that is
registered later is skipped instead of raising a ``KeyError``.

Language switching is a window-level operation because the theme, the rail and
every page share one ``Translator``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app import version
from cleanyourmail_app.domain.providers import Provider, provider_by_id
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.cli import CliError
from cleanyourmail_app.services.installer import InstallerUnavailable
from cleanyourmail_app.services.settings import SettingsStore
from cleanyourmail_app.services.updates import RELEASES_PAGE, UpdateInfo
from cleanyourmail_app.ui.dialogs.feedback import FeedbackDialog
from cleanyourmail_app.ui.pages.connect import ConnectPage
from cleanyourmail_app.ui.pages.preferences import PreferencesPage
from cleanyourmail_app.ui.pages.provider import ProviderPage
from cleanyourmail_app.ui.pages.review import ReviewPage
from cleanyourmail_app.ui.style import set_dynamic_property, theme_stylesheet
from cleanyourmail_app.ui.workers import BackgroundCall

#: The wizard order, used for the rail and the page keys.
STEPS: tuple[str, ...] = ("provider", "connect", "preferences", "review")

#: A decorative separator between rail steps, not translatable copy.
_ARROW = "\u2192"

#: Automatic checks are skipped when the last one is younger than six hours.
UPDATE_CHECK_INTERVAL_SECONDS = 6 * 60 * 60

#: Let the first page paint before asking GitHub, so a slow network is invisible.
UPDATE_STARTUP_DELAY_MS = 1500

#: Total time the window spends waiting for update workers during close.
UPDATE_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class MainWindow(QMainWindow):
    """Own the window chrome, the progress rail and the page stack."""

    def __init__(
        self,
        settings: SettingsStore,
        translator: Translator,
        services: AppServices,
        *,
        update_checker: Callable[[str], UpdateInfo | None] | None = None,
        update_downloader: Callable[[UpdateInfo], Path] | None = None,
        update_installer: Callable[[Any], object] | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.translator = translator
        self.services = services
        self.update_checker = update_checker
        self.update_downloader = update_downloader
        self.update_installer = update_installer

        #: What the provider page handed over; the Connect page consumes it.
        self.pending_provider: Provider | None = None
        self.pending_email = ""

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("pageStack")
        self.step_labels: dict[str, QLabel] = {}
        self.pages: dict[str, QWidget] = {}
        #: Guards the header language combo against re-entering its handler
        #: while ``retranslate`` rewrites the item texts.
        self._syncing_language = False
        #: The first successful sidecar read is enough for this run; opening the
        #: feedback dialog again must not start the sidecar a second time.
        self._sidecar_version_cache: str | None = None

        #: Update state. The version is kept separately so a language switch can
        #: rebuild the banner without asking GitHub again or losing the version.
        self._update_info: UpdateInfo | None = None
        self._update_version = ""
        self._update_state = "idle"
        self._update_message_key = ""
        self._update_error_key = ""
        self._update_auto_available = False
        self._update_allow_github = False
        self._update_check_manual = False
        self._update_ui_blocked = False
        self._update_startup_timer: QTimer | None = None
        self._update_check_worker = BackgroundCall(self)
        self._update_download_worker = BackgroundCall(self)
        self._update_check_worker.succeeded.connect(self._on_update_check_succeeded)
        self._update_check_worker.failed.connect(self._on_update_check_failed)
        self._update_check_worker.finished.connect(self._on_update_check_finished)
        self._update_download_worker.succeeded.connect(
            self._on_update_download_succeeded
        )
        self._update_download_worker.failed.connect(self._on_update_download_failed)

        self.setMinimumSize(900, 620)
        self.resize(1040, 820)
        self.setStyleSheet(theme_stylesheet())
        self._apply_icon()

        self._build()
        self.retranslate()

        if self.update_checker is not None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._maybe_check_updates)
            timer.start(UPDATE_STARTUP_DELAY_MS)
            self._update_startup_timer = timer

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        central = QWidget(self)
        central.setObjectName("surface")
        root = QVBoxLayout(central)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(18)

        self.app_label = QLabel(central)
        self.app_label.setObjectName("section")
        self.privacy_label = QLabel(central)
        self.privacy_label.setObjectName("muted")
        self.privacy_label.setWordWrap(True)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.app_label)
        header.addStretch(1)
        header.addWidget(self.privacy_label)
        header.addSpacing(12)
        self.update_button = QPushButton(central)
        self.update_button.setObjectName("updateButton")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.clicked.connect(self._on_updates_clicked)
        self.update_button.setVisible(self.update_checker is not None)
        header.addWidget(self.update_button)
        header.addSpacing(12)
        self.feedback_button = QPushButton(central)
        self.feedback_button.setObjectName("feedbackButton")
        self.feedback_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.feedback_button.clicked.connect(self._open_feedback)
        header.addWidget(self.feedback_button)
        header.addSpacing(12)
        self.language_combo = QComboBox(central)
        self.language_combo.setObjectName("headerLanguage")
        self.language_combo.setMinimumWidth(110)
        self._build_header_languages()
        self.language_combo.currentIndexChanged.connect(
            self._on_header_language_changed
        )
        header.addWidget(self.language_combo)
        root.addLayout(header)

        root.addWidget(self._build_update_banner(central))

        root.addWidget(self._build_rail(central))

        divider = QFrame(central)
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(divider)

        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.provider_page = ProviderPage(self.settings, self.translator, self)
        self.provider_page.continueRequested.connect(self._on_continue)
        self.add_page("provider", self.provider_page)

        self.connect_page = ConnectPage(self.services, self)
        self.connect_page.backRequested.connect(self._on_connect_back)
        self.connect_page.connectionSucceeded.connect(self._on_connected)
        self.add_page("connect", self.connect_page)

        self.preferences_page = PreferencesPage(self.services, self)
        self.preferences_page.continueRequested.connect(self._on_preferences_continue)
        self.preferences_page.backRequested.connect(self._on_preferences_back)
        self.preferences_page.languageChanged.connect(self.set_language)
        self.add_page("preferences", self.preferences_page)

        self.review_page = ReviewPage(self.services, self)
        self.review_page.backRequested.connect(self._on_review_back)
        self.add_page("review", self.review_page)

        self.show_page("provider")

    def _build_update_banner(self, parent: QWidget) -> QWidget:
        """A slim, hidden strip: version, primary action and Later."""
        banner = QFrame(parent)
        banner.setObjectName("updateBanner")
        banner.setVisible(False)
        row = QHBoxLayout(banner)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)

        self.update_banner = banner
        self.update_banner_label = QLabel(banner)
        self.update_banner_label.setObjectName("updateBannerLabel")
        self.update_banner_label.setWordWrap(True)
        row.addWidget(self.update_banner_label, 1)

        self.update_github_button = QPushButton(banner)
        self.update_github_button.setObjectName("updateGithubButton")
        self.update_github_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_github_button.clicked.connect(self._open_release_page)
        row.addWidget(self.update_github_button)

        self.update_open_button = QPushButton(banner)
        self.update_open_button.setObjectName("updateOpenButton")
        self.update_open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_open_button.clicked.connect(self._on_update_primary_clicked)
        row.addWidget(self.update_open_button)

        self.update_later_button = QPushButton(banner)
        self.update_later_button.setObjectName("updateLaterButton")
        self.update_later_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_later_button.clicked.connect(self._dismiss_update_banner)
        row.addWidget(self.update_later_button)
        return banner

    def _build_rail(self, parent: QWidget) -> QWidget:
        """Provider, Connect, Preferences, Review, in that order."""
        rail = QWidget(parent)
        rail.setObjectName("progressRail")
        row = QHBoxLayout(rail)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        for index, step in enumerate(STEPS):
            if index:
                arrow = QLabel(_ARROW, rail)
                arrow.setObjectName("muted")
                row.addWidget(arrow, 0, Qt.AlignmentFlag.AlignVCenter)

            label = QLabel(rail)
            label.setObjectName("step")
            label.setProperty("active", False)
            label.setProperty("done", False)
            self.step_labels[step] = label
            row.addWidget(label)

        row.addStretch(1)
        return rail

    def _apply_icon(self) -> None:
        icon_path = Path(__file__).with_name("resources") / "app-icon.svg"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

    # -- page flow ----------------------------------------------------------

    def add_page(self, key: str, page: QWidget) -> None:
        """Register a page under one of the wizard step keys."""
        if key not in STEPS:
            raise ValueError(f"unknown wizard step: {key}")
        if key in self.pages:
            raise ValueError(f"the {key} page is already registered")
        self.pages[key] = page
        self.stack.addWidget(page)

    def show_page(self, key: str) -> None:
        """Show a registered page and mark the rail up to it."""
        if key not in self.pages:
            raise KeyError(f"the {key} page is not registered yet")

        self.stack.setCurrentWidget(self.pages[key])
        current = STEPS.index(key)
        for index, step in enumerate(STEPS):
            label = self.step_labels[step]
            set_dynamic_property(label, "active", step == key)
            set_dynamic_property(label, "done", index < current)

    def current_page_key(self) -> str:
        """The key of the visible page, or ``""`` when none is registered."""
        widget = self.stack.currentWidget()
        for key, page in self.pages.items():
            if page is widget:
                return key
        return ""

    def _on_continue(self, provider_id: str, email: str) -> None:
        """Resolve what the provider page sent and hand it to Connect.

        The pair is kept on the window as well, so a page that is registered
        later can still read the account the wizard is working on.
        """
        self.pending_provider = provider_by_id(provider_id)
        self.pending_email = email
        if "connect" not in self.pages:
            return
        page = self.pages["connect"]
        set_provider = getattr(page, "set_provider", None)
        if callable(set_provider) and self.pending_provider is not None:
            set_provider(self.pending_provider, self.pending_email)
        self.show_page("connect")

    def _on_connect_back(self) -> None:
        """Return to the provider page, dropping any typed secret or code."""
        page = self.pages.get("connect")
        clear = getattr(page, "clear_sensitive", None)
        if callable(clear):
            clear()
        self.show_page("provider")

    def _on_connected(self) -> None:
        """Advance after a successful doctor, when the next page exists.

        The Preferences page reloads first, so it always reflects the settings
        file the connection may have just touched.
        """
        if "preferences" in self.pages:
            page = self.pages["preferences"]
            reload_page = getattr(page, "reload", None)
            if callable(reload_page):
                reload_page()
            self.show_page("preferences")

    def _on_preferences_continue(self) -> None:
        """Advance to Review with a clean page, when it exists."""
        if "review" not in self.pages:
            return
        page = self.pages["review"]
        reload_page = getattr(page, "reload", None)
        if callable(reload_page):
            reload_page()
        self.show_page("review")

    def _on_preferences_back(self) -> None:
        """Return to Connect, when that page is registered."""
        if "connect" in self.pages:
            page = self.pages["connect"]
            reenter = getattr(page, "reenter", None)
            if callable(reenter):
                reenter()
            self.show_page("connect")

    def _on_review_back(self) -> None:
        """Return to Preferences without applying anything implicitly."""
        if "preferences" in self.pages:
            reload_page = getattr(self.pages["preferences"], "reload", None)
            if callable(reload_page):
                reload_page()
            self.show_page("preferences")

    # -- header language control -------------------------------------------

    def _build_header_languages(self) -> None:
        """The header language control, available on every wizard page."""
        for language in self.translator.available_languages:
            self.language_combo.addItem(language, language)

    def _on_header_language_changed(self, index: int) -> None:
        if self._syncing_language:
            return
        language = self.language_combo.itemData(index)
        if isinstance(language, str) and language != self.translator.language:
            self.set_language(language)

    def _sync_header_language(self) -> None:
        """Show the active language without triggering another switch."""
        self._syncing_language = True
        try:
            for index in range(self.language_combo.count()):
                code = self.language_combo.itemData(index)
                self.language_combo.setItemText(
                    index, self.translator.t(f"language.{code}")
                )
                if code == self.translator.language:
                    self.language_combo.setCurrentIndex(index)
            self.language_combo.setAccessibleName(
                self.translator.t("language.label")
            )
        finally:
            self._syncing_language = False

    # -- feedback -----------------------------------------------------------

    def _open_feedback(self) -> None:
        """Open the local dialog with local facts only.

        Only the sidecar's ``--version`` is read, best-effort. The dialog never
        sends anything on open and no network client is constructed here.
        """
        stored = self.settings.load()
        dialog = FeedbackDialog(
            version.__version__,
            self._sidecar_version(),
            provider_by_id(stored.provider),
            stored.preferences,
            self.translator,
            self,
        )
        # ``finished`` fires for both Accept/Reject and the window close. Delete
        # from the signal; never touch the dialog after ``exec`` returns because
        # Qt may already have destroyed the C++ object.
        dialog.finished.connect(dialog.deleteLater)
        dialog.exec()

    def _sidecar_version(self) -> str:
        """Bare sidecar version, or ``unknown`` when it cannot be read.

        A successful read is cached for the life of the window, and the
        client's verified version is reused after a connection test. The
        local ``version()`` call itself is capped by ``VERSION_TIMEOUT``.
        """
        if self._sidecar_version_cache is not None:
            return self._sidecar_version_cache

        cached = getattr(self.services.cli, "cached_version", None)
        if isinstance(cached, str) and cached.strip():
            bare = self._bare_version(cached)
            if bare != "unknown":
                self._sidecar_version_cache = bare
                return bare

        try:
            line = self.services.cli.version()
        except CliError:
            return "unknown"
        bare = self._bare_version(line)
        if bare != "unknown":
            self._sidecar_version_cache = bare
        return bare

    @staticmethod
    def _bare_version(line: str) -> str:
        """Strip the product prefix (``CleanYourMail 1.3.0`` → ``1.3.0``)."""
        text = line.strip()
        prefix = "CleanYourMail "
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :].strip()
        return text or "unknown"

    # -- updates ------------------------------------------------------------

    def _maybe_check_updates(self) -> None:
        """Automatic check: at most once per six hours, silent on failure."""
        if self.update_checker is None or self._updates_busy():
            return
        try:
            stored = self.settings.load()
        except (OSError, ValueError):
            stored = None
        now = int(time.time())
        last = stored.last_update_check if stored is not None else 0
        if last and now - last < UPDATE_CHECK_INTERVAL_SECONDS:
            return
        self._start_update_check(manual=False)

    def _on_updates_clicked(self) -> None:
        """The header button always checks on demand, ignoring the throttle."""
        if self._updates_busy():
            return
        self._start_update_check(manual=True)

    def _updates_busy(self) -> bool:
        return (
            self._update_check_worker.active
            or self._update_download_worker.active
            or self._update_state in {"downloading", "installing"}
        )

    def _start_update_check(self, *, manual: bool) -> None:
        checker = self.update_checker
        if checker is None or self._updates_busy():
            return
        self._update_check_manual = manual
        if not manual:
            self._record_update_check()
        started = self._update_check_worker.start(
            lambda: checker(version.__version__)
        )
        if not started:
            self._update_check_manual = False
        self._refresh_update_banner()

    def _record_update_check(self) -> None:
        """Stamp the check before it starts; a read-only profile is not fatal."""
        try:
            self.settings.update_last_update_check(int(time.time()))
        except (OSError, TypeError, ValueError):
            return

    def _on_update_check_succeeded(self, info: object) -> None:
        if self._update_transition_in_progress():
            return
        manual = self._update_check_manual
        if info is None:
            if manual:
                self._show_update_message("update.up_to_date")
            return

        version_text = getattr(info, "version", "")
        if not isinstance(version_text, str) or not version_text.strip():
            if manual:
                self._show_update_message("update.check_failed", allow_github=True)
            return

        self._update_info = info
        self._update_version = version_text.strip()
        self._update_auto_available = self._auto_install_available(info)
        self._update_message_key = ""
        self._update_error_key = ""
        self._update_allow_github = False
        self._update_state = "available"
        self._refresh_update_banner()

    def _on_update_check_failed(self, error: object) -> None:
        if self._update_transition_in_progress():
            return
        if not self._update_check_manual:
            return
        self._show_update_message("update.check_failed", allow_github=True)

    def _on_update_check_finished(self) -> None:
        # A finished event may arrive after the next check has already started;
        # do not clear the newer check's manual/automatic marker in that case.
        if not self._update_check_worker.active:
            self._update_check_manual = False
        self._refresh_update_banner()

    def _update_transition_in_progress(self) -> bool:
        """True while a confirmed download or install owns the update flow."""
        return (
            self._update_state in {"downloading", "installing"}
            or self._update_download_worker.active
        )

    def _auto_install_available(self, info: object) -> bool:
        installer_url = getattr(info, "installer_url", "")
        checksum_url = getattr(info, "checksum_url", "")
        return bool(
            installer_url
            and checksum_url
            and callable(self.update_downloader)
            and callable(self.update_installer)
        )

    def _show_update_message(self, key: str, *, allow_github: bool = False) -> None:
        """Show manual feedback in the banner without a pending version."""
        self._update_info = None
        self._update_version = ""
        self._update_auto_available = False
        self._update_error_key = ""
        self._update_message_key = key
        self._update_allow_github = allow_github
        self._update_state = "message"
        self._refresh_update_banner()

    def _refresh_update_banner(self) -> None:
        """Rebuild every visible banner string from the current state."""
        state = self._update_state
        if state == "idle":
            self.update_banner.setVisible(False)
            return

        t = self.translator.t
        label = ""
        primary = ""
        primary_visible = False
        primary_enabled = True
        later_enabled = True
        github_visible = False
        github_enabled = True

        if state == "available":
            label = (
                t(self._update_error_key)
                if self._update_error_key
                else t("update.available", version=self._update_version)
            )
            primary = (
                t("update.install")
                if self._update_auto_available
                else t("update.open_github")
            )
            primary_visible = True
            primary_enabled = not self._update_check_worker.active
            # A secondary release-page escape hatch is shown only when the
            # primary button is Install update. It is also useful after a
            # download, hash or redirect failure while a retry is still offered.
            github_visible = self._update_auto_available
            github_enabled = primary_enabled
        elif state == "downloading":
            label = t("update.downloading")
            primary = (
                t("update.install")
                if self._update_auto_available
                else t("update.open_github")
            )
            primary_visible = True
            primary_enabled = False
            later_enabled = False
        elif state == "installing":
            label = t("update.installing")
            primary = t("update.install")
            primary_visible = True
            primary_enabled = False
            later_enabled = False
        elif state == "message":
            label = t(self._update_message_key)
            primary = t("update.open_github")
            primary_visible = self._update_allow_github
        else:
            self.update_banner.setVisible(False)
            return

        self.update_banner_label.setText(label)
        self.update_banner.setAccessibleName(label)
        self._configure_update_button(
            self.update_github_button,
            t("update.open_github"),
            visible=github_visible,
            enabled=github_enabled,
        )
        self._configure_update_button(
            self.update_open_button,
            primary,
            visible=primary_visible,
            enabled=primary_enabled,
        )
        self._configure_update_button(
            self.update_later_button,
            t("update.later"),
            visible=True,
            enabled=later_enabled,
        )
        self.update_banner.setVisible(True)

    @staticmethod
    def _configure_update_button(
        button: QPushButton, text: str, *, visible: bool, enabled: bool
    ) -> None:
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(text)
        button.setVisible(visible)
        button.setEnabled(enabled)

    def _on_update_primary_clicked(self) -> None:
        if self._update_state in {"downloading", "installing"}:
            return
        if self._update_auto_available and self._update_info is not None:
            self._confirm_and_install_update()
            return
        self._open_release_page()

    def _confirm_and_install_update(self) -> None:
        info = self._update_info
        if info is None:
            return
        if self.review_page.is_busy():
            self._update_state = "available"
            self._update_error_key = "update.review_busy"
            self._refresh_update_banner()
            return
        t = self.translator.t
        answer = QMessageBox.question(
            self,
            t("update.confirm_title"),
            t("update.confirm", version=self._update_version),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_update_download(info)

    def _set_update_blocking(self, blocking: bool) -> None:
        """Make the window non-interactive while a confirmed update owns it.

        The whole central widget is disabled, not only the banner, so a person
        cannot start an Apply, an Outlook wait or type feedback between the
        confirmation and the quit. Every failure path calls this with
        ``False`` before showing its message.
        """
        if self._update_ui_blocked == blocking:
            return
        self._update_ui_blocked = blocking
        central = self.centralWidget()
        if central is not None:
            central.setEnabled(not blocking)
        if blocking:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _start_update_download(self, info: object) -> None:
        downloader = self.update_downloader
        if downloader is None or not callable(downloader):
            self._update_state = "available"
            self._update_error_key = "update.download_failed"
            self._refresh_update_banner()
            return
        if self._update_download_worker.active:
            return
        self._set_update_blocking(True)
        self._update_state = "downloading"
        self._update_error_key = ""
        self._refresh_update_banner()
        if not self._update_download_worker.start(lambda: downloader(info)):
            self._set_update_blocking(False)
            self._update_state = "available"
            self._update_error_key = "update.download_failed"
            self._refresh_update_banner()

    def _on_update_download_succeeded(self, result: object) -> None:
        if self._update_state != "downloading":
            return
        installer = self.update_installer
        if not callable(installer):
            self._set_update_blocking(False)
            self._update_auto_available = False
            self._update_error_key = "update.install_failed"
            self._update_state = "available"
            self._refresh_update_banner()
            return
        if self.review_page.is_busy():
            self._set_update_blocking(False)
            self._update_error_key = "update.review_busy"
            self._update_state = "available"
            self._refresh_update_banner()
            return

        self._update_state = "installing"
        self._refresh_update_banner()
        try:
            # Only the path returned by this download is ever installed.
            installer(result)
        except InstallerUnavailable:
            self._set_update_blocking(False)
            self._update_auto_available = False
            self._update_error_key = "update.dev_unavailable"
            self._update_state = "available"
            self._refresh_update_banner()
            return
        except Exception:  # noqa: BLE001 - any failure keeps the old app open
            self._set_update_blocking(False)
            self._update_auto_available = False
            self._update_error_key = "update.install_failed"
            self._update_state = "available"
            self._refresh_update_banner()
            return
        self._quit_for_update()

    def _on_update_download_failed(self, error: object) -> None:
        if self._update_state != "downloading":
            return
        self._set_update_blocking(False)
        if self._update_info is None:
            self._show_update_message("update.download_failed", allow_github=True)
            return
        self._update_state = "available"
        self._update_error_key = "update.download_failed"
        self._refresh_update_banner()

    def _dismiss_update_banner(self) -> None:
        if self._update_state in {"downloading", "installing"}:
            return
        self._update_state = "idle"
        self._update_info = None
        self._update_version = ""
        self._update_message_key = ""
        self._update_error_key = ""
        self._update_auto_available = False
        self._update_allow_github = False
        self._refresh_update_banner()

    def _open_release_page(self) -> None:
        target = QUrl(RELEASES_PAGE)
        if (
            target.isValid()
            and target.scheme().lower() == "https"
            and target.host()
        ):
            QDesktopServices.openUrl(target)

    def _quit_for_update(self) -> None:
        """Close the app after the helper is running; tests replace this."""
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's contract
        """Stop the startup timer and update workers before the window goes."""
        if self._update_startup_timer is not None:
            self._update_startup_timer.stop()
        if self._update_ui_blocked:
            self._set_update_blocking(False)
        self._shutdown_update_workers()
        super().closeEvent(event)

    def _shutdown_update_workers(self) -> None:
        """Wait for both workers under one total deadline, not 5 s each."""
        deadline = time.monotonic() + UPDATE_SHUTDOWN_TIMEOUT_SECONDS
        for worker in (self._update_check_worker, self._update_download_worker):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.shutdown(remaining)

    # -- language -----------------------------------------------------------

    def set_language(self, language: str) -> None:
        """Switch the shared translator and refresh every visible string."""
        self.translator.set_language(language)
        self.retranslate()
        self._remember_language()

    def _remember_language(self) -> None:
        """Persist the choice best-effort; a read-only profile is not fatal."""
        try:
            current = self.settings.load()
            if current.preferences.language == self.translator.language:
                return
            self.settings.update_preferences(
                replace(current.preferences, language=self.translator.language)
            )
        except OSError:
            return

    def retranslate(self) -> None:
        """Refresh the window chrome, the rail and every registered page."""
        t = self.translator.t
        self.setWindowTitle(t("app.window_title"))
        self.app_label.setText(t("app.name"))
        self.privacy_label.setText(t("app.privacy"))
        self.update_button.setText(t("update.open"))
        self.update_button.setAccessibleName(t("update.open"))
        self.update_button.setToolTip(t("update.check_tooltip"))
        self.feedback_button.setText(t("feedback.open"))
        self.feedback_button.setAccessibleName(t("feedback.open"))
        self.feedback_button.setToolTip(t("feedback.open"))
        self._sync_header_language()
        for step in STEPS:
            self.step_labels[step].setText(t(f"progress.{step}"))
        self._refresh_update_banner()
        for page in self.pages.values():
            retranslate = getattr(page, "retranslate", None)
            if callable(retranslate):
                retranslate()
