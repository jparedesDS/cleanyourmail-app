# Architecture

## The short version

```text
┌──────────────────────┐        HTTP on 127.0.0.1        ┌──────────────────────┐
│ Browser / local UI   │ ──────────────────────────────> │ app.py HTTP server   │
│ static/index.html    │ <────────────────────────────── │ sessions, CSRF, API  │
└──────────────────────┘                                 └──────────┬───────────┘
                                                                  │ subprocess
                                                                  v
                                                       ┌──────────────────────┐
                                                       │ cleanyourmail CLI    │
                                                       │ tools/mail.py        │
                                                       └──────────┬───────────┘
                                                                  │ IMAP / SMTP
                                                                  v
                                                       ┌──────────────────────┐
                                                       │ Mail provider        │
                                                       └──────────────────────┘
```

The app does not speak IMAP. The CLI does. The app is a local UI and a process wrapper.

## Components

| Component | Responsibility |
|---|---|
| `app.py` | Entry point; delegates to `server.main`. |
| `cleanyourmail_app/server.py` | Binds `127.0.0.1`, validates the one-time token, manages sessions, serves static files and exposes the JSON API. |
| `cleanyourmail_app/cli.py` | Finds `tools/mail.py`, runs the CLI as a subprocess with `--config` and `--json`, parses the JSON result. |
| `cleanyourmail_app/security.py` | Startup token comparison, in-memory sessions and CSRF tokens. |
| `cleanyourmail_app/settings.py` | Stores only the CLI and config paths in a small JSON file under the user's app-data directory. |
| `static/` | Vanilla HTML/CSS/JS. No framework, no build step, no external assets. |

## Why a local web UI

- It runs everywhere Python runs, with no native toolkit dependency.
- The browser provides the rendering, accessibility and copy/paste for free.
- No Electron/Node runtime, no remote content, no third-party assets.
- A future Tauri shell can reuse the same local API and UI if a native binary is worth the extra
  packaging and signing work.

## Why the CLI stays a subprocess

The CLI is the contract. The app calls:

```text
python tools/mail.py <command> --config <path> --json
```

and reads JSON from stdout. This keeps:

- one implementation of classification, planning, journaling and safety rules;
- process isolation between the UI and the mailbox code;
- compatibility with CLI fixes and new commands;
- a small app codebase with no IMAP or OAuth logic.

The trade-off is that the app cannot stream fine-grained progress yet. A future version can add a
`--progress` JSON-lines mode to the CLI and consume it without changing the safety model.

## Request flow

1. `app.py` generates a one-time token, starts the server on a random port and prints
   `http://127.0.0.1:<port>/?token=<token>`.
2. The browser opens the URL. The server consumes the token, creates a session and redirects to `/`
   with an `HttpOnly`, `SameSite=Strict` cookie.
3. The UI fetches `/api/state`, receives the CSRF token and the current paths, and renders.
4. Every POST sends the session cookie, `X-CSRF-Token` and a localhost `Origin`.
5. The server validates all three, runs the CLI, parses JSON and returns a result.
6. The UI renders the result with DOM text nodes, never `innerHTML`.

## State

The app stores only:

```json
{
  "cli_path": ".../cleanyourmail/tools/mail.py",
  "config_path": ".../cleanyourmail.toml"
}
```

under the per-user app-data directory. It never stores passwords, tokens, message data, plans or
journals. Those belong to the CLI and its `state_dir`.

## Plan review and apply

`plan` runs the CLI and returns `{path, plan}`. The app keeps the plan path in memory and sets
`plan_reviewed = false`. The UI must display the plan and the user must check the review box, which
calls `/api/plan/review`. `apply` is refused unless `plan_reviewed` is true and the request includes
`confirm: "APPLY"`. After a successful apply, the plan is marked applied and a second apply is
refused until a new plan is built. Unsubscribe can still use the same plan.

Unsubscribe is a separate endpoint with its own checkbox, `confirm: "UNSUBSCRIBE"` and a 1–50 cap.
Undo is a separate endpoint with `confirm: "UNDO"` and a validated run id.

## Failure handling

- CLI exit code 0 + JSON: rendered normally.
- CLI exit code 2/1 with JSON: rendered as an error, stderr shown.
- CLI timeout: HTTP 400 with a clear message.
- Missing CLI/config: HTTP 400 with a setup hint.
- Invalid JSON/CSRF/Origin: HTTP 400/403; no command runs.
- Unexpected exception: HTTP 500; the traceback goes to the terminal, not the browser.

## Future work

- A `--progress` JSON-lines mode in the CLI for scan/apply progress.
- A Tauri shell with signed binaries for non-technical users.
- OS keychain integration for the password (still optional; the current default is memory only).
- More provider-specific setup hints in the UI.
- A dry-run visual diff of the journal before undo.
