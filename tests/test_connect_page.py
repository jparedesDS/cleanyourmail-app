"""The Connect page: guided app-password connections, secret save and doctor.

Every test runs headless (``tests/conftest.py``) and uses a fake sidecar: no
network, no mailbox and no real user profile. The fake records the argv it was
given, writes a small TOML on ``init`` and can fail or block ``doctor`` so the
UI's success and failure paths are deterministic.

Three rules drive the assertions below:

* The app password never reaches argv, QSettings, a label or the log.
* Gmail only accepts a 16-letter App Password; the field is cleared on save.
* ``doctor`` runs off the UI thread, with Save disabled until it answers.
"""

from __future__ import annotations

import json
import logging
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cleanyourmail_app.domain.models import AppSettings
from cleanyourmail_app.domain.providers import CUSTOM, provider_by_id
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.ui.main_window import MainWindow
from cleanyourmail_app.ui.pages import connect as CONNECT

#: A valid Gmail App Password, used only as a sentinel: no real credential.
SECRET = "qwertyuiopasdfgh"

#: The sidecar's documented IMAP presets, including Proton's 1143/STARTTLS.
#: ``init`` applies these only when no ``--host`` overrides the default.
PRESETS: dict[str, tuple[str, int, bool, bool]] = {
    "gmail.com": ("imap.gmail.com", 993, True, False),
    "googlemail.com": ("imap.gmail.com", 993, True, False),
    "yahoo.com": ("imap.mail.yahoo.com", 993, True, False),
    "icloud.com": ("imap.mail.me.com", 993, True, False),
    "me.com": ("imap.mail.me.com", 993, True, False),
    "fastmail.com": ("imap.fastmail.com", 993, True, False),
    "proton.me": ("127.0.0.1", 1143, False, True),
    "protonmail.com": ("127.0.0.1", 1143, False, True),
}

TEMPLATE = """\
# CleanYourMail configuration -- keep this file out of git.

[account]
name = "personal"
email = "{email}"
imap_host = "{host}"
imap_port = {port}
imap_ssl = {ssl}
imap_starttls = {starttls}
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
    """A ``CliClient`` stand-in that records argv and writes a config on init."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.init_ok = True
        self.doctor_ok = True
        self.doctor_threads: list[threading.Thread] = []
        self.doctor_gate: threading.Event | None = None

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
        command = args[0]
        if command == "init":
            return self._init(args)
        if command == "doctor":
            self.doctor_threads.append(threading.current_thread())
            if self.doctor_gate is not None:
                self.doctor_gate.wait(10)
            if self.doctor_ok:
                return {
                    "ok": True,
                    "exit_code": 0,
                    "data": {"ok": True},
                    "stdout": json.dumps({"ok": True}),
                    "stderr": "",
                }
            return {
                "ok": False,
                "exit_code": 2,
                "data": {"ok": False},
                "stdout": "",
                "stderr": "Mail: authentication failed for the server\n",
            }
        raise AssertionError(f"unexpected sidecar command: {args}")

    def _init(self, args: list[str]) -> dict[str, Any]:
        if not self.init_ok:
            return {
                "ok": False,
                "exit_code": 2,
                "data": {},
                "stdout": "",
                "stderr": "Config: cannot write the file\n",
            }
        target = Path(args[args.index("--path") + 1])
        email = args[args.index("--email") + 1]
        domain = email.rsplit("@", 1)[-1].lower()
        if "--host" in args:
            # An explicit host replaces the preset with the 993/TLS default,
            # exactly like the sidecar's init_template.
            host = args[args.index("--host") + 1]
            port, ssl, starttls = 993, True, False
        else:
            host, port, ssl, starttls = PRESETS.get(
                domain, ("imap.example.com", 993, True, False)
            )
        secret = ""
        if "--secret-file" in args:
            secret = args[args.index("--secret-file") + 1]
        target.parent.mkdir(parents=True, exist_ok=True)
        # TOML reads a backslash as an escape, so the Windows path is written
        # with forward slashes, exactly as the real sidecar does.
        target.write_text(
            TEMPLATE.format(
                email=email,
                host=host,
                port=port,
                ssl=str(ssl).lower(),
                starttls=str(starttls).lower(),
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
    page.set_provider(provider_by_id("gmail"), "me@gmail.com")
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
    """Every visible string a page holds, for the no-secret assertion."""
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


# --- Gmail instructions ----------------------------------------------------


def test_gmail_shows_the_two_factor_checklist_and_a_password_field(
    page, services
):
    t = services.translator.t

    assert page.title_label.text() == t("connect.gmail.title")
    assert page.intro_label.text() == t("connect.gmail.intro")
    assert [label.text() for label in page.step_labels] == [
        t("connect.gmail.step_1"),
        t("connect.gmail.step_2"),
        t("connect.gmail.step_3"),
    ]
    assert page.checklist.isHidden() is False
    assert page.two_factor_label.text() == t("connect.gmail.two_factor_missing")
    assert page.two_factor_label.isHidden() is False
    assert page.password_edit.isHidden() is False
    assert page.password_label.text() == t("connect.app_password.label")
    assert page.password_edit.placeholderText() == t(
        "connect.app_password.placeholder"
    )
    assert page.save_button.text() == t("connect.app_password.save")
    assert page.save_button.isEnabled() is False


def test_gmail_offers_the_google_security_and_app_password_pages(
    qtbot, page, services
):
    t = services.translator.t
    gmail = provider_by_id("gmail")
    app_passwords = dict(gmail.help_links)["app_passwords"]

    assert page.security_button.text() == t("connect.gmail.open_security")
    assert page.app_passwords_button.text() == t("connect.gmail.open_app_passwords")
    assert page.app_passwords_button.isHidden() is False

    qtbot.mouseClick(page.security_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.app_passwords_button, Qt.MouseButton.LeftButton)

    assert FakeDesktopServices.opened == [gmail.help_url, app_passwords]


def test_gmail_copy_asks_for_2fa_and_an_app_password(page, services):
    t = services.translator.t
    copy = " ".join(
        [page.title_label.text(), page.intro_label.text(), _labels(page)]
    ).lower()

    assert "2-step verification" in copy
    assert "app password" in copy
    assert t("connect.app_password.help") in _labels(page)
    assert t("connect.app_password.placeholder") in _labels(page)


# --- Other app-password providers -----------------------------------------


@pytest.mark.parametrize("provider_id", ["yahoo", "icloud", "fastmail"])
def test_other_providers_show_their_own_app_password_instructions(
    qtbot, services, provider_id
):
    t = services.translator.t
    provider = provider_by_id(provider_id)
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(provider, f"me@{provider_id}.com")

    assert page.title_label.text() == t(f"connect.{provider_id}.title")
    assert page.intro_label.text() == t(f"connect.{provider_id}.intro")
    assert page.checklist.isHidden() is True
    assert page.two_factor_label.isHidden() is True
    assert page.app_passwords_button.isHidden() is True
    assert page.security_button.text() == t(f"connect.{provider_id}.open_security")
    assert page.password_edit.isHidden() is False

    qtbot.mouseClick(page.security_button, Qt.MouseButton.LeftButton)
    assert FakeDesktopServices.opened == [provider.help_url]


def test_a_fresh_provider_selection_clears_the_previous_state(
    page, services
):
    page.password_edit.setText(SECRET)
    assert page.save_button.isEnabled() is True

    page.set_provider(provider_by_id("yahoo"), "me@yahoo.com")

    assert page.password_edit.text() == ""
    assert page.save_button.isEnabled() is False
    assert page.error_label.isHidden() is True
    assert page.status_label.text() == ""


# --- Validation ------------------------------------------------------------


def test_the_save_button_unlocks_only_for_a_complete_gmail_password(page, services):
    t = services.translator.t

    page.password_edit.setText("qwertyuiopasdfg")
    assert page.save_button.isEnabled() is False
    assert page.password_error.isHidden() is False
    assert page.password_error.text() == t("connect.app_password.invalid")
    assert page.password_edit.property("invalid") is True

    page.password_edit.setText(SECRET)
    assert page.save_button.isEnabled() is True
    assert page.password_error.isHidden() is True
    assert page.password_edit.property("invalid") is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "qwertyuiopasdfg",
        "qwertyuiopasdfghj",
        "QWERTYUIOPASDFGH",
        "qwertyuiopasdfg1",
        "qwertyuiopasdfg-",
    ],
)
def test_invalid_gmail_passwords_keep_save_disabled(page, text):
    page.password_edit.setText(text)

    assert page.save_button.isEnabled() is False


@pytest.mark.parametrize(
    "text",
    [SECRET, " qwertyuiopasdfgh ", "qwer tyui opas dfgh"],
)
def test_pasted_gmail_passwords_are_accepted_with_spaces(page, text):
    page.password_edit.setText(text)

    assert page.save_button.isEnabled() is True


def test_other_providers_accept_any_non_empty_password(qtbot, services):
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(provider_by_id("fastmail"), "me@fastmail.com")

    page.password_edit.setText("   ")
    assert page.save_button.isEnabled() is False

    page.password_edit.setText("app-specific password")
    assert page.save_button.isEnabled() is True


# --- Saving ----------------------------------------------------------------


def _save(qtbot, page, signal=None):
    """Click Save inside a wait for ``signal`` (success needs a real wait)."""
    if signal is None:
        qtbot.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
        return None
    with qtbot.waitSignal(signal, timeout=5000) as blocker:
        qtbot.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
    return blocker


def test_saving_writes_the_secret_runs_doctor_and_clears_the_field(
    qtbot, page, services, cli
):
    services.config.secret_path.parent.mkdir(parents=True, exist_ok=True)
    page.password_edit.setText("qwer tyui opas dfgh")

    _save(qtbot, page, page.connectionSucceeded)

    assert services.config.secret_path.read_text(encoding="utf-8") == SECRET
    assert page.password_edit.text() == ""
    assert not hasattr(page, "secret")

    commands = [call["args"][0] for call in cli.calls]
    assert commands == ["init", "doctor"]
    doctor = cli.calls[-1]
    assert doctor["config_path"] == services.config.config_path()
    assert doctor["args"] == ["doctor"]

    # No argv ever carried the secret.
    assert all(SECRET not in " ".join(call["args"]) for call in cli.calls)

    # doctor ran off the UI thread.
    assert cli.doctor_threads
    assert all(
        thread is not threading.main_thread() for thread in cli.doctor_threads
    )

    assert page.status_label.text() == services.translator.t("connect.doctor.ok")
    assert page.status_label.property("kind") == "success"
    assert page.error_label.isHidden() is True


def test_gmail_dot_com_keeps_the_preset_values(
    qtbot, page, services, cli
):
    """The explicit host matches the sidecar preset, so .com is unchanged."""
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)

    init = cli.calls[0]["args"]
    assert init[init.index("--host") + 1] == "imap.gmail.com"
    config = tomllib.loads(
        services.config.config_path().read_text(encoding="utf-8")
    )
    assert config["account"]["imap_host"] == "imap.gmail.com"
    assert config["account"]["imap_port"] == 993
    assert config["account"]["imap_ssl"] is True
    assert config["account"]["email"] == "me@gmail.com"
    assert Path(config["account"]["password_file"]) == services.config.secret_path


@pytest.mark.parametrize(
    ("provider_id", "host"),
    [
        ("yahoo", "imap.mail.yahoo.com"),
        ("icloud", "imap.mail.me.com"),
        ("fastmail", "imap.fastmail.com"),
    ],
)
def test_app_password_providers_write_their_documented_host(
    qtbot, services, cli, provider_id, host
):
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(provider_by_id(provider_id), f"me@{provider_id}.com")
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)

    init = cli.calls[0]["args"]
    assert init[init.index("--host") + 1] == host
    config = tomllib.loads(
        services.config.config_path().read_text(encoding="utf-8")
    )
    assert config["account"]["imap_host"] == host
    assert config["account"]["imap_port"] == 993
    assert config["account"]["imap_ssl"] is True


@pytest.mark.parametrize(
    ("provider_id", "email", "host"),
    [
        # A Google Workspace domain is not in the sidecar's preset table.
        ("gmail", "me@workspace.example", "imap.gmail.com"),
        # iCloud presets icloud.com and me.com, not mac.com.
        ("icloud", "me@mac.com", "imap.mail.me.com"),
        # Fastmail presets fastmail.com, not fastmail.fm.
        ("fastmail", "me@fastmail.fm", "imap.fastmail.com"),
        # Yahoo presets yahoo.com, not the other catalog TLDs.
        ("yahoo", "me@yahoo.co.uk", "imap.mail.yahoo.com"),
    ],
    ids=["google-workspace", "mac-com", "fastmail-fm", "yahoo-co-uk"],
)
def test_catalog_domains_outside_the_sidecar_presets_get_a_host(
    qtbot, services, cli, provider_id, email, host
):
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(provider_by_id(provider_id), email)
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)

    init = cli.calls[0]["args"]
    assert init[init.index("--host") + 1] == host
    config = tomllib.loads(
        services.config.config_path().read_text(encoding="utf-8")
    )
    assert config["account"]["imap_host"] == host
    assert config["account"]["imap_port"] == 993
    assert config["account"]["imap_ssl"] is True


def test_proton_leaves_the_bridge_preset_intact(qtbot, services, cli):
    """Passing ``--host`` would replace 1143/STARTTLS with 993/TLS."""
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(provider_by_id("proton"), "me@proton.me")
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)

    init = cli.calls[0]["args"]
    assert "--host" not in init
    config = tomllib.loads(
        services.config.config_path().read_text(encoding="utf-8")
    )
    assert config["account"]["imap_host"] == "127.0.0.1"
    assert config["account"]["imap_port"] == 1143
    assert config["account"]["imap_ssl"] is False
    assert config["account"]["imap_starttls"] is True


def test_save_is_disabled_while_doctor_runs(qtbot, page, services, cli):
    cli.doctor_gate = threading.Event()
    page.password_edit.setText(SECRET)

    with qtbot.waitSignal(page.connectionSucceeded, timeout=10000):
        qtbot.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
        try:
            assert page.save_button.isEnabled() is False
            assert page.status_label.text() == services.translator.t(
                "connect.doctor.running"
            )
            assert page.back_button.isEnabled() is False
        finally:
            cli.doctor_gate.set()

    assert page.password_edit.text() == ""
    assert page.status_label.text() == services.translator.t("connect.doctor.ok")


def test_a_doctor_failure_shows_the_provider_error_and_stays(
    qtbot, page, services, cli
):
    t = services.translator.t
    cli.doctor_ok = False
    page.password_edit.setText(SECRET)
    successes: list[bool] = []
    page.connectionSucceeded.connect(lambda: successes.append(True))

    _save(qtbot, page, page.doctorFinished)

    assert successes == []
    assert page.error_label.isHidden() is False
    assert page.error_label.text() == t("connect.doctor.failed")
    assert page.hint_label.isHidden() is False
    assert page.hint_label.text() == t("connect.doctor.hint")
    assert page.back_button.isEnabled() is True
    # The secret was already written and cleared; a retry starts with a new
    # paste, so Save stays disabled until the field is filled again.
    assert page.password_edit.text() == ""
    assert page.save_button.isEnabled() is False
    assert services.config.secret_path.read_text(encoding="utf-8") == SECRET


def test_a_retry_after_a_failure_can_succeed(qtbot, page, services, cli):
    cli.doctor_ok = False
    page.password_edit.setText(SECRET)
    _save(qtbot, page, page.doctorFinished)

    cli.doctor_ok = True
    page.password_edit.setText(SECRET)
    _save(qtbot, page, page.connectionSucceeded)

    assert page.error_label.isHidden() is True
    assert page.status_label.text() == services.translator.t("connect.doctor.ok")


def test_a_secret_write_failure_is_reported_without_the_secret(
    qtbot, page, services, cli, monkeypatch
):
    def fail(path, value):
        raise OSError(f"cannot write {path}")

    monkeypatch.setattr(CONNECT, "save_app_password", fail)
    page.password_edit.setText(SECRET)

    _save(qtbot, page)

    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.secret_write")
    # The field is cleared even when the write fails, so the value is not left
    # behind for a screenshot or a later error path.
    assert page.password_edit.text() == ""
    assert SECRET not in page.error_label.text()
    assert cli.calls and cli.calls[-1]["args"][0] == "init"


def test_a_config_failure_is_reported_inline(qtbot, page, services, cli):
    cli.init_ok = False
    page.password_edit.setText(SECRET)

    _save(qtbot, page)

    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.config")
    assert not services.config.secret_path.exists()
    assert cli.calls[-1]["args"][0] == "init"
    # Nothing was written, so the paste stays for a retry.
    assert page.password_edit.text() == SECRET
    assert page.save_button.isEnabled() is True


def test_a_missing_sidecar_is_reported_and_the_page_stays_usable(
    qtbot, page, services, monkeypatch
):
    def missing(*args, **kwargs):
        raise CONNECT.CliError("Cannot start the CleanYourMail sidecar")

    monkeypatch.setattr(services.cli, "run", missing)
    page.password_edit.setText(SECRET)

    _save(qtbot, page)

    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.config")
    assert page.password_edit.text() == SECRET
    assert page.save_button.isEnabled() is True
    assert page.back_button.isEnabled() is True


# --- No secret escapes -----------------------------------------------------


def test_the_secret_is_never_rendered_stored_or_logged(
    qtbot, page, services, caplog
):
    caplog.set_level(logging.DEBUG)
    services.settings.save(AppSettings(provider="gmail", email="me@gmail.com"))
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)

    assert SECRET not in _labels(page)
    assert SECRET not in page.windowTitle()
    assert SECRET not in services.settings.path.read_text(encoding="utf-8")
    assert SECRET not in caplog.text
    # The only place the value is allowed to live is the secret file.
    assert services.config.secret_path.read_text(encoding="utf-8") == SECRET


def test_the_page_does_not_keep_the_secret_after_save(qtbot, page, services):
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)

    assert not hasattr(page, "secret")
    assert not hasattr(page, "_secret")
    assert page.password_edit.text() == ""


def test_undo_cannot_restore_the_saved_password(qtbot, page, services):
    """``QLineEdit.clear()`` leaves the value undoable; Ctrl+Z must not."""
    page.password_edit.setText(SECRET)

    _save(qtbot, page, page.connectionSucceeded)
    assert page.password_edit.text() == ""

    page.password_edit.undo()

    assert page.password_edit.text() == ""
    assert SECRET not in _labels(page)


# --- Custom and Outlook ----------------------------------------------------


def test_custom_imap_requires_a_host_before_saving(qtbot, services, cli):
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(CUSTOM, "me@example.com")
    page.password_edit.setText(SECRET)

    assert page.host_edit.isHidden() is False
    assert page.save_button.isEnabled() is False

    page.host_edit.setText("imap.example.com")

    assert page.save_button.isEnabled() is True
    _save(qtbot, page, page.connectionSucceeded)
    init = cli.calls[0]["args"]
    assert init[init.index("--host") + 1] == "imap.example.com"


def test_outlook_never_offers_a_password_field(qtbot, services):
    page = CONNECT.ConnectPage(services)
    qtbot.addWidget(page)
    page.set_provider(provider_by_id("outlook"), "me@corp.example")

    assert page.title_label.text() == services.translator.t("connect.outlook.title")
    assert page.intro_label.text() == services.translator.t("connect.outlook.intro")
    assert page.password_edit.isHidden() is True
    assert page.save_button.isHidden() is True
    assert page.start_button.isHidden() is False
    # Task 8 replaced the interim disabled panel with the device-code flow.
    assert page.start_button.isEnabled() is True
    assert page.outlook_limitation.isHidden() is False


# --- Shell wiring ----------------------------------------------------------


def test_continue_from_the_provider_page_reaches_the_connect_page(window, services):
    _select(window, "gmail", "me@gmail.com")

    assert window.current_page_key() == "connect"
    assert window.connect_page.provider.id == "gmail"
    assert window.connect_page.email == "me@gmail.com"
    assert window.step_labels["connect"].property("active") is True


def test_a_successful_connection_advances_to_the_next_page(
    qtbot, window, services
):
    _select(window, "gmail", "me@gmail.com")
    window.connect_page.password_edit.setText(SECRET)

    _save(qtbot, window.connect_page, window.connect_page.connectionSucceeded)

    assert window.current_page_key() == "preferences"


def test_the_shell_owns_the_real_preferences_page(window, services):
    """Task 9 registers the page, so Connect always has somewhere to advance."""
    assert window.pages["preferences"] is window.preferences_page


def test_back_returns_to_the_provider_page_without_losing_the_account(
    qtbot, window, services
):
    _select(window, "gmail", "me@gmail.com")
    connect_page = window.connect_page

    qtbot.mouseClick(connect_page.back_button, Qt.MouseButton.LeftButton)

    assert window.current_page_key() == "provider"
    assert window.provider_page.selected_provider.id == "gmail"
    assert window.provider_page.email_edit.text() == "me@gmail.com"


def test_back_requested_is_emitted(qtbot, page):
    with qtbot.waitSignal(page.backRequested, timeout=1000) as blocker:
        qtbot.mouseClick(page.back_button, Qt.MouseButton.LeftButton)

    assert blocker.args == []


# --- Language --------------------------------------------------------------


def test_switching_language_updates_the_connect_page(window, services):
    _select(window, "gmail", "me@gmail.com")

    window.set_language("es")

    t = Translator("es").t
    connect_page = window.connect_page
    assert connect_page.title_label.text() == t("connect.gmail.title")
    assert [label.text() for label in connect_page.step_labels] == [
        t("connect.gmail.step_1"),
        t("connect.gmail.step_2"),
        t("connect.gmail.step_3"),
    ]
    assert connect_page.security_button.text() == t("connect.gmail.open_security")
    assert connect_page.save_button.text() == t("connect.app_password.save")
    assert window.step_labels["connect"].text() == "Conectar"
