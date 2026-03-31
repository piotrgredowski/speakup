from __future__ import annotations

import os
import warnings
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar, Generator
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class KokoroTTSAdapter(TTSAdapter):
    """Kokoro TTS adapter using the kokoro library.

    Note: This adapter always outputs WAV format since Kokoro produces PCM audio.
    If mp3 is requested, it will be output as WAV with a clear warning.
    """

    name: ClassVar[str] = "kokoro"

    _SUPPORTED_FORMATS: ClassVar[set[str]] = {"wav", "mp3"}

    def __init__(self, lang_code: str = "a", default_voice: str = "af_heart", repo_id: str = "hexgrad/Kokoro-82M", offline: bool = True):
        self.lang_code = lang_code
        self.default_voice = default_voice
        self.repo_id = repo_id
        self.offline = offline
        self._pipeline = None

    @contextmanager
    def _offline_env(self) -> Generator[None, None, None]:
        """Context manager to temporarily set offline environment variables.

        This ensures environment changes are isolated and restored after use.
        """
        if not self.offline:
            yield
            return

        prev_hf = os.environ.get("HF_HUB_OFFLINE")
        prev_transformers = os.environ.get("TRANSFORMERS_OFFLINE")

        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            yield
        finally:
            if prev_hf is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prev_hf

            if prev_transformers is None:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
            else:
                os.environ["TRANSFORMERS_OFFLINE"] = prev_transformers

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "wav") -> AudioResult:
        if audio_format not in self._SUPPORTED_FORMATS:
            raise AdapterError(f"Kokoro adapter supports only {'/'.join(self._SUPPORTED_FORMATS)} output, got: {audio_format}")

        output_dir.mkdir(parents=True, exist_ok=True)
        wav_path = output_dir / f"tts-{uuid4().hex}.wav"
        selected_voice = self.default_voice if voice == "default" else voice

        try:
            with self._offline_env():
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="dropout option adds dropout after all but last recurrent layer",
                        category=UserWarning,
                    )
                    warnings.filterwarnings(
                        "ignore",
                        message="`torch.nn.utils.weight_norm` is deprecated",
                        category=FutureWarning,
                    )
                    import torch
                    from kokoro import KPipeline

                if self._pipeline is None:
                    self._pipeline = KPipeline(lang_code=self.lang_code, repo_id=self.repo_id)

                chunks = []
                for result in self._pipeline(text, voice=selected_voice, speed=speed):
                    if result.audio is not None:
                        chunks.append(result.audio.detach().cpu().flatten())

                if not chunks:
                    raise AdapterError("Kokoro TTS produced no audio")

                audio = torch.cat(chunks).clamp(-1, 1)
                pcm = (audio * 32767).to(torch.int16).numpy().tobytes()

                with wave.open(str(wav_path), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(pcm)

        except AdapterError:
            raise
        except Exception as exc:
            if self.offline:
                raise AdapterError(
                    f"Kokoro TTS failed in offline mode: {exc}. "
                    f"Ensure model files are cached locally for repo_id={self.repo_id}"
                ) from exc
            raise AdapterError(f"Kokoro TTS failed: {exc}") from exc

        return AudioResult(kind="file", value=str(wav_path), provider=self.name, mime_type="audio/wav")

