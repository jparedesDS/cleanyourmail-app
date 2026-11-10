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

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.providers import Provider, provider_by_id
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.settings import SettingsStore
from cleanyourmail_app.ui.pages.connect import ConnectPage
from cleanyourmail_app.ui.pages.preferences import PreferencesPage
from cleanyourmail_app.ui.pages.provider import ProviderPage
from cleanyourmail_app.ui.pages.review import ReviewPage
from cleanyourmail_app.ui.style import set_dynamic_property, theme_stylesheet

#: The wizard order, used for the rail and the page keys.
STEPS: tuple[str, ...] = ("provider", "connect", "preferences", "review")

#: A decorative separator between rail steps, not translatable copy.
_ARROW = "\u2192"


class MainWindow(QMainWindow):
    """Own the window chrome, the progress rail and the page stack."""

    def __init__(
        self,
        settings: SettingsStore,
        translator: Translator,
        services: AppServices,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.translator = translator
        self.services = services

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

        self.setMinimumSize(900, 620)
        self.resize(1040, 820)
        self.setStyleSheet(theme_stylesheet())
        self._apply_icon()

        self._build()
        self.retranslate()

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

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.app_label)
        header.addStretch(1)
        header.addWidget(self.privacy_label)
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
            self.show_page("connect")

    def _on_review_back(self) -> None:
        """Return to Preferences without applying anything implicitly."""
        if "preferences" in self.pages:
            reload_page = getattr(self.pages["preferences"], "reload", None)
            if callable(reload_page):
                reload_page()
            self.show_page("preferences")

    # -- language -----------------------------------------------------------

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
        self._sync_header_language()
        for step in STEPS:
            self.step_labels[step].setText(t(f"progress.{step}"))
        for page in self.pages.values():
            retranslate = getattr(page, "retranslate", None)
            if callable(retranslate):
                retranslate()
