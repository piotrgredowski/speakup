from __future__ import annotations

from ..models import MessageEvent, NotifyRequest


def request_from_pi_payload(payload: dict) -> NotifyRequest:
    message = payload.get("message") or payload.get("text") or ""
    event_raw = payload.get("event", "final")
    try:
        event = MessageEvent(event_raw)
    except Exception:
        event = MessageEvent.FINAL

    return NotifyRequest(
        message=message,
        event=event,
        conversation_id=payload.get("conversationId"),
        task_id=payload.get("taskId"),
        agent=payload.get("agent", "pi"),
        metadata=payload.get("metadata", {}),
    )
