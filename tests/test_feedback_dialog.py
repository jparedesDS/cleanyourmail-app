"""The opt-in feedback dialog and the header button.

No test here touches the network. Every Send goes to a fake
``send_feedback``; opening the dialog may only read local settings and ask the
sidecar for its local version, nothing else.

The dialog receives no ``AppSettings`` and no account address on purpose, so
the tests treat the email, a state path and a token as sentinels that must never
reach the checklist, a label or a status line.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QWidget

from cleanyourmail_app import version
from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.domain.providers import Provider, provider_by_id
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.cli import CliError
from cleanyourmail_app.services.feedback import FeedbackError
from cleanyourmail_app.ui.dialogs import feedback as feedback_dialog
from cleanyourmail_app.ui.dialogs.feedback import FeedbackDialog
from cleanyourmail_app.ui.main_window import MainWindow

APP_VERSION = "0.3.0"
SIDECAR_VERSION = "1.2.2"
WINDOWS_TEXT = "Windows-11-10.0.22631-SP0"
EMAIL_SENTINEL = "account-sentinel@example.com"
PATH_SENTINEL = r"C:\Users\sentinel\AppData\Roaming\cleanyourmail-app"
TOKEN_SENTINEL = "token-sentinel-f3a9"


@pytest.fixture
def preferences() -> Preferences:
    return Preferences(
        categories=["newsletter", "promotion"],
        mode="folders",
        language="en",
    )


@pytest.fixture
def provider() -> Provider:
    return provider_by_id("gmail")


@pytest.fixture
def window(qtbot, app_services) -> MainWindow:
    window = MainWindow(app_services.settings, app_services.translator, app_services)
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.fixture
def dialog(qtbot, monkeypatch, translator, provider, preferences) -> FeedbackDialog:
    monkeypatch.setattr(
        feedback_dialog.platform, "platform", lambda: WINDOWS_TEXT
    )
    dialog = FeedbackDialog(
        APP_VERSION,
        SIDECAR_VERSION,
        provider,
        preferences,
        translator,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _all_text(widget: QWidget) -> str:
    """Every string a person could read in the dialog, for sentinel checks."""
    chunks: list[str] = []
    for child in [widget, *widget.findChildren(QWidget)]:
        for name in ("text", "toPlainText", "placeholderText", "toolTip"):
            getter = getattr(child, name, None)
            if callable(getter):
                value = getter()
                if isinstance(value, str):
                    chunks.append(value)
        if isinstance(child, QComboBox):
            chunks.extend(child.itemText(index) for index in range(child.count()))
    return "\n".join(chunks)


# --- Header button ---------------------------------------------------------


def test_the_feedback_button_is_in_the_header_on_every_page(window, translator):
    button = window.feedback_button

    assert button.objectName() == "feedbackButton"
    assert button.text() == translator.t("feedback.open")
    assert button.accessibleName() == translator.t("feedback.open")

    for page in ("provider", "connect", "preferences", "review", "provider"):
        window.show_page(page)
        assert button.isVisible(), page


def test_the_header_button_follows_the_language(window, app_services):
    window.set_language("es")

    assert window.feedback_button.text() == Translator("es").t("feedback.open")
    assert window.feedback_button.accessibleName() == Translator("es").t(
        "feedback.open"
    )


def test_clicking_the_header_button_opens_the_dialog_with_safe_arguments(
    qtbot, window, app_services, monkeypatch
):
    stored = Preferences(
        categories=["social"],
        mode="archive",
        language="es",
    )
    app_services.settings.save(
        AppSettings(provider="gmail", email=EMAIL_SENTINEL, preferences=stored)
    )
    captured: dict[str, object] = {}

    class _Finished:
        def connect(self, slot) -> None:
            captured["finished_connected"] = True

    class FakeDialog:
        def __init__(
            self,
            app_version,
            sidecar_version,
            provider,
            preferences,
            translator,
            parent=None,
        ):
            captured.update(
                app_version=app_version,
                sidecar_version=sidecar_version,
                provider=provider,
                preferences=preferences,
                translator=translator,
                parent=parent,
            )
            self.finished = _Finished()

        def deleteLater(self) -> None:
            captured["deleted"] = True

        def exec(self) -> int:
            captured["executed"] = True
            return 1

    monkeypatch.setattr(
        "cleanyourmail_app.ui.main_window.FeedbackDialog", FakeDialog
    )
    monkeypatch.setattr(app_services.cli, "version", lambda: "CleanYourMail 1.2.2")
    monkeypatch.setattr(
        app_services.cli,
        "run",
        lambda *args, **kwargs: pytest.fail("opening feedback must not run the sidecar"),
    )

    qtbot.mouseClick(window.feedback_button, Qt.MouseButton.LeftButton)

    assert captured["executed"] is True
    assert captured["app_version"] == version.__version__
    assert captured["sidecar_version"] == SIDECAR_VERSION
    assert captured["provider"].id == "gmail"
    assert captured["preferences"] == stored
    assert captured["translator"] is window.translator
    assert captured["parent"] is window
    assert EMAIL_SENTINEL not in repr(captured)
    assert captured["finished_connected"] is True


def test_opening_feedback_handles_a_missing_sidecar(
    qtbot, window, app_services, monkeypatch
):
    captured: dict[str, object] = {}

    class _Finished:
        def connect(self, slot) -> None:
            return None

    class FakeDialog:
        def __init__(self, app_version, sidecar_version, *args):
            captured["sidecar_version"] = sidecar_version
            self.finished = _Finished()

        def deleteLater(self) -> None:
            return None

        def exec(self) -> int:
            return 1

    def missing() -> str:
        raise CliError("sidecar not found")

    monkeypatch.setattr(
        "cleanyourmail_app.ui.main_window.FeedbackDialog", FakeDialog
    )
    monkeypatch.setattr(app_services.cli, "version", missing)

    qtbot.mouseClick(window.feedback_button, Qt.MouseButton.LeftButton)

    assert captured["sidecar_version"] == "unknown"


def test_repeated_opens_do_not_accumulate_dialogs(
    qtbot, window, app_services, monkeypatch
):
    class FakeDialog(QDialog):
        created: list[FakeDialog] = []

        def __init__(
            self,
            app_version,
            sidecar_version,
            provider,
            preferences,
            translator,
            parent=None,
        ):
            super().__init__(parent)
            type(self).created.append(self)

        def exec(self) -> int:
            self.finished.emit(0)
            return 0

    version_calls: list[str] = []

    def read_version() -> str:
        version_calls.append("read")
        return "CleanYourMail 1.2.2"

    monkeypatch.setattr(
        "cleanyourmail_app.ui.main_window.FeedbackDialog", FakeDialog
    )
    monkeypatch.setattr(app_services.cli, "version", read_version)

    for _ in range(2):
        qtbot.mouseClick(window.feedback_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(
            lambda: not window.findChildren(FakeDialog),
            timeout=2000,
        )

    assert len(FakeDialog.created) == 2
    assert window.findChildren(FakeDialog) == []
    # The first successful read is reused; the second open starts no sidecar.
    assert version_calls == ["read"]


def test_opening_and_closing_the_real_dialog_does_not_double_delete(
    qtbot, window, app_services, monkeypatch
):
    monkeypatch.setattr(window, "_sidecar_version", lambda: SIDECAR_VERSION)

    def close_modal() -> None:
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.reject()

    QTimer.singleShot(50, close_modal)
    window._open_feedback()
    qtbot.wait(50)

    assert window.findChildren(FeedbackDialog) == []


# --- Dialog shape and prefill ---------------------------------------------


def test_the_dialog_is_modal_and_scrollable(dialog):
    assert dialog.isModal() is True
    assert dialog.scroll.widgetResizable() is True
    assert dialog.contact_edit.maxLength() == 200
    assert [dialog.kind_combo.itemData(index) for index in range(dialog.kind_combo.count())] == [
        "feedback",
        "bug",
    ]


def test_the_checklist_contains_only_reviewed_facts(dialog):
    text = dialog.checklist_edit.toPlainText()

    assert f"CleanYourMail app {APP_VERSION}" in text
    assert f"Sidecar: {SIDECAR_VERSION}" in text
    assert f"Windows: {WINDOWS_TEXT}" in text
    assert "Provider: Gmail" in text
    assert "Mode: folders" in text
    assert "Categories: newsletter, promotion" in text
    assert "Language: en" in text

    lowered = text.lower()
    for sentinel in (
        EMAIL_SENTINEL,
        PATH_SENTINEL,
        TOKEN_SENTINEL,
        "<abc@example>",
        "password",
        "cookie",
        "authorization",
    ):
        assert sentinel.lower() not in lowered
    assert "\\users" not in lowered
    assert "c:" not in lowered


def test_the_copy_mentions_telemetry_and_what_not_to_include(dialog):
    body = f"{dialog.body_label.text()} {dialog.checklist_help.text()}".lower()

    assert "telemetry" in body
    for forbidden in ("password", "token", "email address", "subject", "message id"):
        assert forbidden in body


def test_retranslate_refreshes_every_visible_string(qtbot, provider, preferences):
    translator = Translator("en")
    dialog = FeedbackDialog(
        APP_VERSION,
        SIDECAR_VERSION,
        provider,
        preferences,
        translator,
    )
    qtbot.addWidget(dialog)

    translator.set_language("es")
    dialog.retranslate()

    assert dialog.windowTitle() == translator.t("feedback.title")
    assert dialog.title_label.text() == translator.t("feedback.title")
    assert dialog.body_label.text() == translator.t("feedback.body")
    assert dialog.kind_combo.itemText(0) == translator.t("feedback.kind_feedback")
    assert dialog.kind_combo.itemText(1) == translator.t("feedback.kind_bug")
    assert dialog.message_edit.placeholderText() == translator.t(
        "feedback.message_placeholder"
    )
    assert dialog.contact_edit.placeholderText() == translator.t(
        "feedback.contact_placeholder"
    )
    assert dialog.consent_checkbox.text() == translator.t("feedback.consent")
    assert dialog.send_button.text() == translator.t("feedback.send")
    assert dialog.close_button.text() == translator.t("feedback.close")
    assert dialog.send_button.accessibleName() == translator.t("feedback.send")


# --- Validation and consent ------------------------------------------------


def test_send_without_consent_shows_the_consent_error(
    qtbot, dialog, monkeypatch, translator
):
    calls: list[object] = []
    monkeypatch.setattr(
        feedback_dialog, "send_feedback", lambda payload: calls.append(payload)
    )
    dialog.message_edit.setPlainText("A small idea for the review page.")

    qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)

    assert dialog.status_label.text() == translator.t("feedback.consent_required")
    assert calls == []


def test_send_with_an_empty_message_and_checklist_shows_empty(
    qtbot, dialog, monkeypatch, translator
):
    calls: list[object] = []
    monkeypatch.setattr(
        feedback_dialog, "send_feedback", lambda payload: calls.append(payload)
    )
    dialog.message_edit.clear()
    dialog.checklist_edit.clear()
    dialog.consent_checkbox.setChecked(True)

    qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)

    assert dialog.status_label.text() == translator.t("feedback.empty")
    assert calls == []


# --- Sending ---------------------------------------------------------------


def test_a_valid_send_runs_off_the_ui_thread_and_shows_sent(
    qtbot, dialog, monkeypatch, translator
):
    started = threading.Event()
    release = threading.Event()
    sent: list[object] = []
    worker_threads: list[int] = []

    def fake_send(payload) -> None:
        sent.append(payload)
        worker_threads.append(threading.get_ident())
        started.set()
        release.wait(5)

    monkeypatch.setattr(feedback_dialog, "send_feedback", fake_send)
    dialog.kind_combo.setCurrentIndex(1)
    dialog.message_edit.setPlainText("The review screen could explain what moves.")
    dialog.contact_edit.setText("tester#1234")
    dialog.consent_checkbox.setChecked(True)

    try:
        qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)

        assert started.wait(3)
        assert dialog.send_button.isEnabled() is False
        assert dialog.message_edit.isEnabled() is False
        assert dialog.checklist_edit.isEnabled() is False
        assert dialog.contact_edit.isEnabled() is False
        assert dialog.kind_combo.isEnabled() is False
        assert dialog.consent_checkbox.isEnabled() is False
        assert dialog.status_label.text() == translator.t("feedback.sending")
        assert dialog.status_label.property("role") == "muted"
    finally:
        release.set()

    qtbot.waitUntil(
        lambda: dialog.status_label.text() == translator.t("feedback.sent"),
        timeout=5000,
    )
    assert len(sent) == 1
    payload = sent[0]
    assert payload.kind == "bug"
    assert payload.message == "The review screen could explain what moves."
    assert payload.checklist == dialog.checklist_edit.toPlainText().strip()
    assert payload.contact == "tester#1234"
    assert (
        payload.app_version
        == f"CleanYourMail app {APP_VERSION} / sidecar {SIDECAR_VERSION}"
    )
    assert payload.as_dict()["website"] == ""
    assert worker_threads and worker_threads[0] != threading.get_ident()
    assert dialog.send_button.isEnabled() is True
    assert dialog.message_edit.isEnabled() is True
    assert dialog.consent_checkbox.isEnabled() is True
    assert dialog.status_label.property("role") == "success"
    # The text is kept after a successful send so nothing has to be retyped.
    assert dialog.message_edit.toPlainText() == (
        "The review screen could explain what moves."
    )


def test_closing_while_sending_waits_briefly_and_worker_finishes_cleanly(
    qtbot, dialog, monkeypatch, translator
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def fake_send(payload) -> None:
        started.set()
        release.wait(5)
        finished.set()

    monkeypatch.setattr(feedback_dialog, "send_feedback", fake_send)
    dialog.message_edit.setPlainText("Please close this while it is sending.")
    dialog.consent_checkbox.setChecked(True)
    qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)
    assert started.wait(3)

    began = time.monotonic()
    try:
        # The Close button calls reject(), which never emits a QCloseEvent.
        qtbot.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
        elapsed = time.monotonic() - began
        assert elapsed < 2
        assert dialog.isVisible() is False
    finally:
        release.set()

    qtbot.waitUntil(finished.is_set, timeout=5000)
    # The late signal is delivered to a hidden but live dialog without error.
    qtbot.waitUntil(lambda: dialog.send_button.isEnabled(), timeout=5000)
    assert dialog.status_label.text() == translator.t("feedback.sent")


@pytest.mark.parametrize(
    "key",
    ["feedback.rate_limited", "feedback.not_configured", "feedback.failed"],
)
def test_a_failed_send_shows_the_localized_error(
    qtbot, dialog, monkeypatch, translator, key
):
    def fail(payload) -> None:
        raise FeedbackError(key)

    monkeypatch.setattr(feedback_dialog, "send_feedback", fail)
    dialog.message_edit.setPlainText("A normal report.")
    dialog.consent_checkbox.setChecked(True)

    qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: dialog.status_label.text() == translator.t(key), timeout=5000
    )
    assert dialog.status_label.text() == translator.t(key)
    assert dialog.status_label.property("role") == "error"
    assert dialog.send_button.isEnabled() is True


def test_an_unexpected_error_is_generic_and_does_not_leak_its_text(
    qtbot, dialog, monkeypatch, translator
):
    def fail(payload) -> None:
        raise RuntimeError(f"private failure {TOKEN_SENTINEL} {PATH_SENTINEL}")

    monkeypatch.setattr(feedback_dialog, "send_feedback", fail)
    dialog.message_edit.setPlainText("A normal report.")
    dialog.consent_checkbox.setChecked(True)

    qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: dialog.status_label.text() == translator.t("feedback.failed"),
        timeout=5000,
    )
    text = _all_text(dialog)
    assert TOKEN_SENTINEL not in text
    assert PATH_SENTINEL not in text
    assert dialog.status_label.text() == translator.t("feedback.failed")


def test_no_secret_sentinel_reaches_any_dialog_text(
    qtbot, dialog, monkeypatch, translator
):
    monkeypatch.setattr(feedback_dialog, "send_feedback", lambda payload: None)
    dialog.message_edit.setPlainText("The undo note could be clearer.")
    dialog.contact_edit.setText("tester")
    dialog.consent_checkbox.setChecked(True)

    qtbot.mouseClick(dialog.send_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(
        lambda: dialog.status_label.text() == translator.t("feedback.sent"),
        timeout=5000,
    )
    text = _all_text(dialog).lower()
    for sentinel in (EMAIL_SENTINEL, PATH_SENTINEL, TOKEN_SENTINEL):
        assert sentinel.lower() not in text
    assert "authorization" not in text
    assert "bearer" not in text
