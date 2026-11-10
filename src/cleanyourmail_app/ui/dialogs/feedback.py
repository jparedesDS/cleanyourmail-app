"""The opt-in feedback dialog: explicit consent, editable checklist, no telemetry.

The dialog receives only the non-sensitive facts it may show: the app version,
the sidecar version, the provider label, the cleaning preferences and the
translator. It never sees the account address, a config path, a token or a
message. Nothing is sent until the person presses Send and accepts the consent
line; the HTTP call runs on the shared thread pool so the window stays
responsive while it waits.
"""

from __future__ import annotations

import platform

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.feedback import (
    FEEDBACK_KINDS,
    build_checklist,
    feedback_payload,
    validate_feedback,
)
from cleanyourmail_app.domain.models import Preferences
from cleanyourmail_app.domain.providers import Provider
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.feedback import FeedbackError, send_feedback
from cleanyourmail_app.ui.style import set_dynamic_property


class _FeedbackSignals(QObject):
    """Carry one already-localized status key back to the dialog.

    The worker never sends an exception message: an unexpected failure is the
    generic ``feedback.failed`` key, so no path, token or server text can reach
    a label by accident.
    """

    finished = Signal(str)


class _FeedbackJob(QRunnable):
    """Run one HTTP POST without blocking the UI thread."""

    def __init__(self, payload: object, signals: _FeedbackSignals) -> None:
        super().__init__()
        self._payload = payload
        self._signals = signals

    def run(self) -> None:  # noqa: D401 - QRunnable's contract
        key = ""
        try:
            send_feedback(self._payload)  # type: ignore[arg-type]
        except FeedbackError as error:
            key = error.key
        except Exception:
            # The exception text may contain a path or a token; it is never
            # rendered or logged. The person sees the generic failure copy.
            key = "feedback.failed"
        try:
            self._signals.finished.emit(key)
        except RuntimeError:
            # The dialog closed while the request was still in flight.
            pass


class FeedbackDialog(QDialog):
    """A local form that sends only after an explicit Send and consent."""

    def __init__(
        self,
        app_version: str,
        sidecar_version: str,
        provider: Provider | None,
        preferences: Preferences,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._app_version = app_version
        self._sidecar_version = sidecar_version
        self._provider = provider
        self._preferences = preferences
        self._translator = translator
        self._busy = False
        self._status_key: str | None = None
        self._status_role = "muted"
        self._worker_waited = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _FeedbackSignals()
        self._signals.finished.connect(self._on_finished)

        self._build_ui()
        self.retranslate()

    # -- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("feedbackDialog")
        self.setModal(True)
        self.setMinimumSize(620, 560)
        self.resize(680, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("feedbackScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget(self.scroll)
        content.setObjectName("feedbackContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)

        self.title_label = QLabel(content)
        self.title_label.setObjectName("feedbackTitle")
        self.title_label.setWordWrap(True)

        self.body_label = QLabel(content)
        self.body_label.setObjectName("feedbackBody")
        self.body_label.setWordWrap(True)

        self.kind_label = QLabel(content)
        self.kind_combo = QComboBox(content)
        self.kind_combo.setObjectName("feedbackKind")
        for kind in FEEDBACK_KINDS:
            self.kind_combo.addItem("", kind)

        self.message_label = QLabel(content)
        self.message_edit = QTextEdit(content)
        self.message_edit.setObjectName("feedbackMessage")
        self.message_edit.setFixedHeight(120)

        self.checklist_label = QLabel(content)
        self.checklist_edit = QTextEdit(content)
        self.checklist_edit.setObjectName("feedbackChecklist")
        self.checklist_edit.setFixedHeight(170)

        self.checklist_help = QLabel(content)
        self.checklist_help.setObjectName("feedbackChecklistHelp")
        self.checklist_help.setWordWrap(True)

        self.contact_label = QLabel(content)
        self.contact_edit = QLineEdit(content)
        self.contact_edit.setObjectName("feedbackContact")
        self.contact_edit.setMaxLength(200)

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addWidget(self.kind_label)
        layout.addWidget(self.kind_combo)
        layout.addWidget(self.message_label)
        layout.addWidget(self.message_edit)
        layout.addWidget(self.checklist_label)
        layout.addWidget(self.checklist_edit)
        layout.addWidget(self.checklist_help)
        layout.addWidget(self.contact_label)
        layout.addWidget(self.contact_edit)
        layout.addStretch(1)

        self.consent_checkbox = QCheckBox(self)
        self.consent_checkbox.setObjectName("feedbackConsent")

        self.status_label = QLabel(self)
        self.status_label.setObjectName("feedbackStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "muted")
        self.status_label.hide()

        self.send_button = QPushButton(self)
        self.send_button.setObjectName("feedbackSend")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self.send)

        self.close_button = QPushButton(self)
        self.close_button.setObjectName("feedbackClose")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.close_button)
        buttons.addStretch(1)

        footer = QWidget(self)
        footer.setObjectName("feedbackFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(28, 10, 28, 18)
        footer_layout.setSpacing(8)
        footer_layout.addWidget(self.consent_checkbox)
        footer_layout.addWidget(self.status_label)
        footer_layout.addLayout(buttons)

        self.scroll.setWidget(content)
        outer.addWidget(self.scroll, 1)
        outer.addWidget(footer)

        self._prefill_checklist()

    def _prefill_checklist(self) -> None:
        """Show only the facts the design reviewed; nothing account-specific."""
        provider_label = self._provider.label if self._provider is not None else ""
        checklist = build_checklist(
            app_version=self._app_version,
            sidecar_version=self._sidecar_version,
            provider=provider_label,
            mode=self._preferences.mode,
            categories=self._preferences.categories,
            language=self._translator.language,
            windows_version=platform.platform(),
        )
        self.checklist_edit.setPlainText(checklist)

    # -- sending ------------------------------------------------------------

    def send(self) -> None:
        """Validate locally, then start one worker; never send implicitly."""
        if self._busy:
            return

        kind = str(self.kind_combo.currentData() or "")
        message = self.message_edit.toPlainText()
        checklist = self.checklist_edit.toPlainText()
        contact = self.contact_edit.text()

        key = validate_feedback(
            kind=kind,
            message=message,
            checklist=checklist,
            contact=contact,
        )
        if key is not None:
            self._show_status(key, role="error")
            return
        if not self.consent_checkbox.isChecked():
            self._show_status("feedback.consent_required", role="error")
            return

        payload = feedback_payload(
            kind=kind,
            message=message,
            checklist=checklist,
            contact=contact,
            app_version=(
                f"CleanYourMail app {self._app_version}"
                f" / sidecar {self._sidecar_version}"
            ),
        )
        self._set_busy(True)
        self._show_status("feedback.sending", role="muted")
        try:
            self._pool.start(_FeedbackJob(payload, self._signals))
        except RuntimeError:
            # The pool is shutting down with the application.
            self._set_busy(False)
            self._show_status("feedback.failed", role="error")

    def _on_finished(self, key: str) -> None:
        self._set_busy(False)
        if key:
            self._show_status(key, role="error")
        else:
            self._show_status("feedback.sent", role="success")

    def _set_busy(self, busy: bool) -> None:
        """Disable the form while the request is in flight."""
        self._busy = busy
        for widget in (
            self.kind_combo,
            self.message_edit,
            self.checklist_edit,
            self.contact_edit,
            self.consent_checkbox,
            self.send_button,
        ):
            widget.setEnabled(not busy)
        self.send_button.setText(
            self._translator.t("feedback.sending" if busy else "feedback.send")
        )

    def _show_status(self, key: str, *, role: str = "success") -> None:
        """Show one localized status line; ``sending`` stays muted, not green."""
        self._status_key = key
        self._status_role = role
        self.status_label.setText(self._translator.t(key))
        set_dynamic_property(self.status_label, "role", role)
        self.status_label.show()

    def _wait_for_worker(self) -> None:
        """Give an in-flight request one bounded grace period, once."""
        if self._worker_waited or not self._busy:
            return
        self._worker_waited = True
        self._pool.waitForDone(500)

    def done(self, result: int) -> None:  # noqa: N802 - Qt's contract
        """Cover Close, Esc and ``reject()``; they never fire a close event."""
        self._wait_for_worker()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's contract
        """A window close waits through ``done``; do not wait twice."""
        self._wait_for_worker()
        super().closeEvent(event)

    # -- translation --------------------------------------------------------

    def retranslate(self) -> None:
        """Refresh the title, labels, placeholders, buttons and a11y names."""
        t = self._translator.t
        self.setWindowTitle(t("feedback.title"))
        self.title_label.setText(t("feedback.title"))
        self.body_label.setText(t("feedback.body"))
        self.kind_label.setText(t("feedback.kind"))
        self.kind_combo.setItemText(0, t("feedback.kind_feedback"))
        self.kind_combo.setItemText(1, t("feedback.kind_bug"))
        self.message_label.setText(t("feedback.message"))
        self.message_edit.setPlaceholderText(t("feedback.message_placeholder"))
        self.checklist_label.setText(t("feedback.checklist"))
        self.checklist_help.setText(t("feedback.checklist_help"))
        self.contact_label.setText(t("feedback.contact"))
        self.contact_edit.setPlaceholderText(t("feedback.contact_placeholder"))
        self.consent_checkbox.setText(t("feedback.consent"))
        self.send_button.setText(
            t("feedback.sending" if self._busy else "feedback.send")
        )
        self.close_button.setText(t("feedback.close"))

        if self._status_key is not None:
            self.status_label.setText(t(self._status_key))
            set_dynamic_property(
                self.status_label,
                "role",
                self._status_role,
            )

        self.title_label.setAccessibleName(self.title_label.text())
        self.body_label.setAccessibleName(self.body_label.text())
        self.kind_combo.setAccessibleName(self.kind_label.text())
        self.message_edit.setAccessibleName(self.message_label.text())
        self.checklist_edit.setAccessibleName(self.checklist_label.text())
        self.contact_edit.setAccessibleName(self.contact_label.text())
        self.consent_checkbox.setAccessibleName(self.consent_checkbox.text())
        self.send_button.setAccessibleName(self.send_button.text())
        self.close_button.setAccessibleName(self.close_button.text())


__all__ = ["FeedbackDialog"]
