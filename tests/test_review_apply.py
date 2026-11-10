"""The Review page after the gate: apply, the journal and undo.

Every test is headless and offline. The helper tests at the top drive a real
``CliClient`` against ``tests/fixtures/fake_cli.py`` so the argv contract with
the frozen 1.2.2 sidecar is pinned; the page tests use a ``FakeCli`` that records
typed-helper calls and answers with the JSON shapes the sidecar really prints.

What these tests pin down:

* apply asks for confirmation, always passes ``--yes --action move --limit`` and
  never exceeds ``Preferences.max_moves`` or the plan's own move count;
* a successful apply shows the run id and closes the plan's gate for good;
* a failed apply shows localized copy; a partial apply with a run id keeps undo
  discoverable and also closes the gate;
* the journal lists runs, has an empty state, and undo needs confirmation and
  passes the full run id back to the sidecar;
* nothing here ever calls an unsubscribe helper and no secret reaches a label,
  argv or the log.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QTableWidget

from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.cli import CliClient, CliError
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.ui.pages.review import REPORT_TOP, ReviewPage

#: A Gmail App Password used only as a sentinel: no real credential.
SECRET = "qwertyuiopasdfgh"

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_cli.py"

SCAN = {
    "mailboxes": {"INBOX": {"uidvalidity": 7, "found": 10, "cached": 10}},
    "categories": {"newsletter": 6, "promotion": 4},
    "total": 10,
}

REPORT = {
    "totals": {"messages": 10, "groups": 2, "protected": 3},
    "groups": [],
}

#: A plan with real moves: 3 newsletter + 2 promotion messages.
PLAN_MOVES = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 10, "groups": 2, "protected": 3},
    "actions": [
        {
            "id": "a1",
            "type": "move",
            "group": "newsletter-example",
            "category": "newsletter",
            "mailbox": "INBOX",
            "uids": [1, 2, 3],
            "dest": "CleanYourMail/Newsletters",
        },
        {
            "id": "a2",
            "type": "move",
            "group": "promotion-shop",
            "category": "promotion",
            "mailbox": "INBOX",
            "uids": [4, 5],
            "dest": "CleanYourMail/Promotions",
        },
    ],
    "groups": [],
}

APPLY_OK = {
    "run": "20261110T120000Z-abc123",
    "moved": 5,
    "unsubscribes": [],
    "failures": [],
}

APPLY_PARTIAL = {
    "run": "20261110T120000Z-part01",
    "moved": 3,
    "error": "server closed the connection",
}

JOURNAL_RUNS = [
    {
        "run": "20261110T120000Z-new001",
        "ts": "2026-11-10T12:00:00+00:00",
        "account": "me@example.com",
        "ops": 3,
        "messages": 5,
        "unsubs": 0,
    },
    {
        "run": "20261109T093000Z-old001",
        "ts": "2026-11-09T09:30:00+00:00",
        "account": "me@example.com",
        "ops": 1,
        "messages": 2,
        "unsubs": 0,
    },
]

UNDO_OK = {
    "run": "20261110T130000Z-und001",
    "source_run": "20261110T120000Z-new001",
    "restored": 5,
    "failed": 0,
    "refused": 0,
    "operations": [],
}


def _result(data: dict[str, Any], *, ok: bool = True, exit_code: int = 0) -> dict[str, Any]:
    """The normalized ``CliClient.run`` result, which is what pages receive."""
    return {
        "ok": ok,
        "exit_code": exit_code,
        "data": data,
        "stdout": json.dumps(data),
        "stderr": "",
    }


def _plan_result(plan: dict[str, Any]) -> dict[str, Any]:
    return _result({"path": "plan.json", "plan": plan})


class FakeCli:
    """A typed-helper stand-in: records calls and returns JSON payloads."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.scan_result: Any = _result(SCAN)
        self.report_result: Any = _result(REPORT)
        self.plan_result: Any = _plan_result(PLAN_MOVES)
        self.apply_result: Any = _result(APPLY_OK)
        self.journal_result: Any = _result({"runs": JOURNAL_RUNS})
        self.undo_result: Any = _result(UNDO_OK)
        self.apply_gate: threading.Event | None = None
        self.journal_gate: threading.Event | None = None

    def _answer(self, result: Any) -> dict[str, Any]:
        if isinstance(result, BaseException):
            raise result
        return result

    def scan(self, days: int, *, config_path: Path | None = None) -> dict[str, Any]:
        self.calls.append(("scan", days, config_path))
        return self._answer(self.scan_result)

    def report(self, top: int = REPORT_TOP, *, config_path: Path | None = None):
        self.calls.append(("report", top, config_path))
        return self._answer(self.report_result)

    def plan(
        self,
        mode: str,
        categories: list[str],
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("plan", mode, list(categories), config_path))
        return self._answer(self.plan_result)

    def apply(
        self,
        plan_path: str,
        limit: int,
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("apply", plan_path, limit, config_path))
        if self.apply_gate is not None:
            self.apply_gate.wait(timeout=5)
        return self._answer(self.apply_result)

    def journal(
        self, limit: int = 20, *, config_path: Path | None = None
    ) -> dict[str, Any]:
        self.calls.append(("journal", limit, config_path))
        if self.journal_gate is not None:
            self.journal_gate.wait(timeout=5)
        return self._answer(self.journal_result)

    def undo(self, run: str, *, config_path: Path | None = None) -> dict[str, Any]:
        self.calls.append(("undo", run, config_path))
        return self._answer(self.undo_result)

    def unsubscribe(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("apply must never call unsubscribe")

    def unsubs(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("apply must never call unsubs")


@pytest.fixture
def cli() -> FakeCli:
    return FakeCli()


@pytest.fixture
def services(tmp_path, translator, settings_store, cli) -> AppServices:
    config = ConfigService(cli, tmp_path / "appdata", tmp_path / "secret.txt")
    return AppServices(
        cli=cli, config=config, settings=settings_store, translator=translator
    )


@pytest.fixture
def page(qtbot, services) -> ReviewPage:
    page = ReviewPage(services)
    qtbot.addWidget(page)
    page.show()
    return page


@pytest.fixture
def confirm(monkeypatch) -> dict[str, Any]:
    """Answer ``QMessageBox.question`` and record every prompt."""
    holder: dict[str, Any] = {
        "answer": QMessageBox.StandardButton.Yes,
        "calls": [],
    }

    def question(*args: object, **kwargs: object):
        holder["calls"].append((args, kwargs))
        return holder["answer"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return holder


def _wait(page: ReviewPage, qtbot, timeout: int = 5000) -> None:
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=timeout)


def _labels(widget) -> str:
    """Every visible string the page could leak, tables included."""
    texts = [child.text() for child in widget.findChildren(QLabel)]
    texts.extend(child.text() for child in widget.findChildren(QPushButton))
    for table in widget.findChildren(QTableWidget):
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                item = table.item(row, column)
                if item is not None:
                    texts.append(item.text())
    texts.append(widget.windowTitle())
    return " ".join(texts)


def _ready_to_apply(page: ReviewPage) -> None:
    page.set_plan(_plan_result(PLAN_MOVES))
    page.review_checkbox.setChecked(True)


# --- The typed CliClient helpers -------------------------------------------


class Sidecar:
    """Drive ``tests/fixtures/fake_cli.py`` through its environment contract."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.response = tmp_path / "response.txt"
        self.argv = tmp_path / "argv.json"
        self.stderr = tmp_path / "stderr.txt"
        self._monkeypatch = monkeypatch
        self.response.write_text("", encoding="utf-8")
        self.stderr.write_text("", encoding="utf-8")
        monkeypatch.setenv("FAKE_CLI_RESPONSE", str(self.response))
        monkeypatch.setenv("FAKE_CLI_ARGV", str(self.argv))
        monkeypatch.setenv("FAKE_CLI_STDERR", str(self.stderr))
        monkeypatch.setenv("FAKE_CLI_EXIT", "0")
        monkeypatch.delenv("CYM_CLI", raising=False)

    def respond(self, payload: object, *, exit_code: int = 0) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.response.write_text(text, encoding="utf-8")
        self._monkeypatch.setenv("FAKE_CLI_EXIT", str(exit_code))

    def client(self) -> CliClient:
        return CliClient([sys.executable, str(FAKE_CLI)])

    def recorded_argv(self) -> list[str]:
        return json.loads(self.argv.read_text(encoding="utf-8"))


@pytest.fixture
def sidecar(tmp_path, monkeypatch) -> Sidecar:
    return Sidecar(tmp_path, monkeypatch)


def test_apply_helper_passes_plan_yes_move_limit_and_config(sidecar, tmp_path):
    sidecar.respond(APPLY_OK)
    plan = tmp_path / "plan.json"
    config = tmp_path / "cleanyourmail.toml"

    result = sidecar.client().apply(plan, 12, config_path=config)

    assert result["ok"] is True
    assert result["data"] == APPLY_OK
    assert sidecar.recorded_argv() == [
        "apply",
        str(plan),
        "--yes",
        "--action",
        "move",
        "--limit",
        "12",
        "--json",
        "--config",
        str(config),
    ]


def test_journal_helper_passes_the_limit_and_parses_runs(sidecar):
    sidecar.respond({"runs": JOURNAL_RUNS})

    result = sidecar.client().journal(20)

    assert result["ok"] is True
    assert result["data"]["runs"] == JOURNAL_RUNS
    assert sidecar.recorded_argv() == ["journal", "--limit", "20", "--json"]


def test_undo_helper_passes_the_run_and_yes(sidecar):
    sidecar.respond(UNDO_OK)

    result = sidecar.client().undo("20261110T120000Z-new001")

    assert result["ok"] is True
    assert result["data"] == UNDO_OK
    assert sidecar.recorded_argv() == [
        "undo",
        "--run",
        "20261110T120000Z-new001",
        "--yes",
        "--json",
    ]


def test_apply_and_undo_use_timeouts_that_match_their_work(monkeypatch):
    client = CliClient(["cym-cli"])
    seen: list[int] = []

    def execute(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
        seen.append(timeout)
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")

    monkeypatch.setattr(client, "_execute", execute)

    client.apply("plan.json", 5)
    client.undo("20261110T120000Z-abc123")

    assert seen == [1800, 900]


@pytest.mark.parametrize("limit", [0, -1, True, "5", None])
def test_apply_and_journal_helpers_refuse_a_bad_limit(sidecar, limit):
    client = sidecar.client()

    with pytest.raises(ValueError):
        client.apply("plan.json", limit)
    with pytest.raises(ValueError):
        client.journal(limit)


@pytest.mark.parametrize("plan_path", ["", "   ", None])
def test_apply_helper_refuses_an_empty_plan_path(sidecar, plan_path):
    with pytest.raises(ValueError):
        sidecar.client().apply(plan_path, 5)


@pytest.mark.parametrize("run", ["", "   ", None, "-nope", "bad run"])
def test_undo_helper_refuses_a_bad_run_id(sidecar, run):
    with pytest.raises(ValueError):
        sidecar.client().undo(run)


# --- The review gate and apply ---------------------------------------------


def test_apply_stays_disabled_until_the_plan_is_reviewed(page, cli, qtbot):
    page.set_plan(_plan_result(PLAN_MOVES))

    assert page.review_checkbox.isEnabled() is True
    assert page.apply_button.isEnabled() is False

    page.apply_button.click()
    qtbot.wait(50)

    assert cli.calls == []


def test_the_apply_button_route_still_requires_review(page, cli, qtbot):
    page.set_plan(_plan_result(PLAN_MOVES))
    page.apply_button.setEnabled(True)  # simulate a programmatic bypass

    page.apply_button.click()
    qtbot.wait(50)

    assert cli.calls == []


def test_apply_aside_a_confirmation_is_required(page, cli, qtbot, confirm):
    _ready_to_apply(page)
    confirm["answer"] = QMessageBox.StandardButton.No

    page.apply_button.click()
    qtbot.wait(50)

    assert cli.calls == []
    assert len(confirm["calls"]) == 1
    assert page.apply_button.isEnabled() is True


def test_apply_passes_the_reviewed_plan_and_a_clamped_limit(
    page, cli, qtbot, services, confirm
):
    _ready_to_apply(page)

    page.apply_button.click()
    _wait(page, qtbot)

    assert cli.calls == [
        ("apply", "plan.json", 5, services.config.config_path())
    ]
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False


def test_apply_never_exceeds_the_max_moves_policy(
    page, cli, qtbot, services, settings_store, confirm
):
    settings_store.save(AppSettings(preferences=Preferences(max_moves=2)))
    _ready_to_apply(page)

    page.apply(999)
    _wait(page, qtbot)

    assert cli.calls == [
        ("apply", "plan.json", 2, services.config.config_path())
    ]


def test_apply_without_a_limit_uses_the_policy_capped_by_the_plan(
    page, cli, qtbot, services, settings_store, confirm
):
    settings_store.save(AppSettings(preferences=Preferences(max_moves=3)))
    _ready_to_apply(page)

    page.apply(0)
    _wait(page, qtbot)

    assert cli.calls == [
        ("apply", "plan.json", 3, services.config.config_path())
    ]


def test_a_successful_apply_shows_the_run_and_closes_the_gate_for_that_plan(
    page, cli, qtbot, services, confirm
):
    _ready_to_apply(page)

    page.apply_button.click()
    _wait(page, qtbot)

    t = services.translator.t
    assert t("apply.done", count=5) in page.status_label.text()
    assert t("apply.id", run=APPLY_OK["run"]) in page.status_label.text()
    assert page.error_label.isHidden() is True
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    assert page.undo_button.isEnabled() is True

    # A second apply is impossible even if the box is forced back on.
    page.review_checkbox.setChecked(True)
    page.apply(5)
    qtbot.wait(50)

    assert [call[0] for call in cli.calls] == ["apply"]


def test_a_new_plan_reopens_the_gate_after_an_apply(page, qtbot, confirm):
    _ready_to_apply(page)
    page.apply(5)
    _wait(page, qtbot)

    page.set_plan(_plan_result(PLAN_MOVES))

    assert page.review_checkbox.isEnabled() is True
    assert page.review_checkbox.isChecked() is False
    page.review_checkbox.setChecked(True)
    assert page.apply_button.isEnabled() is True


def test_a_failed_apply_without_a_run_shows_only_localized_copy(
    page, cli, qtbot, services, confirm
):
    cli.apply_result = _result(
        {"error": "login refused for the server"}, ok=False, exit_code=2
    )
    _ready_to_apply(page)

    page.apply_button.click()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.apply")
    assert page.error_label.isHidden() is False
    assert "login refused" not in _labels(page)
    assert page.plan_move_count() == 5
    # A started apply may have moved mail before the error: the gate stays
    # closed until a fresh scan or plan.
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False

    page.apply(5)
    page.review_checkbox.setChecked(True)
    page.apply_button.click()
    qtbot.wait(50)

    assert [call[0] for call in cli.calls] == ["apply"]


def test_an_apply_with_no_answer_closes_the_gate_and_blocks_a_second_try(
    page, cli, qtbot, services, confirm
):
    cli.apply_result = CliError("the sidecar did not answer")
    _ready_to_apply(page)

    page.apply_button.click()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.apply")
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False

    page.apply(5)
    page.review_checkbox.setChecked(True)
    page.apply_button.click()
    qtbot.wait(50)

    assert [call[0] for call in cli.calls] == ["apply"]


def test_a_partial_apply_with_a_run_keeps_undo_discoverable_and_closes_the_gate(
    page, cli, qtbot, services, confirm
):
    cli.apply_result = _result(APPLY_PARTIAL, ok=False, exit_code=2)
    _ready_to_apply(page)

    page.apply_button.click()
    _wait(page, qtbot)

    t = services.translator.t
    assert t("apply.failed") in page.status_label.text()
    assert t("apply.id", run=APPLY_PARTIAL["run"]) in page.status_label.text()
    assert page.error_label.text() == t("apply.partial")
    assert "server closed" not in _labels(page)
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    assert page.undo_button.isEnabled() is True

    page.apply(5)
    qtbot.wait(50)

    assert [call[0] for call in cli.calls] == ["apply"]


def test_apply_disables_every_control_while_it_runs(page, cli, qtbot, confirm):
    cli.apply_gate = threading.Event()
    _ready_to_apply(page)

    page.apply_button.click()
    qtbot.waitUntil(lambda: page.is_busy(), timeout=5000)

    for button in (
        page.scan_button,
        page.report_button,
        page.plan_button,
        page.journal_button,
        page.undo_button,
        page.apply_button,
    ):
        assert button.isEnabled() is False, button.text()
    assert page.review_checkbox.isEnabled() is False

    cli.apply_gate.set()
    _wait(page, qtbot)


# --- The journal ------------------------------------------------------------


def test_the_journal_lists_runs_with_full_ids(page, cli, qtbot, services):
    page.load_journal()
    _wait(page, qtbot)

    assert cli.calls[-1] == ("journal", 20, services.config.config_path())
    dialog = page.journal_dialog
    assert dialog is not None
    assert dialog.table.rowCount() == len(JOURNAL_RUNS)
    assert dialog.table.columnCount() == 4
    assert dialog.table.item(0, 1).text() == JOURNAL_RUNS[0]["run"]
    assert dialog.table.item(1, 1).text() == JOURNAL_RUNS[1]["run"]
    assert dialog.table.item(0, 2).text() == "5"
    assert dialog.table.item(0, 3).text() == "3"
    assert dialog.undo_button.isEnabled() is False
    # A generic journal load does not choose the footer's undo target.
    assert page.last_run is None
    assert page.undo_button.isEnabled() is False

    dialog.table.selectRow(0)

    assert dialog.undo_button.isEnabled() is True
    assert dialog.selected_run() == JOURNAL_RUNS[0]["run"]

    dialog.close()
    assert page.journal_dialog is None


def test_an_empty_journal_shows_the_empty_state(page, cli, qtbot, services):
    cli.journal_result = _result({"runs": []})

    page.load_journal()
    _wait(page, qtbot)

    dialog = page.journal_dialog
    assert dialog is not None
    assert dialog.empty_label.isHidden() is False
    assert dialog.empty_label.text() == services.translator.t("review.journal_empty")
    assert dialog.table.isHidden() is True
    assert dialog.undo_button.isEnabled() is False


def test_an_empty_journal_clears_the_undo_last_run_target(
    page, cli, qtbot, confirm
):
    _ready_to_apply(page)
    page.apply_button.click()
    _wait(page, qtbot)
    assert page.last_run == APPLY_OK["run"]
    assert page.undo_button.isEnabled() is True

    cli.journal_result = _result({"runs": []})
    page.load_journal()
    _wait(page, qtbot)

    assert page.last_run is None
    assert page.undo_button.isEnabled() is False


def test_the_journal_button_opens_the_journal(page, cli, qtbot):
    page.journal_button.click()
    _wait(page, qtbot)

    assert cli.calls[-1][0] == "journal"
    assert page.journal_dialog is not None


def test_a_journal_failure_shows_localized_copy(page, cli, qtbot, services):
    cli.journal_result = _result(
        {"error": "journal.jsonl is unreadable"}, ok=False, exit_code=2
    )

    page.load_journal()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.journal")
    assert "journal.jsonl" not in _labels(page)
    assert page.journal_dialog is None


# --- Undo -------------------------------------------------------------------


def test_undo_needs_confirmation_and_passes_the_selected_run(
    page, cli, qtbot, services, confirm
):
    page.load_journal()
    _wait(page, qtbot)
    dialog = page.journal_dialog
    dialog.table.selectRow(0)
    confirm["answer"] = QMessageBox.StandardButton.No

    dialog.undo_button.click()
    qtbot.wait(50)

    assert not [call for call in cli.calls if call[0] == "undo"]

    confirm["answer"] = QMessageBox.StandardButton.Yes
    dialog.undo_button.click()
    _wait(page, qtbot)

    undo_calls = [call for call in cli.calls if call[0] == "undo"]
    assert undo_calls == [
        ("undo", JOURNAL_RUNS[0]["run"], services.config.config_path())
    ]
    assert page.status_label.text() == services.translator.t(
        "review.undo.done", count=5
    )


def test_undo_without_a_run_points_at_the_journal(page, cli, qtbot, services):
    page.undo("")
    qtbot.wait(50)

    assert cli.calls == []
    assert page.status_label.text() == services.translator.t("review.undo.empty")

    page.undo("   ")
    qtbot.wait(50)

    assert cli.calls == []


def test_a_failed_undo_shows_localized_copy_and_keeps_the_target(
    page, cli, qtbot, services, confirm
):
    _ready_to_apply(page)
    page.apply_button.click()
    _wait(page, qtbot)
    cli.undo_result = _result(
        {"error": "connection lost during undo"}, ok=False, exit_code=2
    )

    page.undo_button.click()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.undo")
    assert "connection lost" not in _labels(page)
    assert page.undo_button.isEnabled() is True


def test_a_partial_undo_shows_the_restored_count_and_the_failures(
    page, cli, qtbot, services, confirm
):
    _ready_to_apply(page)
    page.apply_button.click()
    _wait(page, qtbot)
    cli.undo_result = _result(
        {
            "run": "20261110T130000Z-und002",
            "source_run": APPLY_OK["run"],
            "restored": 3,
            "failed": 1,
            "refused": 0,
            "operations": [],
        },
        ok=False,
        exit_code=2,
    )

    page.undo_button.click()
    _wait(page, qtbot)

    assert page.status_label.text() == services.translator.t(
        "review.undo.done", count=3
    )
    assert page.error_label.text() == services.translator.t(
        "review.undo.partial", failed=1, refused=0
    )
    assert page.undo_button.isEnabled() is False


def test_an_undo_with_nothing_restored_shows_the_error(
    page, cli, qtbot, services, confirm
):
    _ready_to_apply(page)
    page.apply_button.click()
    _wait(page, qtbot)
    cli.undo_result = _result(
        {
            "run": "20261110T130000Z-und003",
            "source_run": APPLY_OK["run"],
            "restored": 0,
            "failed": 0,
            "refused": 0,
            "operations": [],
        },
        ok=False,
        exit_code=2,
    )

    page.undo_button.click()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.undo")
    assert page.status_label.isHidden() is True
    assert services.translator.t("review.undo.done", count=0) not in _labels(page)


def test_undo_last_run_after_an_apply_keeps_the_gate_closed(
    page, cli, qtbot, services, confirm
):
    _ready_to_apply(page)
    page.apply_button.click()
    _wait(page, qtbot)

    page.undo_button.click()
    _wait(page, qtbot)

    assert cli.calls[-1][:2] == ("undo", APPLY_OK["run"])
    assert page.status_label.text() == services.translator.t(
        "review.undo.done", count=5
    )
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False


def test_undo_refreshes_the_open_journal(page, cli, qtbot, services, confirm):
    page.load_journal()
    _wait(page, qtbot)
    dialog = page.journal_dialog
    dialog.table.selectRow(1)
    cli.journal_result = _result({"runs": [JOURNAL_RUNS[0]]})

    dialog.undo_button.click()
    _wait(page, qtbot)

    undo_calls = [call for call in cli.calls if call[0] == "undo"]
    assert undo_calls == [
        ("undo", JOURNAL_RUNS[1]["run"], services.config.config_path())
    ]
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == JOURNAL_RUNS[0]["run"]
    assert dialog.undo_button.isEnabled() is False


def test_a_failed_quiet_refresh_keeps_the_undo_feedback_and_dialog(
    page, cli, qtbot, services, confirm
):
    page.load_journal()
    _wait(page, qtbot)
    dialog = page.journal_dialog
    dialog.table.selectRow(0)
    # The undo succeeds, but the journal refresh that follows does not.
    cli.journal_result = _result(
        {"error": "journal.jsonl is unreadable"}, ok=False, exit_code=2
    )

    dialog.undo_button.click()
    _wait(page, qtbot)

    assert page.status_label.text() == services.translator.t(
        "review.undo.done", count=5
    )
    assert page.error_label.isHidden() is True
    assert page.journal_dialog is dialog
    assert dialog.isVisible() is True
    assert dialog.table.rowCount() == len(JOURNAL_RUNS)


def test_reload_discards_a_journal_response_from_before_the_new_page(
    page, cli, qtbot
):
    cli.journal_gate = threading.Event()
    page.load_journal()
    qtbot.waitUntil(lambda: page.is_busy(), timeout=5000)
    assert page.journal_dialog is not None

    page.reload()
    cli.journal_gate.set()
    page._pool.waitForDone(5000)
    qtbot.wait(50)

    assert page.journal_dialog is None
    assert page.is_busy() is False


def test_a_stale_journal_response_does_not_reopen_a_closed_dialog(
    page, cli, qtbot
):
    cli.journal_gate = threading.Event()
    page.load_journal()
    qtbot.waitUntil(lambda: page.is_busy(), timeout=5000)
    dialog = page.journal_dialog
    assert dialog is not None

    dialog.close()
    cli.journal_gate.set()
    page._pool.waitForDone(5000)
    qtbot.wait(50)

    assert page.journal_dialog is None
    assert page.is_busy() is False


# --- Safety -----------------------------------------------------------------


def test_apply_journal_and_undo_never_touch_unsubscribe(page, cli, qtbot, confirm):
    _ready_to_apply(page)
    page.apply_button.click()
    _wait(page, qtbot)

    page.load_journal()
    _wait(page, qtbot)
    dialog = page.journal_dialog
    dialog.table.selectRow(0)
    dialog.undo_button.click()
    _wait(page, qtbot)

    assert {call[0] for call in cli.calls} == {"apply", "journal", "undo"}


def test_no_secret_reaches_a_label_argv_or_the_log(
    page, cli, qtbot, services, confirm, caplog
):
    caplog.set_level(logging.DEBUG)
    cli.apply_result = _result(
        {"error": f"authentication failed with {SECRET}"}, ok=False, exit_code=2
    )
    _ready_to_apply(page)

    page.apply_button.click()
    _wait(page, qtbot)

    assert SECRET not in _labels(page)
    assert SECRET not in json.dumps(cli.calls, default=str)
    assert SECRET not in caplog.text
    assert services.config.secret_path.exists() is False


# --- Copy -------------------------------------------------------------------


def test_the_journal_and_undo_controls_are_translated(qtbot, services):
    services.translator.set_language("es")
    page = ReviewPage(services)
    qtbot.addWidget(page)
    t = services.translator.t

    assert page.journal_button.text() == t("review.journal")
    assert page.undo_button.text() == t("review.undo.button")

    page.load_journal()
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=5000)
    dialog = page.journal_dialog
    assert dialog.windowTitle() == t("review.journal")
    assert dialog.table.horizontalHeaderItem(0).text() == t("review.journal_when")
    assert dialog.undo_button.text() == t("review.undo.selected")
