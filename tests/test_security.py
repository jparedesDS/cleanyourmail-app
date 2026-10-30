from __future__ import annotations

import unittest

from cleanyourmail_app.security import SessionStore


class SessionTest(unittest.TestCase):
    def test_create_get_and_destroy(self):
        store = SessionStore()
        session = store.create()
        self.assertIsNotNone(store.get(session.session_id))
        self.assertTrue(store.token_matches(session.csrf, session.csrf))
        self.assertFalse(store.token_matches(session.csrf, "wrong"))
        store.destroy(session.session_id)
        self.assertIsNone(store.get(session.session_id))

    def test_expired_session_is_dropped(self):
        store = SessionStore(ttl=1)
        session = store.create()
        session.last_seen -= 2
        self.assertIsNone(store.get(session.session_id))

    def test_many_sessions_are_bounded(self):
        store = SessionStore()
        ids = [store.create().session_id for _ in range(12)]
        self.assertLessEqual(len(store._sessions), 8)
        self.assertIsNotNone(store.get(ids[-1]))


if __name__ == "__main__":
    unittest.main()
