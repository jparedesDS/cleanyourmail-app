"""Tests for the CLI sidecar client; they never touch a mailbox or network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cleanyourmail_app.services.cli import (
    EXPECTED_CLI_VERSION,
    VERSION_TIMEOUT,
    CliClient,
    CliError,
    CliVersionMismatch,
    find_sidecar,
)

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_cli.py"


class FakeCli:
    """Drive ``tests/fixtures/fake_cli.py`` through its environment contract."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.response = tmp_path / "response.txt"
        self.argv = tmp_path / "argv.json"
        self.stderr = tmp_path / "stderr.txt"
        self._monkeypatch = monkeypatch
        self.response.write_text("", encoding="utf-8")
        self.stderr.write_text("", encoding="utf-8")
        monkeypatch.setenv("FAKE_CLI_RESPONSE", str(self.response))
        monkeypatch.setenv("FAKE_CLI_ARGV", str(self.argv))
        monkeypatch.setenv("FAKE_CLI_STDERR", str(self.stderr))
        monkeypatch.setenv("FAKE_CLI_EXIT", "0")
        monkeypatch.delenv("CYM_CLI", raising=False)

    def respond(
        self,
        payload: str | dict,
        *,
        exit_code: int = 0,
        stderr: str = "",
    ) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.response.write_text(text, encoding="utf-8")
        self.stderr.write_text(stderr, encoding="utf-8")
        self._monkeypatch.setenv("FAKE_CLI_EXIT", str(exit_code))

    def client(self, env: dict[str, str] | None = None) -> CliClient:
        return CliClient([sys.executable, str(FAKE_CLI)], env=env)

    def recorded_argv(self) -> list[str]:
        return json.loads(self.argv.read_text(encoding="utf-8"))


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    return FakeCli(tmp_path, monkeypatch)


def test_run_returns_ok_data_and_exit_code(fake: FakeCli, tmp_path: Path):
    payload = {"ok": True, "server": {"host": "imap.example.com", "capabilities": []}}
    fake.respond(payload)

    result = fake.client().run(["doctor"], config_path=tmp_path / "cleanyourmail.toml")

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["data"] == payload
    assert result["stdout"].strip() == json.dumps(payload)
    assert result["stderr"] == ""


def test_run_appends_json_and_config(fake: FakeCli, tmp_path: Path):
    fake.respond({"ok": True})
    config = tmp_path / "cleanyourmail.toml"

    fake.client().run(["doctor"], config_path=config)

    assert fake.recorded_argv() == ["doctor", "--json", "--config", str(config)]


def test_run_without_config_omits_config_flag(fake: FakeCli):
    fake.respond({"ok": True})

    fake.client().run(["validate"])

    argv = fake.recorded_argv()
    assert argv == ["validate", "--json"]
    assert "--config" not in argv


def test_non_zero_exit_returns_stderr_without_raising(fake: FakeCli, tmp_path: Path):
    fake.respond(
        {"ok": False, "error": "no config"},
        exit_code=2,
        stderr=f"Config: Config file not found: {tmp_path / 'absent.toml'}\n",
    )

    result = fake.client().run(["doctor"], config_path=tmp_path / "absent.toml")

    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert result["data"] == {"ok": False, "error": "no config"}
    assert "Config file not found" in result["stderr"]


def test_non_json_output_leaves_data_empty(fake: FakeCli):
    fake.respond("Stopped: IMAP refused the login\n", exit_code=2)

    result = fake.client().run(["doctor"])

    assert result["ok"] is False
    assert result["exit_code"] == 2
    assert result["data"] == {}
    assert "IMAP refused" in result["stdout"]


def test_json_after_a_progress_line_is_still_read(fake: FakeCli):
    fake.respond('Warning: cache is cold\n{"ok": true, "total": 2}\n')

    result = fake.client().run(["scan"])

    assert result["ok"] is True
    assert result["data"] == {"ok": True, "total": 2}


def test_json_failure_wins_over_a_zero_exit(fake: FakeCli):
    fake.respond({"ok": False, "error": "locked"})

    result = fake.client().run(["apply", "plan.json"])

    assert result["exit_code"] == 0
    assert result["ok"] is False


def test_version_reads_the_sidecar_line(fake: FakeCli):
    fake.respond("CleanYourMail 1.2.2\n")

    assert fake.client().version() == "CleanYourMail 1.2.2"
    assert fake.recorded_argv() == ["--version"]


def test_version_raises_when_the_sidecar_fails(fake: FakeCli):
    fake.respond("", exit_code=2, stderr="boom")

    with pytest.raises(CliError):
        fake.client().version()


def test_version_uses_a_short_local_timeout(monkeypatch: pytest.MonkeyPatch):
    client = CliClient(["cym-cli"])
    seen: dict[str, object] = {}

    def fake_execute(argv, timeout):
        seen["argv"] = argv
        seen["timeout"] = timeout
        return subprocess.CompletedProcess(
            argv, 0, "CleanYourMail 1.2.2\n", ""
        )

    monkeypatch.setattr(client, "_execute", fake_execute)

    assert client.version() == "CleanYourMail 1.2.2"
    assert seen["argv"] == ["cym-cli", "--version"]
    assert seen["timeout"] == VERSION_TIMEOUT
    assert VERSION_TIMEOUT <= 5


def test_cached_version_appears_after_a_verified_read(fake: FakeCli):
    fake.respond("CleanYourMail 1.2.2\n")
    client = fake.client()

    assert client.cached_version is None
    client.verify_version()

    assert client.cached_version == EXPECTED_CLI_VERSION


def test_missing_executable_raises_cli_error(tmp_path: Path):
    client = CliClient(["cym-cli-does-not-exist-xyz"])

    with pytest.raises(CliError):
        client.run(["validate"])


def test_find_sidecar_returns_none_without_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("CYM_CLI", raising=False)

    assert find_sidecar(tmp_path) is None


def test_find_sidecar_finds_the_bundled_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("CYM_CLI", raising=False)
    bundled = tmp_path / "resources" / "cli" / "cym-cli.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"fake")

    assert find_sidecar(tmp_path) == bundled


def test_find_sidecar_checks_cym_cli_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bundled = tmp_path / "resources" / "cli" / "cym-cli.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"fake")
    override = tmp_path / "override" / "cym-cli.exe"
    override.parent.mkdir()
    override.write_bytes(b"fake")
    monkeypatch.setenv("CYM_CLI", str(override))

    assert find_sidecar(tmp_path) == override
    assert find_sidecar(tmp_path, explicit=str(bundled)) == bundled


def test_no_secret_is_passed_in_argv_or_output(fake: FakeCli, tmp_path: Path):
    sentinel = "sentinel-app-password"
    fake.respond({"ok": True, "email": "me@example.com"})
    client = fake.client(env={"CYM_PASSWORD": sentinel})

    result = client.run(["doctor"], config_path=tmp_path / "cleanyourmail.toml")

    argv = fake.recorded_argv()
    assert sentinel not in " ".join(argv)
    assert not any(token.lower().startswith("--password") for token in argv)
    assert sentinel not in result["stdout"] + result["stderr"]
    # The client forwards the caller's environment and adds no keys of its own.
    assert set(client.env) == set(os.environ) | {"CYM_PASSWORD"}

def test_verify_version_caches_a_success(fake: FakeCli):
    fake.respond("CleanYourMail 1.2.2\n")

    class CountingClient(CliClient):
        def __init__(self) -> None:
            super().__init__([sys.executable, str(FAKE_CLI)])
            self.version_calls = 0

        def version(self) -> str:
            self.version_calls += 1
            return super().version()

    client = CountingClient()

    assert client.verify_version() == EXPECTED_CLI_VERSION
    assert client.verify_version() == EXPECTED_CLI_VERSION
    assert client.version_calls == 1


def test_verify_version_rejects_a_different_build(fake: FakeCli):
    fake.respond("CleanYourMail 1.2.1\n")

    with pytest.raises(CliVersionMismatch, match="1.2.1"):
        fake.client().verify_version()


def test_verify_version_propagates_a_missing_sidecar(tmp_path: Path):
    client = CliClient(["cym-cli-does-not-exist-xyz"])

    with pytest.raises(CliError):
        client.verify_version()


def test_run_cancels_a_slow_sidecar_and_returns_a_normalized_result():
    event = threading.Event()
    client = CliClient([sys.executable, "-c", "import time; time.sleep(30)"])
    result: dict[str, object] = {}
    started = time.monotonic()

    def work() -> None:
        result.update(
            client.run(["connect", "outlook", "--wait"], timeout=60, cancel_event=event)
        )

    worker = threading.Thread(target=work)
    worker.start()
    event.set()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert time.monotonic() - started < 10
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["exit_code"] == -1
    assert result["data"] == {}

def test_print_version_returns_the_sidecar_line(fake: FakeCli):
    fake.respond("CleanYourMail 1.2.2\n")

    assert fake.client().print_version() == EXPECTED_CLI_VERSION
