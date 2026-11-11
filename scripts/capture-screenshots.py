"""Capture the two documentation screenshots with synthetic data.

Run from the repo root:

    python scripts/capture-screenshots.py

The Qt platform is forced offscreen so no real desktop session is needed. The
window uses a temporary settings store and a never-executed fake CLI command, so
no real account, secret or mailbox is touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cleanyourmail_app.domain.models import AppSettings, Preferences  # noqa: E402
from cleanyourmail_app.i18n import Translator  # noqa: E402
from cleanyourmail_app.services.app_services import AppServices  # noqa: E402
from cleanyourmail_app.services.cli import CliClient  # noqa: E402
from cleanyourmail_app.services.config import ConfigService  # noqa: E402
from cleanyourmail_app.services.settings import SettingsStore  # noqa: E402
from cleanyourmail_app.ui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "images"

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

REPORT = {
    "account": "demo@example.com",
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
            "unsubscribe": {"mode": "manual", "automatic": False, "url": None},
            "recommended": "move",
        },
    ],
    "stale": [],
    "manual_unsubscribe": [],
    "protected": [],
    "auto_unsubscribe": [],
}

PLAN = {
    "version": 1,
    "generated": "2026-11-10T12:00:00+00:00",
    "account": "demo@example.com",
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
    "groups": [],
}


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)

    with tempfile.TemporaryDirectory(prefix="cym-shots-") as temporary:
        base = Path(temporary)
        settings = SettingsStore(base / "settings.json")
        settings.save(
            AppSettings(
                provider="gmail",
                email="demo@example.com",
                preferences=Preferences(categories=["newsletter", "promotion"]),
            )
        )
        services = AppServices(
            cli=CliClient([sys.executable, str(base / "fake-cli.py")]),
            config=ConfigService(
                CliClient([sys.executable, str(base / "fake-cli.py")]),
                base / "appdata",
                base / "secret.txt",
            ),
            settings=settings,
            translator=Translator("en"),
        )
        window = MainWindow(settings, services.translator, services)
        window.resize(1040, 980)
        window.show()
        app.processEvents()

        card = next(
            item for item in window.provider_page.cards if item.provider.id == "gmail"
        )
        card.click()
        window.provider_page.email_edit.setText("demo@example.com")
        app.processEvents()
        window.grab().save(str(OUTPUT / "app-provider.png"))

        window.show_page("review")
        review = window.review_page
        review.set_scan({"ok": True, "exit_code": 0, "data": SCAN, "stdout": "", "stderr": ""})
        review.set_report({"ok": True, "exit_code": 0, "data": REPORT, "stdout": "", "stderr": ""})
        review.set_plan(
            {
                "ok": True,
                "exit_code": 0,
                "data": {"path": "plan.json", "plan": PLAN},
                "stdout": "",
                "stderr": "",
            }
        )
        app.processEvents()
        review.scroll.ensureWidgetVisible(review.review_checkbox, 0, 40)
        app.processEvents()
        window.grab().save(str(OUTPUT / "app-review.png"))

        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
