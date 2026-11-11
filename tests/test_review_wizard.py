"""The Review page as a three-step wizard: scan, report and plan.

The page tests use a ``FakeCli`` like the other Review tests. They pin the
navigation (only one step visible at a time, Back keeps completed results), the
step bar, the retranslation of the wizard copy, and the plan cards: an action
may show only the messages it will move, never a protected group's messages.

No test reads a real mailbox, a body or a Message-ID: the fixtures carry
sentinel strings for those fields to prove the page does not render them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QLabel

from cleanyourmail_app.i18n import Translator
from cleanyourmail_app.services.app_services import AppServices
from cleanyourmail_app.services.config import ConfigService
from cleanyourmail_app.ui.pages.review import REPORT_TOP, ReviewPage

SCAN = {
    "mailboxes": {"INBOX": {"uidvalidity": 7, "found": 10, "cached": 10}},
    "categories": {"newsletter": 6, "promotion": 4},
    "total": 10,
}

REPORT = {
    "totals": {"messages": 10, "groups": 2, "protected": 3},
    "groups": [
        {
            "key": "newsletter-example",
            "category": "newsletter",
            "domain": "news.example",
            "count": 6,
            "unread": 1,
            "samples": ["Weekly digest", "New arrivals", "Editor's picks"],
            "unsubscribe": {"mode": "one-click"},
        },
        {
            "key": "promotion-shop",
            "category": "promotion",
            "domain": "shop.example",
            "count": 4,
            "unread": 1,
            "samples": ["Autumn sale"],
            "unsubscribe": {"mode": "manual"},
        },
    ],
}

LONG_SUBJECT = "A long subject that must wrap inside the card " * 8

PLAN_MESSAGES = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 10, "groups": 3, "protected": 3},
    "actions": [
        {
            "id": "a1",
            "type": "move",
            "group": "newsletter-example",
            "category": "newsletter",
            "mailbox": "INBOX",
            "uids": [1, 2],
            "dest": "CleanYourMail/Newsletters",
        },
        {
            "id": "a2",
            "type": "move",
            "group": "promotion-shop",
            "category": "promotion",
            "mailbox": "INBOX",
            "uids": [5, 6],
            "dest": "CleanYourMail/Promotions",
        },
    ],
    "groups": [
        {
            "key": "newsletter-example",
            "category": "newsletter",
            "domain": "news.example",
            "count": 6,
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
                {
                    "uid": 4,
                    "mailbox": "INBOX",
                    "sender": "news@news.example",
                    "name": "Example News",
                    "subject": "Members only",
                    "date": "2026-10-04T08:00:00+00:00",
                },
            ],
        },
        {
            "key": "promotion-shop",
            "category": "promotion",
            "domain": "shop.example",
            "count": 4,
            "messages": [
                {
                    "uid": 5,
                    "mailbox": "INBOX",
                    "sender": "sale@shop.example",
                    "name": "Example Shop",
                    "subject": "Autumn sale",
                    "date": "2026-10-05T08:00:00+00:00",
                },
                {
                    "uid": 6,
                    "mailbox": "INBOX",
                    "sender": "sale@shop.example",
                    "name": "Example Shop",
                    "subject": LONG_SUBJECT,
                    "date": "2026-10-06T08:00:00+00:00",
                    "body": "BODY-SENTINEL",
                    "message_id": "MSGID-SENTINEL",
                },
            ],
        },
        {
            "key": "protected-bank",
            "category": "newsletter",
            "domain": "bank.example",
            "count": 1,
            "protected": True,
            "messages": [
                {
                    "uid": 99,
                    "mailbox": "INBOX",
                    "sender": "alerts@bank.example",
                    "name": "Bank",
                    "subject": "PROTECTED-SENTINEL",
                    "date": "2026-10-07T08:00:00+00:00",
                }
            ],
        },
    ],
}

PLAN_MORE_PREVIEWS = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 5, "groups": 1, "protected": 0},
    "actions": [
        {
            "id": "a1",
            "type": "move",
            "group": "newsletter-example",
            "category": "newsletter",
            "mailbox": "INBOX",
            "uids": [1, 2, 3, 4, 5],
            "dest": "CleanYourMail/Newsletters",
        }
    ],
    "groups": [
        {
            "key": "newsletter-example",
            "category": "newsletter",
            "domain": "news.example",
            "count": 5,
            "messages": [
                {
                    "uid": uid,
                    "mailbox": "INBOX",
                    "sender": "news@news.example",
                    "name": "Example News",
                    "subject": f"Preview {uid}",
                    "date": "2026-10-01T08:00:00+00:00",
                }
                for uid in (1, 2, 3)
            ],
        }
    ],
}

PLAN_SAMPLES_ONLY = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 4, "groups": 1, "protected": 0},
    "actions": [
        {
            "id": "a1",
            "type": "move",
            "group": "old-style",
            "category": "newsletter",
            "mailbox": "INBOX",
            "uids": [1, 2, 3, 4],
            "dest": "CleanYourMail/Newsletters",
        }
    ],
    "groups": [
        {
            "key": "old-style",
            "category": "newsletter",
            "domain": "old.example",
            "count": 4,
            "samples": ["Old digest", "Old arrivals"],
        }
    ],
}

PLAN_SAMPLES_OVER = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 3, "groups": 1, "protected": 0},
    "actions": [
        {
            "id": "a1",
            "type": "move",
            "group": "old-style",
            "category": "newsletter",
            "mailbox": "INBOX",
            "uids": [1],
            "dest": "CleanYourMail/Newsletters",
        }
    ],
    "groups": [
        {
            "key": "old-style",
            "category": "newsletter",
            "domain": "old.example",
            "count": 3,
            "samples": ["Old digest", "Old arrivals", "Old picks"],
        }
    ],
}

PLAN_ZERO = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 0, "groups": 0, "protected": 0},
    "actions": [],
    "groups": [],
}

PLAN_UNSUBSCRIBE_ONLY = {
    "version": 1,
    "mode": "folders",
    "stats": {"messages": 6, "groups": 1, "protected": 0},
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


def _result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "exit_code": 0,
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
        self.plan_result: Any = _plan_result(PLAN_MESSAGES)

    def scan(self, days: int, *, config_path: Path | None = None) -> dict[str, Any]:
        self.calls.append(("scan", days, config_path))
        return self.scan_result

    def report(self, top: int = REPORT_TOP, *, config_path: Path | None = None):
        self.calls.append(("report", top, config_path))
        return self.report_result

    def plan(
        self,
        mode: str,
        categories: list[str],
        *,
        config_path: Path | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("plan", mode, list(categories), config_path))
        return self.plan_result


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


def _wait(page: ReviewPage, qtbot, timeout: int = 5000) -> None:
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=timeout)


def _texts(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def _plan_card(page: ReviewPage, index: int):
    return page.plan_cards_layout.itemAt(index).widget()


# --- Steps 1 and 2 ---------------------------------------------------------


def test_the_page_starts_on_the_scan_step_with_only_its_content(page, services):
    t = services.translator.t

    assert page.current_step() == 0
    assert page.scan_step.isHidden() is False
    assert page.report_step.isHidden() is True
    assert page.plan_step.isHidden() is True
    assert page.scan_title_label.text() == t("review.wizard.scan.title")
    assert page.scan_body_label.text() == t("review.wizard.scan.body")
    assert page.scan_button.text() == t("review.wizard.scan.action")
    assert page.scan_result.isHidden() is True
    assert page.scan_continue_button.isHidden() is True
    assert page.report_continue_button.isHidden() is True
    assert page.status_label.isHidden() is True
    assert page.error_label.isHidden() is True


def test_a_successful_scan_shows_the_result_and_continues(page, cli, qtbot, services):
    t = services.translator.t

    page.start_scan()
    _wait(page, qtbot)

    assert cli.calls[-1][:2] == ("scan", 365)
    assert page.current_step() == 0
    assert page.scan_result.isHidden() is False
    assert page.scan_continue_button.isHidden() is False
    assert page.scan_result_label.text() == t(
        "review.wizard.scan.result", messages=10, categories=2
    )

    page.scan_continue_button.click()

    assert page.current_step() == 1
    assert page.scan_step.isHidden() is True
    assert page.report_step.isHidden() is False
    assert page.report_title_label.text() == t("review.wizard.report.title")


def test_a_report_shows_sender_cards_and_continues_to_the_plan(page, services):
    t = services.translator.t
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))

    assert page.current_step() == 1
    assert page.report_result.isHidden() is False
    assert page.report_continue_button.isHidden() is False
    assert page.report_cards_layout.count() == 2
    first = _texts(page.report_cards_layout.itemAt(0).widget())
    assert "news.example" in first
    assert "Weekly digest" in first
    assert t("review.wizard.report.group", count=6, unread=1) in first

    page.report_continue_button.click()

    assert page.current_step() == 2
    assert page.plan_step.isHidden() is False
    assert page.report_step.isHidden() is True
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False


def test_back_preserves_the_scan_and_the_report(page):
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MESSAGES))

    page.step_back_button.click()

    assert page.current_step() == 1
    assert page.report_result.isHidden() is False
    assert page.report_cards_layout.count() == 2
    assert page.report_continue_button.isHidden() is False

    page.step_back_button.click()

    assert page.current_step() == 0
    assert page.scan_result.isHidden() is False
    assert page.scan_total_label.text() == "10"
    assert page.scan_continue_button.isHidden() is False
    assert page.step_back_button.isHidden() is True


def test_back_from_a_long_plan_shrinks_the_step_stack(qtbot, page):
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MESSAGES))
    page.show_step(2)
    qtbot.wait(30)
    tall = page.step_stack.height()

    page.show_step(0)
    qtbot.wait(30)

    assert page.step_stack.height() < tall
    assert page.step_stack.height() <= page.scan_step.sizeHint().height() + 60


def test_the_step_bar_marks_active_and_done_steps(page):
    labels = page.wizard_step_labels

    assert labels[0].property("active") is True
    assert labels[0].property("done") is False

    page.set_scan(_result(SCAN))
    page.show_step(1)

    assert labels[0].property("active") is False
    assert labels[0].property("done") is True
    assert labels[1].property("active") is True
    assert labels[1].property("done") is False

    page.set_report(_result(REPORT))
    page.show_step(2)

    assert labels[1].property("done") is True
    assert labels[2].property("active") is True


def test_show_step_before_a_plan_shows_a_disabled_gate(page, services):
    page.show_step(2)

    assert page.current_step() == 2
    assert page.plan_step.isHidden() is False
    assert page.plan_title_label.text() == services.translator.t(
        "review.wizard.plan.title"
    )
    assert page.plan_result.isHidden() is True
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    assert page.apply_button.isHidden() is False
    assert page.plan_button.text() == services.translator.t(
        "review.wizard.plan.action"
    )


def test_reload_returns_to_the_scan_step_and_clears_everything(page):
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MESSAGES))
    page.review_checkbox.setChecked(True)

    page.reload()

    assert page.current_step() == 0
    assert page.scan_result.isHidden() is True
    assert page.report_result.isHidden() is True
    assert page.plan_result.isHidden() is True
    assert page.scan_total_label.text() == "0"
    assert page.report_cards_layout.count() == 0
    assert page.plan_cards_layout.count() == 0
    assert page.plan_move_count() == 0
    assert page.review_checkbox.isChecked() is False
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isHidden() is True
    assert page.undo_button.isHidden() is True
    assert page.step_back_button.isHidden() is True


def test_a_new_scan_clears_the_report_and_plan_and_returns_to_scan(page, qtbot):
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MESSAGES))

    page.start_scan()

    assert page.current_step() == 0
    assert page.report_result.isHidden() is True
    assert page.plan_result.isHidden() is True
    assert page.plan_move_count() == 0
    assert page.review_checkbox.isEnabled() is False
    _wait(page, qtbot)


def test_a_new_report_clears_the_plan_and_stays_on_the_report(page, qtbot):
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MESSAGES))

    page.start_report()

    assert page.current_step() == 1
    assert page.report_result.isHidden() is False
    assert page.plan_result.isHidden() is True
    assert page.plan_move_count() == 0
    assert page.review_checkbox.isEnabled() is False
    _wait(page, qtbot)


def test_a_new_plan_stays_on_the_plan_step(page, qtbot):
    page.start_plan()
    _wait(page, qtbot)

    assert page.current_step() == 2
    assert page.plan_cards_layout.count() == 2
    assert page.review_checkbox.isEnabled() is True


def test_the_journal_stays_in_the_footer_on_every_step(page):
    for step in (0, 1, 2):
        page.show_step(step)
        assert page.journal_button.isHidden() is False


# --- Copy ------------------------------------------------------------------


def test_retranslation_without_a_plan_updates_the_apply_label(qtbot, services):
    page = ReviewPage(services)
    qtbot.addWidget(page)
    services.translator.set_language("es")

    page.retranslate()

    assert page.apply_button.text() == services.translator.t("review.apply")


def test_spanish_retranslation_updates_the_whole_wizard(page, services):
    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    page.set_plan(_plan_result(PLAN_MESSAGES))
    services.translator.set_language("es")

    page.retranslate()

    t = services.translator.t
    assert [label.text() for label in page.wizard_step_labels] == [
        t("review.wizard.steps.scan"),
        t("review.wizard.steps.report"),
        t("review.wizard.steps.plan"),
    ]
    assert page.scan_title_label.text() == t("review.wizard.scan.title")
    assert page.scan_button.text() == t("review.wizard.scan.action")
    assert page.scan_continue_button.text() == t("review.wizard.scan.continue")
    assert page.report_title_label.text() == t("review.wizard.report.title")
    assert page.report_continue_button.text() == t("review.wizard.report.continue")
    assert page.plan_title_label.text() == t("review.wizard.plan.title")
    assert page.step_back_button.text() == t("review.wizard.back")
    assert page.back_button.text() == t("review.wizard.leave")
    assert page.apply_button.text() == t("review.apply_count", count=4)
    assert page.report_result_label.text() == t(
        "review.wizard.report.result", messages=10, groups=2, protected=3
    )
    plan_text = _texts(page.plan_cards_layout.itemAt(0).widget())
    assert t("preferences.category.newsletter.label") in plan_text
    assert t("review.wizard.plan.count_many", count=2, sender="news.example") in plan_text


# --- Plan message cards ----------------------------------------------------


def test_plan_cards_show_only_the_messages_the_action_will_move(page):
    page.set_plan(_plan_result(PLAN_MESSAGES))

    assert page.plan_cards_layout.count() == 2
    first = _texts(_plan_card(page, 0))
    assert "CleanYourMail/Newsletters" in first
    assert "Your weekly digest" in first
    assert "New arrivals" in first
    assert "Editor's picks" not in first
    assert "Members only" not in first
    assert "2026-10-01 08:00" in first

    second = _texts(_plan_card(page, 1))
    assert "CleanYourMail/Promotions" in second
    assert "Autumn sale" in second
    assert LONG_SUBJECT in second
    assert "2026-10-06 08:00" in second

    everything = _texts(page.plan_cards)
    assert "PROTECTED-SENTINEL" not in everything
    assert "BODY-SENTINEL" not in everything
    assert "MSGID-SENTINEL" not in everything


def test_a_long_subject_wraps_inside_its_card(page):
    page.set_plan(_plan_result(PLAN_MESSAGES))

    labels = [
        label
        for label in page.plan_cards.findChildren(QLabel)
        if LONG_SUBJECT in label.text()
    ]

    assert labels
    assert all(label.wordWrap() for label in labels)


def test_plan_cards_explain_missing_previews(page, services):
    page.set_plan(_plan_result(PLAN_MORE_PREVIEWS))

    card = _texts(_plan_card(page, 0))
    assert "Preview 1" in card
    assert "Preview 2" in card
    assert "Preview 3" in card
    assert "Preview 4" not in card
    assert services.translator.t("review.wizard.plan.more", count=2) in card
    assert page.plan_move_count() == 5


def test_a_plan_without_messages_falls_back_to_samples(page, services):
    page.set_plan(_plan_result(PLAN_SAMPLES_ONLY))

    assert page.current_step() == 2
    card = _texts(_plan_card(page, 0))
    assert "Old digest" in card
    assert "Old arrivals" in card
    assert services.translator.t("review.wizard.plan.more", count=2) in card
    assert page.plan_move_count() == 4
    assert page.review_checkbox.isEnabled() is True


def test_samples_fallback_does_not_show_more_subjects_than_uids(page):
    page.set_plan(_plan_result(PLAN_SAMPLES_OVER))

    card = _texts(_plan_card(page, 0))
    assert "Old digest" in card
    assert "Old arrivals" not in card
    assert "Old picks" not in card
    assert page.plan_move_count() == 1


def test_zero_move_and_unsubscribe_only_plans_keep_the_gate_closed(page, services):
    t = services.translator.t

    page.set_plan(_plan_result(PLAN_ZERO))

    assert page.current_step() == 2
    assert page.plan_move_count() == 0
    assert page.plan_cards_layout.count() == 0
    assert page.plan_summary_label.text() == t("review.zero_moves")
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    assert page.apply_button.text() == t("review.apply")

    page.set_plan(_plan_result(PLAN_UNSUBSCRIBE_ONLY))

    assert page.plan_move_count() == 0
    assert page.plan_cards_layout.count() == 1
    card = _texts(_plan_card(page, 0))
    assert t("review.plan.no_destination") in card
    assert t("review.plan.unsubscribe_one_click") in card
    assert page.review_checkbox.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    page.review_toggled(True)
    assert page.apply_button.isEnabled() is False


def test_the_apply_label_shows_the_move_count_and_only_on_the_plan_step(page):
    t = Translator("en").t

    page.set_scan(_result(SCAN))
    page.set_report(_result(REPORT))
    assert page.apply_button.isHidden() is True
    assert page.undo_button.isHidden() is True

    page.set_plan(_plan_result(PLAN_MESSAGES))

    assert page.apply_button.isHidden() is False
    assert page.apply_button.text() == t("review.apply_count", count=4)

    page.show_step(1)
    assert page.apply_button.isHidden() is True
    assert page.undo_button.isHidden() is True
