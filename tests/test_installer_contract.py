"""Packaging contract: static installer/spec rules plus the frozen binaries.

The static checks always run: they catch a move back to a machine-wide install,
a destructive uninstaller, a console-subsystem app or an accidentally committed
sidecar before anyone builds the installer. The source app version test also
always runs. The sidecar checks need ``CYM_CLI``; the frozen app check needs
``CYM_APP_EXE``. Missing binaries skip rather than silently testing the source
tree, so the default suite needs no build product or network.

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
SMOKE = ROOT / "scripts" / "smoke-installer.ps1"
SIDECAR_BUILD = ROOT / "scripts" / "build-cli-sidecar.ps1"

SIDECAR_VERSION = "CleanYourMail 1.2.2"
APP_VERSION = "CleanYourMail app 0.3.0"

# Inno Setup writes the literal AppId as "{{GUID}" (the doubled brace escapes
# the opening brace). Exactly one such line is allowed, and it must be a GUID.
APP_ID = re.compile(
    r"^\{\{([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\}$"
)

UNINSTALL_SECTIONS = ("uninstalldelete", "uninstallrun")
PATH_FIELDS = ("name", "filename", "workingdir")
USER_DATA_TOKENS = (
    "{userappdata}",
    "{appdata}",
    "{localappdata}",
    "{userprofile}",
    ".secrets",
    "cleanyourmail-app",
)


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


def _single_assignment(text: str, name: str) -> str:
    """The value of exactly one ``name=...`` line, or a test failure."""
    matches = re.findall(rf"^{re.escape(name)}=(.*)$", text, re.MULTILINE)
    assert len(matches) == 1, f"expected exactly one {name}= line, found {len(matches)}"
    return matches[0].strip()


def _field(entry: str, name: str) -> str | None:
    match = re.search(rf"\b{name}:\s*\"([^\"]*)\"", entry, re.IGNORECASE)
    return match.group(1) if match else None


def _assert_safe_uninstall_sections(text: str) -> None:
    """Reject [UninstallDelete]/[UninstallRun] entries that leave ``{app}``.

    A future entry must be a normalised ``{app}``-relative path. ``..``,
    drive-absolute paths, appdata/secrets tokens and unchecked parameters all
    fail. The shipped installer has neither section; this guard is what makes
    adding one a deliberate, tested decision.
    """
    sections = _sections(text)
    for section in UNINSTALL_SECTIONS:
        for entry in sections.get(section, []):
            if not entry or entry.startswith(";"):
                continue

            checked = False
            for field in PATH_FIELDS:
                value = _field(entry, field)
                if value is None:
                    continue
                checked = True
                lowered = value.lower()
                assert not any(token in lowered for token in USER_DATA_TOKENS), (
                    f"{section} touches user data: {entry}"
                )
                assert lowered.startswith("{app}"), (
                    f"{section} path is outside {{app}}: {entry}"
                )

                remainder = value[len("{app}") :]
                if remainder:
                    assert remainder.startswith(("\\", "/")), (
                        f"{section} path is not {{app}}-relative: {entry}"
                    )
                    relative = remainder.replace("/", "\\").strip("\\")
                    if relative:
                        assert all(
                            part not in ("", ".", "..") for part in relative.split("\\")
                        ), f"{section} path escapes {{app}}: {entry}"
                        assert not re.match(r"^[A-Za-z]:", relative), (
                            f"{section} path is drive-absolute: {entry}"
                        )

            parameters = _field(entry, "parameters")
            if parameters is not None:
                checked = True
                lowered = parameters.lower()
                assert not any(token in lowered for token in USER_DATA_TOKENS), (
                    f"{section} parameters touch user data: {entry}"
                )
                assert ".." not in parameters, (
                    f"{section} parameters can escape {{app}}: {entry}"
                )

            assert checked, f"{section} entry has no inspected path: {entry}"


# ---------------------------------------------------------------------------
# Static checks: they run in every CI matrix entry.
# ---------------------------------------------------------------------------


def test_installer_is_per_user_and_named_for_this_version():
    text = _read(INSTALLER)

    assert _single_assignment(text, "PrivilegesRequired") == "lowest"
    assert (
        _single_assignment(text, "DefaultDirName")
        == r"{localappdata}\Programs\CleanYourMail"
    )
    assert _single_assignment(text, "OutputBaseFilename") == "CleanYourMail-Setup-0.3.0"
    assert _single_assignment(text, "ArchitecturesAllowed") == "x64"
    assert _single_assignment(text, "ArchitecturesInstallIn64BitMode") == "x64"
    assert _single_assignment(text, "Compression") == "lzma2"
    assert _single_assignment(text, "SetupLogging") == "yes"
    assert _single_assignment(text, "UninstallDisplayIcon").lower().startswith("{app}\\")

    app_id = _single_assignment(text, "AppId")
    match = APP_ID.fullmatch(app_id)
    assert match, f"AppId is not one valid GUID: {app_id!r}"
    assert match.group(1).upper() != "6C5F9A7E-2D4B-4E8A-9C31-3F0B6B1D8A42"

    assert 'Name: "english"' in text
    assert 'Name: "spanish"' in text
    assert r'Name: "{autoprograms}\CleanYourMail"' in text
    assert "desktopicon" in text
    assert "Flags: unchecked" in text
    assert r'Source: "..\dist\CleanYourMail\*"' in text
    assert "THIRD_PARTY_NOTICES.md" in text
    assert "LICENSE" in text


def test_uninstaller_has_no_uninstall_delete_or_run():
    text = _read(INSTALLER)
    sections = _sections(text)

    assert "uninstalldelete" not in sections, (
        "the installer must not delete user data; use Inno's tracked-file removal"
    )
    assert "uninstallrun" not in sections, (
        "the installer must not run user-data commands on uninstall"
    )
    _assert_safe_uninstall_sections(text)


@pytest.mark.parametrize(
    "section,entry",
    [
        (
            "UninstallDelete",
            r'Type: files; Name: "{userappdata}\cleanyourmail-app\settings.json"',
        ),
        (
            "UninstallDelete",
            r'Type: files; Name: "{app}\..\..\Users\Public\.secrets\cleanyourmail.txt"',
        ),
        (
            "UninstallDelete",
            r'Type: files; Name: "{app}\..\..\cleanyourmail-app\settings.json"',
        ),
        (
            "UninstallRun",
            r'Filename: "{app}\..\..\evil.exe"',
        ),
        (
            "UninstallRun",
            r'Filename: "{app}\safe.exe"; Parameters: "/c del {userappdata}\x"',
        ),
    ],
)
def test_uninstall_guard_rejects_user_data_paths(tmp_path: Path, section: str, entry: str):
    script = tmp_path / "malicious.iss"
    script.write_text(f"[{section}]\n{entry}\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_safe_uninstall_sections(script.read_text(encoding="utf-8"))


def test_uninstall_guard_accepts_an_app_local_entry(tmp_path: Path):
    script = tmp_path / "safe.iss"
    script.write_text(
        '[UninstallDelete]\nType: files; Name: "{app}\\unins000.dat"\n',
        encoding="utf-8",
    )

    _assert_safe_uninstall_sections(script.read_text(encoding="utf-8"))


def test_spec_is_onedir_windowed_and_bundles_the_sidecar():
    text = _read(SPEC)

    assert re.search(r'^\s*name="CleanYourMail",\s*$', text, re.MULTILINE)
    assert re.search(r'^\s*contents_directory="\.",\s*$', text, re.MULTILINE)
    assert re.search(r"^\s*console=False,\s*$", text, re.MULTILINE)
    assert "COLLECT(" in text
    assert "exclude_binaries=True" in text
    assert re.search(
        r'a\.datas\s*\+=\s*Tree\(\s*str\(\s*RESOURCES\s*/\s*"cli"\s*\)\s*,'
        r'\s*prefix="resources/cli"\s*\)',
        text,
    ), "the sidecar must be staged with Tree(..., prefix='resources/cli')"
    assert "theme.qss" in text
    assert 'glob("*.json")' in text
    assert '"ui" / "resources"' in text
    assert "cym-cli.exe" in text


def test_gitignore_covers_build_outputs():
    lines = {line.strip().rstrip("/") for line in _read(GITIGNORE).splitlines()}

    assert "resources/cli" in lines
    assert ".build" in lines
    assert "dist" in lines
    assert "build" in lines


def test_smoke_installer_is_secret_safe_and_checks_the_state_dir():
    text = _read(SMOKE)

    assert "Get-FileHash" not in text, "the smoke must not hash user data"
    assert "Get-Content -LiteralPath $SecretFile" not in text
    assert "LastWriteTimeUtc" in text
    assert "%LOCALAPPDATA%" in text or "$env:LOCALAPPDATA" in text
    assert 'Join-Path $env:LOCALAPPDATA "cleanyourmail-app"' in text
    assert '"state"' in text or "\\state" in text
    assert "cleanyourmail.txt" in text


def test_sidecar_reuse_requires_a_clean_matching_checkout():
    text = _read(SIDECAR_BUILD)

    assert "describe --tags --exact-match" in text
    assert "remote get-url origin" in text
    assert "status --porcelain" in text
    assert "re-cloning" in text


# ---------------------------------------------------------------------------
# Version checks: source always, frozen binaries when staged.
# ---------------------------------------------------------------------------

requires_sidecar = pytest.mark.skipif(
    not os.environ.get("CYM_CLI"),
    reason="CYM_CLI is not set; the frozen 1.2.2 sidecar is not available",
)
requires_frozen_app = pytest.mark.skipif(
    not os.environ.get("CYM_APP_EXE"),
    reason="CYM_APP_EXE is not set; the frozen app is not available",
)


def _source_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "src"), env.get("PYTHONPATH", "")) if part
    )
    return env


def _sidecar_command() -> list[str]:
    value = os.environ.get("CYM_CLI", "")
    path = Path(value)
    if not path.is_file():
        pytest.fail(f"CYM_CLI does not point to a file: {value}")
    return [str(path)]


def test_source_app_version():
    completed = subprocess.run(
        [sys.executable, "-m", "cleanyourmail_app", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=_source_env(),
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == APP_VERSION


@requires_sidecar
def test_frozen_sidecar_version_is_pinned():
    assert CliClient(_sidecar_command()).version() == SIDECAR_VERSION


@requires_sidecar
def test_frozen_sidecar_validate_fails_cleanly_without_a_config(tmp_path: Path):
    missing = tmp_path / "absent.toml"

    result = CliClient(_sidecar_command()).run(["validate"], config_path=missing)

    assert result["ok"] is False
    assert result["exit_code"] != 0
    message = (result["stderr"] + result["stdout"]).lower()
    assert "config" in message
    assert "not found" in message
    assert "traceback" not in message


@requires_frozen_app
def test_frozen_app_version():
    exe = Path(os.environ["CYM_APP_EXE"])
    assert exe.is_file(), f"CYM_APP_EXE does not point to a file: {exe}"

    completed = subprocess.run(
        [str(exe), "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == APP_VERSION
