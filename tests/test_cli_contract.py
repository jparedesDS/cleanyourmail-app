"""Contract tests against the frozen CleanYourMail 1.3.0 sidecar.

They run only when ``CYM_CLI`` points to the sidecar, so the default suite needs
no binary, no mailbox and no network. The sidecar version and the app's JSON
assumptions are pinned here; a drift in either fails the build.

``CYM_CLI`` names one executable (or launcher) path, the same value
``find_sidecar`` reads.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cleanyourmail_app.services.cli import CliClient

SIDECAR_VERSION = "CleanYourMail 1.3.0"

pytestmark = pytest.mark.skipif(
    not os.environ.get("CYM_CLI"),
    reason="CYM_CLI is not set; the frozen 1.3.0 sidecar is not available",
)


def _sidecar_command() -> list[str]:
    value = os.environ.get("CYM_CLI", "")
    path = Path(value)
    if not path.is_file():
        pytest.fail(f"CYM_CLI does not point to a file: {value}")
    return [str(path)]


@pytest.fixture(scope="module")
def client() -> CliClient:
    return CliClient(_sidecar_command())


def test_version_is_pinned(client: CliClient):
    assert client.version() == SIDECAR_VERSION


def test_validate_returns_ok(client: CliClient, tmp_path: Path):
    config = tmp_path / "cleanyourmail.toml"
    init = client.run(
        ["init", "--email", "me@example.com", "--host", "imap.example.com"],
        config_path=config,
    )
    assert init["exit_code"] == 0, init["stderr"]

    result = client.run(["validate"], config_path=config)

    assert result["ok"] is True, result["stderr"]
    assert result["exit_code"] == 0
    assert result["data"].get("ok") is True


def test_doctor_without_a_config_fails_cleanly(client: CliClient, tmp_path: Path):
    # An absent --config keeps the test offline even on a machine with a real
    # config at the CLI's default path: doctor never reaches the network.
    missing = tmp_path / "absent.toml"

    result = client.run(["doctor"], config_path=missing)

    assert result["exit_code"] != 0
    assert result["ok"] is False
    message = (result["stderr"] + result["stdout"]).lower()
    assert "config" in message
    assert "not found" in message
