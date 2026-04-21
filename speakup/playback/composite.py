from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

from ..errors import AdapterError

_DEFAULT_SAMPLE_RATE = 44_100
_DEFAULT_CHANNEL_LAYOUT = "stereo"


def _seconds(value_ms: int) -> str:
    return f"{value_ms / 1000:.3f}"


def compose_audio_segments(
    paths: list[Path],
    *,
    output_dir: Path,
    lead_in_ms: int = 120,
    gap_ms: int = 60,
) -> Path:
    normalized_paths = [Path(path) for path in paths]
    if len(normalized_paths) < 2:
        raise AdapterError("Need at least two audio paths to compose playback")

    missing = [str(path) for path in normalized_paths if not path.exists()]
    if missing:
        raise AdapterError(f"Cannot compose missing audio files: {', '.join(missing)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"playback-{uuid4().hex}.wav"
    ffmpeg_bin = os.environ.get("SPEAKUP_FFMPEG_BIN", "ffmpeg")

    command = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y"]
    input_count = 0
    filter_parts: list[str] = []
    concat_inputs: list[str] = []

    def add_silence(duration_ms: int) -> None:
        nonlocal input_count
        if duration_ms <= 0:
            return
        command.extend(
            [
                "-f",
                "lavfi",
                "-t",
                _seconds(duration_ms),
                "-i",
                f"anullsrc=r={_DEFAULT_SAMPLE_RATE}:cl={_DEFAULT_CHANNEL_LAYOUT}",
            ]
        )
        filter_parts.append(
            f"[{input_count}:a]aformat=sample_fmts=s16:sample_rates={_DEFAULT_SAMPLE_RATE}:channel_layouts={_DEFAULT_CHANNEL_LAYOUT},asetpts=N/SR/TB[a{input_count}]"
        )
        concat_inputs.append(f"[a{input_count}]")
        input_count += 1

    add_silence(lead_in_ms)

    for index, path in enumerate(normalized_paths):
        command.extend(["-i", str(path)])
        filter_parts.append(
            f"[{input_count}:a]aformat=sample_fmts=s16:sample_rates={_DEFAULT_SAMPLE_RATE}:channel_layouts={_DEFAULT_CHANNEL_LAYOUT},asetpts=N/SR/TB[a{input_count}]"
        )
        concat_inputs.append(f"[a{input_count}]")
        input_count += 1
        if index < len(normalized_paths) - 1:
            add_silence(gap_ms)

    filter_parts.append(
        f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}:v=0:a=1[out]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-ar",
            str(_DEFAULT_SAMPLE_RATE),
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )

    try:
        subprocess.run(command, check=True, capture_output=True)
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        detail = exc.stderr.decode("utf-8", errors="replace").strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        raise AdapterError(f"Audio composition failed: {detail}") from exc

    return output_path
