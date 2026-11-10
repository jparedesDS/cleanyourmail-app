"""The fourth wizard page: scan, report, plan, apply, journal and undo.

The page is a *view* of the sidecar. It never implements IMAP, classification,
planning, moves or undo; it asks ``CliClient`` for ``scan``, ``report``,
``plan``, ``apply``, ``journal`` and ``undo`` in worker threads and renders the
JSON. No mailbox change happens before the person reviews the plan and confirms
the apply dialog, and only the sidecar touches a mailbox.

Filing is the decisions the person made on the Preferences page: the plan call
receives the stored ``categories`` and ``mode`` (``folders`` or ``archive``)
verbatim, and apply's limit is clamped to ``max_moves`` and the plan's own move
count, so the UI cannot exceed policy. The review checkbox is enabled only by a
plan with at least one move; Apply follows that checkbox. A successful or
partial apply closes that plan's gate for good, and only a new scan or plan
reopens it.

The journal is a modal list of recent runs. Undo always asks for confirmation
and passes the full run id the sidecar printed; it never guesses. Apply never
unsubscribes: ``--action move`` is explicit in the typed helper and unsubscribe
stays a separate future action.

Language is a window-level concern: payloads are kept so ``retranslate`` can
re-render category names, unsubscribe modes, status counts and the journal in
the new catalog without asking the sidecar again. A plan is cleared whenever a
new scan starts or a new plan fails, and every error is localized copy, never
the sidecar's raw output.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.models import CATEGORIES, Preferences
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices

#: The app has no scan-window preference; one year is the documented default.
SCAN_DAYS = 365

#: How many sender groups the report shows, matching the CLI's own default.
REPORT_TOP = 30

#: How many recent runs the journal dialog asks for.
JOURNAL_LIMIT = 20

#: Localized status and error keys per command.
_RUNNING_KEYS = {
    "scan": "review.scanning",
    "report": "review.report.running",
    "plan": "review.plan.running",
    "apply": "apply.running",
    "journal": "review.journal_loading",
    "undo": "review.undo.running",
}
_ERROR_KEYS = {
    "scan": "errors.scan",
    "report": "errors.report",
    "plan": "errors.plan",
    "apply": "errors.apply",
    "journal": "errors.journal",
    "undo": "errors.undo",
}

#: Sidecar unsubscribe modes to catalog keys.
_UNSUBSCRIBE_KEYS = {
    "one-click": "review.plan.unsubscribe_one_click",
    "mailto": "review.plan.unsubscribe_email",
    "http": "review.plan.unsubscribe_link",
    "manual": "review.plan.unsubscribe_manual",
}


class _ReviewSignals(QObject):
    """Carry one worker result back to the page.

    The sidecar's raw output never crosses the thread boundary: a successful
    call sends the normalized result dict, and a failure sends only its action
    and token, so no argument, path or server message can reach a label by
    accident.
    """

    finished = Signal(str, int, object)
    failed = Signal(str, int)


class _CommandJob(QRunnable):
    """Run one sidecar command without blocking the UI thread."""

    def __init__(
        self,
        action: str,
        work: object,
        token: int,
        signals: _ReviewSignals,
    ) -> None:
        super().__init__()
        self._action = action
        self._work = work
        self._token = token
        self._signals = signals

    def run(self) -> None:  # noqa: D401 - QRunnable's contract
        try:
            result = self._work()  # type: ignore[operator]
        except Exception:
            # A missing sidecar, a timeout or a crash is a failed command, not
            # a reason to take the wizard down. The exception text may name a
            # path and is never rendered or logged.
            try:
                self._signals.failed.emit(self._action, self._token)
            except RuntimeError:
                pass
            return
        try:
            self._signals.finished.emit(self._action, self._token, result)
        except RuntimeError:
            # The window closed while the command was still running.
            pass


class JournalDialog(QDialog):
    """A modal list of journal runs with an Undo action for the selected row.

    The table never shortens the run id that is passed back to the sidecar: a
    display-only id would make undo ambiguous. Selecting one row is the only
    way to enable its Undo button; the page owns the confirmation and the
    worker, so this dialog stays a view.
    """

    undoRequested = Signal(str)

    def __init__(
        self,
        translator: Translator,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._runs: list[dict[str, Any]] = []
        self._state = "loading"
        self._busy = False
        self.setModal(True)
        self.setMinimumSize(620, 380)
        self.setObjectName("journalDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.table = QTableWidget(0, 4, self)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setVisible(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(220)
        self.table.setVisible(False)
        self.table.itemSelectionChanged.connect(self._selection_changed)

        self.empty_label = QLabel(self)
        self.empty_label.setObjectName("muted")
        self.empty_label.setWordWrap(True)

        self.undo_button = QPushButton(self)
        self.undo_button.setObjectName("primary")
        self.undo_button.setMinimumWidth(170)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._emit_undo)

        self.close_button = QPushButton(self)
        self.close_button.setObjectName("secondary")
        self.close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.close_button)

        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty_label, 1)
        layout.addLayout(buttons)

        self.retranslate()

    # -- state --------------------------------------------------------------

    def set_loading(self) -> None:
        """Show the loading copy until the worker hands over the runs."""
        self._state = "loading"
        self._runs = []
        self._busy = False
        self.table.setRowCount(0)
        self.table.setVisible(False)
        self.empty_label.setVisible(True)
        self._refresh_empty()
        self.undo_button.setEnabled(False)

    def set_runs(self, runs: list[dict[str, Any]]) -> None:
        """Render the runs; an empty list is a real, explained state."""
        self._runs = runs
        self._state = "runs" if runs else "empty"
        self.table.setRowCount(len(runs))
        for row, run in enumerate(runs):
            run_id = str(run.get("run") or "")
            self._set_cell(row, 0, self._when(run.get("ts")))
            self._set_cell(row, 1, run_id)
            self._set_cell(row, 2, str(self._int(run.get("messages"))))
            self._set_cell(row, 3, str(self._int(run.get("ops"))))
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setVisible(bool(runs))
        self.empty_label.setVisible(not runs)
        self._refresh_empty()
        self.undo_button.setEnabled(False)

    def set_busy(self, busy: bool) -> None:
        """Disable selection and Undo while a sidecar command owns the page."""
        self._busy = busy
        self.table.setEnabled(not busy)
        self.undo_button.setEnabled(not busy and self.selected_run() is not None)

    def selected_run(self) -> str | None:
        """The full run id of the selected row, or ``None``."""
        selection = self.table.selectionModel()
        if selection is None or not selection.hasSelection():
            return None
        row = self.table.currentRow()
        if 0 <= row < len(self._runs):
            run = self._runs[row].get("run")
            return str(run) if isinstance(run, str) and run else None
        return None

    # -- slots --------------------------------------------------------------

    def _selection_changed(self) -> None:
        self.undo_button.setEnabled(not self._busy and self.selected_run() is not None)

    def _emit_undo(self) -> None:
        run = self.selected_run()
        if run and not self._busy:
            self.undoRequested.emit(run)

    # -- rendering ----------------------------------------------------------

    def _set_cell(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, column, item)

    @staticmethod
    def _int(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return value

    @staticmethod
    def _when(value: object) -> str:
        """A compact local-looking stamp; the sidecar's ISO text is kept."""
        text = str(value or "")
        if "T" in text:
            text = text.replace("T", " ", 1)
        return text[:19]

    def _refresh_empty(self) -> None:
        if self._state == "loading":
            self.empty_label.setText(self._translator.t("review.journal_loading"))
        else:
            self.empty_label.setText(self._translator.t("review.journal_empty"))

    def retranslate(self) -> None:
        """Refresh the title, headers and buttons in the active language."""
        t = self._translator.t
        self.setWindowTitle(t("review.journal"))
        headers = (
            t("review.journal_when"),
            t("review.journal_run"),
            t("review.journal_messages"),
            t("review.journal_ops"),
        )
        for column, text in enumerate(headers):
            item = self.table.horizontalHeaderItem(column)
            if item is None:
                self.table.setHorizontalHeaderItem(column, QTableWidgetItem(text))
            else:
                item.setText(text)
        self.table.setAccessibleName(", ".join(headers))
        self.undo_button.setText(t("review.undo.selected"))
        self.close_button.setText(t("review.close"))
        self._refresh_empty()


class ReviewPage(QWidget):
    """Scan cards, a report table, a plan table and the review gate."""

    backRequested = Signal()

    def __init__(
        self,
        services: AppServices,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        self._settings = services.settings
        self._translator = services.translator
        self._pool = QThreadPool.globalInstance()
        self._busy: str | None = None
        self._token = 0
        self._gate_updating = False
        self._scan: dict[str, Any] | None = None
        self._report: dict[str, Any] | None = None
        self._plan: dict[str, Any] | None = None
        self._plan_path: str | None = None
        self._report_top = REPORT_TOP
        self._status_key: str | None = None
        self._status_args: dict[str, object] = {}
        self._status_extra_key: str | None = None
        self._status_extra_args: dict[str, object] = {}
        self._error_key: str | None = None
        self._error_args: dict[str, object] = {}
        #: A started apply may have moved messages even when its outcome is
        #: unknown, so this closes the plan's gate as soon as apply begins.
        #: Only a fresh scan or plan clears it.
        self._applied = False
        #: The newest run the page knows about, for the footer's undo shortcut.
        self._last_run: str | None = None
        self._journal_dialog: JournalDialog | None = None
        self._journal_quiet = False
        # Unparented on purpose, like the Connect page: a job that outlives the
        # page keeps its emitter alive and Qt drops the receiver instead of
        # raising when the window closes mid-scan.
        self._signals = _ReviewSignals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        self._build()
        self.reload()

    # -- public state -------------------------------------------------------

    def reload(self) -> None:
        """Forget every answer and close the gate.

        Called when the shell enters the page, so a plan built before the
        person changed Preferences is never mistaken for the current one. An
        in-flight worker is invalidated by the token, not killed.
        """
        self._token += 1
        self._busy = None
        self._journal_quiet = False
        self._close_journal_dialog()
        self._applied = False
        self._set_status(None)
        self._set_error(None)
        self._reset_answers()
        self._refresh_actions()
        self._sync_feedback()

    def _reset_answers(self) -> None:
        """Blank the scan, report and plan; a new scan makes them all stale."""
        self._scan = None
        self._report = None
        self.scan_total_label.setText("0")
        self.scan_categories_label.setText(
            self._translator.t("review.plan.unsubscribe_none")
        )
        self.scan_mailboxes_label.setText("0")
        self.report_total_label.setText("0")
        self.report_groups_label.setText("0")
        self.report_protected_label.setText("0")
        self.report_table.setRowCount(0)
        self._clear_plan()

    def is_busy(self) -> bool:
        """Whether a sidecar command is in flight."""
        return self._busy is not None

    @property
    def plan_path(self) -> str | None:
        """Where the last successful plan was written, for a later apply."""
        return self._plan_path

    @property
    def last_run(self) -> str | None:
        """The newest run the page knows, used by the Undo last run action."""
        return self._last_run

    @property
    def journal_dialog(self) -> JournalDialog | None:
        """The open journal dialog, if any; None once it is closed."""
        return self._journal_dialog

    def plan_move_count(self) -> int:
        """How many messages the current plan would move."""
        if not self._plan:
            return 0
        total = 0
        for action in self._plan.get("actions") or []:
            if not isinstance(action, Mapping) or action.get("type") != "move":
                continue
            uids = action.get("uids")
            if isinstance(uids, (list, tuple)):
                total += len(uids)
        return total

    def build_plan(self, preferences: Preferences | None = None) -> dict[str, Any]:
        """Ask the sidecar for a plan with the person's categories and mode.

        Synchronous, like the other typed helpers; the Plan button runs it in a
        worker thread. ``preferences`` defaults to what ``SettingsStore`` holds,
        which is the same policy Preferences writes to the TOML on Continue.
        """
        if preferences is None:
            preferences = self._settings.load().preferences
        if not isinstance(preferences, Preferences):
            raise TypeError("build_plan() needs a Preferences value")
        return self._services.cli.plan(
            preferences.mode,
            preferences.categories,
            config_path=self._services.config.config_path(),
        )

    # -- commands -----------------------------------------------------------

    def start_scan(self, days: int = SCAN_DAYS) -> None:
        """Scan the last ``days`` days of headers in the background."""
        config_path = self._services.config.config_path()
        self._start("scan", lambda: self._services.cli.scan(days, config_path=config_path))

    def start_report(self, top: int = REPORT_TOP) -> None:
        """Build the sender report from the cache in the background."""
        self._report_top = top if isinstance(top, int) and top > 0 else REPORT_TOP
        config_path = self._services.config.config_path()
        self._start("report", lambda: self._services.cli.report(top, config_path=config_path))

    def start_plan(self, preferences: Preferences | None = None) -> None:
        """Build a dry-run plan in the background, never applying it."""
        self._start("plan", lambda: self.build_plan(preferences))

    def apply(self, limit: int = 0) -> None:
        """Apply the reviewed plan after confirmation.

        ``limit`` defaults to the stored ``max_moves`` and is then clamped to
        the policy and to the plan's own move count. The button is only enabled
        after the review checkbox; this method also refuses while busy, after
        an apply, and without a move-bearing plan, so a stale call cannot run
        the same plan twice.
        """
        if self._busy is not None or self._applied:
            return
        path = self._plan_path
        moves = self.plan_move_count()
        if not path or moves <= 0:
            return

        preferences = self._settings.load().preferences
        requested = (
            limit
            if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0
            else preferences.max_moves
        )
        effective = min(requested, preferences.max_moves, moves)
        if effective <= 0:
            return

        if not self._confirm_apply(effective):
            return
        # The modal dialog can only be dismissed by the event loop, but keep
        # the guard here so a callback that starts another command wins.
        if self._busy is not None or self._applied:
            return

        # The moment the worker starts, the outcome is uncertain: a timeout or
        # a crash can leave messages moved with no result to parse. Close this
        # plan's gate now and reserve "apply" for a fresh scan or plan.
        self._applied = True
        self._refresh_gate()

        config_path = self._services.config.config_path()
        self._start(
            "apply",
            lambda: self._services.cli.apply(
                path, effective, config_path=config_path
            ),
        )

    def _apply_clicked(self) -> None:
        """The button route: never apply while the review box is not checked."""
        if not self.review_checkbox.isChecked():
            return
        self.apply()

    def _go_back(self) -> None:
        """Return to Preferences; applying is never implicit on page leave."""
        if self._busy is None:
            self.backRequested.emit()

    def load_journal(self) -> None:
        """Fetch the newest runs and show them in the modal journal."""
        self._request_journal(quiet=False)

    def undo(self, run: str = "") -> None:
        """Restore one journal run after an explicit confirmation."""
        if self._busy is not None:
            return
        run_id = run.strip() if isinstance(run, str) else ""
        if not run_id:
            self._set_status("review.undo.empty")
            self._set_error(None)
            self._sync_feedback()
            return
        if not self._confirm_undo(run_id):
            return
        if self._busy is not None:
            return
        config_path = self._services.config.config_path()
        self._start(
            "undo",
            lambda: self._services.cli.undo(run_id, config_path=config_path),
        )

    def _request_journal(self, *, quiet: bool) -> None:
        """Load the journal; a quiet refresh never disturbs visible feedback."""
        if self._busy is not None:
            return
        if quiet and self._journal_dialog is None:
            return
        dialog = self._journal_dialog
        if not quiet:
            dialog = self._ensure_journal_dialog()
            dialog.set_loading()
            dialog.show()
            dialog.raise_()
        if dialog is not None:
            dialog.set_busy(True)
        config_path = self._services.config.config_path()

        def work() -> dict[str, Any]:
            return self._services.cli.journal(
                JOURNAL_LIMIT, config_path=config_path
            )

        self._start("journal", work, quiet=quiet)

    # -- confirmation -------------------------------------------------------

    def _confirm_apply(self, count: int) -> bool:
        return self._ask(
            self._translator.t("review.apply"),
            self._translator.t("apply.confirm", count=count),
        )

    def _confirm_undo(self, run: str) -> bool:
        return self._ask(
            self._translator.t("review.undo.title"),
            self._translator.t("review.undo.confirm_run", run=run),
        )

    def _ask(self, title: str, text: str) -> bool:
        """A Yes/No question; No is the default and the safe answer."""
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    # -- worker plumbing ----------------------------------------------------

    def _start(self, action: str, work: object, *, quiet: bool = False) -> None:
        if self._busy is not None:
            return
        self._token += 1
        self._busy = action
        if action == "journal":
            self._journal_quiet = quiet
        if not quiet:
            self._set_error(None)
            if action == "scan":
                # New headers make every old answer stale, including a plan
                # whose UIDs the cache may have pruned. Re-plan before apply.
                self._reset_answers()
            self._set_status(_RUNNING_KEYS[action])
        self._refresh_actions()
        self._sync_feedback()
        self._pool.start(_CommandJob(action, work, self._token, self._signals))

    def _on_finished(self, action: str, token: int, result: object) -> None:
        if token != self._token:
            return
        self._busy = None
        quiet = self._journal_quiet if action == "journal" else False
        if action == "journal":
            self._journal_quiet = False

        if action == "apply" and self._is_partial_apply(result):
            try:
                self._apply_partial(result)
            except Exception:
                self._fail(action)
            self._refresh_actions()
            return
        if action == "undo" and self._is_partial_undo(result):
            try:
                self._undo_finished(result)
            except Exception:
                self._fail(action)
            self._refresh_actions()
            return

        if (
            action == "journal"
            and quiet
            and (not isinstance(result, Mapping) or result.get("ok") is False)
        ):
            # A background refresh after undo must not erase the restored
            # count or close the journal; keep both as the person left them.
            if self._journal_dialog is not None:
                self._journal_dialog.set_busy(False)
            self._refresh_actions()
            return

        self._refresh_actions()
        if not isinstance(result, Mapping) or result.get("ok") is False:
            self._fail(action)
            return
        try:
            if action == "scan":
                self.set_scan(result)
            elif action == "report":
                self.set_report(result)
            elif action == "plan":
                self.set_plan(result)
            elif action == "apply":
                self._apply_succeeded(result)
            elif action == "journal":
                self._journal_finished(result, quiet=quiet)
            elif action == "undo":
                self._undo_finished(result)
        except Exception:
            # A malformed payload is a failed command, not a page crash; the
            # person gets the same localized copy as any other failure.
            self._fail(action)

    def _on_failed(self, action: str, token: int) -> None:
        if token != self._token:
            return
        self._busy = None
        quiet = self._journal_quiet if action == "journal" else False
        if action == "journal":
            self._journal_quiet = False
        if action == "journal" and quiet:
            # A background refresh after undo must not erase the restored
            # count; leave the dialog as it was and keep the feedback.
            if self._journal_dialog is not None:
                self._journal_dialog.set_busy(False)
            self._refresh_actions()
            return
        self._refresh_actions()
        self._fail(action)

    def _fail(self, action: str) -> None:
        """Drop the failed answer and show localized copy, never raw output."""
        self._set_status(None)
        self._set_error(_ERROR_KEYS[action])
        if action == "scan":
            self._scan = None
            self.scan_total_label.setText("0")
            self.scan_categories_label.setText(
                self._translator.t("review.plan.unsubscribe_none")
            )
            self.scan_mailboxes_label.setText("0")
        elif action == "report":
            self._report = None
            self.report_total_label.setText("0")
            self.report_groups_label.setText("0")
            self.report_protected_label.setText("0")
            self.report_table.setRowCount(0)
        elif action == "plan":
            self._clear_plan()
        elif action == "journal":
            self._close_journal_dialog()
        self._sync_feedback()

    # -- apply results ------------------------------------------------------

    def _is_partial_apply(self, result: object) -> bool:
        """A failed call that still moved messages and printed its run id."""
        if not isinstance(result, Mapping) or result.get("ok") is not False:
            return False
        payload = self._payload(result)
        run = payload.get("run")
        moved = payload.get("moved")
        return (
            isinstance(run, str)
            and bool(run)
            and isinstance(moved, int)
            and not isinstance(moved, bool)
            and moved > 0
        )

    def _apply_succeeded(self, result: object) -> None:
        payload = self._payload(result)
        run = payload.get("run")
        if not isinstance(run, str) or not run:
            raise ValueError("apply result needs a run id")
        moved = self._int(payload.get("moved"))
        # v1.2.2 exits non-zero when `failures` is non-empty, so an ok=True
        # payload is a complete run; partial runs take `_apply_partial`.
        self._mark_applied(run)
        self._set_status(
            "apply.done",
            extra=("apply.id", {"run": run}),
            count=moved,
        )
        self._set_error(None)
        self._sync_feedback()

    def _apply_partial(self, result: object) -> None:
        payload = self._payload(result)
        run = payload.get("run")
        if not isinstance(run, str) or not run:
            raise ValueError("partial apply result needs a run id")
        self._mark_applied(run)
        # The run is real and undoable, but it stopped early: show both facts
        # and never pass the sidecar's raw error text through.
        self._set_status(
            "apply.failed",
            extra=("apply.id", {"run": run}),
        )
        self._set_error("apply.partial")
        self._sync_feedback()

    def _mark_applied(self, run: str) -> None:
        """Close this plan's gate permanently and remember the run to undo."""
        self._applied = True
        self._last_run = run
        self._refresh_actions()

    # -- journal and undo results ------------------------------------------

    def _journal_finished(self, result: object, *, quiet: bool) -> None:
        payload = self._payload(result)
        runs: list[dict[str, Any]] = []
        raw = payload.get("runs")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                run = item.get("run")
                if isinstance(run, str) and run:
                    runs.append(dict(item))

        dialog = self._journal_dialog
        if dialog is None:
            # The person closed the dialog while the worker was running; a
            # late answer must not pop it back open.
            return
        dialog.set_runs(runs)
        if not runs:
            # An empty journal means there is nothing for "Undo last run" to
            # target, even if an older apply remembered a run.
            self._last_run = None
        if not quiet:
            # A generic journal load must not choose the footer's target: the
            # newest entry may be an undo record or another run this page did
            # not apply. Only a successful/partial apply sets `_last_run`.
            self._set_status(None)
            self._set_error(None)
            self._sync_feedback()
        self._refresh_actions()

    def _ensure_journal_dialog(self) -> JournalDialog:
        if self._journal_dialog is None:
            dialog = JournalDialog(self._translator, self)
            dialog.undoRequested.connect(self.undo)
            dialog.finished.connect(self._journal_closed)
            self._journal_dialog = dialog
        return self._journal_dialog

    def _close_journal_dialog(self) -> None:
        dialog = self._journal_dialog
        self._journal_dialog = None
        if dialog is not None:
            dialog.set_busy(False)
            dialog.close()

    def _journal_closed(self, _result: int) -> None:
        """A closed dialog invalidates an in-flight journal answer."""
        dialog = self._journal_dialog or self.sender()
        self._journal_dialog = None
        if isinstance(dialog, JournalDialog):
            dialog.deleteLater()
        if self._busy != "journal":
            return
        quiet = self._journal_quiet
        self._journal_quiet = False
        self._token += 1
        self._busy = None
        if not quiet:
            self._set_status(None)
            self._set_error(None)
        self._refresh_actions()
        self._sync_feedback()

    def _is_partial_undo(self, result: object) -> bool:
        """A failed undo that still restored or attempted something."""
        if not isinstance(result, Mapping) or result.get("ok") is not False:
            return False
        payload = self._payload(result)
        restored = payload.get("restored")
        if isinstance(restored, bool) or not isinstance(restored, int):
            return False
        failed = self._int(payload.get("failed"))
        refused = self._int(payload.get("refused"))
        return restored > 0 or failed > 0 or refused > 0

    def _undo_finished(self, result: object) -> None:
        payload = self._payload(result)
        restored = payload.get("restored")
        if isinstance(restored, bool) or not isinstance(restored, int):
            raise ValueError("undo result needs a restored count")
        failed = self._int(payload.get("failed"))
        refused = self._int(payload.get("refused"))
        if restored == 0 and failed == 0 and refused == 0:
            raise ValueError("undo result has no operations")
        # The newest journal entry is now the undo itself, not a useful
        # "undo last run" target; force a fresh choice from the journal.
        self._last_run = None
        self._set_status("review.undo.done", count=restored)
        if failed or refused:
            self._set_error(
                "review.undo.partial", failed=failed, refused=refused
            )
        else:
            self._set_error(None)
        self._sync_feedback()
        self._refresh_actions()
        if self._journal_dialog is not None:
            self._request_journal(quiet=True)

    def _clear_plan(self) -> None:
        self._plan = None
        self._plan_path = None
        self._applied = False
        self.plan_table.setRowCount(0)
        self.plan_summary_label.setText("")
        self.plan_note.setVisible(False)
        self._refresh_gate()

    # -- rendering ----------------------------------------------------------

    def set_scan(self, result: object) -> None:
        """Render a ``scan --json`` payload (raw result or bare payload)."""
        self._scan = self._payload(result)
        payload = self._scan
        total = self._int(payload.get("total"))
        self.scan_total_label.setText(str(total))
        self.scan_mailboxes_label.setText(str(len(payload.get("mailboxes") or {})))
        self.scan_categories_label.setText(self._category_counts(payload.get("categories")))
        self._set_error(None)
        self._set_status("review.scan_done" if total else "review.scan_empty")
        self._sync_feedback()

    def set_report(self, result: object) -> None:
        """Render a ``report --json`` payload (raw result or bare payload)."""
        self._report = self._payload(result)
        payload = self._report
        totals = payload.get("totals")
        if not isinstance(totals, Mapping):
            totals = {}
        messages = self._int(totals.get("messages"), self._int(payload.get("cached")))
        groups = totals.get("groups")
        if not isinstance(groups, int):
            groups = len(payload.get("groups") or [])
        self.report_total_label.setText(str(messages))
        self.report_groups_label.setText(str(groups))
        self.report_protected_label.setText(str(self._int(totals.get("protected"))))
        self._render_report(payload)
        self._set_error(None)
        self._set_status("review.report.done")
        self._sync_feedback()

    def set_plan(self, result: object) -> None:
        """Render a ``plan --json`` payload (raw result or bare payload)."""
        payload = self._payload(result)
        path = payload.get("path")
        self._plan_path = str(path) if isinstance(path, str) else None
        nested = payload.get("plan")
        if isinstance(nested, Mapping):
            payload = dict(nested)
        self._plan = payload or None
        # A new plan is a new review: its gate starts closed even if the
        # previous plan was already applied.
        self._applied = False
        self._render_plan()
        self._set_error(None)
        self._set_status(
            "review.plan.done" if self.plan_move_count() else "review.zero_moves"
        )
        self._sync_feedback()

    @staticmethod
    def _payload(result: object) -> dict[str, Any]:
        """Unwrap ``CliClient.run``'s result, or accept a bare payload."""
        if not isinstance(result, Mapping):
            return {}
        if "ok" in result and isinstance(result.get("data"), Mapping):
            return dict(result["data"])
        return dict(result)

    @staticmethod
    def _int(value: object, default: int = 0) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        return value

    def _render_report(self, payload: Mapping[str, Any]) -> None:
        groups = payload.get("groups") or []
        rows = [group for group in groups if isinstance(group, Mapping)][
            : self._report_top
        ]
        self.report_table.setRowCount(len(rows))
        for row, group in enumerate(rows):
            unsubscribe = group.get("unsubscribe")
            mode = ""
            if isinstance(unsubscribe, Mapping):
                mode = str(unsubscribe.get("mode") or "")
            self._set_cell(
                self.report_table,
                row,
                0,
                self._category_label(str(group.get("category") or "")),
            )
            self._set_cell(self.report_table, row, 1, str(group.get("domain") or ""))
            self._set_cell(self.report_table, row, 2, str(self._int(group.get("count"))))
            self._set_cell(self.report_table, row, 3, str(self._int(group.get("unread"))))
            self._set_cell(self.report_table, row, 4, self._unsubscribe_label(mode))

    def _render_plan(self) -> None:
        rows = self._plan_rows()
        self.plan_table.setRowCount(len(rows))
        for row, entry in enumerate(rows):
            self._set_cell(
                self.plan_table, row, 0, self._category_label(entry["category"])
            )
            self._set_cell(self.plan_table, row, 1, entry["destination"])
            self._set_cell(self.plan_table, row, 2, str(entry["messages"]))
            self._set_cell(self.plan_table, row, 3, self._unsubscribe_label(entry["modes"]))

        moves = self.plan_move_count()
        if self._plan:
            groups = len(
                {
                    action.get("group")
                    for action in self._plan.get("actions") or []
                    if isinstance(action, Mapping) and action.get("group")
                }
            )
            if moves:
                self.plan_summary_label.setText(
                    self._translator.t(
                        "review.summary", messages=moves, groups=groups or 1
                    )
                )
            else:
                self.plan_summary_label.setText(
                    self._translator.t("review.zero_moves")
                )
        else:
            self.plan_summary_label.setText("")

        stats = self._plan.get("stats") if self._plan else None
        protected = 0
        if isinstance(stats, Mapping):
            protected = self._int(stats.get("protected"))
        self.plan_note.setVisible(bool(protected))
        self._refresh_gate()

    def _plan_rows(self) -> list[dict[str, Any]]:
        """One row per category/destination, with its messages and unsub modes."""
        moves: dict[tuple[str, str], int] = {}
        unsubscribe: dict[str, set[str]] = {}
        for action in (self._plan or {}).get("actions") or []:
            if not isinstance(action, Mapping):
                continue
            category = str(action.get("category") or "")
            if action.get("type") == "move":
                destination = str(action.get("dest") or "")
                key = (category, destination)
                uids = action.get("uids")
                moves[key] = moves.get(key, 0) + (
                    len(uids) if isinstance(uids, (list, tuple)) else 0
                )
            elif action.get("type") == "unsubscribe":
                mode = str(action.get("mode") or "")
                if mode:
                    unsubscribe.setdefault(category, set()).add(mode)

        no_destination = self._translator.t("review.plan.no_destination")
        rows: list[dict[str, Any]] = []
        for (category, destination), messages in moves.items():
            rows.append(
                {
                    "category": category,
                    "destination": destination or no_destination,
                    "messages": messages,
                    "modes": sorted(unsubscribe.get(category, ())),
                }
            )
        moved = {category for category, _ in moves}
        for category, modes in unsubscribe.items():
            if category in moved:
                continue
            rows.append(
                {
                    "category": category,
                    "destination": no_destination,
                    "messages": 0,
                    "modes": sorted(modes),
                }
            )

        order = {category: index for index, category in enumerate(CATEGORIES)}
        rows.sort(
            key=lambda row: (
                order.get(row["category"], len(CATEGORIES)),
                row["category"],
                row["destination"],
            )
        )
        return rows

    # -- gate ---------------------------------------------------------------

    def review_toggled(self, checked: bool) -> None:
        """Recompute Apply from the checkbox; a disabled gate stays closed."""
        if self._gate_updating:
            return
        self._refresh_gate()

    def _refresh_gate(self) -> None:
        enabled = (
            not self._applied
            and self.plan_move_count() > 0
            and self._busy is None
        )
        if not enabled and self.review_checkbox.isChecked():
            self._gate_updating = True
            try:
                self.review_checkbox.setChecked(False)
            finally:
                self._gate_updating = False
        self.review_checkbox.setEnabled(enabled)
        self.apply_button.setEnabled(enabled and self.review_checkbox.isChecked())

    def _refresh_actions(self) -> None:
        busy = self._busy is not None
        self.back_button.setEnabled(not busy)
        for button in (
            self.scan_button,
            self.report_button,
            self.plan_button,
            self.journal_button,
        ):
            button.setEnabled(not busy)
        self.undo_button.setEnabled(not busy and self._last_run is not None)
        self._refresh_gate()
        if self._journal_dialog is not None:
            self._journal_dialog.set_busy(busy)

    # -- feedback -----------------------------------------------------------

    def _set_status(
        self,
        key: str | None,
        *,
        extra: tuple[str, dict[str, object]] | None = None,
        **args: object,
    ) -> None:
        """Remember a status key (plus one appended key) for retranslation."""
        self._status_key = key
        self._status_args = dict(args)
        self._status_extra_key = extra[0] if extra else None
        self._status_extra_args = dict(extra[1]) if extra else {}

    def _set_error(self, key: str | None, **args: object) -> None:
        self._error_key = key
        self._error_args = dict(args)

    def _sync_feedback(self) -> None:
        t = self._translator.t
        status = (
            t(self._status_key, **self._status_args) if self._status_key else ""
        )
        if self._status_extra_key:
            status = " ".join(
                part
                for part in (
                    status,
                    t(self._status_extra_key, **self._status_extra_args),
                )
                if part
            )
        self.status_label.setText(status)
        self.status_label.setVisible(bool(status))
        error = t(self._error_key, **self._error_args) if self._error_key else ""
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))

    # -- layout -------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        body = QWidget(self.scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(12)

        self.title_label = QLabel(body)
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)
        self.subtitle_label = QLabel(body)
        self.subtitle_label.setObjectName("subtitle")
        self.subtitle_label.setWordWrap(True)

        self.scan_button = QPushButton(body)
        self.scan_button.setObjectName("secondary")
        self.scan_button.setMinimumWidth(150)
        self.scan_button.clicked.connect(lambda: self.start_scan(SCAN_DAYS))
        self.report_button = QPushButton(body)
        self.report_button.setObjectName("secondary")
        self.report_button.setMinimumWidth(150)
        self.report_button.clicked.connect(lambda: self.start_report(REPORT_TOP))
        self.plan_button = QPushButton(body)
        self.plan_button.setObjectName("primary")
        self.plan_button.setMinimumWidth(150)
        self.plan_button.clicked.connect(lambda: self.start_plan())
        self.journal_button = QPushButton(body)
        self.journal_button.setObjectName("secondary")
        self.journal_button.setMinimumWidth(150)
        self.journal_button.clicked.connect(self.load_journal)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.scan_button)
        actions.addWidget(self.report_button)
        actions.addWidget(self.plan_button)
        actions.addWidget(self.journal_button)
        actions.addStretch(1)

        self.status_label = QLabel(body)
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)

        self.error_label = QLabel(body)
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)

        self.scan_total_title, self.scan_total_label = self._stat_card(body)
        self.scan_categories_title, self.scan_categories_label = self._stat_card(body)
        self.scan_mailboxes_title, self.scan_mailboxes_label = self._stat_card(body)
        scan_cards = QHBoxLayout()
        scan_cards.setContentsMargins(0, 0, 0, 0)
        scan_cards.setSpacing(12)
        for title, value in (
            (self.scan_total_title, self.scan_total_label),
            (self.scan_categories_title, self.scan_categories_label),
            (self.scan_mailboxes_title, self.scan_mailboxes_label),
        ):
            scan_cards.addWidget(self._card(body, title, value), 1)

        self.report_group = QGroupBox(body)
        report_layout = QVBoxLayout(self.report_group)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(8)
        self.report_total_title, self.report_total_label = self._stat_card(
            self.report_group
        )
        self.report_groups_title, self.report_groups_label = self._stat_card(
            self.report_group
        )
        self.report_protected_title, self.report_protected_label = self._stat_card(
            self.report_group
        )
        report_cards = QHBoxLayout()
        report_cards.setContentsMargins(0, 0, 0, 0)
        report_cards.setSpacing(12)
        for title, value in (
            (self.report_total_title, self.report_total_label),
            (self.report_groups_title, self.report_groups_label),
            (self.report_protected_title, self.report_protected_label),
        ):
            report_cards.addWidget(self._card(self.report_group, title, value), 1)
        self.report_table = self._table(
            self.report_group,
            ("review.plan.category", "review.report.sender", "review.plan.messages",
             "review.report.unread", "review.plan.unsubscribe"),
        )
        report_layout.addLayout(report_cards)
        report_layout.addWidget(self.report_table)

        self.plan_group = QGroupBox(body)
        plan_layout = QVBoxLayout(self.plan_group)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        plan_layout.setSpacing(8)
        self.plan_table = self._table(
            self.plan_group,
            ("review.plan.category", "review.plan.destination", "review.plan.messages",
             "review.plan.unsubscribe"),
        )
        self.plan_summary_label = QLabel(self.plan_group)
        self.plan_summary_label.setObjectName("muted")
        self.plan_summary_label.setWordWrap(True)
        self.plan_note = QLabel(self.plan_group)
        self.plan_note.setObjectName("muted")
        self.plan_note.setWordWrap(True)
        plan_layout.addWidget(self.plan_table)
        plan_layout.addWidget(self.plan_summary_label)
        plan_layout.addWidget(self.plan_note)

        self.review_checkbox = QCheckBox(body)
        self.review_checkbox.setObjectName("reviewGate")
        self.review_checkbox.setChecked(False)
        self.review_checkbox.setEnabled(False)
        self.review_checkbox.toggled.connect(self.review_toggled)

        self.unsubscribe_toggle = QToolButton(body)
        self.unsubscribe_toggle.setCheckable(True)
        self.unsubscribe_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.unsubscribe_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.unsubscribe_toggle.setAutoRaise(True)
        self.unsubscribe_toggle.toggled.connect(self._toggle_unsubscribe)

        self.unsubscribe_panel = QWidget(body)
        unsubscribe_layout = QVBoxLayout(self.unsubscribe_panel)
        unsubscribe_layout.setContentsMargins(0, 0, 0, 0)
        unsubscribe_layout.setSpacing(6)
        self.unsubscribe_warning = QLabel(self.unsubscribe_panel)
        self.unsubscribe_warning.setObjectName("warningPanel")
        self.unsubscribe_warning.setWordWrap(True)
        self.unsubscribe_unavailable = QLabel(self.unsubscribe_panel)
        self.unsubscribe_unavailable.setObjectName("muted")
        self.unsubscribe_unavailable.setWordWrap(True)
        self.unsubscribe_manual = QLabel(self.unsubscribe_panel)
        self.unsubscribe_manual.setObjectName("muted")
        self.unsubscribe_manual.setWordWrap(True)
        self.unsubscribe_spam = QLabel(self.unsubscribe_panel)
        self.unsubscribe_spam.setObjectName("muted")
        self.unsubscribe_spam.setWordWrap(True)
        unsubscribe_layout.addWidget(self.unsubscribe_warning)
        unsubscribe_layout.addWidget(self.unsubscribe_unavailable)
        unsubscribe_layout.addWidget(self.unsubscribe_manual)
        unsubscribe_layout.addWidget(self.unsubscribe_spam)
        self.unsubscribe_panel.setVisible(False)

        self.undo_button = QPushButton(self)
        self.undo_button.setObjectName("secondary")
        self.undo_button.setMinimumWidth(180)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(lambda: self.undo(self._last_run or ""))

        self.apply_button = QPushButton(self)
        self.apply_button.setObjectName("primary")
        self.apply_button.setMinimumWidth(180)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply_clicked)

        self.back_button = QPushButton(self)
        self.back_button.setObjectName("secondary")
        self.back_button.setMinimumWidth(140)
        self.back_button.clicked.connect(self._go_back)

        footer = QHBoxLayout()
        footer.setContentsMargins(32, 12, 32, 24)
        footer.addWidget(self.back_button)
        footer.addStretch(1)
        footer.addWidget(self.undo_button)
        footer.addWidget(self.apply_button)

        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addLayout(actions)
        root.addWidget(self.status_label)
        root.addWidget(self.error_label)
        root.addLayout(scan_cards)
        root.addWidget(self.report_group)
        root.addWidget(self.plan_group)
        root.addWidget(self.review_checkbox)
        root.addWidget(self.unsubscribe_toggle)
        root.addWidget(self.unsubscribe_panel)
        root.addStretch(1)

        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        outer.addLayout(footer)

        self.retranslate()

    def _stat_card(self, parent: QWidget) -> tuple[QLabel, QLabel]:
        title = QLabel(parent)
        title.setObjectName("muted")
        title.setWordWrap(True)
        value = QLabel("0", parent)
        value.setObjectName("section")
        value.setWordWrap(True)
        return title, value

    @staticmethod
    def _card(parent: QWidget, title: QLabel, value: QLabel) -> QFrame:
        """Put one stat's title above its value inside a themed card."""
        card = QFrame(parent)
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(title)
        layout.addWidget(value)
        return card

    def _table(self, parent: QWidget, headers: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setVisible(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(150)
        table.setAccessibleName(
            ", ".join(self._translator.t(key) for key in headers)
        )
        return table

    @staticmethod
    def _set_cell(table: QTableWidget, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, column, item)

    def _toggle_unsubscribe(self, opened: bool) -> None:
        self.unsubscribe_panel.setVisible(opened)
        self.unsubscribe_toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow
        )

    # -- copy ---------------------------------------------------------------

    def retranslate(self) -> None:
        """Refresh every string, including values already rendered."""
        t = self._translator.t

        self.title_label.setText(t("review.title"))
        self.subtitle_label.setText(t("review.subtitle"))
        self.scan_button.setText(t("review.scan"))
        self.report_button.setText(t("review.report.title"))
        self.plan_button.setText(t("review.plan.title"))
        self.report_group.setTitle(t("review.report.title"))
        self.plan_group.setTitle(t("review.plan.title"))

        self.scan_total_title.setText(t("review.scan_total"))
        self.scan_categories_title.setText(t("review.report.categories"))
        self.scan_mailboxes_title.setText(t("review.scan_mailboxes"))
        self.report_total_title.setText(t("review.report.total"))
        self.report_groups_title.setText(t("review.report.groups"))
        self.report_protected_title.setText(t("review.report.protected"))

        for table, keys in (
            (
                self.report_table,
                (
                    "review.plan.category",
                    "review.report.sender",
                    "review.plan.messages",
                    "review.report.unread",
                    "review.plan.unsubscribe",
                ),
            ),
            (
                self.plan_table,
                (
                    "review.plan.category",
                    "review.plan.destination",
                    "review.plan.messages",
                    "review.plan.unsubscribe",
                ),
            ),
        ):
            for column, key in enumerate(keys):
                item = table.horizontalHeaderItem(column)
                if item is None:
                    table.setHorizontalHeaderItem(column, QTableWidgetItem(t(key)))
                else:
                    item.setText(t(key))

        self.plan_note.setText(t("review.plan.protected_note"))
        self.review_checkbox.setText(t("review.reviewed"))
        self.apply_button.setText(t("review.apply"))
        self.journal_button.setText(t("review.journal"))
        self.undo_button.setText(t("review.undo.button"))
        self.back_button.setText(t("common.back"))
        self.unsubscribe_toggle.setText(t("review.unsubscribe.title"))
        self.unsubscribe_warning.setText(t("review.unsubscribe.warning"))
        self.unsubscribe_unavailable.setText(t("review.unsubscribe.unavailable"))
        self.unsubscribe_manual.setText(t("review.unsubscribe.manual_note"))
        self.unsubscribe_spam.setText(t("review.unsubscribe.spam_note"))

        for table, keys in (
            (
                self.report_table,
                (
                    "review.plan.category",
                    "review.report.sender",
                    "review.plan.messages",
                    "review.report.unread",
                    "review.plan.unsubscribe",
                ),
            ),
            (
                self.plan_table,
                (
                    "review.plan.category",
                    "review.plan.destination",
                    "review.plan.messages",
                    "review.plan.unsubscribe",
                ),
            ),
        ):
            table.setAccessibleName(", ".join(t(key) for key in keys))

        # Rendered values carry translated category names and modes.
        if self._scan is not None:
            self.scan_categories_label.setText(
                self._category_counts(self._scan.get("categories"))
            )
        if self._report is not None:
            self._render_report(self._report)
        if self._plan is not None:
            self._render_plan()
        if self._journal_dialog is not None:
            self._journal_dialog.retranslate()
        self._sync_feedback()

    def _category_label(self, category: str) -> str:
        if not category:
            return ""
        key = f"preferences.category.{category}.label"
        text = self._translator.t(key)
        return text if text != key else category

    def _category_counts(self, categories: object) -> str:
        if not isinstance(categories, Mapping) or not categories:
            return self._translator.t("review.plan.unsubscribe_none")
        parts: list[str] = []
        seen: set[str] = set()
        for category in CATEGORIES:
            if category in categories:
                seen.add(category)
                parts.append(
                    f"{self._category_label(category)} {self._int(categories[category])}"
                )
        for category, count in categories.items():
            if isinstance(category, str) and category not in seen:
                parts.append(f"{self._category_label(category)} {self._int(count)}")
        return ", ".join(parts)

    def _unsubscribe_label(self, modes: object) -> str:
        if isinstance(modes, str):
            modes = (modes,) if modes else ()
        labels: list[str] = []
        for mode in modes or ():
            if not isinstance(mode, str) or not mode:
                continue
            key = _UNSUBSCRIBE_KEYS.get(mode, "review.plan.unsubscribe_manual")
            label = self._translator.t(key)
            if label not in labels:
                labels.append(label)
        if not labels:
            return self._translator.t("review.plan.unsubscribe_none")
        return ", ".join(labels)
