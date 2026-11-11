# CleanYourMail auto-update 0.6.0 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real Windows auto-update flow: GitHub check, SHA-256-verified installer download, silent per-user install through a helper, and relaunch.

**Architecture:** `services/updates.py` reads the GitHub release and downloads/verifies assets; a small temp `.cmd` helper waits for the app to exit, runs the Inno installer silently, and starts the new version. `MainWindow` shows a header Updates button and banner, with background workers and a single confirmation.

**Tech Stack:** PySide6, GitHub Releases API, urllib, hashlib, cmd.exe helper, Inno Setup.

**Spec:** `docs/superpowers/specs/2026-11-11-auto-update-design.md`

## Global Constraints

- App 0.6.0; sidecar stays 1.3.0; installer `CleanYourMail-Setup-0.6.0.exe`.
- No install without the person pressing **Install update** and confirming.
- HTTPS only; GitHub hosts only; exact asset names; SHA-256 must match before execution.
- No secrets, account email, mailbox data or tokens sent to GitHub.
- English/Spanish; no hardcoded visible copy.
- The installer remains unsigned; document SmartScreen.
- The app must work offline and never loop on failure.
- The helper waits for the app PID, installs per-user, deletes the installer only on success,
  reopens the app.

## Review Focus

- A missing `.sha256`, wrong hash, wrong filename or non-GitHub host must refuse execution.
- A partial download must not leave a file that looks installable.
- A failed installer must reopen the old app, not loop or leave the app closed.
- The startup check must not run more than once per six hours and must be silent on failure.
- A manual check must show up-to-date/failure feedback.
- The banner must not cover the wizard on the 900×620 minimum size.
- An unpackaged/dev app must not try to replace itself.

---

### Task 1: Update feed, download and verification

**Files:**
- Create: `src/cleanyourmail_app/services/updates.py`
- Modify: `src/cleanyourmail_app/domain/models.py`
- Modify: `src/cleanyourmail_app/services/settings.py`
- Create: `tests/test_updates.py`
- Modify: `tests/test_models.py`, `tests/test_settings.py`

**Interfaces:**
- `UpdateInfo(version, tag, installer_url="", checksum_url="", notes="", published_at="")`.
- `parse_version(value) -> tuple[int, ...]`, `is_newer(latest, current) -> bool`.
- `check_for_update(current_version, *, opener=None) -> UpdateInfo | None`.
- `download_update(info, *, opener=None, target_dir=None) -> Path`.
- `UpdateError(RuntimeError)`.
- `AppSettings.last_update_check: int = 0`, persisted and preserved by `update_preferences`.

- [ ] **Step 1: Write failing tests**

Cover:
- version parsing/tag `v0.6.0`, malformed values not newer;
- release JSON with assets returns `UpdateInfo` URLs;
- no release/newer returns `None`;
- an asset with a wrong name or missing checksum still returns info but marks auto-install unavailable
  (empty URLs) rather than running;
- HTTP/JSON errors raise `UpdateError`;
- download verifies a correct SHA-256; wrong/missing hash raises and leaves no `.exe`;
- a download over the 200 MB cap raises;
- a non-GitHub URL is refused;
- `AppSettings` round-trip and `SettingsStore.update_preferences` preserve `last_update_check`.

Run: `python -m pytest tests/test_updates.py tests/test_models.py tests/test_settings.py -v`
Expected: FAIL with import/attribute errors.

- [ ] **Step 2: Implement the feed and settings**

Parse the GitHub release `tag_name`, `assets` and `body`. Build the exact expected asset names from
the version. Validate URLs with `urllib.parse`; allow only `https` and hosts `github.com` /
`objects.githubusercontent.com`. Download to a `.part` file in `%TEMP%`, stream with a 200 MB cap,
hash with SHA-256, compare with the `.sha256` content, then `os.replace` to the final `.exe` name.
Never execute anything here.

- [ ] **Step 3: Run tests**

`python -m pytest tests/test_updates.py tests/test_models.py tests/test_settings.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/cleanyourmail_app/services/updates.py src/cleanyourmail_app/domain/models.py src/cleanyourmail_app/services/settings.py tests/test_updates.py tests/test_models.py tests/test_settings.py
git commit -m "feat: check and verify app updates"
```

---

### Task 2: Update banner, header button and download/install flow

**Files:**
- Create: `src/cleanyourmail_app/ui/workers.py`
- Create: `src/cleanyourmail_app/services/installer.py`
- Modify: `src/cleanyourmail_app/ui/main_window.py`
- Modify: `src/cleanyourmail_app/i18n/en.json`, `es.json`
- Modify: `src/cleanyourmail_app/ui/theme.qss`
- Create: `tests/test_ui_updates.py`
- Create: `tests/test_installer.py`

**Interfaces:**
- `BackgroundCall(QObject)` with `succeeded`, `failed`, `finished`, `start(call)`, `active`.
- `UpdateInfo` as Task 1.
- `MainWindow(..., update_checker=None, update_downloader=None, update_launcher=None)`; the real
  `app.main` passes the real functions. `None` disables the automatic check and hides the header
  button (tests can opt in).
- `MainWindow.update_button`, `update_banner`, `update_banner_label`, `update_open_button`,
  `update_later_button`.
- `install_update(installer, app_exe, pid, *, launcher=None) -> Path`.

- [ ] **Step 1: Write failing UI/installer tests**

Cover:
- no checker → no startup network and no visible Updates button;
- checker returning a newer version → banner with version and Install/Later;
- Install → downloader called once; success → launcher called with the installer/app/PID; failure
  shows localized copy and keeps the banner;
- manual check with no update shows “up to date”; failure shows “could not check”;
- automatic check is silent on failure and is skipped within six hours;
- language switch retranslates the banner;
- confirmation “No” does not download/install;
- unpackaged/dev app refuses auto-install with a localized message;
- helper script contains the quoted installer/app paths, the PID wait, silent installer flags, and
  deletes itself; a fake launcher proves it is started detached.

Run: `python -m pytest tests/test_ui_updates.py tests/test_installer.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement the worker and installer helper**

Adapt the thread/QObject bridge from CleanYourPhone. Build the `.cmd` helper with `chcp 65001`,
`tasklist` PID polling, `start /wait` installer flags, success-only deletion, and `start` the app.
Use `subprocess.Popen([...], creationflags=CREATE_NO_WINDOW)`; inject a launcher for tests. Refuse
when `not getattr(sys, "frozen", False)` or when the installer/app path is missing.

- [ ] **Step 3: Implement the header/banner**

Add an **Updates** button in the header before Feedback. Add a hidden banner below the header with
the version label and Install/Later. Start the automatic check with a 1.5 s QTimer only when a
checker is injected and the six-hour throttle allows it. Use `BackgroundCall` for check/download.
On Install: confirm, download, verify, then `install_update`, show “Installing…”, `QApplication.quit()`.
Keep the release-page fallback when auto assets are unavailable. Add all `update.*` keys to both
catalogs; update `app.privacy` to mention update checks use GitHub.

- [ ] **Step 4: Run tests**

`python -m pytest tests/test_ui_updates.py tests/test_installer.py tests/test_i18n.py -v`
then the full suite and ruff.

- [ ] **Step 5: Commit**

```bash
git add src/cleanyourmail_app/ui/workers.py src/cleanyourmail_app/services/installer.py src/cleanyourmail_app/ui/main_window.py src/cleanyourmail_app/i18n src/cleanyourmail_app/ui/theme.qss tests/test_ui_updates.py tests/test_installer.py
git commit -m "feat: download and install app updates"
```

---

### Task 3: App 0.6.0 packaging, docs and build

**Files:**
- Modify: `src/cleanyourmail_app/version.py`
- Modify: `packaging/installer.iss`
- Modify: `scripts/build-app.ps1`, `scripts/smoke-installer.ps1`
- Modify: `.github/workflows/tests.yml`
- Modify: `tests/test_version.py`, `tests/test_installer_contract.py`
- Modify: `README.md` and `README.*.md` (0.5.0 → 0.6.0; sidecar stays 1.3.0)
- Modify: `docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `SECURITY.md`,
  `THIRD_PARTY_NOTICES.md` if current versions are named.

- [ ] **Step 1: Bump to 0.6.0** in code/tests/installer/CI/smoke and all current READMEs/docs.
- [ ] **Step 2: Document auto-update** in the English README and docs: GitHub check, hash verification,
  confirmation, silent per-user install, relaunch, unsigned warning, fallback.
- [ ] **Step 3: Build/smoke**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-app.ps1 -SkipSidecar
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke-installer.ps1
```

Expected: app `CleanYourMail app 0.6.0`, sidecar `1.3.0`, installer smoke OK.
Record size/hash.

- [ ] **Step 4: Full tests + commit**

`python -m pytest -q`, `python -m ruff check src tests`.
Commit `build: release 0.6.0 with automatic updates`.

---

### Task 4: Release 0.6.0 and verify

- [ ] Push the branch, wait for CI, merge `main`, tag `v0.6.0`, publish the CI installer + SHA-256.
- [ ] Verify the release assets include the installer and `.sha256` with the exact names the app
  expects.
- [ ] Install 0.6.0 once and confirm the Updates button and a manual “up to date” check against the
  live release.
- [ ] Document that a real update can only be exercised once 0.6.1 exists; the unit/integration tests
  with fake releases cover the download/verify/helper path.
