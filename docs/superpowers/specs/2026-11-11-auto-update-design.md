# CleanYourMail app auto-update design

**Date:** 2026-11-11

**Status:** Approved by the maintainer ("si quiero que la app descargue e instale sola").

## Intent

Let an installed CleanYourMail app check the public GitHub release feed, tell the person when a
newer version exists, and — after one explicit **Install update** click — download the installer,
verify its published SHA-256, close the app, run the per-user installer silently, and reopen the new
version. This is a real update flow, not only a link to GitHub.

## Goals

- Startup check at most once every six hours; a header **Updates** button checks on demand.
- Banner with the new version and **Install update** / **Later**.
- Download the exact `CleanYourMail-Setup-<version>.exe` asset over HTTPS.
- Verify the installer against the release's `.sha256` asset before executing anything.
- Show download/installation status; one confirmation before the app closes.
- Run the installer silently as the current user, then reopen the app.
- Keep the app usable when offline, when the release is malformed or when auto-install is not
  available; fall back to opening the release page.
- English and Spanish copy; no telemetry.

## Non-goals

- No background install without the person pressing **Install update**.
- No delta updates, updater service, scheduled task or always-on process.
- No code signing in this release. The installer remains unsigned; Windows SmartScreen may warn.
- No macOS/Linux updater.
- No change to the sidecar or mailbox engine. Sidecar remains 1.3.0.

## Architecture

```text
Startup timer / Updates button
  → GitHub Releases API (latest)
  → UpdateInfo(version, installer_url, checksum_url, notes)
  → banner
  → Install update
  → download installer + .sha256 over HTTPS
  → SHA-256 check
  → confirmation
  → temp .cmd helper
       waits for this PID to exit
       runs installer /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER
       deletes the installer on success
       starts the installed app
  → app quits
```

- `services/updates.py` is network-only; it never starts an installer itself.
- `services/installer.py` (or the same module) builds the helper command; it is injectable for tests.
- `MainWindow` owns the UI state and the background calls. A failed check is silent on the automatic
  path and visible on the manual path.
- `AppSettings.last_update_check` stores the last automatic check (Unix seconds) and is preserved by
  `SettingsStore.update_preferences`.
- The check uses the public GitHub API with a `User-Agent: CleanYourMail/<version>` header.

## Release contract

The release must contain exactly these assets:

```text
CleanYourMail-Setup-<version>.exe
CleanYourMail-Setup-<version>.exe.sha256
```

The `.sha256` file contains `<64 hex>  CleanYourMail-Setup-<version>.exe`. If either asset is
missing or the hash does not match, auto-install is refused and the UI offers the release page
instead. The app never runs an installer from an unrecognised host or filename.

## Security

- HTTPS only; allowed hosts are `github.com` and GitHub's release CDN.
- Asset name must match the version; download cap 200 MB; hash checked before execution.
- The installer is unsigned in 0.6.0, so SHA-256 is integrity, not publisher authentication.
  Code signing remains the next security step.
- No credentials, account email, mailbox data or tokens are sent to GitHub. The only request is
  the public release metadata and the two public assets.
- The helper script is written to a private temp file, quotes every path, waits for the app PID,
  deletes the installer only on success and deletes itself.
- The app does not install silently at startup; a person must press **Install update** and confirm.

## UX copy

- Header: **Updates** / **Actualizaciones**.
- Banner: **CleanYourMail 0.6.0 is available.** / **CleanYourMail 0.6.0 está disponible.**
- Buttons: **Install update** / **Instalar actualización**, **Later** / **Más tarde**.
- Downloading: **Downloading update…**; verifying: **Verifying update…**.
- Confirmation: **Install 0.6.0 now? The app will close and restart.** / **¿Instalar 0.6.0 ahora? La app se cerrará y se reiniciará.**
- Manual no-update: **You're up to date.**; failure: **Could not check for updates. Check your connection.**
- Dev/unpackaged fallback: **Automatic updates are available in the installed app. Open GitHub instead.**

## Risks

- **GitHub/release compromise:** TLS and SHA-256 from the same release do not protect against a
  compromised maintainer account. Code signing is the mitigation; until then the confirmation and
  visible release notes are the human check.
- **Unsigned installer / SmartScreen:** documented; the helper runs the same installer a person
  would run manually.
- **Installer failure:** the helper leaves the downloaded installer for diagnosis and reopens the
  old app; it never loops.
- **Antivirus:** a downloaded installer launched by a helper is a common pattern; the user may see a
  prompt. The fallback is the release page.
- **Update check privacy:** GitHub sees the IP and app version; no account data. The privacy copy
  says update checks use GitHub.
