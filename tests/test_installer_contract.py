"""Packaging contract: static installer/spec rules plus the frozen sidecar.

The static checks always run: they catch a move back to a machine-wide install,
a destructive uninstaller, a console-subsystem app or an accidentally committed
sidecar before anyone builds the installer. The live checks need ``CYM_CLI`` to
point at the staged sidecar (and optionally ``CYM_APP_EXE`` at the frozen app);
without it they are skipped, so the default suite needs no binary or network.

No test here reads a real config, secret or mailbox.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from cleanyourmail_app.services.cli import CliClient

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "packaging" / "installer.iss"
SPEC = ROOT / "cleanyourmail-app.spec"
GITIGNORE = ROOT / ".gitignore"

SIDECAR_VERSION = "CleanYourMail 1.2.2"
APP_VERSION = "CleanYourMail app 0.3.0"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing packaging file: {path}"
    return path.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, list[str]]:
    """Split an Inno Setup script into ``[Section]`` -> entry lines."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        match = re.fullmatch(r"\[([^\]]+)\]", line)
        if match:
            current = match.group(1).lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


# ---------------------------------------------------------------------------
# Static checks: they run in every CI matrix entry.
# ---------------------------------------------------------------------------


def test_installer_is_per_user_and_named_for_this_version():
    text = _read(INSTALLER)

    assert re.search(r"^PrivilegesRequired=lowest\s*$", text, re.MULTILINE)
    assert r"{localappdata}\Programs\CleanYourMail" in text
    assert re.search(
        r"^OutputBaseFilename=CleanYourMail-Setup-0\.3\.0\s*$", text, re.MULTILINE
    )
    assert re.search(r"^ArchitecturesAllowed=x64\s*$", text, re.MULTILINE)
    assert re.search(r"^UninstallDisplayIcon=\{app\}", text, re.MULTILINE)
    assert re.search(r"^SetupLogging=yes\s*$", text, re.MULTILINE)
    assert 'Name: "english"' in text
    assert 'Name: "spanish"' in text
    assert r'Name: "{autoprograms}\CleanYourMail"' in text
    assert "desktopicon" in text
    assert "Flags: unchecked" in text
    assert re.search(r"^AppId=\{\{[0-9A-F-]{36}\}", text, re.MULTILINE)
    assert "6C5F9A7E-2D4B-4E8A-9C31-3F0B6B1D8A42" not in text
    assert r'Source: "..\dist\CleanYourMail\*"' in text
    assert "THIRD_PARTY_NOTICES.md" in text
    assert "LICENSE" in text


def test_uninstaller_never_deletes_user_data():
    sections = _sections(_read(INSTALLER))
    entries = [
        line
        for line in sections.get("uninstalldelete", [])
        if line and not line.startswith(";")
    ]

    for entry in entries:
        lowered = entry.lower()
        assert "%appdata%" not in lowered, f"uninstaller touches appdata: {entry}"
        assert ".secrets" not in lowered, f"uninstaller touches secrets: {entry}"
        assert "cleanyourmail-app" not in lowered, f"uninstaller touches app state: {entry}"

    # If a section is ever added, its names must stay inside the install dir.
    for entry in entries:
        name = re.search(r"(?:^|\s)Name:\s*\"([^\"]+)\"", entry)
        if name is not None:
            assert name.group(1).lower().startswith("{app}"), entry


def test_spec_is_onedir_windowed_and_bundles_the_sidecar():
    text = _read(SPEC)

    assert 'name="CleanYourMail"' in text
    assert 'contents_directory="."' in text
    assert re.search(r"^\s*console=False,\s*$", text, re.MULTILINE)
    assert "COLLECT(" in text
    assert "exclude_binaries=True" in text
    assert "resources/cli" in text
    assert 'Tree(' in text
    assert "theme.qss" in text
    assert 'glob("*.json")' in text
    assert '"ui" / "resources"' in text
    assert 'i18n' in text
    assert "cym-cli.exe" in text


def test_gitignore_covers_build_outputs():
    lines = {line.strip().rstrip("/") for line in _read(GITIGNORE).splitlines()}

    assert "resources/cli" in lines
    assert ".build" in lines
    assert "dist" in lines
    assert "build" in lines


# ---------------------------------------------------------------------------
# Live checks: only with the staged sidecar (and optionally the frozen app).
# ---------------------------------------------------------------------------

pytestmark_live = pytest.mark.skipif(
    not os.environ.get("CYM_CLI"),
    reason="CYM_CLI is not set; the frozen 1.2.2 sidecar is not available",
)


def _sidecar_command() -> list[str]:
    value = os.environ.get("CYM_CLI", "")
    path = Path(value)
    if not path.is_file():
        pytest.fail(f"CYM_CLI does not point to a file: {value}")
    return [str(path)]


@pytestmark_live
def test_frozen_sidecar_version_is_pinned():
    assert CliClient(_sidecar_command()).version() == SIDECAR_VERSION


@pytestmark_live
def test_frozen_sidecar_validate_fails_cleanly_without_a_config(tmp_path: Path):
    missing = tmp_path / "absent.toml"

    result = CliClient(_sidecar_command()).run(["validate"], config_path=missing)

    assert result["ok"] is False
    assert result["exit_code"] != 0
    message = (result["stderr"] + result["stdout"]).lower()
    assert "config" in message
    assert "not found" in message
    assert "traceback" not in message


@pytestmark_live
def test_frozen_app_version():
    exe = os.environ.get("CYM_APP_EXE")
    if exe:
        command = [str(Path(exe)), "--version"]
    else:
        command = [sys.executable, "-m", "cleanyourmail_app", "--version"]

    env = dict(os.environ)
    if not exe:
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(ROOT / "src"), env.get("PYTHONPATH", "")) if part
        )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == APP_VERSION
