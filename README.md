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

# CleanYourMail app

**Your inbox, minus the noise — as a native Windows app.** CleanYourMail app is a PySide6 front end
for the [CleanYourMail](https://github.com/jparedesDS/cleanyourmail) CLI. It guides you through
connecting a mailbox, choosing what to clean, reviewing a reversible plan and undoing it.

No browser, no local server, no account, no telemetry, no bodies, no permanent deletion. The only
network request the app makes itself is the feedback POST you explicitly send.

> **Status:** `0.4.0` is the current Windows early-MVP release. It adds opt-in feedback from the
> app header and the website. The installer bundles the frozen CleanYourMail CLI `1.2.2` sidecar.
> Gmail is validated; Outlook depends on Microsoft's consent model. See
> [Provider status](#provider-status).

## Download

[CleanYourMail app 0.4.0 for Windows 10/11 x64](https://github.com/jparedesDS/cleanyourmail-app/releases/latest)
is a per-user installer that bundles the pinned CleanYourMail CLI `1.2.2` sidecar and needs no
administrator rights.

The 0.4.0 installer is not code-signed. Windows SmartScreen may show an "Unknown publisher"
warning on first launch: choose **More info**, then **Run anyway**, and compare the SHA-256
published with the release against `CleanYourMail-Setup-0.4.0.exe`:

```powershell
Get-FileHash .\CleanYourMail-Setup-0.4.0.exe -Algorithm SHA256
```

The release also publishes a `.sha256` file in `HASH  filename` format.

Gmail works with an App Password and 2-Step Verification. Outlook / Microsoft 365 does not work
one-click: Microsoft 365 needs tenant admin consent, and personal Outlook.com accounts need a
verified publisher. macOS and Linux are out of scope for 0.4.0.

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

## Requirements

- Windows 10/11 x64 for the installer.
- Python **3.12+** only to run from source.
- The CleanYourMail CLI `1.2.2` sidecar. The installer bundles it; for development, point `CYM_CLI`
  at a built `cym-cli.exe` with the same JSON contract. The app does not run `mail.py` directly.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m cleanyourmail_app --version
```

`python -m cleanyourmail_app --version` prints `CleanYourMail app 0.4.0`.

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
[website form](https://jparedesds.github.io/cleanyourmail-web/#feedback). Nothing is collected in
the background, and the app sends nothing until you press **Send** and accept the consent line.

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

## Provider status

| Provider | App path | Status |
|---|---|---|
| Gmail | App Password + 2FA | pass, validated with CLI 1.2.2 |
| Outlook / Microsoft 365 | Device code | partial: Microsoft 365 needs tenant admin consent; Outlook.com personal needs a verified publisher |
| Yahoo, iCloud, Fastmail | App password | documented, not smoke-tested |
| Proton Bridge | Bridge password | documented, not smoke-tested |
| Custom IMAP | Host; fixed port 993 with TLS | documented, not smoke-tested |

The app reports these states honestly. It does not claim one-click Outlook support.

## Security model

- **Local only, except opt-in feedback.** No account, cloud, telemetry or body access. The app
  makes no background network request; the only request it makes itself is the feedback POST after
  you press Send and accept the consent line.
- **CLI only.** The app cannot add capabilities the CLI does not have.
- **No secret in argv.** App passwords are written to the CLI `password_file`; the app never passes
  them as command-line arguments.
- **No secret at rest in app settings.** Secrets never enter QSettings, logs, error dialogs or test
  output.
- **Review first.** No write without a reviewed plan; undo stays one click away.
- **No permanent deletion.** Moves and archives are reversible.
- **No unsubscribe in 0.4.0.** The plan may show unsubscribe modes, but Apply only moves messages.
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
| `src/cleanyourmail_app/services/` | Sidecar client (`cli.py`), config (`config.py`), secrets (`secrets.py`), OAuth (`oauth.py`) and settings (`settings.py`). |
| `src/cleanyourmail_app/i18n/` | English and Spanish strings. |
| `scripts/` | Sidecar/app builds and the installer smoke test. |
| `packaging/` | Inno Setup script and icons. |
| `tests/` | pytest and pytest-qt suite with fake CLI fixtures. |
| `docs/superpowers/specs/` | Design docs (0.3.0 app, 0.4.0 feedback). |
| `docs/superpowers/plans/` | Task-by-task implementation plan. |

## Links

- App releases: <https://github.com/jparedesDS/cleanyourmail-app/releases/latest>
- Skill and CLI: <https://github.com/jparedesDS/cleanyourmail>
- Website: <https://jparedesds.github.io/cleanyourmail-web/>
- Safety model: <https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md>

## License

MIT. See [LICENSE](LICENSE).
