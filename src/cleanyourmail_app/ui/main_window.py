"""The wizard shell: one window, a progress rail and stacked pages.

``MainWindow`` is the only object that knows the step order. Pages report what
happened through signals; the shell resolves ids, remembers the account it was
handed and moves the rail forward. Task 7 registers the Connect page through
:meth:`add_page`, so the shell does not need to change for that step.

Language switching is a window-level operation because the theme, the rail and
every page share one ``Translator``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
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
from cleanyourmail_app.ui.pages.provider import ProviderPage
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
        """Resolve what the provider page sent and move on when possible.

        Task 6 ships only the first page; Task 7 registers ``connect``. Until
        then the shell keeps the handoff in ``pending_provider`` and stays put
        rather than showing a blank step.
        """
        self.pending_provider = provider_by_id(provider_id)
        self.pending_email = email
        if "connect" in self.pages:
            self.show_page("connect")

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
        for step in STEPS:
            self.step_labels[step].setText(t(f"progress.{step}"))
        for page in self.pages.values():
            retranslate = getattr(page, "retranslate", None)
            if callable(retranslate):
                retranslate()
