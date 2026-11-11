"""The Review page: scan, report and a plan with a review gate.

Every test is headless and offline. The page tests use a ``FakeCli`` that
records the typed helper calls and returns the JSON shapes the frozen 1.2.2
sidecar really prints; the three helper tests at the top run a real
``CliClient`` against ``tests/fixtures/fake_cli.py`` so the argv contract is
pinned, not assumed.

What these tests pin down:

* Scan asks for 365 days, report for the top 30 senders, and the plan receives
  exactly the categories and mode stored in ``Preferences``.
* The scan cards show the cached total and per-category counts; the report
  cards show totals and sender groups.
* The plan cards have destination, category, message count and unsubscribe mode.
* The review checkbox is enabled only by a plan with at least one move; Apply
  follows the checkbox and refuses zero-move or unsubscribe-only plans.
* A sidecar failure shows localized copy and leaves the gate closed.
* Preferences Continue reaches the page. Apply, the journal and undo are
  covered separately in ``test_review_apply.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QLabel

from cleanyourmail_app.domain.models import AppSettings, Preferences
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.cli import CliClient, CliError
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.ui.main_window import MainWindow
from cleanyourmail_app.ui.pages.review import REPORT_TOP, SCAN_DAYS, ReviewPage

#: A Gmail App Password used only as a sentinel by the shell test.
SECRET = "qwertyuiopasdfgh"

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_cli.py"

#: ``scan --json`` on the frozen sidecar.
SCAN = {
    "mailboxes": {
        "INBOX": {
            "uidvalidity": 7,
            "found": 10,
            "cached": 10,
            "failed": 0,
            "pruned": 0,
            "uidvalidity_reset": 0,
        }
    },
    "categories": {"newsletter": 6, "promotion": 4},
    "total": 10,
}

#: ``report --json`` on the frozen sidecar.
REPORT = {
    "account": "me@example.com",
    "cached": 10,
    "oldest": "2025-01-01T00:00:00+00:00",
    "newest": "2026-01-01T00:00:00+00:00",
    "totals": {
        "messages": 10,
        "groups": 2,
        "actionable": 7,
        "protected": 3,
        "categories": {"newsletter": 6, "promotion": 4},
        "unread": 2,
    },
    "categories": {"newsletter": 6, "promotion": 4},
    "groups": [
        {
            "key": "newsletter-example",
            "category": "newsletter",
            "domain": "news.example",
            "senders": ["a@news.example"],
            "count": 6,
            "actionable": 4,
            "unread": 1,
            "samples": ["Weekly digest", "New arrivals", "Editor's picks"],
            "unsubscribe": {"mode": "one-click", "automatic": True, "url": "https://x.test/u"},
            "recommended": "move",
        },
        {
            "key": "promotion-shop",
            "category": "promotion",
            "domain": "shop.example",
            "senders": ["b@shop.example"],
            "count": 4,
            "actionable": 3,
            "unread": 1,
            "samples": ["Autumn sale"],
            "unsubscribe": {"mode": "manual", "automatic": False, "url": None},
            "recommended": "move",
        },
    ],
    "stale": [],
    "manual_unsubscribe": [],
    "protected": [],
    "auto_unsubscribe": [],
}

#: A plan with real moves: 3 newsletter + 2 promotion messages.
PLAN_MOVES = {
    "version": 1,
    "generated": "2026-11-10T12:00:00+00:00",
    "account": "me@example.com",
    "mode": "folders",
    "uidvalidity": {"INBOX": 7},
    "stats": {
        "messages": 10,
        "groups": 2,
        "actionable": 5,
        "protected": 3,
        "categories": {"newsletter": 6, "promotion": 4},
        "unread": 2,
    },
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
    "groups": [
        {
            "key": "newsletter-example",
            "category": "newsletter",
            "domain": "news.example",
            "messages": [
                {
                    "uid": 1,
                    "mailbox": "INBOX",
                    "sender": "news@news.example",
                    "name": "Example News",
                    "subject": "Your weekly digest",
                    "date": "2026-10-01T08:00:00+00:00",
                },
                {
                    "uid": 2,
                    "mailbox": "INBOX",
                    "sender": "news@news.example",
                    "name": "Example News",
                    "subject": "New arrivals",
                    "date": "2026-10-02T08:00:00+00:00",
                },
                {
                    "uid": 3,
                    "mailbox": "INBOX",
                    "sender": "news@news.example",
                    "name": "Example News",
                    "subject": "Editor's picks",
                    "date": "2026-10-03T08:00:00+00:00",
                },
            ],
        },
        {
            "key": "promotion-shop",
            "category": "promotion",
            "domain": "shop.example",
            "messages": [
                {
                    "uid": 4,
                    "mailbox": "INBOX",
                    "sender": "sale@shop.example",
                    "name": "Example Shop",
                    "subject": "Autumn sale",
                    "date": "2026-10-04T08:00:00+00:00",
                },
                {
                    "uid": 5,
                    "mailbox": "INBOX",
                    "sender": "sale@shop.example",
                    "name": "Example Shop",
                    "subject": "Last days",
                    "date": "2026-10-05T08:00:00+00:00",
                },
            ],
        },
    ],
}

#: A plan that only asks the sender to unsubscribe; no message moves.
PLAN_UNSUBSCRIBE_ONLY = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 6, "groups": 1, "actionable": 0, "protected": 0},
    "actions": [
        {
            "id": "u1",
            "type": "unsubscribe",
            "group": "newsletter-example",
            "category": "newsletter",
            "domain": "news.example",
            "sender": "a@news.example",
            "target": "https://news.example/unsubscribe",
            "mode": "one-click",
        }
    ],
    "groups": [],
}

#: A plan whose rules matched nothing to move.
PLAN_ZERO_MOVES = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 0, "groups": 0, "actionable": 0, "protected": 0},
    "actions": [],
    "groups": [],
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


def _card_text(card: object) -> str:
    """Every label inside one card, joined for content assertions."""
    return "\n".join(label.text() for label in card.findChildren(QLabel))


class FakeCli:
    """A typed-helper stand-in: records calls and returns JSON payloads."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.scan_result: Any = _result(SCAN)
        self.report_result: Any = _result(REPORT)
        self.plan_result: Any = _plan_result(PLAN_MOVES)

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
def window(qtbot, services) -> MainWindow:
    window = MainWindow(services.settings, services.translator, services)
    qtbot.addWidget(window)
    window.show()
    return window


def _wait(page: ReviewPage, qtbot) -> None:
    """Wait for the worker thread to hand its result back to the page."""
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=5000)


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


def test_scan_helper_passes_days_and_asks_for_json(sidecar):
    sidecar.respond(SCAN)

    result = sidecar.client().scan(365)

    assert result["ok"] is True
    assert result["data"] == SCAN
    assert sidecar.recorded_argv() == ["scan", "--days", "365", "--json"]


def test_report_helper_passes_the_top_limit(sidecar):
    sidecar.respond(REPORT)

    result = sidecar.client().report(30)

    assert result["ok"] is True
    assert sidecar.recorded_argv() == ["report", "--top", "30", "--json"]


def test_plan_helper_passes_mode_and_each_category(sidecar):
    sidecar.respond({"path": "plan.json", "plan": PLAN_MOVES})

    result = sidecar.client().plan("archive", ["newsletter", "promotion"])

    assert result["ok"] is True
    assert sidecar.recorded_argv() == [
        "plan",
        "--mode",
        "archive",
        "--category",
        "newsletter",
        "--category",
        "promotion",
        "--json",
    ]


def test_plan_helper_appends_the_config_path(sidecar, tmp_path):
    sidecar.respond({"path": "plan.json", "plan": PLAN_MOVES})
    config = tmp_path / "cleanyourmail.toml"

    sidecar.client().plan("folders", ["spam"], config_path=config)

    assert sidecar.recorded_argv() == [
        "plan",
        "--mode",
        "folders",
        "--category",
        "spam",
        "--json",
        "--config",
        str(config),
    ]


def test_plan_helper_refuses_an_unknown_mode_or_category(sidecar):
    client = sidecar.client()

    with pytest.raises(ValueError):
        client.plan("delete", ["newsletter"])
    with pytest.raises(ValueError):
        client.plan("folders", ["everything"])


# --- Scan ------------------------------------------------------------------


def test_scan_uses_the_days_it_is_given_and_shows_counts(page, cli, qtbot, services):
    page.start_scan(SCAN_DAYS)
    _wait(page, qtbot)

    assert cli.calls[-1][:2] == ("scan", 365)
    assert page.scan_total_label.text() == "10"
    t = services.translator.t
    counts = page.scan_categories_label.text()
    assert t("preferences.category.newsletter.label") in counts
    assert t("preferences.category.promotion.label") in counts
    assert "6" in counts and "4" in counts
    assert page.scan_mailboxes_label.text() == "1"
    assert page.error_label.isHidden() is True
    assert page.status_label.text() == t("review.scan_done")


def test_the_scan_button_scans_a_year(page, cli, qtbot, services):
    page.scan_button.click()
    _wait(page, qtbot)

    assert cli.calls[-1][1] == 365
    assert page.status_label.text() == services.translator.t("review.scan_done")


def test_a_failed_scan_shows_localized_copy(page, cli, qtbot, services):
    cli.scan_result = _result({"ok": False, "error": "login refused"}, ok=False, exit_code=2)

    page.start_scan(365)
    _wait(page, qtbot)

    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.scan")
    assert page.scan_total_label.text() == "0"


def test_a_missing_sidecar_fails_the_scan_without_raising(
    page, cli, qtbot, services
):
    cli.scan_result = CliError("sidecar missing")

    page.start_scan(365)
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.scan")
    assert page.scan_button.isEnabled() is True


# --- Report ----------------------------------------------------------------


def test_report_shows_totals_and_sender_groups(page, services):
    page.set_report(_result(REPORT))

    t = services.translator.t
    assert page.report_total_label.text() == "10"
    assert page.report_groups_label.text() == "2"
    assert page.report_protected_label.text() == "3"
    assert page.report_cards_layout.count() == 2
    first = _card_text(page.report_cards_layout.itemAt(0).widget())
    assert t("preferences.category.newsletter.label") in first
    assert "news.example" in first
    assert t("review.wizard.report.group", count=6, unread=1) in first
    assert "Weekly digest" in first
    assert t(
        "review.wizard.plan.unsubscribe",
        modes=t("review.plan.unsubscribe_one_click"),
    ) in first


def test_the_report_button_asks_for_the_top_thirty(page, cli, qtbot):
    page.report_button.click()
    _wait(page, qtbot)

    assert cli.calls[-1][:2] == ("report", 30)
    assert page.report_cards_layout.count() == 2


def test_a_failed_report_shows_localized_copy(page, cli, qtbot, services):
    cli.report_result = _result(
        {"ok": False, "error": "The cache is empty."}, ok=False, exit_code=2
    )

    page.report_button.click()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.report")
    assert page.report_cards_layout.count() == 0
    assert page.report_result.isHidden() is True


# --- Plan ------------------------------------------------------------------


def test_build_plan_uses_the_preferences_it_is_given(page, cli, services):
    preferences = Preferences(categories=["social", "spam"], mode="archive")

    result = page.build_plan(preferences)

    assert result["ok"] is True
    _, mode, categories, config_path = cli.calls[-1]
    assert mode == "archive"
    assert categories == ["social", "spam"]
    assert config_path == services.config.config_path()


def test_the_plan_button_passes_the_stored_categories_and_mode(
    page, cli, qtbot, settings_store
):
    settings_store.save(
        AppSettings(
            provider="gmail",
            email="me@example.com",
            preferences=Preferences(categories=["newsletter", "spam"], mode="archive"),
        )
    )

    page.plan_button.click()
    _wait(page, qtbot)

    _, mode, categories, _ = cli.calls[-1]
    assert mode == "archive"
    assert categories == ["newsletter", "spam"]
    assert page.plan_cards_layout.count() == 2


def test_the_plan_cards_show_category_destination_messages_and_unsubscribe(
    page, services
):
    page.set_plan(_plan_result(PLAN_MOVES))

    t = services.translator.t
    assert page.plan_cards_layout.count() == 2
    first = _card_text(page.plan_cards_layout.itemAt(0).widget())
    assert t("preferences.category.newsletter.label") in first
    assert "CleanYourMail/Newsletters" in first
    assert t(
        "review.wizard.plan.count_many", count=3, sender="news.example"
    ) in first
    assert "Your weekly digest" in first
    assert "New arrivals" in first
    assert "Editor's picks" in first
    second = _card_text(page.plan_cards_layout.itemAt(1).widget())
    assert t("preferences.category.promotion.label") in second
    assert "CleanYourMail/Promotions" in second
    assert t(
        "review.wizard.plan.count_many", count=2, sender="shop.example"
    ) in second
    assert "Autumn sale" in second
    assert page.plan_path == "plan.json"


def test_a_plan_with_moves_opens_the_review_gate(page):
    page.set_plan(_plan_result(PLAN_MOVES))

    assert page.plan_move_count() == 5
    assert page.review_checkbox.isEnabled() is True
    assert page.review_checkbox.isChecked() is False
    assert page.apply_button.isEnabled() is False

    page.review_checkbox.setChecked(True)

    assert page.apply_button.isEnabled() is True

    page.review_checkbox.setChecked(False)

    assert page.apply_button.isEnabled() is False


def test_a_zero_move_plan_keeps_the_gate_closed(page):
    page.set_plan(_plan_result(PLAN_ZERO_MOVES))

    assert page.plan_move_count() == 0
    assert page.review_checkbox.isEnabled() is False
    assert page.review_checkbox.isChecked() is False
    assert page.apply_button.isEnabled() is False

    # Even a programmatic toggle cannot open the gate.
    page.review_toggled(True)

    assert page.apply_button.isEnabled() is False


def test_an_unsubscribe_only_plan_keeps_the_gate_closed(page, services):
    page.set_plan(_plan_result(PLAN_UNSUBSCRIBE_ONLY))

    t = services.translator.t
    assert page.plan_move_count() == 0
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    # The card still explains what the plan would ask, without offering Apply.
    assert page.plan_cards_layout.count() == 1
    card = _card_text(page.plan_cards_layout.itemAt(0).widget())
    assert t("preferences.category.newsletter.label") in card
    assert t("review.plan.no_destination") in card
    assert t("review.plan.unsubscribe_one_click") in card


def test_a_new_plan_closes_the_gate_again(page):
    page.set_plan(_plan_result(PLAN_MOVES))
    page.review_checkbox.setChecked(True)
    assert page.apply_button.isEnabled() is True

    page.set_plan(_plan_result(PLAN_ZERO_MOVES))

    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False


def test_a_new_scan_makes_the_old_plan_stale(page, cli, qtbot):
    page.set_plan(_plan_result(PLAN_MOVES))
    page.review_checkbox.setChecked(True)

    page.start_scan(365)

    # Start, not finish: the old UIDs are stale the moment the cache changes.
    assert page.plan_move_count() == 0
    assert page.plan_cards_layout.count() == 0
    assert page.plan_result.isHidden() is True
    assert page.review_checkbox.isChecked() is False
    assert page.apply_button.isEnabled() is False
    _wait(page, qtbot)


def test_a_plan_error_shows_a_readable_message_and_leaves_apply_disabled(
    page, cli, qtbot, services
):
    cli.plan_result = _result(
        {"ok": False, "error": "The cache is empty."}, ok=False, exit_code=2
    )

    page.plan_button.click()
    _wait(page, qtbot)

    assert page.error_label.isHidden() is False
    assert page.error_label.text() == services.translator.t("errors.plan")
    assert page.plan_cards_layout.count() == 0
    assert page.plan_result.isHidden() is True
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False


def test_a_sidecar_that_cannot_start_fails_the_plan_cleanly(page, cli, qtbot, services):
    cli.plan_result = CliError("sidecar missing")

    page.plan_button.click()
    _wait(page, qtbot)

    assert page.error_label.text() == services.translator.t("errors.plan")
    assert page.apply_button.isEnabled() is False
    assert page.plan_button.isEnabled() is True


# --- Layout and copy -------------------------------------------------------


def test_the_unsubscribe_section_starts_collapsed_and_explains_it_is_unavailable(
    page, services
):
    assert page.unsubscribe_toggle.isChecked() is False
    assert page.unsubscribe_panel.isHidden() is True
    assert not hasattr(page, "unsubscribe_check")
    assert page.unsubscribe_unavailable.text() == services.translator.t(
        "review.unsubscribe.unavailable"
    )


def test_every_string_is_translated_into_spanish(qtbot, services):
    services.translator.set_language("es")
    page = ReviewPage(services)
    qtbot.addWidget(page)
    t = services.translator.t

    assert page.title_label.text() == t("review.title")
    assert page.scan_button.text() == t("review.wizard.scan.action")
    assert page.review_checkbox.text() == t("review.reviewed")
    assert page.apply_button.text() == t("review.apply")
    assert page.scan_title_label.text() == t("review.wizard.scan.title")
    assert page.plan_title_label.text() == t("review.wizard.plan.title")


def test_a_language_switch_retranslates_the_rendered_values(qtbot, page, services):
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MOVES))

    page.retranslate()

    assert page.plan_title_label.text() == services.translator.t(
        "review.wizard.plan.title"
    )

    services.translator.set_language("es")
    page.retranslate()

    t = services.translator.t
    assert page.plan_title_label.text() == t("review.wizard.plan.title")
    plan_text = _card_text(page.plan_cards_layout.itemAt(0).widget())
    assert t("preferences.category.newsletter.label") in plan_text
    assert t(
        "review.wizard.plan.count_many", count=3, sender="news.example"
    ) in plan_text
    report_text = _card_text(page.report_cards_layout.itemAt(0).widget())
    assert t("review.plan.unsubscribe_one_click") in report_text
    assert page.report_result_label.text() == t(
        "review.wizard.report.result", messages=10, groups=2, protected=3
    )


# --- Shell wiring ----------------------------------------------------------


def _select(window: MainWindow, provider_id: str, email: str) -> None:
    provider_page = window.provider_page
    card = next(card for card in provider_page.cards if card.provider.id == provider_id)
    card.click()
    provider_page.email_edit.setText(email)
    provider_page.continue_button.click()


def test_the_shell_registers_the_review_page(window):
    assert "review" in window.pages
    assert window.pages["review"] is window.review_page
    assert window.stack.indexOf(window.review_page) >= 0


def test_preferences_continue_reaches_the_review_page(window):
    window.show_page("preferences")

    window.preferences_page.continueRequested.emit()

    assert window.current_page_key() == "review"
    assert window.step_labels["review"].property("active") is True
    assert window.step_labels["preferences"].property("done") is True

def test_the_step_bar_has_translated_accessible_names(page, services):
    t = services.translator.t
    assert page.wizard_step_labels[0].accessibleName() == t(
        "review.wizard.step_of", current=1, total=3
    )

    page.show_step(1)

    assert page.wizard_step_labels[0].accessibleName() == t(
        "review.wizard.done_summary",
        summary=t("review.wizard.steps.scan"),
    )
    assert page.wizard_step_labels[1].accessibleName() == t(
        "review.wizard.step_of", current=2, total=3
    )
