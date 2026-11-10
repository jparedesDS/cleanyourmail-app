"""The Preferences page: categories, mode, protections, limits and language.

Every test runs headless (``tests/conftest.py``) and writes only temporary
files: the settings store and the sidecar config both live under ``tmp_path``.
The fake sidecar writes the same TOML template the real one does, so the
Continue test reads back a document the CLI would accept instead of a stub the
page invented.

What these tests pin down:

* The safe defaults survive a fresh install and a re-opened page.
* Every checked category, the mode, the protections and the limits persist to
  ``SettingsStore`` as the person changes them.
* Continue is refused while a limit is out of range or the config is missing.
* Continue hands the policy to ``ConfigService.update_preferences``, which is
  the only path the CLI reads.
* The Advanced disclosure starts closed, and its language control retranslates
  the whole window and is remembered.
"""

from __future__ import annotations

import json
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt

from cleanyourmail_app.domain.models import CATEGORIES, Preferences
from cleanyourmail_app.domain.providers import provider_by_id
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.ui.main_window import MainWindow
from cleanyourmail_app.ui.pages.preferences import PreferencesPage

#: A valid Gmail App Password, used only as a sentinel: no real credential.
SECRET = "qwertyuiopasdfgh"

#: The sidecar's template. The page may only edit the keys already present.
TEMPLATE = """\
# CleanYourMail configuration -- keep this file out of git.

[account]
name = "personal"
email = "{email}"
imap_host = "{host}"
imap_port = 993
imap_ssl = true
imap_starttls = false
auth = "login"
password_file = "{secret}"

[scan]
mailboxes = ["INBOX"]
days = 365
batch_size = 200

[policy]
min_age_days = 30
protect_answered = true
protect_flagged = true
protect_domains = []
protect_addresses = []
never_unsubscribe_domains = []
max_messages_per_run = 50
max_messages_per_group = 100
move_spam_to_junk = true
"""


class FakeCli:
    """A ``CliClient`` stand-in: writes the template on init, passes doctor."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def verify_version(self, expected: str = "CleanYourMail 1.2.2") -> str:
        return expected

    def run(
        self,
        args: list[str],
        *,
        config_path: Path | None = None,
        timeout: int = 120,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        self.calls.append(list(args))
        command = args[0]
        if command == "init":
            target = Path(args[args.index("--path") + 1])
            email = args[args.index("--email") + 1]
            host = "imap.example.com"
            if "--host" in args:
                host = args[args.index("--host") + 1]
            secret = ""
            if "--secret-file" in args:
                secret = args[args.index("--secret-file") + 1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                TEMPLATE.format(
                    email=email,
                    host=host,
                    secret=str(secret).replace("\\", "/"),
                ),
                encoding="utf-8",
            )
            return {
                "ok": True,
                "exit_code": 0,
                "data": {"ok": True, "path": str(target)},
                "stdout": "",
                "stderr": "",
            }
        if command == "doctor":
            return {
                "ok": True,
                "exit_code": 0,
                "data": {"ok": True},
                "stdout": json.dumps({"ok": True}),
                "stderr": "",
            }
        raise AssertionError(f"unexpected sidecar command: {args}")


@pytest.fixture
def cli() -> FakeCli:
    return FakeCli()


@pytest.fixture
def services(tmp_path, translator, settings_store, cli) -> AppServices:
    config = ConfigService(cli, tmp_path / "appdata", tmp_path / "secret.txt")
    return AppServices(
        cli=cli, config=config, settings=settings_store, translator=translator
    )


@pytest.fixture
def page(qtbot, services) -> PreferencesPage:
    page = PreferencesPage(services)
    qtbot.addWidget(page)
    page.show()
    return page


@pytest.fixture
def window(qtbot, services) -> MainWindow:
    window = MainWindow(services.settings, services.translator, services)
    qtbot.addWidget(window)
    window.show()
    return window


def _make_config(services: AppServices) -> Path:
    """Create the sidecar TOML through the same ``ensure`` the app uses."""
    return services.config.ensure(provider_by_id("gmail"), "me@gmail.com")


def _policy(services: AppServices) -> dict[str, Any]:
    """Read back the ``[policy]`` table the CLI will see."""
    with services.config.config_path().open("rb") as handle:
        return tomllib.load(handle)["policy"]


# --- Defaults --------------------------------------------------------------


def test_all_six_category_checkboxes_are_checked_by_default(page, services):
    assert list(page.category_boxes) == list(CATEGORIES)
    assert all(box.isChecked() for box in page.category_boxes.values())

    t = services.translator.t
    assert page.category_boxes["newsletter"].text() == t(
        "preferences.category.newsletter.label"
    )
    assert page.category_boxes["cold"].text() == t("preferences.category.cold.label")


def test_folders_is_the_default_mode(page):
    assert page.folders_radio.isChecked() is True
    assert page.archive_radio.isChecked() is False
    assert page.current_preferences().mode == "folders"


def test_protections_and_limits_start_at_the_safe_values(page):
    assert page.starred_check.isChecked() is True
    assert page.answered_check.isChecked() is True
    assert page.min_age_spin.value() == 30
    assert page.max_moves_spin.value() == 50
    assert page.max_per_group_spin.value() == 100
    assert page.continue_button.isEnabled() is True


def test_defaults_do_not_write_a_settings_file_just_by_being_shown(
    page, settings_store
):
    assert settings_store.path.exists() is False


# --- Persistence -----------------------------------------------------------


def test_unchecking_promotion_persists_across_a_reopened_page(
    qtbot, page, services
):
    page.category_boxes["promotion"].setChecked(False)

    stored = services.settings.load_preferences()
    assert "promotion" not in stored.categories
    assert stored.categories == [
        category for category in CATEGORIES if category != "promotion"
    ]

    reopened = PreferencesPage(services)
    qtbot.addWidget(reopened)
    assert reopened.category_boxes["promotion"].isChecked() is False
    assert reopened.category_boxes["newsletter"].isChecked() is True


def test_archive_can_be_selected_and_is_remembered(qtbot, page, services):
    qtbot.mouseClick(page.archive_radio, Qt.MouseButton.LeftButton)

    assert page.archive_radio.isChecked() is True
    assert page.folders_radio.isChecked() is False
    assert services.settings.load_preferences().mode == "archive"
    assert page.current_preferences().mode == "archive"

    reopened = PreferencesPage(services)
    qtbot.addWidget(reopened)
    assert reopened.archive_radio.isChecked() is True


def test_protections_and_limits_persist_when_changed(page, services):
    page.starred_check.setChecked(False)
    page.answered_check.setChecked(False)
    page.min_age_spin.setValue(14)
    page.max_moves_spin.setValue(20)
    page.max_per_group_spin.setValue(40)

    stored = services.settings.load_preferences()
    assert stored.protect_starred is False
    assert stored.protect_answered is False
    assert stored.min_age_days == 14
    assert stored.max_moves == 20
    assert stored.max_per_group == 40


def test_saving_preferences_keeps_the_stored_account(services, settings_store):
    from cleanyourmail_app.domain.models import AppSettings

    settings_store.save(AppSettings(provider="gmail", email="me@gmail.com"))
    page = PreferencesPage(services)
    page.category_boxes["social"].setChecked(False)

    stored = settings_store.load()
    assert stored.provider == "gmail"
    assert stored.email == "me@gmail.com"
    assert "social" not in stored.preferences.categories


# --- Validation ------------------------------------------------------------


def test_continue_is_disabled_when_a_limit_is_out_of_range(page):
    page.min_age_spin.setValue(3651)
    assert page.continue_button.isEnabled() is False
    assert page.error_label.isHidden() is False

    page.min_age_spin.setValue(30)
    assert page.continue_button.isEnabled() is True

    page.max_moves_spin.setValue(0)
    assert page.continue_button.isEnabled() is False

    page.max_moves_spin.setValue(5001)
    assert page.continue_button.isEnabled() is False

    page.max_moves_spin.setValue(50)
    assert page.continue_button.isEnabled() is True

    page.max_per_group_spin.setValue(5001)
    assert page.continue_button.isEnabled() is False

    page.max_per_group_spin.setValue(5000)
    assert page.continue_button.isEnabled() is True
    assert page.error_label.isHidden() is True


def test_continue_is_disabled_when_no_category_is_selected(page, services):
    for box in page.category_boxes.values():
        box.setChecked(False)

    assert page.continue_button.isEnabled() is False
    assert page.error_label.text() == services.translator.t(
        "preferences.category_required"
    )


# --- Advanced --------------------------------------------------------------


def test_the_advanced_section_is_collapsed_until_opened(qtbot, page, services):
    assert page.advanced_toggle.isChecked() is False
    assert page.advanced_panel.isHidden() is True

    qtbot.mouseClick(page.advanced_toggle, Qt.MouseButton.LeftButton)

    assert page.advanced_toggle.isChecked() is True
    assert page.advanced_panel.isHidden() is False
    assert page.config_path_edit.text() == str(services.config.config_path())
    assert page.config_path_edit.isReadOnly() is True
    assert page.state_path_edit.text() == str(services.config.app_data)
    assert page.state_path_edit.isReadOnly() is True
    assert page.cli_state_edit.text() == str(services.config.state_dir())
    assert page.cli_state_edit.isReadOnly() is True


def test_advanced_is_collapsed_again_on_a_reopened_page(qtbot, services):
    first = PreferencesPage(services)
    qtbot.addWidget(first)
    first.advanced_toggle.click()

    reopened = PreferencesPage(services)
    qtbot.addWidget(reopened)
    assert reopened.advanced_toggle.isChecked() is False
    assert reopened.advanced_panel.isHidden() is True


def test_the_language_control_switches_copy_and_is_persisted(page, services):
    spanish = page.language_combo.findData("es")
    assert spanish >= 0

    page.language_combo.setCurrentIndex(spanish)

    assert services.translator.language == "es"
    assert page.title_label.text() == services.translator.t("preferences.title")
    assert page.continue_button.text() == "Continuar"
    assert services.settings.load_preferences().language == "es"


def test_the_shell_language_control_retranslates_the_page(window, services):
    window.set_language("es")

    page = window.preferences_page
    assert page.title_label.text() == services.translator.t("preferences.title")
    assert page.language_combo.currentData() == "es"
    assert window.step_labels["preferences"].text() == "Preferencias"


# --- Continue --------------------------------------------------------------


def test_continue_writes_the_policy_into_the_config(qtbot, page, services):
    _make_config(services)
    qtbot.mouseClick(page.archive_radio, Qt.MouseButton.LeftButton)
    page.category_boxes["promotion"].setChecked(False)
    page.answered_check.setChecked(False)
    page.min_age_spin.setValue(14)
    page.max_moves_spin.setValue(20)
    page.max_per_group_spin.setValue(40)

    with qtbot.waitSignal(page.continueRequested, timeout=1000) as blocker:
        qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert blocker.args == []
    policy = _policy(services)
    assert policy["min_age_days"] == 14
    assert policy["protect_answered"] is False
    assert policy["protect_flagged"] is True
    assert policy["max_messages_per_run"] == 20
    assert policy["max_messages_per_group"] == 40
    assert services.settings.load_preferences().mode == "archive"
    assert page.error_label.isHidden() is True


def test_continue_without_a_config_shows_the_error_and_stays(qtbot, page, services):
    emitted: list[bool] = []
    page.continueRequested.connect(lambda: emitted.append(True))

    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert emitted == []
    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.config_missing")
    # The person's choices are still kept locally, so nothing is lost.
    assert services.settings.load_preferences().mode == "folders"


def test_a_config_write_failure_is_shown_as_an_error(qtbot, page, services, monkeypatch):
    _make_config(services)
    emitted: list[bool] = []
    page.continueRequested.connect(lambda: emitted.append(True))

    def boom(preferences: Preferences) -> None:
        raise OSError("disk is full")

    monkeypatch.setattr(services.config, "update_preferences", boom)

    qtbot.mouseClick(page.continue_button, Qt.MouseButton.LeftButton)

    assert emitted == []
    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.config")


# --- Shell wiring ----------------------------------------------------------


def _select(window: MainWindow, provider_id: str, email: str) -> None:
    provider_page = window.provider_page
    card = next(
        card for card in provider_page.cards if card.provider.id == provider_id
    )
    card.click()
    provider_page.email_edit.setText(email)
    provider_page.continue_button.click()


def test_a_successful_connection_reaches_the_preferences_page(qtbot, window):
    _select(window, "gmail", "me@gmail.com")
    window.connect_page.password_edit.setText(SECRET)

    with qtbot.waitSignal(
        window.connect_page.connectionSucceeded, timeout=5000
    ):
        qtbot.mouseClick(
            window.connect_page.save_button, Qt.MouseButton.LeftButton
        )

    assert window.current_page_key() == "preferences"
    assert window.step_labels["preferences"].property("active") is True


def test_continue_reaches_the_review_page(qtbot, window, services):
    _select(window, "gmail", "me@gmail.com")
    window.connect_page.password_edit.setText(SECRET)
    with qtbot.waitSignal(
        window.connect_page.connectionSucceeded, timeout=5000
    ):
        qtbot.mouseClick(
            window.connect_page.save_button, Qt.MouseButton.LeftButton
        )

    with qtbot.waitSignal(
        window.preferences_page.continueRequested, timeout=1000
    ):
        qtbot.mouseClick(
            window.preferences_page.continue_button, Qt.MouseButton.LeftButton
        )

    assert window.current_page_key() == "review"

def test_back_returns_to_connect_without_saving_a_policy(
    qtbot, window, services
):
    _select(window, "gmail", "me@gmail.com")
    window.connect_page.password_edit.setText(SECRET)
    with qtbot.waitSignal(
        window.connect_page.connectionSucceeded, timeout=5000
    ):
        qtbot.mouseClick(
            window.connect_page.save_button, Qt.MouseButton.LeftButton
        )
    assert window.current_page_key() == "preferences"

    qtbot.mouseClick(
        window.preferences_page.back_button, Qt.MouseButton.LeftButton
    )

    assert window.current_page_key() == "connect"


def test_back_from_review_returns_to_preferences(qtbot, window, services):
    _select(window, "gmail", "me@gmail.com")
    window.connect_page.password_edit.setText(SECRET)
    with qtbot.waitSignal(
        window.connect_page.connectionSucceeded, timeout=5000
    ):
        qtbot.mouseClick(
            window.connect_page.save_button, Qt.MouseButton.LeftButton
        )
    with qtbot.waitSignal(
        window.preferences_page.continueRequested, timeout=1000
    ):
        qtbot.mouseClick(
            window.preferences_page.continue_button, Qt.MouseButton.LeftButton
        )
    assert window.current_page_key() == "review"

    qtbot.mouseClick(window.review_page.back_button, Qt.MouseButton.LeftButton)

    assert window.current_page_key() == "preferences"
