"""The Connect page's Outlook device-code flow, through a fake sidecar.

Every test runs headless (``tests/conftest.py``) and uses an in-process fake
sidecar: no network, no Microsoft call and no real user profile. The fake
records argv and timeouts, writes a Microsoft TOML on ``init``, and can fail or
block ``connect`` so both the success and the blocked paths are deterministic.

The rules these tests pin:

* The app never calls Microsoft; ``connect outlook --no-wait`` and ``--wait``
  are the only bridge, and ``--json`` is appended by ``CliClient``.
* The window shows the URL and the user code, copies the code only, and never
  renders a token or a refresh token, even if a sidecar response leaks one.
* Known Azure errors become localized copy; the sidecar's stderr is never
  rendered.
* Cancel drops the UI result: a late ``--wait`` or ``doctor`` answer must not
  advance the wizard or save anything.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from cleanyourmail_app.domain.models import AppSettings
from cleanyourmail_app.domain.providers import provider_by_id
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.services.oauth import (
    DeviceCode,
    OAuthError,
    OutlookConnect,
    outlook_failure_reason,
)
from cleanyourmail_app.ui.main_window import MainWindow
from cleanyourmail_app.ui.pages import connect as CONNECT

#: Sentinels. They are not real credentials; the fake sidecar must never let
#: them reach a label, the settings file, the clipboard or the log.
USER_CODE = "ABCD-EFGH"
VERIFICATION_URI = "https://microsoft.com/devicelogin"
PENDING = "C:/Users/test/.secrets/cleanyourmail-device.json"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.secret-access-token"
REFRESH = "0.AAAA-secret-refresh-token"

#: The sidecar's Outlook template, including the OAuth block that
#: ``connect outlook`` requires.
TEMPLATE = """\
# CleanYourMail configuration -- keep this file out of git.

[account]
name = "personal"
email = "{email}"
imap_host = "{host}"
imap_port = 993
imap_ssl = true
imap_starttls = false
auth = "{auth}"
oauth = "microsoft"
"""


class FakeCli:
    """A ``CliClient`` stand-in for ``init``, ``connect`` and ``doctor``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.email = "me@outlook.com"
        self.init_ok = True
        self.start_ok = True
        self.wait_ok = True
        self.doctor_ok = True
        self.start_error = "Microsoft sign-in could not start.\n"
        self.wait_error = "Microsoft sign-in failed.\n"
        self.start_gate: threading.Event | None = None
        self.wait_gate: threading.Event | None = None
        self.doctor_gate: threading.Event | None = None
        self.wait_done = threading.Event()
        self.doctor_done = threading.Event()
        self.connect_threads: list[threading.Thread] = []
        self.wait_threads: list[threading.Thread] = []
        self.doctor_threads: list[threading.Thread] = []

    def run(
        self,
        args: list[str],
        *,
        config_path: Path | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        self.calls.append(
            {"args": list(args), "config_path": config_path, "timeout": timeout}
        )
        command = args[0] if args else ""
        if command == "init":
            return self._init(args)
        if command == "connect":
            return self._connect(args)
        if command == "doctor":
            return self._doctor()
        raise AssertionError(f"unexpected sidecar command: {args}")

    def _init(self, args: list[str]) -> dict[str, Any]:
        if not self.init_ok:
            return self._failure("Config: cannot write the file\n")
        target = Path(args[args.index("--path") + 1])
        self.email = args[args.index("--email") + 1]
        host = args[args.index("--host") + 1] if "--host" in args else "imap.example.com"
        auth = args[args.index("--auth") + 1] if "--auth" in args else "login"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            TEMPLATE.format(email=self.email, host=host, auth=auth),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "exit_code": 0,
            "data": {"ok": True, "path": str(target)},
            "stdout": "",
            "stderr": "",
        }

    def _connect(self, args: list[str]) -> dict[str, Any]:
        if args[:2] != ["connect", "outlook"]:
            raise AssertionError(f"unexpected connect command: {args}")
        self.connect_threads.append(threading.current_thread())
        if "--no-wait" in args:
            if self.start_gate is not None:
                self.start_gate.wait(10)
            if not self.start_ok:
                return self._failure(self.start_error)
            # A hostile payload: a token here would be a sidecar bug, and the
            # page still must copy and render only the code.
            payload = {
                "ok": True,
                "provider": "microsoft",
                "email": self.email,
                "verification_uri": VERIFICATION_URI,
                "user_code": USER_CODE,
                "expires_in": 900,
                "pending": PENDING,
                "next": "connect outlook --wait",
                "access_token": TOKEN,
                "refresh_token": REFRESH,
            }
            return self._ok(payload)

        self.wait_threads.append(threading.current_thread())
        try:
            if self.wait_gate is not None:
                self.wait_gate.wait(10)
            if not self.wait_ok:
                return self._failure(self.wait_error)
            payload = {
                "ok": True,
                "provider": "microsoft",
                "email": self.email,
                "store": "C:/Users/test/.secrets/cleanyourmail-oauth.json",
                "access_token": TOKEN,
                "refresh_token": REFRESH,
            }
            return self._ok(payload)
        finally:
            self.wait_done.set()

    def _doctor(self) -> dict[str, Any]:
        self.doctor_threads.append(threading.current_thread())
        try:
            if self.doctor_gate is not None:
                self.doctor_gate.wait(10)
            if self.doctor_ok:
                return self._ok({"ok": True})
            return self._failure("Mail: authentication failed for the server\n")
        finally:
            self.doctor_done.set()

    @staticmethod
    def _ok(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "exit_code": 0,
            "data": payload,
            "stdout": json.dumps(payload),
            "stderr": "",
        }

    @staticmethod
    def _failure(stderr: str) -> dict[str, Any]:
        return {
            "ok": False,
            "exit_code": 2,
            "data": {"ok": False},
            "stdout": "",
            "stderr": stderr,
        }


class FakeDesktopServices:
    """Collects ``openUrl`` calls so a test never launches a browser."""

    opened: list[str] = []

    @staticmethod
    def openUrl(url: Any) -> bool:  # noqa: N802 - Qt's spelling
        FakeDesktopServices.opened.append(url.toString())
        return True


@pytest.fixture(autouse=True)
def no_browser(monkeypatch):
    FakeDesktopServices.opened = []
    monkeypatch.setattr(CONNECT, "QDesktopServices", FakeDesktopServices)
    return FakeDesktopServices.opened


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
def page(qtbot, services):
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.show()
    page.set_provider(provider_by_id("outlook"), "me@outlook.com")
    return page


@pytest.fixture
def window(qtbot, services):
    window = MainWindow(services.settings, services.translator, services)
    qtbot.addWidget(window)
    window.show()
    return window


def _select(window: MainWindow, provider_id: str, email: str) -> None:
    provider_page = window.provider_page
    card = next(
        card for card in provider_page.cards if card.provider.id == provider_id
    )
    card.click()
    provider_page.email_edit.setText(email)
    provider_page.continue_button.click()


def _labels(widget: QWidget) -> str:
    """Every visible string a page holds, for the no-token assertions."""
    chunks: list[str] = []
    for child in widget.findChildren(QWidget):
        for name in (
            "text",
            "placeholderText",
            "toolTip",
            "statusTip",
            "accessibleName",
            "accessibleDescription",
            "windowTitle",
        ):
            getter = getattr(child, name, None)
            if not callable(getter):
                continue
            try:
                chunks.append(str(getter()))
            except TypeError:
                continue
    return "\n".join(chunks)


def _start(qtbot, page) -> None:
    """Click Connect Microsoft and wait for the code or an error."""
    qtbot.mouseClick(page.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(
        lambda: page.device_code is not None or page.error_label.isVisible(),
        timeout=5000,
    )


def _approve(qtbot, page) -> None:
    qtbot.mouseClick(page.approve_button, Qt.MouseButton.LeftButton)


def _commands(cli: FakeCli) -> list[list[str]]:
    return [call["args"] for call in cli.calls]


# --- The service -----------------------------------------------------------


def test_start_parses_the_device_code_and_pending_path(cli: FakeCli):
    connect = OutlookConnect(cli, Path("config.toml"))

    code = connect.start()

    assert code == DeviceCode(VERIFICATION_URI, USER_CODE, PENDING, 900)
    assert cli.calls[0]["args"] == ["connect", "outlook", "--no-wait"]
    assert cli.calls[0]["config_path"] == Path("config.toml")


def test_start_raises_a_typed_error_with_a_known_reason(cli: FakeCli):
    cli.start_ok = False
    cli.start_error = "Microsoft sign-in failed: AADSTS65001 admin consent required\n"

    with pytest.raises(OAuthError) as excinfo:
        OutlookConnect(cli, None).start()

    assert excinfo.value.reason == "consent"


def test_wait_returns_the_sidecar_result_with_a_long_timeout(cli: FakeCli):
    connect = OutlookConnect(cli, Path("config.toml"))

    result = connect.wait()

    assert result["ok"] is True
    assert cli.calls[0]["args"] == ["connect", "outlook", "--wait"]
    assert cli.calls[0]["timeout"] >= 900
    assert cli.calls[0]["config_path"] == Path("config.toml")


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("AADSTS65001: The user or administrator has not consented", "consent"),
        ("Tenant admin consent is required for this application", "consent"),
        ("AADSTS50020: User account does not exist in tenant", "consent"),
        ("The application needs a verified publisher", "consent"),
        ("error=invalid_grant, the sign-in was revoked", "expired"),
        ("The Microsoft sign-in code expired", "expired"),
        ("The sign-in was declined", "expired"),
        ("Something unexpected happened", "failed"),
    ],
)
def test_known_microsoft_errors_get_a_reason(text: str, reason: str):
    assert outlook_failure_reason(text) == reason


def test_a_sidecar_result_is_classified_by_its_stderr(cli: FakeCli):
    result = FakeCli._failure(
        "Microsoft sign-in failed (unauthorized_client, HTTP 400): "
        "AADSTS65001: admin consent required\n"
    )

    assert outlook_failure_reason(result) == "consent"


# --- Starting the flow -----------------------------------------------------


def test_start_shows_the_url_code_and_the_limitation(qtbot, page, services, cli):
    t = services.translator.t
    # Before the button: the limitation and an enabled Start, no stale code.
    assert page.start_button.isEnabled() is True
    assert page.outlook_limitation.isHidden() is False
    assert page.device_code_panel.isHidden() is True

    _start(qtbot, page)

    code = page.device_code
    assert code is not None
    assert code.verification_uri == VERIFICATION_URI
    assert code.user_code == USER_CODE
    assert code.pending == PENDING
    assert code.expires_in == 900

    assert page.device_code_edit.text() == USER_CODE
    assert page.device_code_edit.isReadOnly() is True
    assert page.device_code_panel.isHidden() is False
    assert page.approve_button.isHidden() is False
    assert page.signin_button.text() == t("connect.outlook.url")
    assert page.copy_code_button.text() == t("connect.outlook.copy_code")
    assert page.start_button.isEnabled() is False

    # The limitation is visible before the person asks Microsoft anything.
    assert page.outlook_limitation.isHidden() is False
    assert page.outlook_limitation.text() == t("connect.outlook.blocked.body")

    assert _commands(cli)[0][:2] == ["init", "--email"]
    assert "--host" in _commands(cli)[0]
    assert _commands(cli)[0][_commands(cli)[0].index("--host") + 1] == (
        "outlook.office365.com"
    )
    assert _commands(cli)[0][_commands(cli)[0].index("--auth") + 1] == "xoauth2"
    assert _commands(cli)[1] == ["connect", "outlook", "--no-wait"]
    assert cli.calls[1]["config_path"] == services.config.config_path()
    # Microsoft's endpoint is called off the UI thread.
    assert cli.connect_threads[0] is not threading.main_thread()


def test_copy_copies_the_code_and_never_the_token(qtbot, page, services):
    t = services.translator.t
    _start(qtbot, page)
    QGuiApplication.clipboard().setText("")

    qtbot.mouseClick(page.copy_code_button, Qt.MouseButton.LeftButton)

    assert QGuiApplication.clipboard().text() == USER_CODE
    assert TOKEN not in QGuiApplication.clipboard().text()
    assert REFRESH not in QGuiApplication.clipboard().text()
    assert page.status_label.text() == t("connect.outlook.copied")


def test_the_signin_button_opens_the_verification_uri(qtbot, page):
    _start(qtbot, page)

    qtbot.mouseClick(page.signin_button, Qt.MouseButton.LeftButton)

    assert FakeDesktopServices.opened == [VERIFICATION_URI]


# --- Approving and testing -------------------------------------------------


def test_approving_waits_then_runs_doctor_and_advances(
    qtbot, window, services, cli
):
    _select(window, "outlook", "me@outlook.com")
    page = window.connect_page
    _start(qtbot, page)

    with qtbot.waitSignal(page.connectionSucceeded, timeout=5000):
        _approve(qtbot, page)

    assert _commands(cli) == [
        ["init", "--email", "me@outlook.com", "--host", "outlook.office365.com",
         "--auth", "xoauth2", "--path", str(services.config.config_path()),
         "--secret-file", str(services.config.secret_path)],
        ["connect", "outlook", "--no-wait"],
        ["connect", "outlook", "--wait"],
        ["doctor"],
    ]
    wait_call = cli.calls[2]
    assert wait_call["timeout"] >= 900
    assert wait_call["config_path"] == services.config.config_path()
    assert cli.wait_threads[0] is not threading.main_thread()

    doctor = cli.calls[3]
    assert doctor["config_path"] == services.config.config_path()
    assert cli.doctor_threads[0] is not threading.main_thread()

    assert window.current_page_key() == "preferences"
    assert page.status_label.text() == services.translator.t("connect.doctor.ok")
    assert page.status_label.property("kind") == "success"
    assert page.error_label.isHidden() is True
    # Outlook never writes the app-password file.
    assert not services.config.secret_path.exists()


def test_a_doctor_failure_after_approval_stays_on_the_connect_page(
    qtbot, window, services, cli
):
    t = services.translator.t
    _select(window, "outlook", "me@outlook.com")
    page = window.connect_page
    cli.doctor_ok = False
    successes: list[bool] = []
    page.connectionSucceeded.connect(lambda: successes.append(True))
    _start(qtbot, page)

    with qtbot.waitSignal(page.doctorFinished, timeout=5000):
        _approve(qtbot, page)

    assert successes == []
    assert window.current_page_key() == "connect"
    assert page.error_label.text() == t("connect.doctor.failed")
    assert page.hint_label.text() == t("connect.doctor.hint")
    assert page.start_button.isEnabled() is True
    assert page.device_code_panel.isHidden() is True


# --- Blocked sign-in -------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "error_key", "hint_key"),
    [
        (
            "Microsoft sign-in failed (unauthorized_client, HTTP 400): "
            "AADSTS65001: The user or administrator has not consented\n",
            "connect.outlook.blocked.title",
            "connect.outlook.blocked.help",
        ),
        (
            "Microsoft sign-in failed: tenant admin consent is required\n",
            "connect.outlook.blocked.title",
            "connect.outlook.blocked.help",
        ),
        (
            "Microsoft sign-in failed: the app has no verified publisher\n",
            "connect.outlook.blocked.title",
            "connect.outlook.blocked.help",
        ),
        (
            "Microsoft sign-in failed (invalid_request): AADSTS50020: User account "
            "'me@outlook.com' does not exist in tenant\n",
            "connect.outlook.blocked.title",
            "connect.outlook.blocked.help",
        ),
        (
            "Microsoft sign-in failed (invalid_grant): the sign-in was revoked\n",
            "connect.outlook.expired",
            "connect.outlook.retry_hint",
        ),
    ],
    ids=["aadsts-65001", "admin-consent", "publisher", "aadsts-50020", "invalid-grant"],
)
def test_a_blocked_sign_in_shows_localized_copy_and_stays(
    qtbot, window, services, cli, message, error_key, hint_key
):
    t = services.translator.t
    _select(window, "outlook", "me@outlook.com")
    page = window.connect_page
    cli.wait_ok = False
    cli.wait_error = message
    successes: list[bool] = []
    page.connectionSucceeded.connect(lambda: successes.append(True))
    _start(qtbot, page)

    _approve(qtbot, page)
    qtbot.waitUntil(lambda: page.error_label.isVisible(), timeout=5000)

    assert successes == []
    assert window.current_page_key() == "connect"
    assert page.error_label.text() == t(error_key)
    assert page.hint_label.text() == t(hint_key)
    # The explanation stays on screen, before and after the failure.
    assert page.outlook_limitation.text() == t("connect.outlook.blocked.body")
    # The code is no longer usable, so the start button offers a new one.
    assert page.device_code_panel.isHidden() is True
    assert page.start_button.isEnabled() is True
    # Doctor never ran and the raw sidecar text was not rendered.
    assert _commands(cli)[-1] == ["connect", "outlook", "--wait"]
    assert "AADSTS" not in _labels(page)
    assert "invalid_grant" not in _labels(page)


def test_a_start_failure_shows_localized_copy_without_raw_sidecar_text(
    qtbot, page, services, cli
):
    t = services.translator.t
    cli.start_ok = False
    cli.start_error = "Traceback: AADSTS65001 admin consent\n"

    _start(qtbot, page)

    assert page.error_label.text() == t("connect.outlook.blocked.title")
    assert page.hint_label.text() == t("connect.outlook.blocked.help")
    assert "AADSTS" not in _labels(page)
    assert page.start_button.isEnabled() is True
    assert page.device_code_panel.isHidden() is True


def test_a_config_failure_is_reported_and_no_connect_command_runs(
    qtbot, page, services, cli
):
    t = services.translator.t
    cli.init_ok = False

    _start(qtbot, page)

    assert page.error_label.text() == t("errors.config")
    assert _commands(cli) == [
        ["init", "--email", "me@outlook.com", "--host", "outlook.office365.com",
         "--auth", "xoauth2", "--path", str(services.config.config_path()),
         "--secret-file", str(services.config.secret_path)]
    ]
    assert page.start_button.isEnabled() is True


# --- Cancel ----------------------------------------------------------------


def test_cancel_drops_a_late_wait_result_without_saving(
    qtbot, page, services, cli
):
    t = services.translator.t
    cli.wait_gate = threading.Event()
    successes: list[bool] = []
    page.connectionSucceeded.connect(lambda: successes.append(True))
    _start(qtbot, page)

    _approve(qtbot, page)
    qtbot.waitUntil(lambda: len(cli.wait_threads) == 1, timeout=5000)
    assert page.cancel_button.isEnabled() is True
    assert page.approve_button.isEnabled() is False

    qtbot.mouseClick(page.cancel_button, Qt.MouseButton.LeftButton)

    assert page.device_code is None
    assert page.device_code_panel.isHidden() is True
    assert page.status_label.text() == t("connect.outlook.cancelled")
    assert page.start_button.isEnabled() is True

    try:
        cli.wait_gate.set()
        qtbot.waitUntil(cli.wait_done.is_set, timeout=5000)
        # Give the queued worker signal time to arrive and be ignored.
        qtbot.wait(200)
    finally:
        cli.wait_gate.set()

    assert successes == []
    assert _commands(cli)[-1] == ["connect", "outlook", "--wait"]
    assert ["doctor"] not in _commands(cli)


def test_cancel_drops_a_late_doctor_result(qtbot, page, services, cli):
    t = services.translator.t
    cli.doctor_gate = threading.Event()
    successes: list[bool] = []
    page.connectionSucceeded.connect(lambda: successes.append(True))
    _start(qtbot, page)

    _approve(qtbot, page)
    qtbot.waitUntil(lambda: len(cli.doctor_threads) == 1, timeout=5000)
    assert page.status_label.text() == t("connect.doctor.running")

    qtbot.mouseClick(page.cancel_button, Qt.MouseButton.LeftButton)

    assert page.start_button.isEnabled() is True
    assert page.status_label.text() == t("connect.outlook.cancelled")

    try:
        cli.doctor_gate.set()
        qtbot.waitUntil(cli.doctor_done.is_set, timeout=5000)
        qtbot.wait(200)
    finally:
        cli.doctor_gate.set()

    assert successes == []
    assert page.error_label.isHidden() is True
    assert page.status_label.text() == t("connect.outlook.cancelled")


# --- No token escapes ------------------------------------------------------


def test_no_token_or_refresh_value_is_rendered_logged_or_stored(
    qtbot, window, services, caplog
):
    caplog.set_level(logging.DEBUG)
    services.settings.save(AppSettings(provider="outlook", email="me@outlook.com"))
    _select(window, "outlook", "me@outlook.com")
    page = window.connect_page
    _start(qtbot, page)

    with qtbot.waitSignal(page.connectionSucceeded, timeout=5000):
        _approve(qtbot, page)

    rendered = "\n".join([_labels(page), page.windowTitle()])
    assert TOKEN not in rendered
    assert REFRESH not in rendered
    assert TOKEN not in services.settings.path.read_text(encoding="utf-8")
    assert REFRESH not in services.settings.path.read_text(encoding="utf-8")
    assert TOKEN not in caplog.text
    assert REFRESH not in caplog.text
    assert TOKEN not in page.device_code_edit.text()
    assert all(
        TOKEN not in " ".join(call["args"]) for call in services.cli.calls
    )
    assert all(
        REFRESH not in " ".join(call["args"]) for call in services.cli.calls
    )
    assert TOKEN not in repr(page.device_code)
    assert REFRESH not in repr(page.device_code)


# --- Language --------------------------------------------------------------


def test_switching_language_updates_the_outlook_flow(qtbot, window, services):
    _select(window, "outlook", "me@outlook.com")
    page = window.connect_page
    _start(qtbot, page)

    window.set_language("es")

    t = Translator("es").t
    assert page.outlook_limitation.text() == t("connect.outlook.blocked.body")
    assert page.start_button.text() == t("connect.outlook.start")
    assert page.copy_code_button.text() == t("connect.outlook.copy_code")
    assert page.signin_button.text() == t("connect.outlook.url")
    assert page.approve_button.text() == t("connect.outlook.approve")
    assert page.cancel_button.text() == t("connect.outlook.cancel")
