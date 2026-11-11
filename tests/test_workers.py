"""The background worker must fail closed when a thread cannot start."""

from __future__ import annotations

import threading

from cleanyourmail_app.ui.workers import BackgroundCall


def test_start_returns_false_when_the_thread_cannot_start(monkeypatch):
    worker = BackgroundCall()
    monkeypatch.setattr(
        threading.Thread,
        "start",
        lambda self: (_ for _ in ()).throw(RuntimeError("no thread")),
    )

    assert worker.start(lambda: None) is False
    assert worker.active is False


def test_worker_can_start_again_after_a_thread_failure(qtbot, monkeypatch):
    worker = BackgroundCall()
    real_start = threading.Thread.start
    attempts = 0

    def flaky_start(self) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("no thread")
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", flaky_start)

    assert worker.start(lambda: 42) is False
    assert worker.active is False

    with qtbot.waitSignal(worker.succeeded, timeout=3000) as blocker:
        assert worker.start(lambda: 42) is True
    assert blocker.args == [42]
