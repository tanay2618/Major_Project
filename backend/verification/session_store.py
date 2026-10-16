"""
In-memory verification sessions.

* Holds the uploaded page images only in RAM - nothing is written to disk.
* Every session belongs to one user; other users cannot read or delete it.
* Sessions expire after SESSION_TTL_SECONDS and are wiped (lazy purge on access).
* Limits concurrent sessions and upload rate per user.

NOTE: this is per-process memory. If you later run several worker processes,
move this to Redis (with encryption) - one worker will not see another's sessions.
"""
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config


@dataclass
class VerificationSession:
    id: str
    user_id: int
    pages: List[bytes]  # PNG bytes, re-encoded, one per page (max 2)
    source_type: str  # "image" | "pdf"
    file_meta: Dict[str, Any]  # editor/producer strings etc. captured BEFORE re-encoding
    created_at: float = field(default_factory=time.time)
    results: Dict[str, Any] = field(default_factory=dict)

    def wipe(self) -> None:
        """Drop the image bytes and all results."""
        self.pages = []
        self.file_meta = {}
        self.results = {}


class RateLimitError(Exception):
    pass


class SessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, VerificationSession] = {}
        self._upload_times: Dict[int, List[float]] = {}
        self._lock = threading.Lock()

    # -- internal helpers (call with lock held) ----------------------------
    def _purge_expired(self) -> None:
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.created_at > config.SESSION_TTL_SECONDS
        ]
        for sid in expired:
            self._sessions.pop(sid).wipe()

    # -- public API ----------------------------------------------------------
    def create(self, user_id: int, pages: List[bytes], source_type: str,
               file_meta: Dict[str, Any]) -> VerificationSession:
        with self._lock:
            self._purge_expired()

            now = time.time()
            recent = [t for t in self._upload_times.get(user_id, []) if now - t < 60]
            if len(recent) >= config.MAX_UPLOADS_PER_MINUTE_PER_USER:
                raise RateLimitError("Too many uploads. Please wait a minute and try again.")
            recent.append(now)
            self._upload_times[user_id] = recent

            # Oldest sessions of this user are evicted so a retry never gets stuck.
            mine = sorted(
                (s for s in self._sessions.values() if s.user_id == user_id),
                key=lambda s: s.created_at,
            )
            while len(mine) >= config.MAX_ACTIVE_SESSIONS_PER_USER:
                oldest = mine.pop(0)
                self._sessions.pop(oldest.id).wipe()

            session = VerificationSession(
                id=secrets.token_urlsafe(32),
                user_id=user_id,
                pages=pages,
                source_type=source_type,
                file_meta=file_meta,
            )
            self._sessions[session.id] = session
            return session

    def get(self, session_id: str, user_id: int) -> Optional[VerificationSession]:
        """Returns the session only if it exists, is unexpired and belongs to user_id."""
        with self._lock:
            self._purge_expired()
            s = self._sessions.get(session_id)
            if s is None or s.user_id != user_id:
                return None
            return s

    def delete(self, session_id: str, user_id: int) -> bool:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None or s.user_id != user_id:
                return False
            self._sessions.pop(session_id).wipe()
            return True


store = SessionStore()
