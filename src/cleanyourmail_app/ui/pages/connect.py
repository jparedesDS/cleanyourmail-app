"""The second wizard page: guide the provider's app password and test it.

Gmail needs 2-Step Verification and an App Password; Yahoo, iCloud and
Fastmail have their own app-password page; Proton Bridge and Custom IMAP use a
plain password. The page branches on ``Provider.auth_kind``, keeps the
provider's instructions visible, and never asks for the account's normal
password or implements IMAP itself.

Saving is deliberately ordered: the sidecar's ``init`` creates the TOML (it
names the ``password_file``), the app writes that file through
``services.secrets``, then ``doctor`` runs in a worker thread. The pasted value
is cleared from the field and from this page's local variables as soon as it
has been written, and it is never passed in argv, stored in settings, logged or
rendered. A failed doctor leaves the saved file in place and shows copy, not
the sidecar's raw output, so a server message can never echo a secret.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.providers import Provider
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.cli import CliError
from cleanyourmail_app.services.config import ConfigServiceError
from cleanyourmail_app.services.secrets import save_app_password
from cleanyourmail_app.ui.style import set_dynamic_property

#: Providers whose connection uses a pasted secret.
SECRET_KINDS = frozenset({"app_password", "bridge", "custom"})

#: Google app passwords are exactly 16 lower-case letters. Google displays them
#: in four groups; people paste those spaces, so they are removed first.
_GMAIL_SECRET_RE = re.compile(r"[a-z]{16}")


def normalise_app_password(provider: Provider | None, value: object) -> str:
    """The value to write: Gmail loses every space, the rest is trimmed.

    App passwords never contain meaningful spaces. A Bridge or Custom password
    might, so only the outer whitespace of a paste is removed there.
    """
    if not isinstance(value, str):
        return ""
    if provider is not None and provider.id == "gmail":
        return "".join(value.split())
    return value.strip()


def is_valid_app_password(provider: Provider | None, value: object) -> bool:
    """Whether the pasted secret satisfies this provider's shape."""
    if not isinstance(value, str) or provider is None:
        return False
    prepared = normalise_app_password(provider, value)
    if not prepared:
        return False
    if provider.id == "gmail":
        return _GMAIL_SECRET_RE.fullmatch(prepared) is not None
    return True


class _DoctorSignals(QObject):
    """Carry one boolean from the worker back to the UI thread."""

    finished = Signal(bool)


class _DoctorJob(QRunnable):
    """Run the sidecar ``doctor`` without blocking the page.

    Only the success flag crosses the thread boundary: the sidecar's stdout and
    stderr stay in the worker, so no server message can reach a label by
    accident. Any failure (including a missing sidecar) is a ``False`` result,
    never an exception in the pool.
    """

    def __init__(
        self,
        cli: object,
        config_path: object,
        signals: _DoctorSignals,
    ) -> None:
        super().__init__()
        self._cli = cli
        self._config_path = config_path
        self._signals = signals

    def run(self) -> None:  # noqa: D401 - QRunnable's contract
        ok = False
        try:
            result = self._cli.run(["doctor"], config_path=self._config_path)  # type: ignore[attr-defined]
            ok = bool(result.get("ok"))
        except Exception:
            # A missing sidecar or a crashed process is a failed test, not a
            # reason to take the wizard down. Nothing is logged: the exception
            # could name a path, and a log is not the place for it.
            ok = False
        try:
            self._signals.finished.emit(ok)
        except RuntimeError:
            # The window was closed while doctor was still running; there is
            # no receiver left to tell, and the pool must not see an exception.
            pass


class ConnectPage(QWidget):
    """Provider instructions, one secret field, Save and a live connection test."""

    connectionSucceeded = Signal()
    backRequested = Signal()
    doctorFinished = Signal(bool)

    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._translator = services.translator
        self._provider: Provider | None = None
        self._email = ""
        self._doctor_running = False
        self._status_key: str | None = None
        self._status_kind = ""
        self._error_key: str | None = None
        self._hint_key: str | None = None
        self._pool = QThreadPool.globalInstance()
        # Unparented on purpose: if the window closes mid-doctor the job keeps
        # the emitter alive and Qt drops the receiver instead of raising.
        self._signals = _DoctorSignals()
        self._signals.finished.connect(self._on_doctor_finished)

        self._build()
        self._apply_provider()
        self.retranslate()
        self._refresh_state()

    # -- public state -------------------------------------------------------

    @property
    def provider(self) -> Provider | None:
        """The provider the shell handed over, or ``None`` before Continue."""
        return self._provider

    @property
    def email(self) -> str:
        """The account address the shell handed over."""
        return self._email

    def set_provider(self, provider: Provider, email: str) -> None:
        """Show the instructions for ``provider`` and start from a clean state.

        Called every time the shell arrives from the provider page. An
        in-flight ``doctor`` is never interrupted mid-write; the shell disables
        Back while it runs, so a new provider can only arrive after it ends.
        """
        if not isinstance(provider, Provider):
            raise TypeError("set_provider() needs a Provider value")
        if self._doctor_running:
            return

        self._provider = provider
        self._email = email.strip() if isinstance(email, str) else ""
        self._clear_password_field()
        self.host_edit.clear()
        self._clear_feedback()
        self._apply_provider()
        self.retranslate()
        self._refresh_state()

    # -- layout -------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        body = QWidget(self.scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(12)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)

        self.subtitle_label = QLabel(self)
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)

        self.intro_label = QLabel(self)
        self.intro_label.setWordWrap(True)

        self.checklist = QWidget(self)
        checklist_layout = QVBoxLayout(self.checklist)
        checklist_layout.setContentsMargins(0, 0, 0, 0)
        checklist_layout.setSpacing(6)
        self.step_labels: list[QLabel] = []
        for _ in range(3):
            label = QLabel(self.checklist)
            label.setWordWrap(True)
            self.step_labels.append(label)
            checklist_layout.addWidget(label)

        self.two_factor_label = QLabel(self)
        self.two_factor_label.setObjectName("warning")
        self.two_factor_label.setWordWrap(True)

        self.start_button = QPushButton(self)
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumWidth(220)
        self.start_button.setEnabled(False)

        self.host_label = QLabel(self)
        self.host_label.setObjectName("section")
        self.host_edit = QLineEdit(self)
        self.host_edit.setObjectName("hostField")
        self.host_edit.setClearButtonEnabled(True)
        self.host_edit.textChanged.connect(self._refresh_state)
        self.host_label.setBuddy(self.host_edit)

        self.password_label = QLabel(self)
        self.password_label.setObjectName("section")
        self.password_edit = QLineEdit(self)
        self.password_edit.setObjectName("passwordField")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.textChanged.connect(self._refresh_state)
        self.password_label.setBuddy(self.password_edit)

        self.help_label = QLabel(self)
        self.help_label.setObjectName("muted")
        self.help_label.setWordWrap(True)

        self.password_error = QLabel(self)
        self.password_error.setObjectName("error")
        self.password_error.setWordWrap(True)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)

        self.error_label = QLabel(self)
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)

        self.hint_label = QLabel(self)
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)

        links = QHBoxLayout()
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(8)
        self.security_button = self._link_button(self)
        self.app_passwords_button = self._link_button(self)
        self.security_button.clicked.connect(self._open_security_page)
        self.app_passwords_button.clicked.connect(self._open_app_passwords_page)
        links.addWidget(self.security_button)
        links.addWidget(self.app_passwords_button)
        links.addStretch(1)

        self.back_button = QPushButton(self)
        self.back_button.setObjectName("secondary")
        self.back_button.setMinimumWidth(140)
        self.back_button.clicked.connect(self._go_back)

        self.save_button = QPushButton(self)
        self.save_button.setObjectName("primary")
        self.save_button.setMinimumWidth(200)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)

        actions = QHBoxLayout()
        actions.setContentsMargins(32, 12, 32, 24)
        actions.addWidget(self.back_button)
        actions.addStretch(1)
        actions.addWidget(self.save_button)

        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addWidget(self.intro_label)
        root.addWidget(self.checklist)
        root.addWidget(self.two_factor_label)
        root.addWidget(self.start_button)
        root.addSpacing(4)
        root.addWidget(self.host_label)
        root.addWidget(self.host_edit)
        root.addWidget(self.password_label)
        root.addWidget(self.password_edit)
        root.addWidget(self.help_label)
        root.addWidget(self.password_error)
        root.addLayout(links)
        root.addWidget(self.status_label)
        root.addWidget(self.error_label)
        root.addWidget(self.hint_label)
        root.addStretch(1)

        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        outer.addLayout(actions)

    @staticmethod
    def _link_button(parent: QWidget) -> QPushButton:
        button = QPushButton(parent)
        button.setObjectName("link")
        return button

    # -- provider branch ----------------------------------------------------

    def _apply_provider(self) -> None:
        """Show only the widgets this provider's auth kind needs."""
        provider = self._provider
        secret_flow = provider is not None and provider.auth_kind in SECRET_KINDS
        is_gmail = provider is not None and provider.id == "gmail"
        is_custom = provider is not None and provider.auth_kind == "custom"
        is_device_code = provider is not None and provider.auth_kind == "device_code"

        self.checklist.setVisible(is_gmail)
        self.two_factor_label.setVisible(is_gmail)
        self.app_passwords_button.setVisible(is_gmail)
        self.host_label.setVisible(is_custom)
        self.host_edit.setVisible(is_custom)
        self.start_button.setVisible(is_device_code)

        for widget in (
            self.password_label,
            self.password_edit,
            self.help_label,
            self.save_button,
        ):
            widget.setVisible(secret_flow)

        self.save_button.setEnabled(False)
        self.security_button.setVisible(provider is not None)

    # -- copy ---------------------------------------------------------------

    def retranslate(self) -> None:
        """Refresh every visible string from the active catalog."""
        t = self._translator.t
        provider = self._provider

        self.subtitle_label.setText(t("connect.subtitle"))
        self.title_label.setText(self._provider_title())
        self.intro_label.setText(self._provider_copy("intro", ""))
        for index, label in enumerate(self.step_labels, start=1):
            label.setText(t(f"connect.gmail.step_{index}"))
        self.two_factor_label.setText(t("connect.gmail.two_factor_missing"))
        self.start_button.setText(t("connect.outlook.start"))

        self.security_button.setText(self._security_button_text())
        self.app_passwords_button.setText(t("connect.gmail.open_app_passwords"))

        self.host_label.setText(t("connect.custom.host"))
        self.host_edit.setPlaceholderText(t("connect.custom.host"))
        self.host_edit.setAccessibleName(t("connect.custom.host"))

        password_key = (
            "connect.custom.auth_password"
            if provider is not None and provider.auth_kind in {"bridge", "custom"}
            else "connect.app_password.label"
        )
        self.password_label.setText(t(password_key))
        self.password_edit.setAccessibleName(t(password_key))
        # "16-character app password" would be wrong for a Bridge/Custom
        # password, so only the app-password providers get that placeholder.
        self.password_edit.setPlaceholderText(
            t("connect.app_password.placeholder")
            if provider is not None and provider.auth_kind == "app_password"
            else ""
        )
        self.help_label.setText(t("connect.app_password.help"))
        self.password_error.setText(t("connect.app_password.invalid"))

        self.back_button.setText(t("connect.back"))
        self.save_button.setText(
            t("connect.app_password.saving")
            if self._doctor_running
            else t("connect.app_password.save")
        )
        self._sync_feedback()

    def _provider_title(self) -> str:
        t = self._translator.t
        if self._provider is None:
            return t("connect.title")
        key = f"connect.{self._provider.id}.title"
        text = t(key)
        return text if text != key else t("connect.title")

    def _provider_copy(self, suffix: str, fallback_key: str) -> str:
        t = self._translator.t
        if self._provider is None:
            return t(fallback_key) if fallback_key else ""
        key = f"connect.{self._provider.id}.{suffix}"
        text = t(key)
        return text if text != key else (t(fallback_key) if fallback_key else "")

    def _security_button_text(self) -> str:
        t = self._translator.t
        if self._provider is None:
            return t("connect.help")
        if self._provider.id == "proton":
            return t("connect.proton.open_help")
        key = f"connect.{self._provider.id}.open_security"
        text = t(key)
        return text if text != key else t("connect.help")

    # -- provider links -----------------------------------------------------

    def _open_security_page(self) -> None:
        if self._provider is not None:
            self._open_url(self._provider.help_url)

    def _open_app_passwords_page(self) -> None:
        if self._provider is None:
            return
        links = dict(self._provider.help_links)
        self._open_url(links.get("app_passwords", self._provider.help_url))

    @staticmethod
    def _open_url(url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # -- enablement ---------------------------------------------------------

    def _refresh_state(self) -> None:
        t = self._translator.t
        provider = self._provider
        secret_flow = provider is not None and provider.auth_kind in SECRET_KINDS

        valid = False
        show_password_error = False
        if secret_flow and provider is not None:
            raw = self.password_edit.text()
            valid = is_valid_app_password(provider, raw)
            if provider.id == "custom":
                valid = valid and bool(self.host_edit.text().strip())
            if provider.id == "gmail":
                show_password_error = bool(raw.strip()) and not valid

        self.password_error.setText(t("connect.app_password.invalid"))
        self.password_error.setVisible(show_password_error)
        set_dynamic_property(self.password_edit, "invalid", show_password_error)
        self.save_button.setEnabled(valid and not self._doctor_running)
        self.back_button.setEnabled(not self._doctor_running)

    def _target_host(self) -> str | None:
        """The host ``init`` should write, or ``None`` to keep its preset.

        The sidecar already knows Gmail, Yahoo, iCloud, Fastmail and Proton
        (including Proton's 1143/STARTTLS); passing ``--host`` would replace
        that preset with the 993/TLS default. Only Custom IMAP needs a host
        from the page, and an explicit host there has no preset to protect.
        """
        provider = self._provider
        if provider is not None and provider.auth_kind == "custom":
            return self.host_edit.text().strip() or None
        return None

    # -- save ---------------------------------------------------------------

    def _save(self) -> None:
        """Ensure the config, write the secret, then test in the background."""
        provider = self._provider
        if provider is None or self._doctor_running:
            return
        if provider.auth_kind not in SECRET_KINDS:
            return

        secret = normalise_app_password(provider, self.password_edit.text())
        if not is_valid_app_password(provider, secret):
            self._refresh_state()
            return
        host = self._target_host()
        if provider.auth_kind == "custom" and host is None:
            self._refresh_state()
            return

        self._clear_feedback()
        self._doctor_running = True
        self._refresh_state()
        self._show_status("connect.app_password.saving", "muted")

        try:
            config_path = self._services.config.ensure(
                provider, self._email, host=host, port=993, ssl=True
            )
        except (CliError, ConfigServiceError, OSError, TypeError, ValueError):
            self._fail("errors.config")
            return

        try:
            save_app_password(self._services.config.secret_path, secret)
        except (OSError, ValueError):
            # Cleared even when the write fails: the value must not be left in
            # the field for a screenshot or a later error path.
            self._clear_password_field()
            secret = ""
            self._fail("errors.secret_write")
            return

        # The field and the local go away as soon as the file is written.
        self._clear_password_field()
        secret = ""
        self._start_doctor(config_path)

    def _clear_password_field(self) -> None:
        """Empty the field without leaving the value in Qt's undo history.

        ``QLineEdit.clear()`` keeps the old text undoable, so Ctrl+Z could
        bring a stored password back on screen. ``setText("")`` clears the
        undo/redo history as part of setting the property.
        """
        self.password_edit.setText("")

    def _start_doctor(self, config_path: object) -> None:
        self._show_status("connect.doctor.running", "muted")
        job = _DoctorJob(self._services.cli, config_path, self._signals)
        self._pool.start(job)

    def _on_doctor_finished(self, ok: bool) -> None:
        self._doctor_running = False
        self._refresh_state()
        if ok:
            self._show_status("connect.doctor.ok", "success")
        else:
            self._show_error("connect.doctor.failed", "connect.doctor.hint")
        self.doctorFinished.emit(ok)
        if ok:
            self.connectionSucceeded.emit()

    # -- feedback -----------------------------------------------------------

    def _show_status(self, key: str, kind: str) -> None:
        self._status_key = key
        self._status_kind = kind
        self._error_key = None
        self._hint_key = None
        self._sync_feedback()

    def _show_error(self, key: str, hint_key: str | None = None) -> None:
        self._status_key = None
        self._status_kind = ""
        self._error_key = key
        self._hint_key = hint_key
        self._sync_feedback()

    def _fail(self, key: str) -> None:
        self._doctor_running = False
        self._refresh_state()
        self._show_error(key)

    def _clear_feedback(self) -> None:
        self._status_key = None
        self._status_kind = ""
        self._error_key = None
        self._hint_key = None
        self._sync_feedback()

    def _sync_feedback(self) -> None:
        """Render the stored keys, so a language switch can refresh them."""
        t = self._translator.t
        self.status_label.setText(t(self._status_key) if self._status_key else "")
        set_dynamic_property(self.status_label, "kind", self._status_kind)
        self.status_label.setVisible(bool(self._status_key))

        self.error_label.setText(t(self._error_key) if self._error_key else "")
        self.error_label.setVisible(bool(self._error_key))

        self.hint_label.setText(t(self._hint_key) if self._hint_key else "")
        self.hint_label.setVisible(bool(self._hint_key))

    # -- navigation ---------------------------------------------------------

    def _go_back(self) -> None:
        if self._doctor_running:
            return
        self.backRequested.emit()
