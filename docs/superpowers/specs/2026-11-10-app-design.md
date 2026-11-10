# CleanYourMail App 0.3.0: design

Date: 2026-11-10
Status: draft for review
Owner: jparedesDS

## Intent

Give Windows users a short, guided path through the existing CleanYourMail safety rules. The app is
not a second cleaning engine: it is a native front end for the frozen CleanYourMail CLI 1.2.2 sidecar.
The skill remains the primary product.

The app opens, asks which provider to connect, guides the connection without a terminal or a TOML
file, lets the person choose what to clean with checkboxes, shows a reversible plan, applies it only
after review, and keeps undo one click away.

## Why now

The current 0.2.0 app is a local web UI that asks for the CLI path, the config path and an OAuth
token. That is not the simple flow the skill promises. CleanYourPhone app 0.1.0 already proved the
pattern: PySide6 wizard, frozen CLI sidecar, per-user Inno Setup installer, pytest-qt and Windows CI.
CleanYourMail app 0.3.0 follows the same pattern.

## Users

- Windows 10/11 x64, Gmail, Outlook/Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge or custom
  IMAP.
- Spanish or English.
- They may not know what IMAP, TOML, an App Password or a device code is.
- They want to see what will change before it changes.

## Goals

1. Install with a double click. No Python, no terminal, no paths.
2. Connect Gmail with a guided 2FA + App Password flow, Outlook with device code, and the other
   providers with app passwords.
3. Never ask for the normal password; never print or log a secret.
4. Choose categories and mode with checkboxes and radios.
5. Always scan, report and plan before applying; require an explicit review.
6. Keep undo one click away and explain what it restores.
7. Explain the Outlook limitation before the person tries: Microsoft 365 needs tenant admin consent;
   Outlook.com personal needs a verified publisher.
8. Local only: no account, cloud, telemetry or body access.

## Non-goals

- macOS or Linux builds. Windows 10/11 x64 first; other systems later.
- Gmail OAuth. Gmail uses an App Password.
- Solving Microsoft's verified-publisher requirement. It is a project-level blocker tracked in #16.
- Installer code signing in 0.3.0.
- Auto-update, an app store or an account system.
- Body or attachment access, permanent deletion, or server-side filter upload.
- A generic "clean everything" button.
- Editing the TOML by hand.

## Approaches considered

**A. Keep the 0.2.0 web UI and add a setup page.** Rejected: still a local server, still manual paths,
and not the CleanYourPhone pattern.

**B. Do the work in-process by importing the CLI modules.** Rejected: duplicates the safety rules,
config handling and plan validation. The CLI must stay the single source of truth.

**C. PySide6 native app + frozen CLI sidecar + Inno Setup.** Chosen. It matches CleanYourPhone 0.1.0,
keeps the CLI as the engine, and gives a real Windows installer.

**D. Electron or Tauri.** Rejected: a second runtime, a web view and a different security surface.

## UX flow

A left-to-right wizard with four pages and a persistent progress rail.

### 1. Welcome / provider

Large choice cards: Gmail, Outlook / Microsoft 365, Yahoo, iCloud, Fastmail, Proton Bridge, Custom
IMAP. Email field. A short note per provider:

- Gmail: 2-Step Verification + App Password.
- Outlook: Microsoft 365 admin consent; Outlook.com personal verified publisher.
- Yahoo/iCloud/Fastmail: app password.
- Proton: Bridge must be running.
- Custom: host and port in Advanced.

### 2. Connect

- **Gmail:** "Open Google security" and "Open App Passwords" buttons; a short 2FA checklist; the
  16-character App Password; Save; `doctor`. The field is cleared after save.
- **Outlook:** "Connect Microsoft" calls the sidecar `connect outlook --no-wait --json`, shows the URL
  and code with a Copy button, waits for "I approved", then calls `connect outlook --wait --json` and
  `doctor`. If Microsoft blocks consent, show the admin-consent / verified-publisher explanation.
- **Others:** provider-specific app password instructions, secret field, Save, `doctor`.
- **Custom:** host, port, TLS and auth under an "Advanced" disclosure.

### 3. Preferences

Checkboxes, all visible:

- Clean: Newsletters, Promotions, Social, Notifications, Cold outreach, Spam.
- Mode: Folders or Archive (radio).
- Protect: Starred, Answered; minimum age in days.
- Limits: max moves per run; max messages per sender group.
- Advanced (collapsed): config path, state path, language.

The app writes these choices into the `[scan]` and `[policy]` sections of the config it created. The
person never edits the TOML.

### 4. Review and clean

- Scan → report summary → plan.
- Plan table: category, destination, messages, unsubscribe mode.
- "I reviewed this plan" checkbox; Apply with a limit; Undo journal.
- Unsubscribe in a separate collapsed section, default off, with the irreversible warning. Spam is
  never selected.

## Provider status

| Provider | App path | Status |
|---|---|---|
| Gmail | App Password + 2FA | pass, validated 1.2.2 |
| Outlook / Microsoft 365 | Device code | partial; M365 admin consent, Outlook.com verified publisher |
| Yahoo, iCloud, Fastmail | App password | documented, not smoke-tested |
| Proton Bridge | Bridge password | documented, not smoke-tested |
| Custom IMAP | Host/port/TLS | documented, not smoke-tested |

The app must show `partial` / `documented` honestly; it must not claim Outlook one-click works.

## Architecture

- Python 3.12, PySide6 6.8+, Windows 10/11 x64.
- `src/cleanyourmail_app/`:
  - `version.py`, `__main__.py`, `app.py`.
  - `ui/main_window.py`, `ui/pages/{provider,connect,preferences,review}.py`, `ui/widgets/`,
    `ui/theme.qss`, `ui/resources/`.
  - `domain/models.py`: Provider, ConnectionState, Preferences, PlanSummary.
  - `services/cli.py`: locate and run the frozen sidecar; JSON contract; timeouts; env; never pass a
    secret in argv or log it.
  - `services/config.py`: create/read the TOML through the sidecar `init`; write the `[scan]` and
    `[policy]` values from the Preferences page; no secrets.
  - `services/secrets.py`: write `password_file` with owner-only permissions; clear memory; no logs.
  - `services/oauth.py`: device-code flow through the sidecar `connect` JSON; the app never handles
    the refresh token.
  - `services/settings.py`: app preferences only, in `%APPDATA%\cleanyourmail-app`.
  - `services/logging.py`: redacted local log.
  - `i18n/en.json`, `i18n/es.json`; English and Spanish first-class.
- CLI sidecar: frozen `CleanYourMail 1.2.2`, `cym-cli.exe`, built from the main repository tag.
- Paths:
  - Config: `%APPDATA%\cleanyourmail-app\cleanyourmail.toml`.
  - Secret: `%USERPROFILE%\.secrets\cleanyourmail.txt` (`password_file`, 0600 on POSIX; user ACL on
    Windows).
  - OAuth store: `%USERPROFILE%\.secrets\cleanyourmail-oauth.json` (sidecar-owned).
  - State: the CLI's default per-user state, or `%LOCALAPPDATA%\cleanyourmail-app\state`.

## Secret handling

- App passwords are written directly to `password_file` with `os.open(..., O_CREAT|O_EXCL, 0o600)`.
  The app never passes the secret in argv, logs it, puts it in QSettings, or shows it again.
- Outlook: the sidecar owns the device-code flow and refresh token. The app only displays the URL and
  code and calls `--wait`.
- The app clears password fields on page change and on lock. The lock action drops the session and
  closes the window.

## Installer

- PyInstaller `--onedir` app plus a frozen `cym-cli.exe` sidecar.
- Inno Setup 6, per-user install to `{localappdata}\Programs\CleanYourMail`, Start Menu shortcut, no
  admin.
- The uninstaller removes app files only; it leaves `%APPDATA%\cleanyourmail-app`,
  `%USERPROFILE%\.secrets` and the CLI state.
- Include the MIT license and PySide6/Qt notices.
- Windows 10/11 x64 only. No signing in 0.3.0; document the SmartScreen warning.
- Build on `windows-latest`, upload the installer and its SHA-256.

## Testing

- pytest and pytest-qt; no real mailbox or network.
- A fake CLI executable with JSON fixtures for every page and error.
- A contract test against the frozen sidecar: `--version` prints `CleanYourMail 1.2.2`, `validate`
  works and `doctor` fails cleanly without a config.
- UI tests: provider selection, checkbox persistence, secret never rendered, Outlook URL/code display,
  plan review gate, apply/undo, error copy.
- Installer smoke: build, silent per-user install, run `--version`, uninstall, assert user data
  survives.
- CI Windows only; Python 3.12 and 3.13.

## Risks

- PySide6 installer size (~100 MB). Acceptable for a Windows app.
- Sidecar drift. Pin 1.2.2 and run the contract test in CI.
- Outlook consumer block. The app explains it and never promises a pass.
- SmartScreen without signing. Document the warning; signing is a later task.
- Users without 2FA/App Password. The wizard guides them; it does not bypass Google.

## Open questions

- App version: `0.3.0` (continue from 0.2.0) or `0.1.0` (new native line)? Proposal: `0.3.0`.
- Delete the old web UI or keep it under `legacy/`? Proposal: delete; git history keeps it.
- Installer signing: defer to a later release.
- App icon: use `brand/final-spectrum/app-icon.svg` from the main repo, converted to `.ico`; default
  Inno icon only if the conversion fails.

## What is left to the builder

The exact widgets, signals, test names and task order belong in the implementation plan. The design
fixes the four-page flow, the sidecar boundary, the secret contract, the provider copy and the
installer shape.
