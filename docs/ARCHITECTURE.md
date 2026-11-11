# Architecture

## The short version

```text
┌──────────────────────────────┐
│ PySide6 wizard               │
│ ui/main_window.py            │
│ ui/pages/{provider,connect,  │
│   preferences,review}.py     │
└──────────────┬───────────────┘
               │ in-process calls
               v
┌──────────────────────────────┐
│ AppServices                  │
│ services/{config,secrets,    │
│   oauth,settings}.py         │
└──────────────┬───────────────┘
               │ argv + JSON, no secret in argv
               v
┌──────────────────────────────┐
│ frozen cym-cli.exe           │
│ CleanYourMail 1.3.0 sidecar  │
└──────────────┬───────────────┘
               │ IMAP / SMTP
               v
┌──────────────────────────────┐
│ Mail provider                │
└──────────────────────────────┘
```

The app does not speak IMAP, plan moves, write the journal or unsubscribe. The CLI does. The app is
a native view and a process wrapper around the frozen sidecar.

## Components

| Component | Responsibility |
|---|---|
| `src/cleanyourmail_app/__main__.py` | `python -m cleanyourmail_app`; prints `--version` before importing Qt. |
| `src/cleanyourmail_app/app.py` | Builds `QApplication`, the translator, `SettingsStore`, `AppServices` and `MainWindow`. |
| `src/cleanyourmail_app/version.py` | Single source of the app version (`0.6.0`). |
| `src/cleanyourmail_app/ui/main_window.py` | Window chrome, progress rail, page stack, navigation, header language switch, the Feedback button and the Updates button/banner. |
| `src/cleanyourmail_app/ui/pages/provider.py` | Seven provider cards, email validation, account handoff. |
| `src/cleanyourmail_app/ui/pages/connect.py` | App-password save, doctor, custom host, Outlook device-code UI, Cancel and sensitive-state clearing. |
| `src/cleanyourmail_app/ui/pages/preferences.py` | Categories, mode, protections, limits, Advanced paths and language; writes the policy through `ConfigService`. |
| `src/cleanyourmail_app/ui/pages/review.py` | Scan/report/plan rendering, review gate, apply, journal and undo. |
| `src/cleanyourmail_app/ui/widgets/` | Provider card widget. |
| `src/cleanyourmail_app/ui/dialogs/feedback.py` | Opt-in feedback dialog: type, message, editable checklist, optional contact, consent and localized status. |
| `src/cleanyourmail_app/domain/` | Provider catalog, settings/preferences models, plan constants and the feedback checklist/payload rules. |
| `src/cleanyourmail_app/services/cli.py` | Locates and runs the sidecar, appends `--json`, parses JSON, verifies the pinned version, supports cancellation. |
| `src/cleanyourmail_app/services/config.py` | Creates the TOML through `init`, refuses a different account/host, maps `--force`, reads `password_file` and `state_dir`, edits only known policy keys. |
| `src/cleanyourmail_app/services/secrets.py` | Writes the app password to the private password file with owner-only permissions. |
| `src/cleanyourmail_app/services/oauth.py` | Runs `connect outlook --no-wait/--wait` and maps known failures; the app never handles a token. |
| `src/cleanyourmail_app/services/settings.py` | Stores provider, email, app preferences and the last automatic update check (`last_update_check`) in `%APPDATA%\cleanyourmail-app\settings.json`; no secrets. |
| `src/cleanyourmail_app/services/feedback.py` | One HTTPS POST to the feedback Worker, only after Send; maps 429/503/network failures to localized keys and never logs the payload. |
| `src/cleanyourmail_app/services/updates.py` | Reads the public GitHub release, compares versions, and downloads the installer plus its `.sha256`; verifies the hash and never executes anything. |
| `src/cleanyourmail_app/services/installer.py` | Writes and starts the temporary silent per-user installer helper; it never downloads or installs without the window's confirmation. |
| `src/cleanyourmail_app/i18n/` | English and Spanish catalogs and the `Translator`. |
| `resources/cli/` (build output) | Staged `cym-cli.exe`, bundled into `dist\CleanYourMail\resources\cli`. |
| `packaging/` | Inno Setup 6 per-user installer and icon. |
| `scripts/` | Sidecar build, app/installer build, installer smoke. |

## Data paths

| Data | Path | Owner |
|---|---|---|
| App settings | `%APPDATA%\cleanyourmail-app\settings.json` | App |
| CLI config | `%APPDATA%\cleanyourmail-app\cleanyourmail.toml` | App creates through `init`; CLI reads |
| App password | `[account] password_file` (default `%USERPROFILE%\.secrets\cleanyourmail.txt`) | App writes; CLI reads |
| Outlook OAuth store | `%USERPROFILE%\.secrets\cleanyourmail-oauth.json` | Sidecar only |
| CLI state/cache/journal | top-level `state_dir`, `CYM_STATE_DIR`, or `%LOCALAPPDATA%\CleanYourMail` | CLI only |

The app never stores a secret in its own settings. The password file is the only credential the app
writes, and it does so after verifying which config will read it.

## Why the CLI stays a subprocess

The CLI is the contract. The app calls:

```text
cym-cli.exe <command> [options] --json [--config <path>]
```

and reads one JSON object from stdout. This keeps:

- one implementation of classification, planning, journaling and safety rules;
- process isolation between the UI and the mailbox code;
- a clear boundary for the OAuth token;
- a small app codebase with no IMAP or OAuth logic.

The trade-off is that fine-grained progress is not streamed yet. A future sidecar can add a
`--progress` JSON-lines mode without changing the safety model.

## Request flow

1. The provider page saves the account in `SettingsStore` and hands provider/email to Connect.
2. Connect calls `CliClient.verify_version()`; a build other than `CleanYourMail 1.3.0` is refused.
3. Connect calls `ConfigService.ensure()`. An existing config for another email or IMAP host raises
   `ConfigMismatchError`; the app asks before running `init --force`.
4. The app writes the app password to `ConfigService.password_file()` — the path the CLI config
   names, not a guessed default — then clears the widget and its undo history.
5. `doctor` runs in a worker thread; a success advances to Preferences.
6. Preferences writes `[scan]`/`[policy]` values line by line, preserving comments and every other
   section, then advances to Review.
7. Review runs `scan`, `report` and `plan` in workers. Apply stays disabled until a plan has at
   least one move and the review checkbox is checked.
8. Apply runs `apply <plan> --yes --action move --limit <n>`; a new apply is refused for the same
   plan. The journal dialog lists runs and undo passes the full run id after confirmation.
9. Outlook uses the sidecar's device flow. Cancel terminates a running `--wait` child; a late result
   is ignored by the page's epoch guard.

## Feedback flow

Feedback is the only network request that carries anything the person writes. The only other
requests the app makes itself are the public GitHub release check and, after a confirmed update,
the two public release assets; none carries account data.

```text
Header Feedback button
        │ click
        v
FeedbackDialog (local form, editable checklist, consent)
        │ Send + consent
        v
services/feedback.py ── HTTPS POST ──→ Cloudflare Worker
                                          │ validate, honeypot, rate limit
                                          v
                                   private Discord webhook
```

- Clicking the button only reads local settings and asks the sidecar for its local version. The
  feedback client is constructed inside Send, after validation and consent.
- The pre-filled checklist is limited to the app version, sidecar version, Windows version, provider
  display name, folder/archive mode, selected category names and language. It never contains the
  account address, config or state paths, senders, subjects, message IDs, passwords, tokens or logs.
- The checklist and message are editable; the optional contact field is the only place for a
  Discord handle, GitHub username or email address.
- The Worker holds the Discord webhook and IP salt as secrets, caps the body and fields, rejects a
  filled honeypot and rate-limits a salted hash of the client IP. It stores no message body.
- No telemetry, analytics, crash reporting, attachments or background upload exists. Failures show
  localized copy; the payload and response body are never logged.
- English and Spanish copy lives in `i18n/*.json`, like the rest of the app.

## Update flow

The installed app checks the public GitHub release feed at most once every six hours, and whenever
the person presses **Updates** in the header. The check sends the app version in its `User-Agent` and
nothing else.

```text
Startup timer / Updates button
  → GitHub Releases API (latest)
  → UpdateInfo(version, installer_url, checksum_url, notes)
  → banner: Install update / Later
  → one confirmation
  → download installer + .sha256 over HTTPS
  → SHA-256 verification
  → temporary .cmd helper waits for the app PID
  → silent per-user installer (/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER)
  → relaunch the installed app
```

- `services/updates.py` is network-only. It accepts HTTPS assets only from `github.com` and GitHub's
  release CDN, requires the `CleanYourMail-Setup-<version>.exe` name, caps the download at 200 MB and
  checks the installer against the downloaded `.sha256` before anything runs. It never executes an
  installer.
- Failure handling follows the UI state: a failed automatic check stays silent and leaves **Updates**
  available; a failed manual check shows a localized message with **Open GitHub**. A release without
  a valid named installer and `.sha256` shows **Open GitHub** instead of **Install update**. A
  download, verification, hash mismatch or redirect failure shows a localized error with **Install
  update** to retry and a secondary **Open GitHub** for the release page. If the helper cannot
  start, the app stays open and the banner offers **Open GitHub**. If the installer starts but
  fails, the helper reopens the old app; no failure banner is persisted, so the person can retry
  from **Updates** or open the release page manually.
- `services/installer.py` builds the helper command. The helper waits for the app PID, quotes every
  path, deletes the installer only after a successful install and reopens the app. It uses
  `%SystemRoot%\System32` tools, fails closed when `tasklist`/`find` cannot report, and writes a
  start marker so the app only quits after the helper is known to be running. It leaves the
  installer for diagnosis if the install fails.
- The installer is unsigned in 0.6.0. SHA-256 is integrity, not publisher authentication; code
  signing is the next security step, and Windows SmartScreen may warn.
- The automatic check never installs anything. Only **Install update** plus the confirmation starts
  the download and verification; the helper runs only after both succeed. A failed check is silent
  on the automatic path and visible on the manual path.

## Failure handling

- Sidecar exit 0 + JSON: rendered normally.
- Sidecar non-zero + JSON: a result with `ok=False`; the page shows localized copy, never raw output.
- Sidecar timeout: `CliError`; the page stays usable. Apply timeouts close the plan gate because the
  outcome is unknown.
- Missing or mismatched sidecar: `errors.cli_failed` / `errors.cli_version`; no config is written.
- Malformed JSON or payload: treated as a failed command; the page does not crash.
- Cancelled Outlook wait: `{ok: False, cancelled: True}`; no token is used.

## Testing and packaging

- `pytest` and `pytest-qt` run headless against fake CLI fixtures; no mailbox or network.
- Feedback tests use a fake `send_feedback`; no test performs an HTTP request.
- Update tests inject a fake opener and a fake launcher; no test downloads or executes a real
  installer.
- `tests/test_cli_contract.py` pins the frozen sidecar when `CYM_CLI` is set.
- PyInstaller builds a windowed `--onedir` app and bundles the sidecar.
- Inno Setup builds a per-user installer; the uninstaller removes app files only.
- CI runs tests on Python 3.12/3.13, builds the sidecar and app, launches the frozen GUI offscreen,
  builds the installer, and runs the silent install/uninstall smoke with sentinel user data.

## Future work

- A sidecar release with configurable IMAP port/TLS and a progress stream.
- A redacted local diagnostics channel that cannot capture secrets.
- Cloudflare Turnstile for feedback if the honeypot and rate limit stop being enough.
- Installer code signing.
- macOS/Linux packaging, if the product needs it.
