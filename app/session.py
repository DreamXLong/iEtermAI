from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from .models import SessionSnapshot, SessionState


class SessionManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot = SessionSnapshot(
            state=SessionState.LOGGED_OUT,
            updated_at=datetime.now(timezone.utc),
            window_detected=False,
        )

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            return self._snapshot.model_copy(deep=True)

    def update(
        self,
        state: SessionState,
        *,
        window_detected: bool | None = None,
        last_command: str | None = None,
        note: str | None = None,
    ) -> SessionSnapshot:
        with self._lock:
            payload = self._snapshot.model_dump()
            payload["state"] = state
            payload["updated_at"] = datetime.now(timezone.utc)
            if window_detected is not None:
                payload["window_detected"] = window_detected
            if last_command is not None:
                payload["last_command"] = last_command
            if note is not None:
                payload["note"] = note
            self._snapshot = SessionSnapshot(**payload)
            return self._snapshot.model_copy(deep=True)
