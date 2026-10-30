# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting:

<https://github.com/jparedesDS/cleanyourmail-app/security/advisories/new>

Include:

- what you were doing and what happened;
- the app version (`v0.1.0` or the commit);
- the operating system and Python version;
- reproduction steps;
- whether a mailbox, credential, plan, journal or local file was exposed.

Do not include real passwords, OAuth tokens, cookies, message bodies, real email addresses or
screenshots of a real inbox. Redact them.

## Security model in one page

The app is a **local front end** for the CleanYourMail CLI. It does not replace the CLI's safety
rules and it does not add capabilities the CLI does not have.

- Binds to `127.0.0.1` only.
- Starts with a one-time token in the URL. The token is consumed and the browser gets an `HttpOnly`,
  `SameSite=Strict` session cookie.
- Every API call requires the session, a CSRF token, a localhost `Origin` and a localhost `Host`.
- Strict Content Security Policy, no inline scripts, no external assets, no telemetry.
- The password is kept in page memory and passed to the CLI subprocess through its environment. It is
  never written to disk or logs.
- No message bodies, no attachments, no permanent deletion.
- The plan is reviewed before moves. Unsubscribe is a separate, explicit, capped step.
- The undo journal belongs to the CLI and is displayed by the app.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the full analysis.

## If you think your mailbox was affected

1. Stop the app (`Ctrl+C` in the terminal).
2. Revoke the app password or OAuth token with your mail provider.
3. Check the CleanYourMail journal with the CLI: `python tools/mail.py journal`.
4. Restore any unwanted move with `python tools/mail.py undo --run <run> --yes`.
5. Report the issue privately with the details above.

## Safe operation

- Run the app as your normal user, not as administrator/root.
- Do not expose the port, reverse-proxy it or run it on a shared/untrusted machine.
- Use a dedicated app password with the narrowest scope the provider allows.
- Keep Python, the OS and the two repositories updated.
- Do not paste real credentials into issues, screenshots or logs.
- Remember that unsubscribe is irreversible; review the target and the cap.
