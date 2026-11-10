"""The fourth wizard page: scan, report and a plan to review.

The page is a *view* of the sidecar's dry run. It never implements IMAP,
classification or planning; it asks ``CliClient`` for ``scan``, ``report`` and
``plan`` in worker threads and renders the JSON into three stat cards and two
tables. Nothing here changes a mailbox: the Review page stops at the gate, and
apply, the journal and unsubscribe arrive with a later task.

Filing is the decisions the person made on the Preferences page: the plan call
receives the stored ``categories`` and ``mode`` (``folders`` or ``archive``)
verbatim, so the app cannot silently plan something else. The review checkbox
is enabled only by a plan with at least one move, and Apply follows that
checkbox; a zero-move or unsubscribe-only plan keeps Apply disabled because
there is nothing to review and move.

Language is a window-level concern: payloads are kept so ``retranslate`` can
re-render category names and unsubscribe modes in the new catalog without
asking the sidecar again. A plan is cleared whenever a new scan starts or a
new plan fails, and every error is localized copy, never the sidecar's raw
output.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cleanyourmail_app.domain.models import CATEGORIES, Preferences
from cleanyourmail_app.services.app_services import AppServices

#: The app has no scan-window preference; one year is the documented default.
SCAN_DAYS = 365

#: How many sender groups the report shows, matching the CLI's own default.
REPORT_TOP = 30

#: Localized status and error keys per command.
_RUNNING_KEYS = {
    "scan": "review.scanning",
    "report": "review.report.running",
    "plan": "review.plan.running",
}
_ERROR_KEYS = {
    "scan": "errors.scan",
    "report": "errors.report",
    "plan": "errors.plan",
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


class ReviewPage(QWidget):
    """Scan cards, a report table, a plan table and the review gate."""

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
        self._error_key: str | None = None
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
        self._status_key = None
        self._error_key = None
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

    def _start(self, action: str, work: object) -> None:
        if self._busy is not None:
            return
        self._token += 1
        self._busy = action
        self._error_key = None
        if action == "scan":
            # New headers make every old answer stale, including a plan whose
            # UIDs the cache may have pruned. Re-plan before applying.
            self._reset_answers()
        self._status_key = _RUNNING_KEYS[action]
        self._refresh_actions()
        self._sync_feedback()
        self._pool.start(_CommandJob(action, work, self._token, self._signals))

    def _on_finished(self, action: str, token: int, result: object) -> None:
        if token != self._token:
            return
        self._busy = None
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
        except Exception:
            # A malformed payload is a failed command, not a page crash; the
            # person gets the same localized copy as any other failure.
            self._fail(action)

    def _on_failed(self, action: str, token: int) -> None:
        if token != self._token:
            return
        self._busy = None
        self._refresh_actions()
        self._fail(action)

    def _fail(self, action: str) -> None:
        """Close the gate, drop the failed answer and show localized copy."""
        self._status_key = None
        self._error_key = _ERROR_KEYS[action]
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
        self._sync_feedback()

    def _clear_plan(self) -> None:
        self._plan = None
        self._plan_path = None
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
        self._error_key = None
        self._status_key = "review.scan_done" if total else "review.scan_empty"
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
        self._error_key = None
        self._status_key = "review.report.done"
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
        self._render_plan()
        self._error_key = None
        self._status_key = (
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
        enabled = self.plan_move_count() > 0 and self._busy is None
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
        for button in (self.scan_button, self.report_button, self.plan_button):
            button.setEnabled(not busy)
        self._refresh_gate()

    # -- feedback -----------------------------------------------------------

    def _sync_feedback(self) -> None:
        t = self._translator.t
        self.status_label.setText(t(self._status_key) if self._status_key else "")
        self.status_label.setVisible(bool(self._status_key))
        self.error_label.setText(t(self._error_key) if self._error_key else "")
        self.error_label.setVisible(bool(self._error_key))

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

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self.scan_button)
        actions.addWidget(self.report_button)
        actions.addWidget(self.plan_button)
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
        self.unsubscribe_check = QCheckBox(self.unsubscribe_panel)
        self.unsubscribe_check.setChecked(False)
        self.unsubscribe_manual = QLabel(self.unsubscribe_panel)
        self.unsubscribe_manual.setObjectName("muted")
        self.unsubscribe_manual.setWordWrap(True)
        self.unsubscribe_spam = QLabel(self.unsubscribe_panel)
        self.unsubscribe_spam.setObjectName("muted")
        self.unsubscribe_spam.setWordWrap(True)
        unsubscribe_layout.addWidget(self.unsubscribe_warning)
        unsubscribe_layout.addWidget(self.unsubscribe_check)
        unsubscribe_layout.addWidget(self.unsubscribe_manual)
        unsubscribe_layout.addWidget(self.unsubscribe_spam)
        self.unsubscribe_panel.setVisible(False)

        self.apply_button = QPushButton(self)
        self.apply_button.setObjectName("primary")
        self.apply_button.setMinimumWidth(180)
        self.apply_button.setEnabled(False)

        footer = QHBoxLayout()
        footer.setContentsMargins(32, 12, 32, 24)
        footer.addStretch(1)
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
        table.setAccessibleName(", ".join(headers))
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
        self.unsubscribe_toggle.setText(t("review.unsubscribe.title"))
        self.unsubscribe_warning.setText(t("review.unsubscribe.warning"))
        self.unsubscribe_check.setText(t("review.unsubscribe.enable"))
        self.unsubscribe_manual.setText(t("review.unsubscribe.manual_note"))
        self.unsubscribe_spam.setText(t("review.unsubscribe.spam_note"))

        # Rendered values carry translated category names and modes.
        if self._scan is not None:
            self.scan_categories_label.setText(
                self._category_counts(self._scan.get("categories"))
            )
        if self._report is not None:
            self._render_report(self._report)
        if self._plan is not None:
            self._render_plan()
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
