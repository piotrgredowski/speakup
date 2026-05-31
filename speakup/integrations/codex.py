from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..app_logging import setup_logging as setup_app_logging
from ..config import load_config_with_repository_registration
from ..history import NotificationHistory
from ..models import MessageEvent, NotifyRequest
from ..service import NotifyService
from ..session_naming import normalize_session_name_candidate

_PAYLOAD_FILE_ARG = "--payload-file"
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_PROPOSED_PLAN_PATTERN = re.compile(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", re.DOTALL | re.IGNORECASE)
_HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,6}\s+")


def build_codex_notify_request(
    *,
    message: str,
    event: str,
    session_name: str | None = None,
    session_id: str | None = None,
    session_key: str | None = None,
    cwd: str | None = None,
    source_tool: str | None = None,
    precomputed_summary: str | None = None,
    skip_summarization: bool = False,
) -> NotifyRequest:
    try:
        message_event = MessageEvent(event)
    except Exception:
        message_event = MessageEvent.FINAL

    return NotifyRequest(
        message=message,
        event=message_event,
        source_tool=source_tool,
        session_name=session_name,
        session_id=session_id or (session_key if session_key else None),
        session_key=session_key,
        agent="codex",
        precomputed_summary=precomputed_summary,
        skip_summarization=skip_summarization,
        metadata={"cwd": cwd} if cwd else {},
    )


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _nested_get(payload: dict, *path: str) -> object:
    value: object = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def extract_session_key(payload: dict) -> str | None:
    return _first_string(
        payload.get("conversation_id"),
        payload.get("conversationId"),
        payload.get("session_key"),
        payload.get("sessionKey"),
        payload.get("session_id"),
        payload.get("sessionId"),
        _nested_get(payload, "session", "id"),
        _nested_get(payload, "session", "session_id"),
        _nested_get(payload, "session", "sessionId"),
        _nested_get(payload, "message", "conversation_id"),
        _nested_get(payload, "message", "session_id"),
    )


def extract_session_id(payload: dict) -> str | None:
    return _first_string(
        payload.get("session_id"),
        payload.get("sessionId"),
        _nested_get(payload, "session", "id"),
        _nested_get(payload, "session", "session_id"),
        _nested_get(payload, "session", "sessionId"),
        extract_session_key(payload),
    )


def extract_session_name(payload: dict) -> str | None:
    candidates = (
        payload.get("session_name"),
        payload.get("sessionName"),
        payload.get("session_title"),
        payload.get("sessionTitle"),
        payload.get("title"),
        _nested_get(payload, "session", "name"),
        _nested_get(payload, "session", "title"),
        _nested_get(payload, "session", "sessionName"),
        _nested_get(payload, "session", "sessionTitle"),
        _nested_get(payload, "metadata", "session_name"),
        _nested_get(payload, "metadata", "sessionName"),
        _nested_get(payload, "metadata", "session_title"),
        _nested_get(payload, "metadata", "sessionTitle"),
    )
    for candidate in candidates:
        if normalized := normalize_session_name_candidate(candidate):
            return normalized
    return None


def _extract_text_from_content(content: object) -> str | None:
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    text = "\n".join(part.strip() for part in parts if part.strip()).strip()
    return text or None


def extract_message(payload: dict) -> str | None:
    message = payload.get("message")
    if isinstance(message, str):
        return message.strip() or None
    if isinstance(message, dict):
        content_text = _extract_text_from_content(message.get("content"))
        if content_text:
            return content_text
        return _first_string(message.get("text"), message.get("message"), message.get("summary"))

    if text := _extract_text_from_content(payload.get("content")):
        return text

    if transcript_path := _first_string(payload.get("transcript_path"), payload.get("transcriptPath")):
        return extract_message_from_transcript(transcript_path)

    return _first_string(payload.get("text"), payload.get("summary"))


def extract_message_from_transcript(transcript_path: str) -> str | None:
    path = Path(transcript_path)
    if not path.exists():
        return None

    last_assistant_text: str | None = None
    for line in path.read_text(errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        if text := _extract_text_from_content(message.get("content")):
            last_assistant_text = text
    return last_assistant_text


def _first_spoken_plan_line(lines: list[str]) -> str | None:
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        if _MARKDOWN_HEADING_PATTERN.match(stripped):
            continue
        return stripped
    return None


def detect_plan_approval_message(message: str) -> str | None:
    match = _PROPOSED_PLAN_PATTERN.search(message)
    if not match:
        return None

    plan = match.group(1).strip()
    if not plan:
        return "Codex is waiting for plan approval."

    if heading := _HEADING_PATTERN.search(plan):
        title = heading.group(1).strip().rstrip(".:;!?")
        if title:
            return f"Codex is waiting for plan approval: {title}."

    lines = plan.splitlines()
    if spoken := _first_spoken_plan_line(lines):
        return f"Codex is waiting for plan approval. {spoken}"

    return "Codex is waiting for plan approval."


def plan_approval_dedupe_key(message: str) -> str:
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return f"plan:{digest}"


def _session_slug(session_key: str) -> str:
    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()
    return digest


def get_plan_approval_state_path(session_key: str) -> Path:
    return Path.home() / ".config" / "speakup" / "codex-plan-approval-state" / f"{_session_slug(session_key)}.json"


def _read_plan_approval_state(session_key: str) -> dict[str, object]:
    path = get_plan_approval_state_path(session_key)
    if not path.exists():
        return {"seen_ids": []}
    try:
        state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"seen_ids": []}
    return state if isinstance(state, dict) else {"seen_ids": []}


def plan_approval_seen(session_key: str | None, dedupe_key: str) -> bool:
    if not session_key:
        return False
    state = _read_plan_approval_state(session_key)
    seen_ids = state.get("seen_ids")
    return isinstance(seen_ids, list) and dedupe_key in seen_ids


def mark_plan_approval_seen(session_key: str | None, dedupe_key: str) -> None:
    if not session_key:
        return
    state = _read_plan_approval_state(session_key)
    seen_ids = state.get("seen_ids")
    if not isinstance(seen_ids, list):
        seen_ids = []
    if dedupe_key not in seen_ids:
        seen_ids.append(dedupe_key)
    path = get_plan_approval_state_path(session_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen_ids": seen_ids}, indent=2) + "\n")


def request_from_codex_payload(payload: dict) -> NotifyRequest:
    hook_event = str(payload.get("hook_event_name") or payload.get("event") or "")
    raw_message = extract_message(payload) or ""
    session_key = extract_session_key(payload)
    session_id = extract_session_id(payload)
    session_name = extract_session_name(payload)
    cwd = _first_string(payload.get("cwd"), _nested_get(payload, "metadata", "cwd"))

    if raw_message and (plan_message := detect_plan_approval_message(raw_message)):
        return build_codex_notify_request(
            message=plan_message,
            event=MessageEvent.NEEDS_INPUT.value,
            session_name=session_name,
            session_id=session_id,
            session_key=session_key,
            cwd=cwd,
            source_tool="Codex",
            precomputed_summary=plan_message,
            skip_summarization=True,
        )

    event = MessageEvent.FINAL.value if hook_event.casefold() == "stop" else MessageEvent.NEEDS_INPUT.value
    return build_codex_notify_request(
        message=raw_message,
        event=event,
        session_name=session_name,
        session_id=session_id,
        session_key=session_key,
        cwd=cwd,
        source_tool="Codex",
    )


def _pointer_slug(cwd: str) -> str:
    return cwd.replace("/", "-").replace("\\", "-").replace(":", "-").strip("-") or "unknown"


def get_session_pointer_path(cwd: str) -> Path:
    return Path.home() / ".config" / "speakup" / "codex-session-pointers" / f"{_pointer_slug(cwd)}.json"


def save_current_session_pointer(cwd: str | None, session_key: str | None, session_name: str | None = None) -> None:
    if not cwd or not session_key:
        return
    path = get_session_pointer_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"session_key": session_key, "session_name": session_name}, indent=2)
        + "\n"
    )


def build_replay_command(session_key: str, count: int = 1) -> str:
    return f"speakup replay {count} --agent codex --session-key {session_key}"


def build_hook_output(session_key: str | None, session_name: str | None = None) -> str:
    if not session_key:
        return ""
    replay = f"Replay cmd: {build_replay_command(session_key)}"
    if session_name:
        return f"Session: {session_name}\n{replay}"
    return replay


def _serialize_request(request: NotifyRequest) -> dict[str, object]:
    payload = asdict(request)
    payload["event"] = request.event.value
    return payload


def _deserialize_request(payload: dict[str, object]) -> NotifyRequest:
    event = payload.get("event", MessageEvent.FINAL.value)
    try:
        payload["event"] = MessageEvent(str(event))
    except Exception:
        payload["event"] = MessageEvent.FINAL
    return NotifyRequest(**payload)


def _write_payload_file(request: NotifyRequest, config_path: str | Path | None) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="speakup-codex-", suffix=".json")
    payload_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "request": _serialize_request(request),
                    "config_path": str(config_path) if config_path else None,
                },
                handle,
            )
    except Exception:
        payload_path.unlink(missing_ok=True)
        raise
    return payload_path


def _detach_stdio() -> None:
    try:
        devnull = open(os.devnull, "a", encoding="utf-8")
    except OSError:
        return

    sys.stdin = devnull
    sys.stdout = devnull
    sys.stderr = devnull


def _notify_worker(request: NotifyRequest, config_path: str | None) -> None:
    _detach_stdio()
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    cwd = metadata.get("cwd") if isinstance(metadata.get("cwd"), str) else None
    config = load_config_with_repository_registration(Path(config_path) if config_path else None, cwd)
    setup_app_logging(config.get("logging", default={}))
    NotifyService(
        config,
        history=NotificationHistory(retention_days=int(config.get("history", "retention_days", default=30))),
    ).notify(request)


def _run_payload_file(payload_path: str | Path) -> None:
    path = Path(payload_path)
    try:
        payload = json.loads(path.read_text())
    finally:
        path.unlink(missing_ok=True)

    request = _deserialize_request(dict(payload["request"]))
    config_path = payload.get("config_path")
    _notify_worker(request, str(config_path) if config_path else None)


def notify_in_background(request: NotifyRequest, *, config_path: str | Path | None = None) -> int:
    payload_path = _write_payload_file(request, config_path)
    env = dict(os.environ)
    pythonpath_parts = [str(_PACKAGE_ROOT)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    cmd = [
        sys.executable,
        "-m",
        "speakup.integrations.codex",
        _PAYLOAD_FILE_ARG,
        str(payload_path),
    ]
    try:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except Exception:
        payload_path.unlink(missing_ok=True)
        raise
    return process.pid or 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != _PAYLOAD_FILE_ARG:
        raise SystemExit(f"Usage: python -m speakup.integrations.codex {_PAYLOAD_FILE_ARG} <path>")

    _run_payload_file(args[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
