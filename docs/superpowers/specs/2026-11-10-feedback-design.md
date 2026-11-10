# CleanYourMail opt-in feedback design

**Date:** 2026-11-10

**Status:** Approved by the maintainer ("hazlo así") before implementation.

## Intent

Let people send a bug report, an idea or a short checklist from the CleanYourMail
website and the Windows app without opening a GitHub account. Feedback is opt-in,
manually submitted and routed through a Cloudflare Worker to a private Discord
channel. Nothing is collected automatically.

The existing CleanYourPhone implementation is the reference: a static form in
the website, a native dialog in the app, and one Worker that holds the Discord
webhook as a secret.

## Goals

- A feedback section on the English and Spanish website with explicit consent,
  a honeypot and a visible success/error state.
- A Feedback button in the app header that opens a local dialog. The dialog
  sends only when the person presses Send and accepts the consent line.
- One `cleanyourmail-feedback` Worker with the Discord webhook in a Cloudflare
  secret, a KV rate limit keyed by a salted hash of the client IP, body/size
  caps and an allowlisted website origin.
- An editable checklist pre-filled from non-sensitive app state.
- App version `0.4.0`, installer `CleanYourMail-Setup-0.4.0.exe`.

## Non-goals

- No telemetry, analytics, crash reporting, background upload or automatic
  sending.
- No attachments, screenshots, message bodies, subjects, sender addresses,
  account addresses, message IDs, config paths or OAuth/app passwords.
- No ticketing, replies, user accounts, email notifications or Discord bot.
- No Cloudflare Turnstile in this release. The honeypot plus a five-minute,
  salted-IP rate limit is the MVP spam control.
- No code signing, macOS/Linux build or unsubscribe feature in this release.

## Constraints

- The Discord webhook URL and the IP salt never appear in either repository,
  the app binary, the website, logs or tests.
- The app does not touch the network at startup, and the feedback client is
  only constructed after Send.
- The Worker does not persist the message body.
- English and Spanish are first-class; all visible app copy goes through the
  translator catalogs.
- Windows 10/11 x64; Python 3.12+ source builds; PySide6 app.
- The website keeps its static, no-cookie, no-third-party-assets model. The only
  new network target is the Worker origin, allowed in the CSP.

## Approaches considered

1. **Link to GitHub Issues from both clients.** No infrastructure, but it
   requires a GitHub account, exposes the reporter's handle and cannot carry an
   app checklist. Rejected.
2. **Post to Discord directly from the clients.** Simple, but the webhook would
   ship in the website and the executable; anyone could spam or delete it.
   Rejected.
3. **Cloudflare Worker in front of a Discord webhook (chosen).** The secret stays
   server-side, the Worker validates and rate-limits, and both clients use one
   public endpoint. It matches the proven CleanYourPhone pattern.

## Architecture

```text
Website form ─┐
              ├─ HTTPS POST ─→ Cloudflare Worker ─→ private Discord webhook
App dialog ───┘                 │
                                ├─ JSON/size validation
                                ├─ honeypot
                                ├─ KV rate limit: SHA-256(IP_SALT + IP), 5 min
                                └─ no body storage
```

- Worker name: `cleanyourmail-feedback`.
- Public URL: `https://cleanyourmail-feedback.subtitleme.workers.dev`.
- KV binding: `FEEDBACK_KV`.
- Secrets/vars: `DISCORD_WEBHOOK_URL` (secret), `IP_SALT` (secret),
  `ALLOWED_ORIGIN=https://jparedesds.github.io`.
- The app sends no `Origin`; the Worker accepts it. The website is the only
  browser origin allowed by CORS.

## Payload

```json
{
  "kind": "feedback",
  "message": "The review screen could explain ...",
  "checklist": "CleanYourMail app 0.4.0\nSidecar 1.2.2\nWindows 10.0.19045\nProvider: Gmail\nMode: folders",
  "contact": "optional Discord/GitHub/email",
  "app_version": "CleanYourMail app 0.4.0 / sidecar 1.2.2",
  "website": ""
}
```

`kind` is `feedback` or `bug`. At least one of `message` or `checklist` is
required. `website` is a honeypot and must stay empty.

The app checklist includes only:

- app version and sidecar version;
- Windows version;
- provider display name (Gmail, Outlook, etc.);
- folder/archive mode and the selected category names;
- the app language.

It never includes the account email, config or state paths, sender addresses,
subjects, message IDs, passwords, tokens or logs.

## App experience

- Header button labeled Feedback / Comentarios, next to the language selector.
- Dialog: type, message, editable checklist, optional contact, consent checkbox,
  Send and Close.
- Send validates locally, requires consent, runs the HTTP request in a worker
  thread, disables the form while sending and shows localized success, rate
  limit, not-configured and network errors.
- The dialog is not opened automatically and sends nothing until Send.

## Website experience

- A `#feedback` section and nav link in `index.html` and `es.html`.
- Type (Improvement/Bug), message, optional checklist, optional contact,
  honeypot, consent and status line.
- `app.js` posts JSON to the Worker; CSP `connect-src` allows only the Worker
  origin. No inline script is added.
- The form is disabled with a clear message if the endpoint is empty.

## Security and privacy

- Webhook and salt live only in Cloudflare secrets.
- The Worker caps the body at 16 KB, the message at 4000 characters, the
  checklist at 6000, contact at 200 and app version at 80.
- Discord mentions are disabled and code fences are neutralised.
- The Worker returns generic errors and does not log or store the body.
- The rate limiter stores only a hashed key with a five-minute TTL.
- The site's CSP and the app's local-only promise stay intact: the only new
  network call happens on explicit Send.

## Rollout

1. Implement the Worker and deploy it with the KV namespace and origin.
2. Add the website form and tests; deploy the site after the app release.
3. Add the app feedback modules, dialog and tests; bump to 0.4.0.
4. Build and smoke the 0.4.0 installer; publish the release.
5. Set the Discord webhook secret manually in Cloudflare; never in chat, a
   repository or a client.

## Risks and mitigations

- **Accidental PII in the checklist:** the dialog is editable, the checklist is
  limited to non-sensitive fields, and the copy tells people to remove anything
  they do not want to send.
- **Spam:** honeypot plus salted-IP rate limit. Turnstile can be added later
  without changing the clients.
- **Webhook loss:** the Worker returns 503; the clients show a localized
  "not configured" message.
- **Endpoint change:** the URL is a single constant in each client; the CSP lists
  exactly that origin.
