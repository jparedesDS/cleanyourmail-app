# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | Yes |

0.2.x and 0.1.x were the retired local-web UI and are no longer supported. This policy covers the
native CleanYourMail app 0.3.x for Windows 10/11 x64.

## Reporting a vulnerability

Do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting:

<https://github.com/jparedesDS/cleanyourmail-app/security/advisories/new>

Include:

- what you were doing and what happened;
- the app version (`python -m cleanyourmail_app --version` or the release tag);
- the Windows version and whether the app came from the installer or source;
- reproduction steps;
- whether a mailbox, credential, plan, journal or local file was exposed.

Do not include real passwords, OAuth tokens, message bodies, real email addresses or screenshots of
a real inbox. Redact them.

## Security model in one page

CleanYourMail app is a **native PySide6 front end** for the frozen CleanYourMail CLI 1.2.2 sidecar.
The app does not replace the CLI's safety rules and does not add capabilities the CLI does not have.

- **No local HTTP server, browser, cookies or CSRF surface.** The UI is a native window. The app
  never opens a web server, never accepts inbound connections and has no web view.
- **No account, cloud or telemetry.** The app makes no network request of its own; network access
  belongs to the sidecar and goes only to the mail provider.
- **App password stays out of argv and settings.** The app writes the app password to the private
  `password_file` named by the CLI config (by default `%USERPROFILE%\.secrets\cleanyourmail.txt`,
  owner-only ACL best-effort). It is never passed as a command-line argument, stored in QSettings,
  logged or rendered again. The password field is cleared with its undo history when the person
  leaves the page.
- **OAuth token is owned by the sidecar.** For Outlook, the app shows Microsoft's device URL and
  code. The sidecar performs the token exchange and stores its refresh token; the app never reads
  or renders it.
- **No body or attachment access.** The CLI scans headers only, and the app only renders the CLI's
  JSON summaries. The app has no IMAP code and no attachment viewer.
- **No permanent deletion.** The app exposes moves and archives only. It has no delete action and
  no server-side filter upload.
- **No unsubscribe in 0.3.0.** The plan may display unsubscribe modes for context, but Apply is
  always `--action move`; the app never sends an unsubscribe request.
- **Review first.** No mailbox change happens without a scanned plan, an explicit review checkbox
  and a confirmation dialog. Apply is limited by policy and by the plan's own move count.
- **Undo belongs to the CLI.** The journal is the CLI's; the app passes the full run id back and
  never guesses. The sidecar re-checks message identity before restoring.
- **Fail closed on drift.** Before creating a config, the app verifies that the sidecar is
  `CleanYourMail 1.2.2`. A different build is refused rather than guessed at.
- **Fail closed on the wrong account.** An existing config for another email or IMAP host is not
  reused; the person must explicitly confirm replacing it, and only then does the app run
  `init --force`.
- **English and Spanish first-class.** Every visible string lives in `i18n/*.json`.

There is deliberately no local log file in 0.3.0. Errors use localized generic copy so a server
message or path cannot leak a secret into a log. The trade-off is reduced diagnostics; a redacted
diagnostics channel is future work.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the full analysis.

## If you think your mailbox was affected

1. Close the app.
2. Revoke the app password or OAuth grant with your mail provider.
3. Check the CleanYourMail journal with the bundled sidecar:
   `cym-cli.exe journal --config <config>` (or the CLI's documented equivalent).
4. Restore any unwanted move with `cym-cli.exe undo --run <run> --yes --config <config>`.
5. Report the issue privately with the details above.

## Safe operation

- Run the app as your normal user, not as administrator.
- Use a dedicated app password with the narrowest scope the provider allows.
- Keep Windows and the app updated.
- Download the installer only from the official release page and verify its published SHA-256.
- Do not paste real credentials into issues, screenshots or chat.
- Remember that unsubscribe is not available in this build; it cannot be triggered accidentally.
