from __future__ import annotations

import os
import warnings
import wave
from pathlib import Path
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class KokoroTTSAdapter(TTSAdapter):
    name = "kokoro"

    def __init__(self, lang_code: str = "a", default_voice: str = "af_heart", repo_id: str = "hexgrad/Kokoro-82M", offline: bool = True):
        self.lang_code = lang_code
        self.default_voice = default_voice
        self.repo_id = repo_id
        self.offline = offline
        self._pipeline = None

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "wav") -> AudioResult:
        if audio_format not in {"wav", "mp3"}:
            raise AdapterError(f"Kokoro adapter supports only wav/mp3 output, got: {audio_format}")

        # Kokoro natively produces PCM audio which we write as WAV.
        # Even if mp3 is requested globally, keep Kokoro output as .wav to avoid
        # mislabeled files and unnecessary lossy conversion.
        output_dir.mkdir(parents=True, exist_ok=True)
        wav_path = output_dir / f"tts-{uuid4().hex}.wav"
        out_path = wav_path
        selected_voice = self.default_voice if voice == "default" else voice

        try:
            if self.offline:
                # Force Hugging Face/Transformers to use local cache only.
                # This must happen before importing kokoro/transformers modules,
                # otherwise they may perform network/cache checks during import.
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"

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

        except Exception as exc:
            if self.offline:
                raise AdapterError(
                    f"Kokoro TTS failed in offline mode: {exc}. "
                    "Ensure model files are already cached locally for repo_id="
                    f"{self.repo_id}"
                ) from exc
            raise AdapterError(f"Kokoro TTS failed: {exc}") from exc

        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/wav")

