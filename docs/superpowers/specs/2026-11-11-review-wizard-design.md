# CleanYourMail Review wizard design

**Date:** 2026-11-11

**Status:** Approved by the maintainer ("A", with per-message detail).

## Intent

The Review page currently shows three commands, three result areas, a table, a gate
and Apply at once. A person cannot tell what is happening, what each command does,
in which order, or that nothing changes until Apply. Replace it with a three-step
sub-wizard that explains one action at a time and names the messages involved.

## Goals

- A clear order: **1 Escanear → 2 Informe → 3 Plan**.
- One primary action per step, with a short "what this does / what it does not do"
  explanation.
- After each command, a plain-language result and a Continue button.
- Completed steps collapse to a one-line summary; Back is available.
- The plan step names the destination, sender and subject of every message that
  will move, not just category/counts.
- The review gate and Apply remain explicit; nothing moves before Apply.
- English and Spanish copy; keep the existing translator architecture.

## Non-goals

- No new engine logic in the app. The CLI remains the only planner/mover.
- No message bodies, attachments or full mailbox browser. The plan preview shows
  only headers already stored by the CLI.
- No change to the provider/connect/preferences pages in this release.
- No unsubscribe action in 0.5.0; the existing availability notice stays.

## Data

The CLI 1.3.0 plan JSON adds `groups[].messages`:

```json
{
  "uid": 123,
  "mailbox": "INBOX",
  "sender": "news@example.com",
  "name": "Example News",
  "subject": "Your weekly digest",
  "date": "2026-10-01T08:00:00+00:00"
}
```

The app filters each group's messages by the matching action's `mailbox` and `uids`,
so the plan step shows exactly the messages the action will move, including when the
run limit takes only part of a group. The app never reads the cache or message bodies.

## Steps

### Step 1 — Escanear

Title: "Paso 1 · Escanea tu buzón".
Body: "Leemos solo el remitente, el asunto y la fecha. No abrimos correos ni movemos nada."
Action: "Escanear ahora".
Result: "Encontramos 10 mensajes en 2 categorías. No se ha cambiado nada."
Continue: "Continuar al informe".

### Step 2 — Informe

Title: "Paso 2 · Mira qué encontramos".
Body: "Este resumen es solo informativo. Los mensajes protegidos no se tocarán."
Action: "Crear informe".
Result cards: matched messages, sender groups, protected/skipped.
Per-sender cards: domain, count, up to three sample subjects, "y N más".
Continue: "Preparar el plan".

### Step 3 — Plan

Title: "Paso 3 · Revisa el plan".
Body: "Esto es exactamente lo que se moverá si aplicas. Nada se mueve hasta que pulses Aplicar."
Action: "Preparar plan".
Each destination card:

```text
Newsletters → CleanYourMail/Newsletters
3 mensajes de news.example
· Your weekly digest
· New arrivals
· Editor's picks
y 2 más
```

Gate: "He revisado el plan y entiendo qué cambia."
Apply: "Aplicar 5 movimientos".
After apply: run id, moved count, "Puedes deshacerlo con Undo."
Undo/journal remain available.

## Behaviour

- Only the active step's content is visible. A step bar at the top shows
  `1 Escanear · 2 Informe · 3 Plan`, with the active/done states.
- A completed step collapses to one summary line; Back returns to the previous
  step without clearing data.
- A new scan clears the old report/plan and returns to step 1.
- A new report clears the old plan and stays on step 2.
- A new plan stays on step 3; the gate is enabled only when there is at least one move.
- Direct `set_scan`, `set_report` and `set_plan` calls show the corresponding step so
  existing integrations and tests remain usable.
- `reload()` resets everything to step 1.
- Commands run off the UI thread as today; the step's button disables while busy.

## Sidecar and release

- CLI 1.3.0 provides `groups[].messages`.
- App 0.5.0 bundles sidecar 1.3.0 and installer `CleanYourMail-Setup-0.5.0.exe`.
- Website JSON-LD softwareVersion moves to 1.3.0; no visual version claim change.
- Feedback helper and Worker are unchanged.

## Risks

- The plan JSON grows with one header preview per actionable message (bounded by
  `max_messages_per_group` and the run cap). It contains no bodies or Message-IDs and
  is redacted by `plan --redact`.
- The app must not show messages from groups that are protected, skipped or outside
  the action's UID subset.
