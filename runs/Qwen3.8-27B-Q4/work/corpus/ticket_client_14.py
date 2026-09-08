===== ticket/client_14.py =====
"""HTTP client wrapper for the ticket service. Stateless between calls."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Callable


class TicketApiError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"ticket api returned {status}: {body[:200]}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 0.2
    max_delay: float = 5.0
    jitter: float = 0.1

    def delay_for(self, attempt: int) -> float:
        raw = min(self.base_delay * (2 ** attempt), self.max_delay)
        return raw + random.random() * self.jitter


class TicketClient:
    def __init__(self, base_url: str, token: str, policy: RetryPolicy | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._policy = policy or RetryPolicy()

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._token}", "content-type": "application/json"}

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    def _send(self, transport: Callable[..., Any], method: str, path: str, body: Any) -> Any:
        last: Exception | None = None
        for attempt in range(self._policy.attempts):
            try:
                status, text = transport(method, self._url(path), self._headers(), json.dumps(body) if body else None)
                if status >= 500:
                    raise TicketApiError(status, text)
                if status >= 400:
                    raise TicketApiError(status, text)
                return json.loads(text) if text else None
            except TicketApiError as exc:
                last = exc
                if exc.status < 500:
                    raise
                time.sleep(self._policy.delay_for(attempt))
        assert last is not None
        raise last

    def fetch_ticket(self, transport: Callable[..., Any], ticket_id: str) -> dict[str, Any]:
        return self._send(transport, "GET", f"/tickets/{ticket_id}", None)

    def list_tickets(self, transport: Callable[..., Any], cursor: str | None = None) -> dict[str, Any]:
        suffix = f"?cursor={cursor}" if cursor else ""
        return self._send(transport, "GET", f"/tickets{suffix}", None)

    def create_ticket(self, transport: Callable[..., Any], payload: dict[str, Any]) -> dict[str, Any]:
        return self._send(transport, "POST", "/tickets", payload)

    def delete_ticket(self, transport: Callable[..., Any], ticket_id: str) -> None:
        self._send(transport, "DELETE", f"/tickets/{ticket_id}", None)

    def paginate(self, transport: Callable[..., Any], limit: int = 1000) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(out) < limit:
            page = self.list_tickets(transport, cursor)
            out.extend(page.get("items", []))
            cursor = page.get("next_cursor")
            if not cursor:
                break
        return out[:limit]

