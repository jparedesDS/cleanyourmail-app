"""The wizard shell and the provider page, driven through real Qt widgets.

These tests never touch the network, a mailbox or the user profile:
``tests/conftest.py`` selects Qt's offscreen platform and injects a temporary
``SettingsStore``.

The page has to answer three questions before the wizard may move on: which
provider, which address, and whether that address is complete. The tests below
pin all three, plus the bilingual title and the shell handoff.
"""

from __future__ import annotations

import re

import pytest
from PySide6.QtCore import Qt

from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.domain.providers import PROVIDERS
from cleanyourmail_app.ui.main_window import MainWindow
from cleanyourmail_app.ui.pages.provider import is_valid_email, normalise_email
from cleanyourmail_app.ui.style import theme_stylesheet
from cleanyourmail_app.ui.widgets.provider_card import ProviderCard

EN_TITLE = "Which email provider do you use?"
ES_TITLE = "¿Qué proveedor de correo usas?"


@pytest.fixture
def window(qtbot, app_services):
    window = MainWindow(app_services.settings, app_services.translator, app_services)
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.fixture
def page(window):
    return window.provider_page


def _card(page, provider_id: str) -> ProviderCard:
    return next(card for card in page.cards if card.provider.id == provider_id)


def _select(qtbot, page, provider_id: str) -> None:
    qtbot.mouseClick(_card(page, provider_id), Qt.MouseButton.LeftButton)


# --- Shell -----------------------------------------------------------------


def test_the_window_starts_on_the_provider_page(window, page):
    assert window.current_page_key() == "provider"
    assert window.stack.currentWidget() is page


def test_the_progress_rail_lists_the_four_steps(window):
    assert list(window.step_labels) == ["provider", "connect", "preferences", "review"]
    assert window.step_labels["provider"].property("active") is True
    assert window.step_labels["connect"].property("done") is False


def test_the_window_loads_the_theme(window):
    assert "providerCard" in window.styleSheet()


def test_the_theme_keeps_touch_targets_at_44_px():
    """Task 5 left ``#link`` and the checkable controls below the target."""

    def block(selector: str) -> str:
        pattern = rf"{re.escape(selector)}[^{{}}]*\{{([^}}]*)\}}"
        match = re.search(pattern, theme_stylesheet())
        assert match is not None, selector
        return match.group(1)

    assert "min-height: 44px;" in block("QPushButton#link")
    assert "min-height: 44px;" in block("QCheckBox")


def test_the_shell_can_show_a_later_page(window):
    # Review is registered by the shell itself; showing it marks the earlier
    # steps done and moves the rail without needing a second registration.
    window.show_page("review")

    assert window.current_page_key() == "review"
    assert window.step_labels["provider"].property("done") is True
    assert window.step_labels["review"].property("active") is True


def test_continue_advances_to_the_registered_connect_page(qtbot, window, page):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail.com")

    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert window.current_page_key() == "connect"
    assert window.connect_page.provider.id == "gmail"


# --- Cards -----------------------------------------------------------------


def test_the_page_shows_seven_provider_cards(page):
    assert len(page.cards) == 7
    assert [card.provider.id for card in page.cards] == [p.id for p in PROVIDERS]
    assert all(isinstance(card, ProviderCard) for card in page.cards)
    assert all(card.isCheckable() for card in page.cards)
    assert all(card.focusPolicy() != Qt.FocusPolicy.NoFocus for card in page.cards)


def test_clicking_gmail_selects_only_gmail(qtbot, page):
    _select(qtbot, page, "gmail")

    gmail = _card(page, "gmail")
    assert gmail.selected is True
    assert page.selected_provider is not None
    assert page.selected_provider.id == "gmail"
    assert [card.selected for card in page.cards] == [
        card is gmail for card in page.cards
    ]


def test_choosing_another_provider_moves_the_selection(qtbot, page):
    _select(qtbot, page, "gmail")
    _select(qtbot, page, "fastmail")

    assert _card(page, "gmail").selected is False
    assert _card(page, "fastmail").selected is True
    assert page.selected_provider.id == "fastmail"


def test_a_card_can_be_selected_from_the_keyboard(qtbot, page):
    gmail = _card(page, "gmail")
    gmail.setFocus()
    qtbot.keyClick(gmail, Qt.Key.Key_Space)

    assert gmail.selected is True
    assert page.selected_provider.id == "gmail"


def test_selecting_a_provider_emits_its_id(qtbot, page):
    with qtbot.waitSignal(page.providerSelected, timeout=1000) as blocker:
        _select(qtbot, page, "icloud")

    assert blocker.args == ["icloud"]


def test_clicking_the_selected_card_keeps_it_selected(qtbot, page):
    _select(qtbot, page, "gmail")
    _select(qtbot, page, "gmail")

    assert _card(page, "gmail").selected is True
    assert page.selected_provider.id == "gmail"


def test_card_labels_do_not_steal_the_click(page):
    gmail = _card(page, "gmail")

    for label in (gmail.title_label, gmail.badge):
        assert label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_a_card_reports_the_honest_status_badge(page):
    outlook = _card(page, "outlook")
    gmail = _card(page, "gmail")

    assert outlook.badge.property("status") == "partial"
    assert outlook.badge.text() == "Limited"
    assert gmail.badge.property("status") == "pass"
    assert gmail.badge.text() == "Tested"


def test_selecting_a_provider_shows_its_note(qtbot, page, app_services):
    _select(qtbot, page, "proton")

    note = app_services.translator.t("provider.proton.note")
    assert page.provider_note.text() == note


# --- Enablement ------------------------------------------------------------


def test_continue_is_disabled_until_a_provider_and_address_are_chosen(qtbot, page):
    assert page.continue_button.isEnabled() is False

    _select(qtbot, page, "gmail")
    assert page.continue_button.isEnabled() is False

    page.email_edit.setText("me@gmail.com")
    assert page.continue_button.isEnabled() is True


def test_a_valid_address_without_a_provider_cannot_continue(page):
    page.email_edit.setText("me@gmail.com")

    assert page.selected_provider is None
    assert page.continue_button.isEnabled() is False


def test_a_valid_address_enables_continue(qtbot, page, app_services):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail.com")

    assert page.continue_button.isEnabled() is True
    assert page.continue_button.text() == app_services.translator.t("provider.continue")


# --- Invalid addresses -----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["me", "me@", "@gmail.com", "me@gmail", "me @gmail.com", "me@.com", "me@gmail..com"],
)
def test_an_invalid_address_keeps_continue_disabled_and_shows_an_error(
    qtbot, page, app_services, text
):
    _select(qtbot, page, "gmail")
    page.email_edit.setText(text)

    assert page.continue_button.isEnabled() is False
    assert page.email_error.isHidden() is False
    assert page.email_error.text() == app_services.translator.t("provider.email.invalid")
    assert page.email_edit.property("invalid") is True


def test_an_empty_field_is_not_an_error(qtbot, page):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail")

    assert page.email_error.isHidden() is False

    page.email_edit.clear()

    assert page.email_error.isHidden() is True
    assert page.email_edit.property("invalid") is False


def test_a_valid_address_clears_the_error(qtbot, page):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail")
    page.email_edit.setText("me@gmail.com")

    assert page.email_error.isHidden() is True
    assert page.email_edit.property("invalid") is False


@pytest.mark.parametrize(
    "text",
    ["me@gmail.com", "first.last+tag@sub.example.co.uk", " a@b.co "],
)
def test_valid_addresses_are_accepted(text):
    assert is_valid_email(normalise_email(text)) is True


@pytest.mark.parametrize("text", ["", "me", "me@", "@gmail.com", "me@gmail", "me@gmail..com"])
def test_incomplete_addresses_are_rejected(text):
    assert is_valid_email(normalise_email(text)) is False


def test_addresses_are_trimmed_and_lowercased():
    assert normalise_email("  Me@Gmail.COM ") == "me@gmail.com"
    assert normalise_email(None) == ""


# --- Handoff ---------------------------------------------------------------


def test_continue_emits_the_provider_id_and_normalised_address(qtbot, page):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("  Me@Gmail.com ")

    with qtbot.waitSignal(page.continueRequested, timeout=1000) as blocker:
        qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert blocker.args == ["gmail", "me@gmail.com"]


def test_continue_saves_the_account_but_never_a_secret(qtbot, page, app_services):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail.com")
    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    stored = app_services.settings.load()
    assert (stored.provider, stored.email) == ("gmail", "me@gmail.com")
    written = app_services.settings.path.read_text(encoding="utf-8").lower()
    assert "password" not in written
    assert "secret" not in written
    assert "token" not in written


def test_the_shell_resolves_the_provider_id(qtbot, window, page):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail.com")
    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert window.pending_provider is not None
    assert window.pending_provider.id == "gmail"
    assert window.pending_email == "me@gmail.com"


def test_continue_preserves_existing_preferences(qtbot, app_services):
    preferences = Preferences(
        categories=["spam"], mode="archive", max_moves=7, language="es"
    )
    app_services.settings.save(
        AppSettings(provider="custom", email="", preferences=preferences)
    )

    window = MainWindow(app_services.settings, app_services.translator, app_services)
    qtbot.addWidget(window)
    page = window.provider_page
    _select(qtbot, page, "custom")
    page.email_edit.setText("me@example.com")
    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    stored = app_services.settings.load()
    assert stored.provider == "custom"
    assert stored.email == "me@example.com"
    assert stored.preferences.categories == ["spam"]
    assert stored.preferences.mode == "archive"
    assert stored.preferences.max_moves == 7


def test_a_previous_account_is_restored_on_start(qtbot, app_services):
    app_services.settings.save(AppSettings(provider="gmail", email="me@gmail.com"))

    window = MainWindow(app_services.settings, app_services.translator, app_services)
    qtbot.addWidget(window)
    page = window.provider_page

    assert page.selected_provider is not None
    assert page.selected_provider.id == "gmail"
    assert page.email_edit.text() == "me@gmail.com"
    assert page.continue_button.isEnabled() is True


def test_a_fresh_install_starts_with_nothing_selected(page):
    assert page.selected_provider is None
    assert page.email_edit.text() == ""
    assert page.provider_note.text() == "Select a provider to continue."


def test_a_language_only_settings_file_does_not_preselect_a_provider(qtbot, app_services):
    app_services.settings.save(AppSettings(provider="custom", email=""))

    window = MainWindow(app_services.settings, app_services.translator, app_services)
    qtbot.addWidget(window)

    assert window.provider_page.selected_provider is None


# --- Language --------------------------------------------------------------


def test_changing_language_updates_the_page_title(window, page):
    assert page.title_label.text() == EN_TITLE

    window.set_language("es")

    assert page.title_label.text() == ES_TITLE


def test_changing_language_updates_the_shell_and_cards(window, page):
    window.set_language("es")

    assert window.windowTitle() == "CleanYourMail — Tu bandeja, sin el ruido."
    assert window.step_labels["provider"].text() == "Proveedor"
    assert window.step_labels["review"].text() == "Revisar"
    assert _card(page, "custom").title_label.text() == "IMAP personalizado"
    assert page.continue_button.text() == "Continuar"


def test_changing_language_back_returns_english(window, page):
    window.set_language("es")
    window.set_language("en")

    assert page.title_label.text() == EN_TITLE
    assert window.step_labels["connect"].text() == "Connect"


def test_switching_language_keeps_the_entered_address(qtbot, page, window):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail.com")

    window.set_language("es")

    assert page.email_edit.text() == "me@gmail.com"
    assert page.continue_button.isEnabled() is True


def test_the_language_choice_is_remembered(window, app_services):
    window.set_language("es")

    assert app_services.settings.load().preferences.language == "es"

# --- Accessibility and settings failures -----------------------------------


def test_the_email_label_is_a_buddy_of_the_email_field(page):
    assert page.email_label.buddy() is page.email_edit


def test_a_settings_write_failure_is_shown_inline(
    qtbot, page, app_services, monkeypatch
):
    _select(qtbot, page, "gmail")
    page.email_edit.setText("me@gmail.com")
    emitted: list[tuple[str, str]] = []
    page.continueRequested.connect(lambda provider, email: emitted.append((provider, email)))

    def fail(settings):
        raise OSError("profile is read-only")

    monkeypatch.setattr(app_services.settings, "save", fail)

    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert emitted == []
    assert page.settings_error.isHidden() is False
    assert page.settings_error.text() == app_services.translator.t(
        "errors.settings_write"
    )


def test_the_header_language_control_is_visible_and_persists(window, page):
    assert window.language_combo.isVisible() is True
    assert window.language_combo.currentData() == "en"
    assert window.language_combo.findData("es") >= 0

    window.language_combo.setCurrentIndex(window.language_combo.findData("es"))

    assert window.translator.language == "es"
    assert page.title_label.text() == window.translator.t("provider.title")
    assert window.windowTitle() == window.translator.t("app.window_title")
    assert window.settings.load_preferences().language == "es"
    assert window.language_combo.currentData() == "es"


def test_switching_language_on_the_preferences_page_keeps_both_controls(
    window
):
    window.set_language("es")

    assert window.language_combo.currentData() == "es"
    assert window.preferences_page.language_combo.currentData() == "es"
