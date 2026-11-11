<p align="center">
  <img src="docs/banner.png" alt="CleanYourMail — your inbox, minus the noise" width="100%">
</p>

<p align="center">
  <a href="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml"><img src="https://github.com/jparedesDS/cleanyourmail-app/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/license-MIT-b9f36a?labelColor=08110d" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12%2B-b9f36a?labelColor=08110d" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/windows-10%2F11%20x64-b9f36a?labelColor=08110d" alt="Windows 10/11 x64">
  <img src="https://img.shields.io/badge/local--by--default-opt%20in%20feedback-b9f36a?labelColor=08110d" alt="Local by default; opt-in feedback">
</p>

<p align="center">
  <b>English</b> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.pt-BR.md">Português (BR)</a> ·
  <a href="README.fr.md">Français</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.ja.md">日本語</a> ·
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.ko.md">한국어</a>
</p>

# CleanYourMail app

**Your inbox, minus the noise — as a native Windows app.** CleanYourMail app is a PySide6 front end
for the [CleanYourMail](https://github.com/jparedesDS/cleanyourmail) CLI. It guides you through
connecting a mailbox, choosing what to clean, reviewing a reversible plan and undoing it.

No browser, no local server, no account, no telemetry, no bodies, no permanent deletion. The app
itself only calls the public GitHub release feed (for updates) and the feedback Worker (only after
you press Send and accept the consent line).

> **Status:** `0.6.0` is the current Windows early-MVP release. It adds automatic updates: the
> installed app checks the public GitHub release, verifies the installer's SHA-256 and installs it
> after one confirmation. The installer bundles the frozen CleanYourMail CLI `1.3.0` sidecar. Gmail
> is validated; Outlook depends on Microsoft's consent model. See
> [Provider status](#provider-status).

## Download

[CleanYourMail app 0.6.0 for Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
is a per-user installer that bundles the pinned CleanYourMail CLI `1.3.0` sidecar and needs no
administrator rights.

The 0.6.0 installer is not code-signed. Windows SmartScreen may show an "Unknown publisher"
warning on first launch: choose **More info**, then **Run anyway**, and compare the SHA-256
published with the release against `CleanYourMail-Setup-0.6.0.exe`:

```powershell
Get-FileHash .\CleanYourMail-Setup-0.6.0.exe -Algorithm SHA256
```

The release also publishes a `.sha256` file in `HASH  filename` format.

Gmail works with an App Password and 2-Step Verification. Outlook / Microsoft 365 does not work
one-click: Microsoft 365 needs tenant admin consent, and personal Outlook.com accounts need a
verified publisher. macOS and Linux are out of scope for 0.6.0.

## Automatic updates

The installed app checks the public
[GitHub release feed](https://github.com/jparedesDS/cleanyourmail-app/releases/latest) at most once
every six hours, and the **Updates** button in the header checks on demand. The request identifies
the app version and your IP address to GitHub; it sends no account data, mailbox data or tokens.

When a newer version exists, a banner offers **Install update** and **Later**. **Install update**
asks for one confirmation. The app then downloads the exact `CleanYourMail-Setup-<version>.exe` asset
and its published `.sha256` file over HTTPS, verifies the SHA-256 before running anything, closes,
runs the installer silently for the current user and reopens the new version.

A failure leaves the app open and usable. A failed automatic check stays silent; press **Updates**
to try manually. A failed manual check shows a localized message with **Open GitHub**. If the
release lacks a valid installer or checksum, the banner offers **Open GitHub** instead of **Install
update**. A download, verification or hash failure shows a localized error with **Install update**
to retry and **Open GitHub** for the release page. If the update helper cannot start, the app stays
open and the banner offers **Open GitHub**. If the installer starts but fails, the helper reopens
the old app; there is no saved failure banner, so use **Updates** to retry or open the release page
manually.

The installer is unsigned in 0.6.0, so Windows SmartScreen may warn during an update just as it does
when you run the installer by hand: choose **More info**, then **Run anyway**. SHA-256 proves the
download is intact, not who published it; code signing is the next security step. If automatic
installation is unavailable (for example, when running from source), the same flow offers the
release page so you can install manually.

## Why this app

The CleanYourMail CLI is the engine and the source of truth. It already owns IMAP access,
classification, plans, reversible moves and the undo journal. What it does not offer is a short path
for someone who does not want to use a terminal or edit a TOML file.

This app adds that path without duplicating the engine:

- Pick a provider and connect without hand-writing a config.
- Choose categories and mode with checkboxes and radios.
- Scan, read the report and inspect the plan before anything changes.
- Apply only after an explicit review, then undo from the same window.
- Read every screen in English or Spanish.

The app never implements IMAP, planning, moves, undo or unsubscribe itself. It calls the frozen
CleanYourMail CLI sidecar and renders the result, so there is one safety model and one set of rules.

## Screenshots

<p align="center">
  <img src="docs/images/app-provider.png" alt="Choose a provider and enter the mailbox address" width="49%">
  <img src="docs/images/app-review.png" alt="Review the plan before applying it" width="49%">
</p>

<p align="center"><em>Synthetic demo data. Choose a provider, then review the plan before applying anything.</em></p>

## Requirements

- Windows 10/11 x64 for the installer.
- Python **3.12+** only to run from source.
- The CleanYourMail CLI `1.3.0` sidecar. The installer bundles it; for development, point `CYM_CLI`
  at a built `cym-cli.exe` with the same JSON contract. The app does not run `mail.py` directly.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` prints `CleanYourMail app 0.6.0`.

Run the tests:

```bash
python -m pytest -q
```

The suite uses fake CLI fixtures. It never needs a real mailbox, credentials or network access.

## What the app does

1. **Welcome / provider.** Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge
   or custom IMAP, plus the email address.
2. **Connect.** A guided App Password flow for Gmail, a device-code flow for Outlook, and
   provider-specific app-password help for the rest. The normal password is never requested.
3. **Preferences.** Categories to clean, folders or archive, protections, limits and language.
4. **Review and clean.** Scan, report, plan, review gate, apply with a limit, and the undo journal.
   The plan's unsubscribe column is informational only: this build never sends unsubscribe
   requests, and Apply always runs with `--action move`.

## Feedback

Feedback is **opt-in and manual**. Open it with the **Feedback** button in the app header or use the
[website form](https://cleanyourmail.org/#feedback). No feedback data is collected in the background,
and the form sends nothing until you press **Send** and accept the consent line. The only automatic
network request is the update check described above.

- The app pre-fills an **editable checklist** with the app and sidecar versions, the Windows
  version, the provider name, the folder/archive mode, the selected categories and the language.
- Edit or delete anything you do not want to share. Do **not** include passwords, tokens, email
  addresses, email subjects, message IDs or file paths in the message or the checklist.
- The optional contact field is the only place to leave a Discord handle, GitHub username or email
  address. It is never required.
- The request goes to a Cloudflare Worker (`cleanyourmail-feedback`), which validates it and
  forwards it to a private Discord channel. The Discord webhook is a Cloudflare secret and never
  ships in the app or the website.
- There is **no account, no telemetry, no analytics and no crash reporting**. The Worker stores no
  message body and applies a short, salted-IP rate limit.

<a id="provider-status"></a>

## Provider status

| Provider | App path | Status |
|---|---|---|
| Gmail | App Password + 2FA | pass, validated with CLI 1.3.0 |
| Outlook / Microsoft 365 | Device code | partial: Microsoft 365 needs tenant admin consent; Outlook.com personal needs a verified publisher |
| Yahoo, iCloud, Fastmail | App password | documented, not smoke-tested |
| Proton Bridge | Bridge password | documented, not smoke-tested |
| Custom IMAP | Host; fixed port 993 with TLS | documented, not smoke-tested |

The app reports these states honestly. It does not claim one-click Outlook support.

## Security model

- **Local by default, no account or telemetry.** The app's own requests are limited to the public
  GitHub release check (app version and IP only; at most every six hours or when you press
  **Updates**), the two public update assets downloaded only after you confirm **Install update**,
  and the feedback POST after you press Send and accept the consent line. Mailbox network access
  belongs to the sidecar and goes only to your mail provider.
- **Verified updates.** The installer is downloaded over HTTPS from the GitHub release, must match
  the published SHA-256, and runs only after one confirmation. The 0.6.0 installer is unsigned, so
  SmartScreen may warn; SHA-256 proves integrity, not the publisher.
- **CLI only.** The app cannot add capabilities the CLI does not have.
- **No secret in argv.** App passwords are written to the CLI `password_file`; the app never passes
  them as command-line arguments.
- **No secret at rest in app settings.** Secrets never enter QSettings, logs, error dialogs or test
  output.
- **Review first.** No write without a reviewed plan; undo stays one click away.
- **No permanent deletion.** Moves and archives are reversible.
- **No unsubscribe in 0.6.0.** The plan may show unsubscribe modes, but Apply only moves messages.
- **English and Spanish first-class.** Every string lives in `i18n/*.json`.

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Project layout

| Path | What it is |
|---|---|
| `src/cleanyourmail_app/` | Native app package. |
| `src/cleanyourmail_app/version.py` | Single source of the app version. |
| `src/cleanyourmail_app/__main__.py` | `python -m cleanyourmail_app` entry point. |
| `src/cleanyourmail_app/app.py` | Builds the local services and opens the wizard. |
| `src/cleanyourmail_app/ui/` | PySide6 window, pages, widgets, theme and resources. |
| `src/cleanyourmail_app/domain/` | Provider catalog, settings, preferences and plan models. |
| `src/cleanyourmail_app/services/` | Sidecar client (`cli.py`), config (`config.py`), secrets (`secrets.py`), OAuth (`oauth.py`), settings (`settings.py`), update check and download (`updates.py`) and the installer helper (`installer.py`). |
| `src/cleanyourmail_app/i18n/` | English and Spanish strings. |
| `scripts/` | Sidecar/app builds and the installer smoke test. |
| `packaging/` | Inno Setup script and icons. |
| `tests/` | pytest and pytest-qt suite with fake CLI fixtures. |
| `docs/superpowers/specs/` | Design docs (0.3.0 app, 0.4.0 feedback, 0.5.0 review wizard, 0.6.0 auto-update). |
| `docs/superpowers/plans/` | Task-by-task implementation plan. |

## Links

- App releases: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill and CLI: <https://github.com/jparedesDS/cleanyourmail>
- Website: <https://cleanyourmail.org/>
- Safety model: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## License

MIT. See [LICENSE](LICENSE).
