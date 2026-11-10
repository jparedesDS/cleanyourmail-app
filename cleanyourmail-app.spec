# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the CleanYourMail desktop app (onedir).

``scripts/build-cli-sidecar.ps1`` stages the frozen CLI under
``resources/cli`` before this spec runs. ``contents_directory="."`` keeps
``resources`` next to ``CleanYourMail.exe`` inside ``dist/CleanYourMail`` so
the frozen ``app_root()`` finds the sidecar with the same relative path used in
development, and the installer ships one self-contained directory.

The app is windowed (``console=False``). The sidecar is a separate console
executable; ``CliClient`` starts it with ``CREATE_NO_WINDOW``.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve()
if ROOT.suffix == ".spec":
    ROOT = ROOT.parent
APP = ROOT / "src" / "cleanyourmail_app"
RESOURCES = ROOT / "resources"
SIDECAR = RESOURCES / "cli" / "cym-cli.exe"
ICON = ROOT / "packaging" / "app.ico"

if not SIDECAR.is_file():
    raise SystemExit(
        f"missing packaging input: {SIDECAR}. "
        "Run scripts/build-cli-sidecar.ps1 before building the app."
    )

for required in (
    APP / "ui" / "theme.qss",
    APP / "ui" / "resources" / "app-icon.svg",
    APP / "i18n" / "en.json",
    APP / "i18n" / "es.json",
):
    if not required.is_file():
        raise SystemExit(f"missing packaging input: {required}")

datas = [(str(APP / "ui" / "theme.qss"), "cleanyourmail_app/ui")]
datas += [
    (str(path), "cleanyourmail_app/ui/resources")
    for path in sorted((APP / "ui" / "resources").iterdir())
    if path.is_file()
]
datas += [
    (str(path), "cleanyourmail_app/i18n")
    for path in sorted((APP / "i18n").glob("*.json"))
]

a = Analysis(
    [str(APP / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
a.datas += Tree(str(RESOURCES / "cli"), prefix="resources/cli")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CleanYourMail",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.is_file() else None,
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CleanYourMail",
)
