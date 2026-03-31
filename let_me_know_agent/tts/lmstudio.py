from __future__ import annotations

import json
import re
import urllib.request
import wave
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from .base import TTSAdapter
from ..errors import AdapterError
from ..models import AudioResult


class SnacModelCache:
    """Explicit singleton for SNAC model caching with lifecycle management."""

    _instance: SnacModelCache | None = None

    def __init__(self) -> None:
        self._model = None
        self._device: str | None = None

    @classmethod
    def get_instance(cls) -> SnacModelCache:
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (useful for testing)."""
        cls._instance = None

    def get_model(self):
        """Get or initialize the SNAC model."""
        if self._model is None:
            try:
                import torch
                from snac import SNAC
            except Exception as exc:
                raise AdapterError(
                    "Orpheus decoding requires optional dependencies: snac, torch, numpy"
                ) from exc

            self._device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            self._model = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval().to(self._device)
        return self._model, self._device


class LMStudioTTSAdapter(TTSAdapter):
    name: ClassVar[str] = "lmstudio"

    _CUSTOM_TOKEN_RE: ClassVar[re.Pattern] = re.compile(r"<custom_token_(\d+)>")
    _ORPHEUS_SAMPLE_RATE: ClassVar[int] = 24000

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 20.0,
        *,
        tts_mode: str = "openai_speech",
        orpheus_voice: str = "tara",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.tts_mode = tts_mode
        self.orpheus_voice = orpheus_voice

    def synthesize(self, text: str, output_dir: Path, *, voice: str = "default", speed: float = 1.0, audio_format: str = "mp3") -> AudioResult:
        if self.tts_mode != "orpheus_completions":
            raise AdapterError(
                "LMStudio TTS only supports Orpheus completions mode. "
                "Set providers.lmstudio.tts_mode='orpheus_completions'."
            )
        return self._synthesize_orpheus(text, output_dir, voice=voice if voice != "default" else self.orpheus_voice, speed=speed)

    def _synthesize_orpheus(self, text: str, output_dir: Path, *, voice: str, speed: float) -> AudioResult:
        if speed != 1.0:
            raise AdapterError("LMStudio Orpheus mode does not support speed control")

        prompt = f"<|audio|>{voice}: {text}<|eot_id|>"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": 1200,
            "temperature": 0.6,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
            "stream": True,
        }
        req = urllib.request.Request(
            f"{self.base_url}/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type.lower() and "application/json" not in content_type.lower():
                    body = resp.read(200).decode("utf-8", errors="replace")
                    raise AdapterError(f"LMStudio Orpheus returned unexpected content-type ({content_type}): {body}")
                token_ids = self._read_orpheus_stream(resp)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"LMStudio Orpheus generation failed: {exc}") from exc

        pcm_chunks = self._decode_orpheus_token_ids(token_ids)
        if not pcm_chunks:
            raise AdapterError("LMStudio Orpheus produced no decodable audio")

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"tts-{uuid4().hex}.wav"
        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self._ORPHEUS_SAMPLE_RATE)
            for chunk in pcm_chunks:
                wav.writeframes(chunk)

        return AudioResult(kind="file", value=str(out_path), provider=self.name, mime_type="audio/wav")

    def _read_orpheus_stream(self, resp) -> list[int]:
        token_ids: list[int] = []

        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = data.get("choices") or []
            if not choices:
                continue
            token_text = (choices[0].get("text") or "").strip()
            if not token_text:
                continue

            for match in self._CUSTOM_TOKEN_RE.findall(token_text):
                token_number = int(match)
                token_id = token_number - 10 - ((len(token_ids) % 7) * 4096)
                if token_id > 0:
                    token_ids.append(token_id)

        return token_ids

    def _decode_orpheus_token_ids(self, token_ids: list[int]) -> list[bytes]:
        pcm_chunks: list[bytes] = []
        for count in range(28, len(token_ids) + 1):
            if count % 7 != 0:
                continue
            multiframe = token_ids[count - 28 : count]
            audio_chunk = self._decode_multiframe(multiframe)
            if audio_chunk:
                pcm_chunks.append(audio_chunk)
        return pcm_chunks

    def _decode_multiframe(self, multiframe: list[int]) -> bytes | None:
        try:
            import numpy as np
            import torch
        except Exception as exc:
            raise AdapterError(
                "Orpheus decoding requires optional dependencies: snac, torch, numpy"
            ) from exc

        if len(multiframe) < 7:
            return None

        model, device = SnacModelCache.get_instance().get_model()

        codes_0 = torch.tensor([], device=device, dtype=torch.int32)
        codes_1 = torch.tensor([], device=device, dtype=torch.int32)
        codes_2 = torch.tensor([], device=device, dtype=torch.int32)

        num_frames = len(multiframe) // 7
        frame = multiframe[: num_frames * 7]

        for j in range(num_frames):
            i = 7 * j
            codes_0 = torch.cat([codes_0, torch.tensor([frame[i]], device=device, dtype=torch.int32)])
            codes_1 = torch.cat(
                [
                    codes_1,
                    torch.tensor([frame[i + 1]], device=device, dtype=torch.int32),
                    torch.tensor([frame[i + 4]], device=device, dtype=torch.int32),
                ]
            )
            codes_2 = torch.cat(
                [
                    codes_2,
                    torch.tensor([frame[i + 2]], device=device, dtype=torch.int32),
                    torch.tensor([frame[i + 3]], device=device, dtype=torch.int32),
                    torch.tensor([frame[i + 5]], device=device, dtype=torch.int32),
                    torch.tensor([frame[i + 6]], device=device, dtype=torch.int32),
                ]
            )

        codes = [codes_0.unsqueeze(0), codes_1.unsqueeze(0), codes_2.unsqueeze(0)]
        for code in codes:
            if torch.any(code < 0) or torch.any(code > 4096):
                return None

        with torch.inference_mode():
            audio_hat = model.decode(codes)

        audio_slice = audio_hat[:, :, 2048:4096]
        audio_np = audio_slice.detach().cpu().numpy()
        audio_int16 = (audio_np * 32767).astype(np.int16)
        return audio_int16.tobytes()
