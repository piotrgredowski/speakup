from __future__ import annotations

import os
import wave
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class OrpheusTTSAdapter(TTSAdapter):
    """Orpheus TTS adapter using orpheus-speech package.

    Orpheus is a high-quality open-source TTS model built on Llama-3b.
    It produces human-like speech with natural intonation and emotion.

    Configuration options:
    - model_name: HuggingFace model (e.g., canopylabs/orpheus-tts-0.1-finetune-prod)
    - voice: Voice name (default: "tara") - options: tara, leah, jess, leo, dan, mia, zac, zoe
    - max_model_len: Max sequence length (default: 2048)
    - offline: Use local model cache only (default: true)
    - timeout_seconds: Generation timeout (default: 120)
    """

    name = "orpheus"

    def __init__(
        self,
        model_name: str = "canopylabs/orpheus-tts-0.1-finetune-prod",
        default_voice: str = "tara",
        max_model_len: int = 2048,
        offline: bool = True,
        timeout_seconds: int = 120,
    ):
        self.model_name = model_name
        self.default_voice = default_voice
        self.max_model_len = max_model_len
        self.offline = offline
        self.timeout_seconds = timeout_seconds
        self._model = None

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        *,
        voice: str = "default",
        speed: float = 1.0,
        audio_format: str = "wav",
    ) -> AudioResult:
        if audio_format not in {"wav", "mp3"}:
            raise AdapterError(f"Orpheus adapter supports only wav/mp3 output, got: {audio_format}")

        # Orpheus outputs 24kHz WAV, output is always WAV regardless of format request
        output_dir.mkdir(parents=True, exist_ok=True)
        wav_path = output_dir / f"tts-{uuid4().hex}.wav"
        selected_voice = self.default_voice if voice == "default" else voice

        try:
            self._synthesize_to_wav(text, selected_voice, wav_path, offline_mode=self.offline)
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            if self.offline:
                # Graceful fallback: if strict offline generation fails, retry once
                # with online mode to pull missing model assets, then restore
                # offline env vars back to enabled.
                prev_hf_offline = os.environ.pop("HF_HUB_OFFLINE", None)
                prev_transformers_offline = os.environ.pop("TRANSFORMERS_OFFLINE", None)
                try:
                    self._model = None
                    self._synthesize_to_wav(text, selected_voice, wav_path, offline_mode=False)
                except BaseException as retry_exc:
                    if isinstance(retry_exc, KeyboardInterrupt):
                        raise
                    raise AdapterError(
                        f"Orpheus TTS failed in offline mode: {exc}. "
                        f"Online retry also failed: {retry_exc}"
                    ) from retry_exc
                finally:
                    # Restore explicit offline=true state for subsequent calls.
                    os.environ["HF_HUB_OFFLINE"] = "1"
                    os.environ["TRANSFORMERS_OFFLINE"] = "1"
                    if prev_hf_offline is None and prev_transformers_offline is None:
                        pass
            else:
                raise AdapterError(f"Orpheus TTS failed: {exc}") from exc

        return AudioResult(
            kind="file",
            value=str(wav_path),
            provider=self.name,
            mime_type="audio/wav",
        )

    def _synthesize_to_wav(self, text: str, voice: str, wav_path: Path, *, offline_mode: bool) -> None:
        if offline_mode:
            # Force Hugging Face to use local cache only
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

        from orpheus_tts import OrpheusModel

        if self._model is None:
            self._model = OrpheusModel(
                model_name=self.model_name,
                max_model_len=self.max_model_len,
            )

        syn_tokens = self._model.generate_speech(
            prompt=text,
            voice=voice,
        )

        chunks = []
        for audio_chunk in syn_tokens:
            if audio_chunk:
                chunks.append(audio_chunk)
        if not chunks:
            raise AdapterError("Orpheus TTS produced no audio")

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            for chunk in chunks:
                wf.writeframes(chunk)
