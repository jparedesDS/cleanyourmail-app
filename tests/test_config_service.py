"""ConfigService: create the TOML through the sidecar and edit only known keys.

Every test uses a fake ``CliClient``: no sidecar binary, mailbox or network.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from cleanyourmail_app.domain.models import Preferences
from cleanyourmail_app.domain.providers import provider_by_id
from cleanyourmail_app.services.config import (
    ConfigMismatchError,
    ConfigService,
    ConfigServiceError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

TEMPLATE = """\
# CleanYourMail configuration -- keep this file out of git.
# The password is NOT stored here; it stays in a local secret file.

[account]
name = "personal"
email = "{email}"
imap_host = "imap.gmail.com"
imap_port = 993
imap_ssl = true
imap_starttls = false
auth = "login"
password_file = "C:/Users/me/.secrets/cleanyourmail.txt"
# Or use an environment variable instead:
# password_env = "CYM_PASSWORD"

[scan]
mailboxes = ["INBOX"]
days = 30
batch_size = 200

[policy]
# Messages younger than this are never moved.
min_age_days = 30
protect_answered = true
protect_flagged = true
protect_domains = []
protect_addresses = []
never_unsubscribe_domains = []
max_messages_per_run = 500
max_messages_per_group = 200
move_spam_to_junk = true

[unsubscribe]
enabled = true
one_click = true
max_requests = 25

[folders]
root = "CleanYourMail"
create = true
"""


class FakeCli:
    """A ``CliClient`` stand-in that records argv and writes a config on init."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.init_ok = True
        self.validate_payload: dict[str, Any] = {
            "ok": True,
            "account": {"email": "me@gmail.com"},
            "scan": {"days": 365},
        }

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
            if not self.init_ok:
                return {
                    "ok": False,
                    "exit_code": 2,
                    "data": {},
                    "stdout": "",
                    "stderr": "Config: cannot write the file\n",
                }
            email = args[args.index("--email") + 1]
            target = Path(args[args.index("--path") + 1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(TEMPLATE.format(email=email), encoding="utf-8")
            return {
                "ok": True,
                "exit_code": 0,
                "data": {"ok": True, "path": str(target)},
                "stdout": "",
                "stderr": "",
            }
        if command == "validate":
            return {
                "ok": True,
                "exit_code": 0,
                "data": dict(self.validate_payload),
                "stdout": "",
                "stderr": "",
            }
        raise AssertionError(f"unexpected sidecar command: {args}")


@pytest.fixture
def cli() -> FakeCli:
    return FakeCli()


@pytest.fixture
def service(cli: FakeCli, tmp_path: Path) -> ConfigService:
    return ConfigService(cli, tmp_path / "app-data")


def test_config_path_is_under_the_injected_app_data(cli: FakeCli, tmp_path: Path):
    app_data = tmp_path / "app-data"
    service = ConfigService(cli, app_data)

    path = service.config_path()

    assert path == app_data / "cleanyourmail.toml"
    assert app_data in path.parents
    assert REPO_ROOT not in path.parents


def test_ensure_calls_init_once_and_returns_the_path(
    service: ConfigService, cli: FakeCli
):
    path = service.ensure(provider_by_id("gmail"), "me@gmail.com")

    assert path == service.config_path()
    assert path.is_file()
    assert len(cli.calls) == 1
    call = cli.calls[0]
    assert call["args"] == [
        "init",
        "--email",
        "me@gmail.com",
        "--path",
        str(path),
        "--secret-file",
        str(Path.home() / ".secrets" / "cleanyourmail.txt"),
    ]
    assert call["config_path"] is None


def test_ensure_honours_an_injected_secret_path(cli: FakeCli, tmp_path: Path):
    secret = tmp_path / "elsewhere" / "secret.txt"
    service = ConfigService(cli, tmp_path / "app-data", secret_path=secret)

    service.ensure(provider_by_id("gmail"), "me@gmail.com")

    args = cli.calls[0]["args"]
    assert args[args.index("--secret-file") + 1] == str(secret)


def test_ensure_outlook_adds_host_and_xoauth2(service: ConfigService, cli: FakeCli):
    service.ensure(provider_by_id("outlook"), "me@corp.example")

    args = cli.calls[0]["args"]
    assert args[args.index("--host") + 1] == "outlook.office365.com"
    assert args[args.index("--auth") + 1] == "xoauth2"
    assert args[:3] == ["init", "--email", "me@corp.example"]


def test_ensure_passes_an_explicit_host_override(
    service: ConfigService, cli: FakeCli
):
    service.ensure(provider_by_id("gmail"), "me@gmail.com", host="imap.gmail.com")

    args = cli.calls[0]["args"]
    assert args[args.index("--host") + 1] == "imap.gmail.com"


def test_ensure_passes_the_custom_imap_host(
    service: ConfigService, cli: FakeCli
):
    service.ensure(
        provider_by_id("custom"), "me@example.com", host="imap.example.com"
    )

    args = cli.calls[0]["args"]
    assert args[args.index("--host") + 1] == "imap.example.com"


def test_ensure_rejects_a_custom_provider_without_a_host(
    service: ConfigService, cli: FakeCli
):
    with pytest.raises(ValueError, match="host"):
        service.ensure(provider_by_id("custom"), "me@example.com")

    assert cli.calls == []


def test_ensure_reports_the_port_limitation_instead_of_inventing_a_flag(
    service: ConfigService, cli: FakeCli
):
    with pytest.raises(ConfigServiceError, match="993"):
        service.ensure(
            provider_by_id("custom"),
            "me@example.com",
            host="imap.example.com",
            port=1143,
        )

    assert cli.calls == []


def test_ensure_reports_the_tls_limitation_instead_of_inventing_a_flag(
    service: ConfigService, cli: FakeCli
):
    with pytest.raises(ConfigServiceError, match="TLS"):
        service.ensure(
            provider_by_id("custom"), "me@example.com", host="imap.example.com", ssl=False
        )

    assert cli.calls == []


def test_ensure_does_not_touch_an_existing_config(
    service: ConfigService, cli: FakeCli
):
    path = service.ensure(provider_by_id("gmail"), "me@gmail.com")
    edited = TEMPLATE.format(email="me@gmail.com").replace(
        "name = \"personal\"", "name = \"edited-by-hand\""
    )
    path.write_text(edited, encoding="utf-8")

    again = service.ensure(provider_by_id("gmail"), "me@gmail.com")

    assert again == path
    assert len(cli.calls) == 1
    assert path.read_text(encoding="utf-8") == edited


def test_ensure_rejects_a_config_for_a_different_email(
    service: ConfigService, cli: FakeCli
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(TEMPLATE.format(email="other@example.com"), encoding="utf-8")

    with pytest.raises(ConfigMismatchError) as excinfo:
        service.ensure(provider_by_id("gmail"), "me@gmail.com")

    assert excinfo.value.existing_email == "other@example.com"
    assert excinfo.value.existing_host == "imap.gmail.com"
    assert len(cli.calls) == 0
    assert "other@example.com" in path.read_text(encoding="utf-8")


def test_ensure_treats_email_case_and_whitespace_insensitively(
    service: ConfigService, cli: FakeCli
):
    path = service.ensure(provider_by_id("gmail"), "Me@Gmail.com")

    again = service.ensure(
        provider_by_id("gmail"), "  me@gmail.com  ", host="imap.gmail.com"
    )

    assert again == path
    assert len(cli.calls) == 1


def test_ensure_rejects_a_config_for_a_different_imap_host(
    service: ConfigService, cli: FakeCli
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@gmail.com").replace(
            'imap_host = "imap.gmail.com"', 'imap_host = "imap.other.example"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigMismatchError) as excinfo:
        service.ensure(
            provider_by_id("gmail"), "me@gmail.com", host="imap.gmail.com"
        )

    assert excinfo.value.existing_host == "imap.other.example"
    assert cli.calls == []


def test_ensure_replace_forces_a_new_config(service: ConfigService, cli: FakeCli):
    path = service.ensure(provider_by_id("gmail"), "first@gmail.com")
    assert path.is_file()

    again = service.ensure(
        provider_by_id("gmail"), "second@gmail.com", replace=True
    )

    assert again == path
    assert len(cli.calls) == 2
    assert cli.calls[-1]["args"][-1] == "--force"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["account"]["email"] == "second@gmail.com"


def test_ensure_replace_on_a_matching_config_still_forces(
    service: ConfigService, cli: FakeCli
):
    service.ensure(provider_by_id("gmail"), "me@gmail.com")

    service.ensure(provider_by_id("gmail"), "me@gmail.com", replace=True)

    assert cli.calls[-1]["args"][-1] == "--force"


def test_ensure_raises_a_clear_error_when_init_fails(
    service: ConfigService, cli: FakeCli
):
    cli.init_ok = False

    with pytest.raises(ConfigServiceError, match="cannot write the file"):
        service.ensure(provider_by_id("gmail"), "me@gmail.com")

    assert not service.config_path().exists()


@pytest.mark.parametrize("email", ["", "   ", "not-an-email"])
def test_ensure_rejects_a_bad_email(service: ConfigService, cli: FakeCli, email: str):
    with pytest.raises(ValueError):
        service.ensure(provider_by_id("gmail"), email)
    assert cli.calls == []


def test_update_preferences_writes_the_policy_and_preserves_everything_else(
    service: ConfigService,
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(TEMPLATE.format(email="me@gmail.com"), encoding="utf-8")

    service.update_preferences(
        Preferences(
            categories=["newsletter"],
            mode="archive",
            protect_starred=False,
            protect_answered=False,
            min_age_days=7,
            max_moves=10,
            max_per_group=25,
            language="es",
        )
    )

    raw = path.read_text(encoding="utf-8")
    data = tomllib.loads(raw)

    assert data["scan"]["days"] == 365
    assert data["scan"]["mailboxes"] == ["INBOX"]
    assert data["scan"]["batch_size"] == 200

    assert data["policy"] == {
        "min_age_days": 7,
        "protect_answered": False,
        "protect_flagged": False,
        "protect_domains": [],
        "protect_addresses": [],
        "never_unsubscribe_domains": [],
        "max_messages_per_run": 10,
        "max_messages_per_group": 25,
        "move_spam_to_junk": True,
    }

    # The account and every unrelated section are untouched.
    assert data["account"]["email"] == "me@gmail.com"
    assert data["account"]["password_file"] == "C:/Users/me/.secrets/cleanyourmail.txt"
    assert data["account"]["imap_host"] == "imap.gmail.com"
    assert data["unsubscribe"]["max_requests"] == 25
    assert data["folders"]["root"] == "CleanYourMail"

    assert "# The password is NOT stored here" in raw
    assert "# Messages younger than this are never moved." in raw
    assert raw.count("[account]") == 1
    assert len(raw.splitlines()) == len(TEMPLATE.format(email="me@gmail.com").splitlines())


def test_update_preferences_keeps_crlf_line_endings(service: ConfigService):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(TEMPLATE.format(email="me@gmail.com").replace("\n", "\r\n").encode())

    service.update_preferences(Preferences(min_age_days=14, max_moves=20))

    raw = path.read_bytes()
    assert b"min_age_days = 14\r\n" in raw
    assert b"max_messages_per_run = 20\r\n" in raw
    assert b"\n" in raw and b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert tomllib.loads(raw.decode("utf-8"))["policy"]["min_age_days"] == 14


def test_update_preferences_refuses_when_a_key_is_missing(service: ConfigService):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    broken = TEMPLATE.format(email="me@gmail.com").replace(
        "max_messages_per_group = 200\n", ""
    )
    path.write_text(broken, encoding="utf-8")

    with pytest.raises(ConfigServiceError, match="max_messages_per_group"):
        service.update_preferences(Preferences())

    assert path.read_text(encoding="utf-8") == broken


def test_update_preferences_refuses_without_a_config(service: ConfigService):
    with pytest.raises(ConfigServiceError, match="cleanyourmail.toml"):
        service.update_preferences(Preferences())


def test_validate_returns_the_sidecar_json(service: ConfigService, cli: FakeCli):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(TEMPLATE.format(email="me@gmail.com"), encoding="utf-8")

    result = service.validate()

    assert result == cli.validate_payload
    assert cli.calls[-1]["args"] == ["validate"]
    assert cli.calls[-1]["config_path"] == path


def test_validate_marks_a_failed_sidecar(service: ConfigService):
    class FailingCli(FakeCli):
        def run(self, args, *, config_path=None, timeout=120):
            return {
                "ok": False,
                "exit_code": 2,
                "data": {},
                "stdout": "",
                "stderr": "Config: no such file\n",
            }

    result = ConfigService(FailingCli(), service.app_data).validate()

    assert result["ok"] is False
    assert "no such file" in result["error"]

def test_password_file_reads_the_configs_absolute_path(service: ConfigService):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    target = Path("C:/Users/me/.secrets/other.txt")
    path.write_text(
        TEMPLATE.format(email="me@gmail.com").replace(
            'password_file = "C:/Users/me/.secrets/cleanyourmail.txt"',
            f'password_file = "{target.as_posix()}"',
        ),
        encoding="utf-8",
    )

    assert service.password_file() == target


def test_password_file_resolves_a_relative_path_against_the_config(
    service: ConfigService,
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@gmail.com").replace(
            'password_file = "C:/Users/me/.secrets/cleanyourmail.txt"',
            'password_file = "secrets/local.txt"',
        ),
        encoding="utf-8",
    )

    assert service.password_file() == path.parent / "secrets" / "local.txt"


def test_password_file_expands_the_user_home(service: ConfigService):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@gmail.com").replace(
            'password_file = "C:/Users/me/.secrets/cleanyourmail.txt"',
            'password_file = "~/.secrets/cleanyourmail.txt"',
        ),
        encoding="utf-8",
    )

    assert service.password_file() == Path.home() / ".secrets" / "cleanyourmail.txt"


def test_password_file_falls_back_when_the_config_is_missing(
    service: ConfigService,
):
    assert service.password_file() == service.secret_path


def test_state_dir_defaults_to_the_cli_local_app_data(
    service: ConfigService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.delenv("CYM_STATE_DIR", raising=False)
    monkeypatch.setattr("cleanyourmail_app.services.config.os.name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert service.state_dir() == tmp_path / "local" / "CleanYourMail"


def test_state_dir_honours_cym_state_dir(
    service: ConfigService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("CYM_STATE_DIR", str(tmp_path / "override"))

    assert service.state_dir() == tmp_path / "override"


def test_state_dir_prefers_the_account_value(
    service: ConfigService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@gmail.com").replace(
            "imap_starttls = false",
            f'imap_starttls = false\nstate_dir = "{(tmp_path / "from-config").as_posix()}"',
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CYM_STATE_DIR", str(tmp_path / "override"))

    assert service.state_dir() == tmp_path / "from-config"

def test_state_dir_reads_the_top_level_cli_key(
    service: ConfigService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@gmail.com").replace(
            "\n[scan]",
            f'\nstate_dir = "{(tmp_path / "top-level").as_posix()}"\n\n[scan]',
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("CYM_STATE_DIR", raising=False)

    assert service.state_dir() == tmp_path / "top-level"

def test_proton_refuses_a_same_email_config_for_another_host(
    service: ConfigService, cli: FakeCli
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@proton.me").replace(
            'imap_host = "imap.gmail.com"', 'imap_host = "imap.other.example"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigMismatchError):
        service.ensure(provider_by_id("proton"), "me@proton.me")

    assert cli.calls == []


def test_proton_accepts_its_preset_host_without_running_init(
    service: ConfigService, cli: FakeCli
):
    path = service.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        TEMPLATE.format(email="me@proton.me").replace(
            'imap_host = "imap.gmail.com"', 'imap_host = "127.0.0.1"'
        ),
        encoding="utf-8",
    )

    again = service.ensure(provider_by_id("proton"), "me@proton.me")

    assert again == path
    assert cli.calls == []
