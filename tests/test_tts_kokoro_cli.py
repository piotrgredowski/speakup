from __future__ import annotations

import stat
from pathlib import Path

import pytest

from let_me_know_agent.errors import AdapterError
from let_me_know_agent.tts.kokoro_cli import KokoroCliTTSAdapter


def _make_cli(tmp_path: Path, script: str) -> Path:
    cli = tmp_path / "kokoro"
    cli.write_text(script)
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    return cli


def test_kokoro_cli_given_valid_command_then_writes_audio_file(tmp_path: Path) -> None:
    cli = _make_cli(
        tmp_path,
        "#!/bin/sh\n"
        "OUT=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output\" ] || [ \"$1\" = \"-o\" ]; then\n"
        "    shift\n"
        "    OUT=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n",
    )

    adapter = KokoroCliTTSAdapter(command=str(cli))
    result = adapter.synthesize("hello", tmp_path / "out", voice="af_heart", speed=1.1, audio_format="mp3")

    assert result.provider == "kokoro_cli"
    assert str(result.value).endswith(".mp3")
    assert Path(str(result.value)).exists()


def test_kokoro_cli_given_nonzero_exit_then_raises_adapter_error(tmp_path: Path) -> None:
    cli = _make_cli(tmp_path, "#!/bin/sh\necho 'boom' >&2\nexit 7\n")
    adapter = KokoroCliTTSAdapter(command=str(cli))

    with pytest.raises(AdapterError) as exc:
        adapter.synthesize("hello", tmp_path / "out")

    assert "exit code 7" in str(exc.value)


def test_kokoro_cli_given_no_output_file_then_raises_adapter_error(tmp_path: Path) -> None:
    cli = _make_cli(tmp_path, "#!/bin/sh\nexit 0\n")
    adapter = KokoroCliTTSAdapter(command=str(cli))

    with pytest.raises(AdapterError) as exc:
        adapter.synthesize("hello", tmp_path / "out")

    assert "did not produce audio file" in str(exc.value)


def test_kokoro_cli_given_long_flags_in_config_then_normalizes_and_succeeds(tmp_path: Path) -> None:
    cli = _make_cli(
        tmp_path,
        "#!/bin/sh\n"
        "OUT=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then\n"
        "    shift\n"
        "    OUT=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n",
    )
    adapter = KokoroCliTTSAdapter(
        command=str(cli),
        args=["--output", "{output}", "--voice", "{voice}", "--speed", "{speed}", "--text", "{text}"],
    )

    result = adapter.synthesize("hello", tmp_path / "out", voice="af_heart", speed=1.0, audio_format="mp3")
    assert Path(str(result.value)).exists()


def test_kokoro_cli_given_default_voice_then_uses_adapter_default_voice(tmp_path: Path) -> None:
    cli = _make_cli(
        tmp_path,
        "#!/bin/sh\n"
        "OUT=''\n"
        "VOICE=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then shift; OUT=\"$1\"; fi\n"
        "  if [ \"$1\" = \"-m\" ]; then shift; VOICE=\"$1\"; fi\n"
        "  shift\n"
        "done\n"
        "if [ \"$VOICE\" = \"default\" ]; then echo 'bad voice' >&2; exit 9; fi\n"
        "echo 'FAKEAUDIO' > \"$OUT\"\n",
    )
    adapter = KokoroCliTTSAdapter(command=str(cli), default_voice="af_heart")
    result = adapter.synthesize("hello", tmp_path / "out", voice="default", speed=1.0, audio_format="mp3")
    assert Path(str(result.value)).exists()


def test_kokoro_cli_given_wav_payload_with_mp3_suffix_then_normalizes_extension(tmp_path: Path) -> None:
    cli = _make_cli(
        tmp_path,
        "#!/bin/sh\n"
        "OUT=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then shift; OUT=\"$1\"; fi\n"
        "  shift\n"
        "done\n"
        "python - <<'PY' \"$OUT\"\n"
        "import struct\n"
        "import sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[1])\n"
        "pcm = b'\\x00\\x00' * 10\n"
        "chunk_size = 36 + len(pcm)\n"
        "byte_rate = 24000 * 2\n"
        "block_align = 2\n"
        "header = (\n"
        "    b'RIFF'\n"
        "    + struct.pack('<I', chunk_size)\n"
        "    + b'WAVE'\n"
        "    + b'fmt '\n"
        "    + struct.pack('<IHHIIHH', 16, 1, 1, 24000, byte_rate, block_align, 16)\n"
        "    + b'data'\n"
        "    + struct.pack('<I', len(pcm))\n"
        ")\n"
        "out.write_bytes(header + pcm)\n"
        "PY\n",
    )
    adapter = KokoroCliTTSAdapter(command=str(cli))
    result = adapter.synthesize("hello", tmp_path / "out", voice="af_heart", speed=1.0, audio_format="mp3")

    assert str(result.value).endswith(".wav")
    assert result.mime_type == "audio/wav"
    assert Path(str(result.value)).exists()
