"""The fourth wizard page: scan, report, plan, apply, journal and undo.

The page is a *view* of the sidecar and a three-step sub-wizard. Only one step
is visible at a time: scan, report and plan, in that order. A completed step
keeps its result and Back returns to it without rebuilding anything. Plan cards
name the destination, sender, subject and date of each action's own UIDs; a
group without an action, or a protected group, is never rendered.

The page never implements IMAP, classification, planning, moves or undo; it
asks ``CliClient`` for ``scan``, ``report``, ``plan``, ``apply``, ``journal``
and ``undo`` in worker threads and renders the JSON. No mailbox change happens
before the person reviews the plan and confirms the apply dialog, and only the
sidecar touches a mailbox.

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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.models import CATEGORIES, Preferences
from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.ui.style import set_dynamic_property

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


class _StepStack(QStackedWidget):
    """A stack that reserves height only for the visible step.

    ``QStackedWidget`` reports the largest size hint of every page. A long
    plan would then leave blank space under the scan step, so the step stack
    asks the current page instead; ``show_step`` calls ``updateGeometry``.
    """

    def sizeHint(self):  # noqa: N802 - Qt's naming
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 - Qt's naming
        current = self.currentWidget()
        return (
            current.minimumSizeHint()
            if current is not None
            else super().minimumSizeHint()
        )


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
    """A three-step review wizard around the sidecar's scan, report and plan."""

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
        self._step = 0
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
        """Forget every answer and return to the scan step.

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
        self.show_step(0)
        self.scroll.verticalScrollBar().setValue(0)
        self._sync_feedback()

    def _reset_answers(self) -> None:
        """Blank the scan, report and plan; a new scan makes them all stale."""
        self._clear_scan()
        self._clear_report()
        self._clear_plan()

    def is_busy(self) -> bool:
        """Whether a sidecar command is in flight."""
        return self._busy is not None

    def current_step(self) -> int:
        """The visible step: 0 scan, 1 report, 2 plan."""
        return self._step

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

    # -- step navigation ----------------------------------------------------

    def show_step(self, index: int) -> None:
        """Show one step; 0 scan, 1 report, 2 plan."""
        index = max(0, min(2, int(index)))
        changed = index != self._step
        self._step = index
        self.step_stack.setCurrentIndex(index)
        self.step_stack.updateGeometry()
        self._update_step_bar()
        self.step_back_button.setVisible(index > 0)
        self.apply_button.setVisible(index == 2)
        self.undo_button.setVisible(index == 2)
        self._refresh_actions()
        if changed:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.minimum())

    def _continue_from_scan(self) -> None:
        if self._busy is None and self._scan is not None:
            self.show_step(1)

    def _continue_from_report(self) -> None:
        if self._busy is None and self._report is not None:
            self.show_step(2)

    def _step_back(self) -> None:
        if self._busy is None and self._step > 0:
            self.show_step(self._step - 1)

    def _update_step_bar(self) -> None:
        t = self._translator.t
        keys = (
            "review.wizard.steps.scan",
            "review.wizard.steps.report",
            "review.wizard.steps.plan",
        )
        for index, label in enumerate(self.wizard_step_labels):
            text = t(keys[index])
            label.setText(text)
            active = index == self._step
            done = index < self._step
            set_dynamic_property(label, "active", active)
            set_dynamic_property(label, "done", done)
            label.setAccessibleName(
                t("review.wizard.done_summary", summary=text)
                if done
                else t("review.wizard.step_of", current=index + 1, total=3)
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
                self.show_step(0)
            elif action == "report":
                # A report built from new headers invalidates the old plan.
                self._clear_plan()
                self.show_step(1)
            elif action == "plan":
                self.show_step(2)
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
            self._clear_scan()
        elif action == "report":
            self._clear_report()
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

    # -- rendering ----------------------------------------------------------

    def set_scan(self, result: object) -> None:
        """Render a ``scan --json`` payload (raw result or bare payload)."""
        self._scan = self._payload(result)
        payload = self._scan
        total = self._int(payload.get("total"))
        categories = payload.get("categories")
        self.scan_total_label.setText(str(total))
        self.scan_mailboxes_label.setText(str(len(payload.get("mailboxes") or {})))
        self.scan_categories_label.setText(self._category_counts(categories))
        self.scan_result_label.setText(
            self._translator.t(
                "review.wizard.scan.result",
                messages=total,
                categories=self._category_count(categories),
            )
        )
        self.scan_result.setVisible(True)
        self.scan_continue_button.setVisible(True)
        # A fresh scan invalidates the old report and plan.
        self._clear_report()
        self._clear_plan()
        self.show_step(0)
        self._set_error(None)
        self._set_status("review.scan_done" if total else "review.scan_empty")
        self._refresh_actions()
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
        protected = self._int(totals.get("protected"))
        self.report_total_label.setText(str(messages))
        self.report_groups_label.setText(str(groups))
        self.report_protected_label.setText(str(protected))
        self.report_result_label.setText(
            self._translator.t(
                "review.wizard.report.result",
                messages=messages,
                groups=groups,
                protected=protected,
            )
        )
        self._render_report(payload)
        self.report_result.setVisible(True)
        self.report_continue_button.setVisible(True)
        # A fresh report invalidates the old plan but keeps the scan.
        self._clear_plan()
        self.show_step(1)
        self._set_error(None)
        self._set_status("review.report.done")
        self._refresh_actions()
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
        self.show_step(2)
        self._set_error(None)
        self._set_status(
            "review.plan.done" if self.plan_move_count() else "review.zero_moves"
        )
        self._refresh_actions()
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
        self._clear_layout(self.report_cards_layout)
        groups = payload.get("groups") or []
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            if self.report_cards_layout.count() >= self._report_top:
                break
            self.report_cards_layout.addWidget(self._report_card(group))

    def _report_card(self, group: Mapping[str, Any]) -> QFrame:
        t = self._translator.t
        card, layout = self._card_frame(self.report_cards)
        card.setProperty("kind", "reportCard")
        domain = str(group.get("domain") or group.get("key") or "")
        category = self._category_label(str(group.get("category") or ""))
        count = self._int(group.get("count"))
        unread = self._int(group.get("unread"))
        layout.addWidget(
            self._wrapped_label(card, domain or t("common.unknown"), "section")
        )
        meta = " · ".join(
            part
            for part in (
                category,
                t("review.wizard.report.group", count=count, unread=unread),
            )
            if part
        )
        layout.addWidget(self._wrapped_label(card, meta, "muted"))

        samples: list[str] = []
        raw_samples = group.get("samples")
        if not isinstance(raw_samples, list):
            raw_samples = group.get("subjects")
        if isinstance(raw_samples, list):
            for sample in raw_samples:
                if isinstance(sample, str) and sample.strip():
                    samples.append(sample)
                if len(samples) == 3:
                    break
        for sample in samples:
            layout.addWidget(self._wrapped_label(card, f"· {sample}"))
        if not samples:
            layout.addWidget(
                self._wrapped_label(card, t("review.wizard.report.no_samples"), "muted")
            )
        remaining = max(0, count - len(samples))
        if samples and remaining:
            layout.addWidget(
                self._wrapped_label(
                    card,
                    t("review.wizard.plan.more", count=remaining),
                    "muted",
                )
            )

        unsubscribe = group.get("unsubscribe")
        mode = ""
        if isinstance(unsubscribe, Mapping):
            mode = str(unsubscribe.get("mode") or "")
        if mode:
            layout.addWidget(
                self._wrapped_label(
                    card,
                    t("review.wizard.plan.unsubscribe", modes=self._unsubscribe_label(mode)),
                    "muted",
                )
            )
        return card

    def _render_plan(self) -> None:
        self._clear_layout(self.plan_cards_layout)
        rows = self._plan_rows()
        for row in rows:
            self.plan_cards_layout.addWidget(self._plan_card(row))

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
        self.plan_result.setVisible(self._plan is not None)
        self._refresh_gate()

    def _plan_card(self, row: Mapping[str, Any]) -> QFrame:
        t = self._translator.t
        card, layout = self._card_frame(self.plan_cards)
        card.setProperty("kind", "planCard")
        layout.addWidget(
            self._wrapped_label(card, str(row["destination"]), "section")
        )
        category = self._category_label(str(row["category"]))
        meta: list[str] = []
        if category:
            meta.append(category)
        messages = self._int(row.get("messages"))
        if messages:
            meta.append(self._count_line(messages, str(row.get("sender") or "")))
        if meta:
            layout.addWidget(self._wrapped_label(card, " · ".join(meta), "muted"))

        items = row.get("items") or []
        for item in items:
            layout.addWidget(self._message_label(card, item))
        if messages and not items:
            layout.addWidget(
                self._wrapped_label(card, t("review.wizard.plan.no_preview"), "muted")
            )
        remaining = self._int(row.get("more"))
        if remaining:
            layout.addWidget(
                self._wrapped_label(
                    card,
                    t("review.wizard.plan.more", count=remaining),
                    "muted",
                )
            )
        modes = row.get("modes") or []
        if modes:
            layout.addWidget(
                self._wrapped_label(
                    card,
                    t("review.wizard.plan.unsubscribe", modes=self._unsubscribe_label(modes)),
                    "muted",
                )
            )
        return card

    def _message_label(self, parent: QWidget, item: Mapping[str, Any]) -> QLabel:
        t = self._translator.t
        sender = str(item.get("sender") or "")
        name = str(item.get("name") or "")
        if name and sender and name != sender:
            sender_line = f"{name} <{sender}>"
        else:
            sender_line = name or sender or t("common.unknown")
        subject = str(item.get("subject") or "") or t("review.wizard.plan.no_subject")
        date = self._display_date(item.get("date"))
        parts = [sender_line, f"· {subject}"]
        if date:
            parts.append(date)
        label = self._wrapped_label(parent, "\n".join(parts))
        label.setObjectName("messagePreview")
        return label

    def _plan_rows(self) -> list[dict[str, Any]]:
        """One destination card per category/destination, with action previews."""
        moves: dict[tuple[str, str], dict[str, Any]] = {}
        unsubscribe: dict[str, set[str]] = {}
        for action in (self._plan or {}).get("actions") or []:
            if not isinstance(action, Mapping):
                continue
            category = str(action.get("category") or "")
            if action.get("type") == "move":
                destination = str(action.get("dest") or "")
                key = (category, destination)
                row = moves.get(key)
                if row is None:
                    row = {
                        "category": category,
                        "destination": destination,
                        "uids": set(),
                        "items": [],
                        "more": 0,
                        "domains": [],
                        "modes": [],
                    }
                    moves[key] = row
                mailbox = str(action.get("mailbox") or "")
                raw_uids = action.get("uids")
                uids = (
                    [
                        uid
                        for uid in raw_uids
                        if isinstance(uid, int) and not isinstance(uid, bool)
                    ]
                    if isinstance(raw_uids, (list, tuple))
                    else []
                )
                for uid in uids:
                    row["uids"].add((mailbox, uid))
                group = self._plan_group(action.get("group"))
                items, more, domain = self._plan_previews(group, mailbox, uids)
                seen = {(str(item.get("mailbox") or ""), item.get("uid")) for item in row["items"]}
                for item in items:
                    identity = (str(item.get("mailbox") or ""), item.get("uid"))
                    if item.get("uid") is None:
                        identity = ("sample", str(item.get("subject") or ""))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    row["items"].append(item)
                row["more"] += more
                if domain and domain not in row["domains"]:
                    row["domains"].append(domain)
            elif action.get("type") == "unsubscribe":
                mode = str(action.get("mode") or "")
                if mode:
                    unsubscribe.setdefault(category, set()).add(mode)

        for (category, _destination), row in moves.items():
            row["modes"] = sorted(unsubscribe.get(category, ()))
        moved_categories = {category for category, _ in moves}
        for category, modes in unsubscribe.items():
            if category in moved_categories:
                continue
            moves[(category, "")] = {
                "category": category,
                "destination": "",
                "uids": set(),
                "items": [],
                "more": 0,
                "domains": [],
                "modes": sorted(modes),
            }

        no_destination = self._translator.t("review.plan.no_destination")
        rows: list[dict[str, Any]] = []
        for row in moves.values():
            rows.append(
                {
                    "category": row["category"],
                    "destination": row["destination"] or no_destination,
                    "sender": ", ".join(row["domains"]),
                    "messages": len(row["uids"]),
                    "items": row["items"],
                    "more": row["more"],
                    "modes": row["modes"],
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

    def _plan_group(self, key: object) -> Mapping[str, Any]:
        if not isinstance(key, str) or not key:
            return {}
        for group in (self._plan or {}).get("groups") or []:
            if not isinstance(group, Mapping):
                continue
            if any(group.get(field) == key for field in ("key", "group", "id")):
                return group
        return {}

    def _plan_previews(
        self,
        group: Mapping[str, Any],
        mailbox: str,
        uids: list[int],
    ) -> tuple[list[dict[str, Any]], int, str]:
        """The previews this action may show, plus how many UIDs lack one."""
        uid_set = set(uids)
        if not group:
            return [], len(uid_set), ""
        domain = str(group.get("domain") or "")
        raw = group.get("messages")
        items: list[dict[str, Any]] = []
        if isinstance(raw, list):
            seen: set[int] = set()
            for preview in raw:
                if not isinstance(preview, Mapping):
                    continue
                if mailbox and str(preview.get("mailbox") or "") != mailbox:
                    continue
                uid = preview.get("uid")
                if isinstance(uid, bool) or not isinstance(uid, int):
                    continue
                if uid not in uid_set or uid in seen:
                    continue
                seen.add(uid)
                items.append(self._preview(preview))
            more = max(0, len(uid_set) - len(items))
        else:
            # A 1.2.2-style plan has no messages; subjects are still useful.
            samples = group.get("samples")
            if isinstance(samples, list):
                for sample in samples:
                    if isinstance(sample, str) and sample.strip():
                        items.append(self._preview({"subject": sample}))
            more = max(0, len(uid_set) - len(items))
        if not domain and items:
            domain = self._sender_domain(items[0].get("sender"))
        return items, more, domain

    @staticmethod
    def _preview(preview: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "uid": preview.get("uid"),
            "mailbox": str(preview.get("mailbox") or ""),
            "sender": str(preview.get("sender") or ""),
            "name": str(preview.get("name") or ""),
            "subject": str(preview.get("subject") or ""),
            "date": str(preview.get("date") or ""),
        }

    @staticmethod
    def _sender_domain(sender: object) -> str:
        text = str(sender or "").strip()
        if "@" not in text:
            return text
        return text.rsplit("@", 1)[-1].lower()

    @staticmethod
    def _display_date(value: object) -> str:
        text = str(value or "")
        if "T" in text:
            text = text.replace("T", " ", 1)
        return text[:16]

    def _count_line(self, count: int, sender: str) -> str:
        key = (
            "review.wizard.plan.count_one"
            if count == 1
            else "review.wizard.plan.count_many"
        )
        return self._translator.t(
            key, count=count, sender=sender or self._translator.t("common.unknown")
        )

    def _clear_scan(self) -> None:
        self._scan = None
        self.scan_total_label.setText("0")
        self.scan_categories_label.setText(
            self._translator.t("review.plan.unsubscribe_none")
        )
        self.scan_mailboxes_label.setText("0")
        self.scan_result_label.setText("")
        self.scan_result.setVisible(False)
        self.scan_continue_button.setVisible(False)

    def _clear_report(self) -> None:
        self._report = None
        self.report_total_label.setText("0")
        self.report_groups_label.setText("0")
        self.report_protected_label.setText("0")
        self.report_result_label.setText("")
        self._clear_layout(self.report_cards_layout)
        self.report_result.setVisible(False)
        self.report_continue_button.setVisible(False)

    def _clear_plan(self) -> None:
        self._plan = None
        self._plan_path = None
        self._applied = False
        self._clear_layout(self.plan_cards_layout)
        self.plan_summary_label.setText("")
        self.plan_note.setVisible(False)
        self.plan_result.setVisible(False)
        self._refresh_gate()

    # -- gate ---------------------------------------------------------------

    def review_toggled(self, checked: bool) -> None:
        """Recompute Apply from the checkbox; a disabled gate stays closed."""
        if self._gate_updating:
            return
        self._refresh_gate()

    def _refresh_gate(self) -> None:
        moves = self.plan_move_count()
        enabled = not self._applied and moves > 0 and self._busy is None
        if not enabled and self.review_checkbox.isChecked():
            self._gate_updating = True
            try:
                self.review_checkbox.setChecked(False)
            finally:
                self._gate_updating = False
        self.review_checkbox.setEnabled(enabled)
        self.apply_button.setEnabled(enabled and self.review_checkbox.isChecked())
        self.apply_button.setText(
            self._translator.t("review.apply_count", count=moves)
            if moves
            else self._translator.t("review.apply")
        )

    def _refresh_actions(self) -> None:
        busy = self._busy is not None
        self.back_button.setEnabled(not busy)
        self.step_back_button.setEnabled(not busy and self._step > 0)
        self.scan_continue_button.setEnabled(not busy and self._scan is not None)
        self.report_continue_button.setEnabled(not busy and self._report is not None)
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

        self.step_bar = QWidget(body)
        bar = QHBoxLayout(self.step_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        self.wizard_step_labels: list[QLabel] = []
        for index in range(3):
            if index:
                dot = QLabel("·", self.step_bar)
                dot.setObjectName("muted")
                bar.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            label = QLabel(self.step_bar)
            label.setObjectName("step")
            label.setProperty("active", False)
            label.setProperty("done", False)
            self.wizard_step_labels.append(label)
            bar.addWidget(label)
        bar.addStretch(1)

        self.status_label = QLabel(body)
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)

        self.error_label = QLabel(body)
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)

        self.step_stack = _StepStack(body)
        self.scan_step = self._build_scan_step(self.step_stack)
        self.report_step = self._build_report_step(self.step_stack)
        self.plan_step = self._build_plan_step(self.step_stack)
        self.step_stack.addWidget(self.scan_step)
        self.step_stack.addWidget(self.report_step)
        self.step_stack.addWidget(self.plan_step)

        self.undo_button = QPushButton(self)
        self.undo_button.setObjectName("secondary")
        self.undo_button.setMinimumWidth(180)
        self.undo_button.setEnabled(False)
        self.undo_button.setVisible(False)
        self.undo_button.clicked.connect(lambda: self.undo(self._last_run or ""))

        self.apply_button = QPushButton(self)
        self.apply_button.setObjectName("primary")
        self.apply_button.setMinimumWidth(180)
        self.apply_button.setEnabled(False)
        self.apply_button.setVisible(False)
        self.apply_button.clicked.connect(self._apply_clicked)

        self.journal_button = QPushButton(self)
        self.journal_button.setObjectName("secondary")
        self.journal_button.setMinimumWidth(150)
        self.journal_button.clicked.connect(self.load_journal)

        self.back_button = QPushButton(self)
        self.back_button.setObjectName("secondary")
        self.back_button.setMinimumWidth(180)
        self.back_button.clicked.connect(self._go_back)

        self.step_back_button = QPushButton(self)
        self.step_back_button.setObjectName("secondary")
        self.step_back_button.setMinimumWidth(120)
        self.step_back_button.setVisible(False)
        self.step_back_button.clicked.connect(self._step_back)

        footer = QHBoxLayout()
        footer.setContentsMargins(32, 12, 32, 24)
        footer.addWidget(self.back_button)
        footer.addWidget(self.step_back_button)
        footer.addStretch(1)
        footer.addWidget(self.journal_button)
        footer.addWidget(self.undo_button)
        footer.addWidget(self.apply_button)

        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)
        root.addWidget(self.step_bar)
        root.addWidget(self.status_label)
        root.addWidget(self.error_label)
        root.addWidget(self.step_stack)
        root.addStretch(1)

        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        outer.addLayout(footer)

        self.retranslate()

    def _build_scan_step(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.scan_title_label = self._wrapped_label(panel, "", "stepTitle")
        self.scan_body_label = self._wrapped_label(panel, "", "muted")
        layout.addWidget(self.scan_title_label)
        layout.addWidget(self.scan_body_label)

        self.scan_button = QPushButton(panel)
        self.scan_button.setObjectName("primary")
        self.scan_button.setMinimumWidth(180)
        self.scan_button.clicked.connect(lambda: self.start_scan(SCAN_DAYS))
        self.scan_continue_button = QPushButton(panel)
        self.scan_continue_button.setObjectName("secondary")
        self.scan_continue_button.setMinimumWidth(190)
        self.scan_continue_button.setVisible(False)
        self.scan_continue_button.clicked.connect(self._continue_from_scan)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.scan_button)
        actions.addStretch(1)
        actions.addWidget(self.scan_continue_button)
        layout.addLayout(actions)

        self.scan_result = QWidget(panel)
        result_layout = QVBoxLayout(self.scan_result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(10)
        self.scan_result_label = self._wrapped_label(self.scan_result, "")

        self.scan_total_title, self.scan_total_label = self._stat_card(self.scan_result)
        self.scan_categories_title, self.scan_categories_label = self._stat_card(
            self.scan_result
        )
        self.scan_mailboxes_title, self.scan_mailboxes_label = self._stat_card(
            self.scan_result
        )
        cards = QHBoxLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(12)
        for title, value in (
            (self.scan_total_title, self.scan_total_label),
            (self.scan_categories_title, self.scan_categories_label),
            (self.scan_mailboxes_title, self.scan_mailboxes_label),
        ):
            cards.addWidget(self._card(self.scan_result, title, value), 1)

        result_layout.addWidget(self.scan_result_label)
        result_layout.addLayout(cards)
        self.scan_result.setVisible(False)
        layout.addWidget(self.scan_result)
        return panel

    def _build_report_step(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.report_title_label = self._wrapped_label(panel, "", "stepTitle")
        self.report_body_label = self._wrapped_label(panel, "", "muted")
        layout.addWidget(self.report_title_label)
        layout.addWidget(self.report_body_label)

        self.report_button = QPushButton(panel)
        self.report_button.setObjectName("primary")
        self.report_button.setMinimumWidth(180)
        self.report_button.clicked.connect(lambda: self.start_report(REPORT_TOP))
        self.report_continue_button = QPushButton(panel)
        self.report_continue_button.setObjectName("secondary")
        self.report_continue_button.setMinimumWidth(180)
        self.report_continue_button.setVisible(False)
        self.report_continue_button.clicked.connect(self._continue_from_report)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.report_button)
        actions.addStretch(1)
        actions.addWidget(self.report_continue_button)
        layout.addLayout(actions)

        self.report_result = QWidget(panel)
        result_layout = QVBoxLayout(self.report_result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(10)
        self.report_result_label = self._wrapped_label(self.report_result, "")

        self.report_total_title, self.report_total_label = self._stat_card(
            self.report_result
        )
        self.report_groups_title, self.report_groups_label = self._stat_card(
            self.report_result
        )
        self.report_protected_title, self.report_protected_label = self._stat_card(
            self.report_result
        )
        cards = QHBoxLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(12)
        for title, value in (
            (self.report_total_title, self.report_total_label),
            (self.report_groups_title, self.report_groups_label),
            (self.report_protected_title, self.report_protected_label),
        ):
            cards.addWidget(self._card(self.report_result, title, value), 1)

        self.report_cards = QWidget(self.report_result)
        self.report_cards_layout = QVBoxLayout(self.report_cards)
        self.report_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.report_cards_layout.setSpacing(8)

        result_layout.addWidget(self.report_result_label)
        result_layout.addLayout(cards)
        result_layout.addWidget(self.report_cards)
        self.report_result.setVisible(False)
        layout.addWidget(self.report_result)
        return panel

    def _build_plan_step(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.plan_title_label = self._wrapped_label(panel, "", "stepTitle")
        self.plan_body_label = self._wrapped_label(panel, "", "muted")
        layout.addWidget(self.plan_title_label)
        layout.addWidget(self.plan_body_label)

        self.plan_button = QPushButton(panel)
        self.plan_button.setObjectName("primary")
        self.plan_button.setMinimumWidth(180)
        self.plan_button.clicked.connect(lambda: self.start_plan())
        self.plan_step_button = self.plan_button

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.plan_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.plan_result = QWidget(panel)
        result_layout = QVBoxLayout(self.plan_result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(8)
        self.plan_summary_label = self._wrapped_label(self.plan_result, "", "muted")
        self.plan_note = self._wrapped_label(self.plan_result, "", "muted")
        self.plan_note.setVisible(False)
        self.plan_cards = QWidget(self.plan_result)
        self.plan_cards_layout = QVBoxLayout(self.plan_cards)
        self.plan_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.plan_cards_layout.setSpacing(8)

        result_layout.addWidget(self.plan_summary_label)
        result_layout.addWidget(self.plan_cards)
        result_layout.addWidget(self.plan_note)
        self.plan_result.setVisible(False)
        layout.addWidget(self.plan_result)

        self.review_checkbox = QCheckBox(panel)
        self.review_checkbox.setObjectName("reviewGate")
        self.review_checkbox.setChecked(False)
        self.review_checkbox.setEnabled(False)
        self.review_checkbox.toggled.connect(self.review_toggled)
        layout.addWidget(self.review_checkbox)

        self.unsubscribe_toggle = QToolButton(panel)
        self.unsubscribe_toggle.setCheckable(True)
        self.unsubscribe_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.unsubscribe_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.unsubscribe_toggle.setAutoRaise(True)
        self.unsubscribe_toggle.toggled.connect(self._toggle_unsubscribe)

        self.unsubscribe_panel = QWidget(panel)
        unsubscribe_layout = QVBoxLayout(self.unsubscribe_panel)
        unsubscribe_layout.setContentsMargins(0, 0, 0, 0)
        unsubscribe_layout.setSpacing(6)
        self.unsubscribe_warning = self._wrapped_label(
            self.unsubscribe_panel, "", "warningPanel"
        )
        self.unsubscribe_unavailable = self._wrapped_label(
            self.unsubscribe_panel, "", "muted"
        )
        self.unsubscribe_manual = self._wrapped_label(
            self.unsubscribe_panel, "", "muted"
        )
        self.unsubscribe_spam = self._wrapped_label(
            self.unsubscribe_panel, "", "muted"
        )
        unsubscribe_layout.addWidget(self.unsubscribe_warning)
        unsubscribe_layout.addWidget(self.unsubscribe_unavailable)
        unsubscribe_layout.addWidget(self.unsubscribe_manual)
        unsubscribe_layout.addWidget(self.unsubscribe_spam)
        self.unsubscribe_panel.setVisible(False)

        layout.addWidget(self.unsubscribe_toggle)
        layout.addWidget(self.unsubscribe_panel)
        return panel

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

    def _card_frame(self, parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(parent)
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        return card, layout

    @staticmethod
    def _wrapped_label(parent: QWidget, text: str, name: str = "") -> QLabel:
        label = QLabel(parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        if name:
            label.setObjectName(name)
        label.setText(text)
        return label

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

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
        self.scan_title_label.setText(t("review.wizard.scan.title"))
        self.scan_body_label.setText(t("review.wizard.scan.body"))
        self.report_title_label.setText(t("review.wizard.report.title"))
        self.report_body_label.setText(t("review.wizard.report.body"))
        self.plan_title_label.setText(t("review.wizard.plan.title"))
        self.plan_body_label.setText(t("review.wizard.plan.body"))
        self.scan_button.setText(t("review.wizard.scan.action"))
        self.report_button.setText(t("review.wizard.report.action"))
        self.plan_button.setText(t("review.wizard.plan.action"))
        self.scan_continue_button.setText(t("review.wizard.scan.continue"))
        self.report_continue_button.setText(t("review.wizard.report.continue"))
        self.step_back_button.setText(t("review.wizard.back"))
        self.back_button.setText(t("review.wizard.leave"))
        self._update_step_bar()

        self.scan_total_title.setText(t("review.scan_total"))
        self.scan_categories_title.setText(t("review.report.categories"))
        self.scan_mailboxes_title.setText(t("review.scan_mailboxes"))
        self.report_total_title.setText(t("review.report.total"))
        self.report_groups_title.setText(t("review.report.groups"))
        self.report_protected_title.setText(t("review.report.protected"))

        self.plan_note.setText(t("review.plan.protected_note"))
        self.review_checkbox.setText(t("review.reviewed"))
        self.journal_button.setText(t("review.journal"))
        self.undo_button.setText(t("review.undo.button"))
        self.unsubscribe_toggle.setText(t("review.unsubscribe.title"))
        self.unsubscribe_warning.setText(t("review.unsubscribe.warning"))
        self.unsubscribe_unavailable.setText(t("review.unsubscribe.unavailable"))
        self.unsubscribe_manual.setText(t("review.unsubscribe.manual_note"))
        self.unsubscribe_spam.setText(t("review.unsubscribe.spam_note"))

        # Rendered values carry translated category names and modes.
        if self._scan is not None:
            categories = self._scan.get("categories")
            self.scan_categories_label.setText(self._category_counts(categories))
            self.scan_result_label.setText(
                t(
                    "review.wizard.scan.result",
                    messages=self._int(self._scan.get("total")),
                    categories=self._category_count(categories),
                )
            )
        if self._report is not None:
            totals = self._report.get("totals")
            if not isinstance(totals, Mapping):
                totals = {}
            messages = self._int(
                totals.get("messages"), self._int(self._report.get("cached"))
            )
            groups = totals.get("groups")
            if not isinstance(groups, int):
                groups = len(self._report.get("groups") or [])
            protected = self._int(totals.get("protected"))
            self.report_result_label.setText(
                t(
                    "review.wizard.report.result",
                    messages=messages,
                    groups=groups,
                    protected=protected,
                )
            )
            self._render_report(self._report)
        if self._plan is not None:
            self._render_plan()
        else:
            self._refresh_gate()
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

    @staticmethod
    def _category_count(categories: object) -> int:
        if not isinstance(categories, Mapping):
            return 0
        return len(categories)

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
