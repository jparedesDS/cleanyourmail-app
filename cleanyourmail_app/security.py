"""One-time startup token, in-memory sessions and CSRF helpers."""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass

SESSION_COOKIE = "cym_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 8


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass
class Session:
    session_id: str
    csrf: str
    created: float
    last_seen: float


class SessionStore:
    def __init__(self, ttl: int = SESSION_TTL_SECONDS) -> None:
        self.ttl = ttl
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        self.prune()
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda item: item.last_seen)
            self._sessions.pop(oldest.session_id, None)
        now = time.time()
        session = Session(
            session_id=new_token(),
            csrf=new_token(),
            created=now,
            last_seen=now,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        now = time.time()
        if now - session.last_seen > self.ttl:
            self._sessions.pop(session_id, None)
            return None
        session.last_seen = now
        return session

    def destroy(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def prune(self) -> None:
        now = time.time()
        expired = [key for key, value in self._sessions.items()
                   if now - value.last_seen > self.ttl]
        for key in expired:
            self._sessions.pop(key, None)

    def token_matches(self, expected: str, provided: str) -> bool:
        return hmac.compare_digest(expected, provided)
