from __future__ import annotations

from ..models import MessageEvent, NotifyRequest


def request_from_pi_payload(payload: dict) -> NotifyRequest:
    message = payload.get("message") or payload.get("text") or ""
    event_raw = payload.get("event", "final")
    try:
        event = MessageEvent(event_raw)
    except Exception:
        event = MessageEvent.FINAL

    conversation_id = payload.get("conversationId")
    session_name = conversation_id
    for key in ("sessionTitle", "session_title", "session-name", "sessionName", "title"):
        if key in payload:
            value = payload.get(key)
            session_name = value.strip() if isinstance(value, str) else value
            break

    return NotifyRequest(
        message=message,
        event=event,
        session_name=session_name,
        conversation_id=conversation_id,
        task_id=payload.get("taskId"),
        agent=payload.get("agent", "pi"),
        precomputed_summary=payload.get("summary"),
        metadata=payload.get("metadata", {}),
    )
