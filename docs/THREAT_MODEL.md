# Threat model

## Scope

This model covers the local CleanYourMail app: the browser UI, the local HTTP server, the CLI
subprocess boundary and the files the app touches. The CLI's own threat model is in
[`cleanyourmail/docs/SAFETY.md`](https://github.com/jparedesDS/cleanyourmail/blob/master/docs/SAFETY.md).

## Assets

- Mailbox credentials: app password or OAuth2 access token.
- Message metadata: sender, subject, date, flags and unsubscribe headers.
- The plan (`plan.json`), the undo journal and the CLI cache.
- The user's mailbox state: folders, labels and messages.
- The local config file and the app's path settings.

## Trust boundaries

1. **Browser ↔ local server.** The browser is the renderer; the server is the authority. The boundary
   is HTTP on `127.0.0.1`.
2. **Server ↔ CLI.** The server passes only a command, a config path and an optional secret in the
   environment. It parses JSON output.
3. **CLI ↔ mail provider.** IMAP/SMTP, outside this app; the CLI's safety model applies.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Another local user opens the app | Random port, one-time URL token, session cookie, `SameSite=Strict`; the app is meant for a single-user machine. |
| Malicious website sends requests to localhost | `Origin` allowlist, CSRF header, `SameSite=Strict` cookie, JSON-only POSTs. |
| DNS rebinding | Server binds `127.0.0.1`; `Host` and `Origin` must be localhost with the actual port. |
| Session theft through XSS | Strict CSP, no inline scripts, no external assets, all email data rendered with `textContent`. |
| Secret in logs | The server does not log request bodies, query strings or cookies. The password is never written to disk. |
| Secret in the repo | The app stores only paths; the password is a page-memory value or `CYM_PASSWORD` in the server environment. |
| Command injection | `subprocess.run` with an argument list and no shell; fixed command names; run ids validated with `[A-Za-z0-9_-]{1,64}`. |
| Path traversal in static files | `resolve()` + `relative_to(static_dir)` + reject `..`; only files under `static/` are served. |
| Malicious CLI output | Parsed as JSON and rendered as text; never evaluated as code or HTML. |
| Plan tampering | The CLI re-checks UIDVALIDITY, flags, category and protected senders at apply time. The app requires a reviewed plan, explicit `APPLY` and allows one apply per plan. |
| Applying unsubscribe by accident | Separate endpoint, separate checkbox, `UNSUBSCRIBE` confirmation, 1–50 cap, never mixed with moves. |
| Permanent deletion | The app has no delete endpoint. The CLI is moves-only by default and refuses without UIDPLUS/MOVE. |
| Undo the wrong run | Run id validation, CLI account check, Message-ID/`X-GM-MSGID` verification. |
| Network exposure | No `--host` option; only `127.0.0.1`. No reverse proxy instructions. |
| Supply-chain compromise | Standard library only; no runtime dependencies; CI runs the same tests on Windows, macOS and Linux. |

## Non-goals

- A hostile local administrator or malware running as the same user.
- A compromised operating system, browser extension or screen recorder.
- Physical access to an unlocked machine.
- Protecting a mailbox from the mail provider itself.
- A multi-user or hosted deployment.
- Guaranteeing that unsubscribe stops a sender.

## Residual risks

- A user can still share a screenshot that contains sender or subject data.
- A user can configure a broad app password; the app cannot narrow provider scopes.
- A user can ignore the plan review; the app enforces a checkbox, not attention.
- The password is visible to the user's browser process while the page is open.
- Local malware with the same user privileges can read the CLI config or the state directory.

## Verification

The test suite covers the session store, the one-time token, CSRF and Origin checks, security headers,
static path traversal, session lock and the CLI wrapper. The app intentionally uses a fake CLI in
tests, not a mailbox.
