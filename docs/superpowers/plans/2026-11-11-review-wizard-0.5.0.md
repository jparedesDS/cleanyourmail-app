# CleanYourMail Review wizard 0.5.0 implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dense Review page with a three-step sub-wizard that explains each read-only step and lists the exact messages the plan will move.

**Architecture:** The CLI 1.3.0 plan JSON includes `groups[].messages` (header previews only). `ReviewPage` keeps its public command/state methods but groups them into a `QStackedWidget` with a three-step bar, plain-language copy, Continue/Back controls and a plan destination list built from the action's UID subset. The app becomes 0.5.0 and bundles sidecar 1.3.0.

**Tech Stack:** PySide6, pytest-qt, CleanYourMail CLI 1.3.0, PyInstaller/Inno Setup.

**Spec:** `docs/superpowers/specs/2026-11-11-review-wizard-design.md`

## Global Constraints

- The CLI remains the only engine; the app does not read the cache or message bodies.
- `groups[].messages` contains only `uid`, `mailbox`, `sender`, `name`, `subject`, `date`.
- Nothing moves before the reviewed Apply; no unsubscribe action in 0.5.0.
- App 0.5.0; sidecar 1.3.0; installer `CleanYourMail-Setup-0.5.0.exe`.
- English and Spanish copy; no hardcoded visible strings.
- Windows 10/11; unsigned installer; per-user; uninstall preserves user data.
- The feedback Worker/helper and its 2800/2500 limits are unchanged.

## Review Focus

- A person goes Back from step 3 to step 2: the report must still be there, and Continue must return to the same plan without rebuilding it.
- A plan action is limited to part of a group: the plan cards must show only the action's UIDs, not every candidate in the group.
- A new scan: old report/plan must disappear and the gate must close.
- A zero-move or unsubscribe-only plan: step 3 must explain why there is nothing to apply.
- A long subject or sender: wrap/truncate without breaking the card layout or exposing a body.
- A sidecar 1.2.2 plan without `messages`: the app must still work (fall back to samples) and the version check should reject the old sidecar before applying.

---

### Task 1: Review sub-wizard structure and step 1/2

**Files:**
- Modify: `src/cleanyourmail_app/ui/pages/review.py`
- Modify: `src/cleanyourmail_app/i18n/en.json`
- Modify: `src/cleanyourmail_app/i18n/es.json`
- Create: `tests/test_review_wizard.py`

**Interfaces:**
- `ReviewPage.show_step(index: int)` with `0=scan, 1=report, 2=plan`.
- `ReviewPage.current_step() -> int`.
- `ReviewPage.scan_continue_button`, `report_continue_button`, `plan_step_button`.
- Existing `scan_button`, `report_button`, `plan_button`, `set_scan`, `set_report`, `set_plan`, `plan_path`, `review_checkbox`, `apply_button`, `undo_button`, `is_busy` remain.
- `set_scan(...)` shows step 0; `set_report(...)` shows step 1; `set_plan(...)` shows step 2.

- [ ] **Step 1: Write the failing step tests**

Use the existing `FakeCli`/fixtures style from `tests/test_review_plan.py`. Cover:
- page starts on step 0 with only scan content/button visible;
- scan success shows the result and `scan_continue_button`, and Continue moves to step 1;
- report success shows the result and `report_continue_button`, and Continue moves to step 2;
- Back from step 2 returns to step 1 and keeps the report; Back from step 1 returns to step 0 and keeps the scan;
- `show_step(2)` before a plan shows the plan step with a disabled gate;
- the step bar marks active/done states and the step title matches;
- `reload()` returns to step 0 and clears all results;
- Spanish retranslation updates step/continue copy.

Run: `python -m pytest tests/test_review_wizard.py -v`
Expected: FAIL because the step API/widgets do not exist.

- [ ] **Step 2: Build the step shell**

In `_build`, create `self.step_bar` with three labels and a `QStackedWidget` `self.step_stack`. Put existing scan widgets in panel 0, report widgets in panel 1 and plan widgets in panel 2. Add `scan_continue_button`, `report_continue_button`, `plan_step_button` (secondary/primary as fits). Keep the page-level Back (Preferences), Journal, Undo and Apply buttons, but show Apply/Undo only on step 2.

Add `show_step`, `current_step`, `_update_step_bar`, and `_continue_from_scan`/`_continue_from_report`. Hide non-active panels. The step bar labels use `step`, `active`, `done` properties and the existing polish helper.

- [ ] **Step 3: Add the plain-language copy**

Add `review.wizard.step_of`, `review.wizard.scan.title/body/action/result/continue`, `review.wizard.report.title/body/action/result/continue`, `review.wizard.plan.title/body/action`, `review.wizard.back`, `review.wizard.done_summary` to both catalogs. Use the copy from the design. Keep the current title/subtitle as the page-level intro only if it fits; the step titles carry the guidance.

- [ ] **Step 4: Wire the step state**

`set_scan(result)` renders the scan cards and shows step 0. `set_report(result)` renders the report and shows step 1. `set_plan(result)` renders the plan and shows step 2. `reload()` resets to step 0. A new scan clears report/plan and returns to step 0; a new report clears plan and stays on step 1. Continue buttons only advance; they do not run commands.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_review_wizard.py tests/test_review_plan.py tests/test_review_apply.py -q`
Expected: new tests pass; update existing tests only where they need an explicit step/Continue or a hidden-button adjustment. Do not weaken existing gate/apply assertions.

- [ ] **Step 6: Commit**

```bash
git add src/cleanyourmail_app/ui/pages/review.py src/cleanyourmail_app/i18n tests/test_review_wizard.py tests/test_review_plan.py tests/test_review_apply.py
git commit -m "feat: guide the review flow one step at a time"
```

---

### Task 2: Plan message cards and the apply gate

**Files:**
- Modify: `src/cleanyourmail_app/ui/pages/review.py`
- Modify: `tests/test_review_wizard.py`
- Modify: `tests/test_review_plan.py`
- Modify: `tests/test_review_apply.py`

**Interfaces:**
- `ReviewPage._plan_rows()` returns rows with `messages` filtered by action `mailbox`/`uids`.
- `ReviewPage.plan_message_count()` (or reuse `plan_move_count()`).
- Each plan card/row exposes the destination, count, sender and subject preview.

- [ ] **Step 1: Add failing message tests**

Build a plan fixture with:
- two actions, each with `uids`;
- groups with `messages` for more UIDs than the action (run-limit case);
- a protected group with messages that must never appear;
- a group with more than three messages and a long subject.

Assert:
- the plan step shows only the action's UIDs;
- each destination card shows the sender and subject for each selected message;
- a group not in any action never appears;
- a long subject wraps/truncates and no body/Message-ID appears;
- with a 1.2.2-style plan lacking `messages`, the page falls back to `samples` without crashing;
- the gate stays disabled for zero moves/unsubs-only.

Run: `python -m pytest tests/test_review_wizard.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement the message cards**

Replace the plan table with a vertical list of destination cards. For each action, match its group by `group` key, filter `group["messages"]` by `mailbox == action["mailbox"]` and `uid in action["uids"]`, and render sender/name, subject and date. Show "y N más" when the action has more UIDs than the messages available. Keep a compact details table optional; the cards are the primary view. Use `QLabel` with word wrap, not a table, for the messages.

- [ ] **Step 3: Keep the gate honest**

The review checkbox stays disabled unless `plan_move_count() > 0` and an action exists. Apply stays disabled until checked. Show the exact number in the Apply label (`Aplicar N movimientos` / `Apply N moves`) and keep the confirmation dialog. After apply, close the gate and show the run/undo copy.

- [ ] **Step 4: Run the full app suite**

Run: `python -m pytest -q` and `python -m ruff check src tests`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/cleanyourmail_app/ui/pages/review.py src/cleanyourmail_app/i18n tests/test_review_wizard.py tests/test_review_plan.py tests/test_review_apply.py
git commit -m "feat: show the messages in the review plan"
```

---

### Task 3: App 0.5.0 and sidecar 1.3.0 packaging

**Files:**
- Modify: `src/cleanyourmail_app/version.py`
- Modify: `scripts/build-cli-sidecar.ps1`
- Modify: `scripts/build-app.ps1`
- Modify: `scripts/smoke-installer.ps1`
- Modify: `packaging/installer.iss`
- Modify: `.github/workflows/tests.yml`
- Modify: `tests/test_version.py`
- Modify: `tests/test_installer_contract.py`
- Modify: `README.md` and `README.*.md`
- Modify: `docs/ARCHITECTURE.md`, `docs/THREAT_MODEL.md`, `docs/FEEDBACK.md` where they name the sidecar/version.
- Modify: `THIRD_PARTY_NOTICES.md` only if it names the version.

- [ ] **Step 1: Update the failing version tests**

App `0.5.0`; sidecar `CleanYourMail 1.3.0`; installer `CleanYourMail-Setup-0.5.0.exe`; version info `0.5.0.0`. Run focused tests; expect failure.

- [ ] **Step 2: Bump the app and pin the sidecar**

Set `version.py` to `0.5.0`; `scripts/build-cli-sidecar.ps1` default tag `v1.3.0`; installer/smoke/build/CI paths to 0.5.0; all 10 READMEs and docs to app 0.5.0 / sidecar 1.3.0. Keep the feedback helper at 1.3.0.

- [ ] **Step 3: Build and smoke**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-cli-sidecar.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-app.ps1 -SkipSidecar
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke-installer.ps1
```

Expected: sidecar `CleanYourMail 1.3.0`, app `CleanYourMail app 0.5.0`, installer smoke OK.

- [ ] **Step 4: Run tests and commit**

```bash
python -m pytest -q
python -m ruff check src tests
git add ...
git commit -m "build: release 0.5.0 with the review wizard"
```

---

### Task 4: Release 0.5.0, website metadata and verification

**Files:**
- Modify: `../cleanyourmail-web/*.html`
- Modify: `../cleanyourmail-web/tests/test_site.py`

- [ ] **Step 1: Update the website JSON-LD softwareVersion to 1.3.0**

All ten pages; recompute each CSP hash. Keep the download CTA on `/releases/latest`.

- [ ] **Step 2: Push, tag and release**

Fast-forward both `main` branches, push, tag app `v0.5.0`, push the tag, wait for CI, and publish the installer + SHA-256. Use the CI-built installer.

- [ ] **Step 3: Verify**

- release latest is `v0.5.0`;
- installer hash matches;
- website serves ten pages with `softwareVersion 1.3.0`;
- the app opens the Review wizard with the 1.3.0 sidecar and shows message subjects;
- feedback still posts (if the webhook is configured).
