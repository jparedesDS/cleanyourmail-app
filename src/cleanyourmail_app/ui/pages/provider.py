"""The first wizard page: which provider, and which mailbox.

The page owns the account half of ``AppSettings``: the provider id and the
email address. It does not create a config or touch a secret — that is the
Connect page's job — so this page stays instant and testable.

Enablement is deliberately boring: a provider must be chosen *and* the address
must be complete before Continue turns on. An incomplete address is reported
inline as soon as something has been typed, never as a modal dialog.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.models import AppSettings
from cleanyourmail_app.domain.providers import PROVIDERS, Provider, detect_provider
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.settings import SettingsStore
from cleanyourmail_app.ui.style import set_dynamic_property
from cleanyourmail_app.ui.widgets.provider_card import ProviderCard

#: Three cards per row keeps every label readable at the minimum window width.
CARD_COLUMNS = 3

#: One local part, then at least one dot-separated domain label and a TLD of two
#: or more characters. Deliberately strict about shape, not about deliverability.
_EMAIL_RE = re.compile(r"^[^@\s]+@(?:[^@\s.]+\.)+[^@\s.]{2,}$")

_MAX_EMAIL_LENGTH = 254


def normalise_email(value: object) -> str:
    """Trim and lower-case an address; non-strings become ``""``.

    Domains are case-insensitive and people paste addresses with stray spaces,
    so the stored value is canonical. Detection in ``domain.providers`` is
    case-insensitive too, which keeps both paths in agreement.
    """
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    """Whether ``value`` looks like a complete address (already normalised)."""
    if not isinstance(value, str) or not value or len(value) > _MAX_EMAIL_LENGTH:
        return False
    return _EMAIL_RE.match(value) is not None


class ProviderPage(QWidget):
    """Seven provider cards, one email field and the Continue action."""

    providerSelected = Signal(str)
    continueRequested = Signal(str, str)

    def __init__(
        self,
        settings: SettingsStore,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._translator = translator
        self.cards: list[ProviderCard] = []
        self._selected_card: ProviderCard | None = None

        self._build()
        self._restore_account()
        self.email_edit.textChanged.connect(self._refresh_state)
        self.retranslate()

    # -- public state -------------------------------------------------------

    @property
    def selected_provider(self) -> Provider | None:
        """The chosen provider, or ``None`` until a card is picked."""
        if self._selected_card is None:
            return None
        return self._selected_card.provider

    # -- layout -------------------------------------------------------------

    def _build(self) -> None:
        # The wizard must fit a 1366x768 laptop; when it cannot, the page
        # scrolls instead of clipping the Continue button.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Tab must reach the cards, not stop on the scroll viewport.
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        body = QWidget(self.scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(14)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, provider in enumerate(PROVIDERS):
            card = ProviderCard(provider, self._translator, self)
            card.clicked.connect(lambda _checked=False, card=card: self._select(card))
            self.cards.append(card)
            grid.addWidget(card, index // CARD_COLUMNS, index % CARD_COLUMNS)
        for column in range(CARD_COLUMNS):
            grid.setColumnStretch(column, 1)

        self.provider_note = QLabel(self)
        self.provider_note.setObjectName("muted")
        self.provider_note.setWordWrap(True)

        self.email_label = QLabel(self)
        self.email_label.setObjectName("section")

        self.email_edit = QLineEdit(self)
        self.email_edit.setObjectName("emailField")
        self.email_edit.setClearButtonEnabled(True)
        self.email_label.setBuddy(self.email_edit)

        self.email_hint = QLabel(self)
        self.email_hint.setObjectName("muted")
        self.email_hint.setWordWrap(True)

        self.email_error = QLabel(self)
        self.email_error.setObjectName("error")
        self.email_error.setWordWrap(True)
        self.email_error.setVisible(False)

        self.settings_error = QLabel(self)
        self.settings_error.setObjectName("error")
        self.settings_error.setWordWrap(True)
        self.settings_error.setVisible(False)

        self.continue_button = QPushButton(self)
        self.continue_button.setObjectName("primary")
        self.continue_button.setMinimumWidth(180)
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._submit)

        actions = QHBoxLayout()
        actions.setContentsMargins(32, 12, 32, 24)
        actions.addStretch(1)
        actions.addWidget(self.continue_button)

        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addLayout(grid)
        root.addWidget(self.provider_note)
        root.addWidget(self.email_label)
        root.addWidget(self.email_edit)
        root.addWidget(self.email_hint)
        root.addWidget(self.email_error)
        root.addWidget(self.settings_error)
        root.addStretch(1)

        # The action stays pinned: a short window scrolls the content, never
        # the Continue button.
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        outer.addLayout(actions)

    def _restore_account(self) -> None:
        """Restore the last account, but only when an address was stored.

        ``AppSettings`` defaults to ``custom``; treating that default as a
        choice would preselect Custom IMAP on a fresh install. A settings file
        that exists only for the language choice stores no address, so it must
        not pick a card either.
        """
        saved = self._settings.load()
        if not saved.email:
            return
        for card in self.cards:
            if card.provider.id == saved.provider:
                self._set_selected_card(card)
                break
        self.email_edit.setText(saved.email)

    # -- interaction --------------------------------------------------------

    def _select(self, card: ProviderCard) -> None:
        # A checkable button toggles before ``clicked`` is delivered, so the
        # page keeps its own choice instead of reading the buttons back.
        previous = self._selected_card
        self._set_selected_card(card)
        if previous is not card:
            self.providerSelected.emit(card.provider.id)
        self._refresh_state()

    def _set_selected_card(self, card: ProviderCard | None) -> None:
        self._selected_card = card
        for other in self.cards:
            other.setSelected(other is card)

    def _refresh_state(self) -> None:
        t = self._translator.t
        selected = self.selected_provider

        if selected is None:
            self.provider_note.setText(t("provider.choose_hint"))
        else:
            self.provider_note.setText(t(f"provider.{selected.id}.note"))

        raw = self.email_edit.text()
        email = normalise_email(raw)
        valid = is_valid_email(email)
        show_error = bool(raw.strip()) and not valid

        self.email_error.setText(t("provider.email.invalid"))
        self.email_error.setVisible(show_error)
        self.settings_error.setText(t("errors.settings_write"))
        set_dynamic_property(self.email_edit, "invalid", show_error)
        self.email_hint.setText(self._email_hint(email, valid, selected))

        self.continue_button.setEnabled(selected is not None and valid)

    def _email_hint(self, email: str, valid: bool, selected: Provider | None) -> str:
        """Help text, or a nudge when the domain belongs to another card."""
        help_text = self._translator.t("provider.email.help")
        if not valid:
            return help_text

        detected = detect_provider(email)
        if detected.id == "custom":
            return help_text
        if selected is not None and selected.id == detected.id:
            return help_text

        label = self._translator.t(f"provider.{detected.id}.label")
        return self._translator.t("provider.email.detected", provider=label)

    def _submit(self) -> None:
        provider = self.selected_provider
        email = normalise_email(self.email_edit.text())
        if provider is None or not is_valid_email(email):
            self._refresh_state()
            return

        current = self._settings.load()
        try:
            self._settings.save(
                AppSettings(
                    provider=provider.id,
                    email=email,
                    preferences=current.preferences,
                    last_update_check=current.last_update_check,
                )
            )
        except (OSError, ValueError, TypeError):
            self.settings_error.setText(self._translator.t("errors.settings_write"))
            self.settings_error.setVisible(True)
            return
        self.settings_error.setVisible(False)
        self.continueRequested.emit(provider.id, email)

    # -- copy ---------------------------------------------------------------

    def retranslate(self) -> None:
        """Refresh every visible string from the active catalog."""
        t = self._translator.t
        self.title_label.setText(t("provider.title"))
        self.subtitle_label.setText(t("provider.subtitle"))
        self.email_label.setText(t("provider.email.label"))
        self.email_edit.setPlaceholderText(t("provider.email.placeholder"))
        self.email_edit.setAccessibleName(t("provider.email.label"))
        self.continue_button.setText(t("provider.continue"))
        for card in self.cards:
            card.retranslate()
        self._refresh_state()
