# Threat model

## Scope

This model covers the native CleanYourMail app 0.4.x: the PySide6 UI, the in-process services, the
frozen `cym-cli.exe` CleanYourMail 1.2.2 sidecar and the files the app touches on Windows 10/11 x64.
It also covers the opt-in feedback path: the app dialog and the website form, the Cloudflare Worker
and the private Discord channel. The CLI's own threat model is in
[`cleanyourmail/docs/SAFETY.md`](https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md).

The retired 0.2.x local-web UI is out of scope. The app has no embedded browser, HTTP server, cookie,
session, CSRF token or localhost listener in 0.4.x. The website is a static, no-cookie page.

## Assets

- Mailbox credentials: an app password (Gmail/Yahoo/iCloud/Fastmail/Proton Bridge/custom IMAP) or the
  sidecar-owned Microsoft OAuth refresh token.
- Message metadata: sender, subject, date, flags and unsubscribe headers.
- The CLI config (`cleanyourmail.toml`), which names `password_file` and `state_dir`.
- The plan (`plan.json`), the undo journal and the CLI cache.
- The user's mailbox state: folders, labels and messages.
- App settings: provider, email and cleaning preferences (never a secret).
- Optional feedback: the message, the editable checklist and an optional contact, only after the
  person presses Send and accepts the consent line.

## Trust boundaries

1. **UI ↔ sidecar.** The UI passes a fixed command, a config path and non-secret options. It reads
   one JSON object from stdout. The app never passes a password in argv or environment; the sidecar
   reads the private password file. The sidecar owns the OAuth token.
2. **Sidecar ↔ provider.** IMAP/SMTP over the network, outside this app; the CLI's safety model and
   TLS rules apply. Custom IMAP in this build is port 993 with TLS only.
3. **App ↔ local filesystem.** The app writes the config, the app-password file and its settings.
   It does not read the OAuth store, message bodies or the CLI cache.
4. **Build ↔ released installer.** The sidecar is built from the pinned tag and staged into the
   app; CI verifies its version and the installed app version.
5. **App/website ↔ feedback Worker.** One HTTPS POST, only after explicit Send and consent. The
   Worker validates size and shape, drops honeypot hits, applies a salted-IP rate limit and forwards
   to a private Discord webhook. The webhook and IP salt are Cloudflare secrets; the Worker keeps no
   message body. The app sends no `Origin`; CORS allows only the website origin.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| App password left in the widget or undo history | The field is cleared with `setText("")` on save, Back and account change; tests assert `undo()` cannot restore it. |
| App password in argv | The app never passes a secret as an argument. `save_app_password` writes the file; `CliClient` argv is asserted secret-free. |
| App password in QSettings, a label or a log | Settings hold only provider/email/preferences. Errors use localized generic copy, and 0.4.0 writes no local log. Tests scan rendered labels and settings. |
| App password written to the wrong account's file | An existing config for another email or IMAP host raises `ConfigMismatchError`; the person must confirm before `init --force`, and the app writes the `password_file` the config actually names. |
| OAuth token exposed to the UI | The app only calls the sidecar's device-code commands and renders URL/code. It never reads the OAuth store or a token field. |
| Command injection through a run id, plan path or host | Argument-list subprocesses with no shell; fixed command names; run ids match a strict pattern; plan path is one argv word; custom host rejects spaces and URL schemes. |
| Malicious or malformed sidecar JSON | Parsed as data, never evaluated; unknown shapes become a failed command, not a crash. Raw stdout/stderr are never rendered. |
| Plan tampering after review | The CLI re-checks UIDVALIDITY, flags, category and protected senders at apply time. The app requires a reviewed plan and allows one apply per plan. |
| Double apply | The gate closes as soon as an apply starts, including a timeout or partial result; only a fresh scan or plan reopens it. |
| Applying unsubscribe by accident | There is no unsubscribe action in 0.4.0. The plan column is informational; Apply is always `--action move`. |
| Accidental PII in feedback | The checklist is editable and limited to app/sidecar versions, Windows version, provider label, mode, categories and language. The dialog copy names passwords, tokens, addresses, subjects, message IDs and paths as things not to include. Tests use an email, a path and a token as sentinels and assert none reach the checklist, a label or a status line. |
| Automatic or background feedback | The app opens no network connection at startup, and the feedback client is constructed only after Send. A send requires the consent checkbox; tests assert nothing is sent without it. |
| Discord webhook leak | The webhook and IP salt live only as Cloudflare secrets and never appear in either repository, the installer, the website, logs or tests. The clients post to the Worker, not to Discord. |
| Feedback spam or abuse | The Worker caps the body at 16 KB and each field, drops filled honeypots, neutralises mentions and code fences, and rate-limits by a salted SHA-256 of the client IP for five minutes. |
| Feedback message retention | The Worker stores no message body and returns generic errors without logging it. Discord retention is outside this app's control and is documented. |
| Undo the wrong run | The full run id from the journal is passed back; the CLI verifies account and message identity. Undo requires confirmation. |
| Permanent deletion | The app has no delete action. The CLI is moves-only by default and refuses without UIDPLUS/MOVE. |
| Unexpected network exposure | The app opens no listening socket and no HTTP server. The only request it makes itself is the opt-in feedback POST after explicit Send; all mail-network access belongs to the sidecar. |
| SmartScreen / unsigned installer | The release documents the unsigned warning and publishes a SHA-256; code signing is deferred. |
| Supply-chain compromise | Dependencies use declared version ranges in `pyproject.toml` and are installed from PyPI at build time; the sidecar is built from an exact tag with a clean-worktree check; CI runs the contract tests and the installer smoke. |
| Malicious website reaching the app | There is no localhost listener, no session cookie and no browser surface to reach. |
| Browser profile or extension compromise | The app does not use a browser. The only browser interaction is the person opening Microsoft's device-login page, which the OS handles. |

## Non-goals

- A hostile local administrator or malware running as the same Windows user.
- A compromised operating system, screen recorder or clipboard manager.
- Physical access to an unlocked machine.
- Protecting a mailbox from the mail provider itself.
- A multi-user or hosted deployment.
- Guaranteeing that a sender honours an unsubscribe request (and 0.4.0 does not send one).
- Preventing a person from typing sensitive data into the editable feedback message or checklist.
- Confidentiality or retention guarantees after Discord receives a feedback message.
- Full custom-IMAP support for ports other than 993 or STARTTLS; that needs a later sidecar.

## Residual risks

- The person can share a screenshot that contains sender or subject data.
- The person can configure a broad app password; the app cannot narrow provider scopes.
- The person can ignore the plan review; the app enforces a checkbox and a confirmation, not
  attention.
- The password file is protected best-effort by a user ACL on Windows; a same-user process can read
  it, as it can read the CLI's own files.
- The sidecar process has the same user privileges as the app.
- Without a local log, diagnosing a failed sidecar call relies on the localized copy and the user's
  own reproduction; this is a deliberate security trade-off.
- Feedback is free text. The checklist excludes sensitive fields by construction, but a person can
  still type an address or a secret into the message or edit it into the checklist.
- Discord and Cloudflare are third parties outside the app's threat model; a message is retained
  according to their policies and the private channel's settings.

## Verification

The suite covers secret-free argv, widget/undo clearing, settings and label scanning, config
mismatch and replace, the actual `password_file` path, version mismatch, HTTPS-only link opening,
Outlook cancellation and late-result suppression, review/apply gating, double apply, journal/undo
run-id handling, and no unsubscribe call. Feedback tests cover the narrow checklist, sentinel
exclusion, consent, no send before Send, localized failures and the Worker payload shape without any
real network request. Packaging tests pin the per-user installer, the uninstaller bounds and the
bundled sidecar; CI launches the frozen GUI and runs the installer smoke with metadata-only
sentinels. Tests use fake CLI processes and never a real mailbox or credential.
