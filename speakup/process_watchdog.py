from __future__ import annotations

import argparse
import os
import signal
import subprocess
import time

from .runtime import RuntimeStateStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Stop an idle SpeakUp-managed provider process.")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--idle-timeout-seconds", type=float, required=True)
    parser.add_argument("--check-interval-seconds", type=float, default=60.0)
    args = parser.parse_args()

    if args.idle_timeout_seconds <= 0:
        return

    store = RuntimeStateStore()
    while True:
        time.sleep(max(1.0, args.check_interval_seconds))
        process = store.get_provider_process(args.provider)
        if process is None or process.pid != args.pid:
            return
        if not store.pid_is_alive(args.pid):
            store.delete_provider_process_if_pid(args.provider, args.pid)
            return
        expected_command = _expected_command(process.payload)
        if expected_command is None or _current_command(args.pid) != expected_command:
            store.delete_provider_process_if_pid(args.provider, args.pid)
            return
        if time.time() - process.last_seen_at < args.idle_timeout_seconds:
            continue

        try:
            os.kill(args.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        store.delete_provider_process_if_pid(args.provider, args.pid)
        return


def _current_command(pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    command = result.stdout.strip()
    return command or None


def _expected_command(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    command = payload.get("command")
    if not isinstance(command, list):
        return None
    return " ".join(str(part) for part in command)


if __name__ == "__main__":
    main()
