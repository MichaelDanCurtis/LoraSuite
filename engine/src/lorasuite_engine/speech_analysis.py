from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(slots=True)
class SpeechWord:
    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = None


@dataclass(slots=True)
class AudioSpeechEvidence:
    transcript: str | None = None
    language: str | None = None
    speech_duration_ratio: float | None = None
    transcript_confidence: float | None = None
    word_count: int | None = None
    speaker_count: int | None = None
    speaker_duration_ratio: float | None = None
    warnings: list[str] = field(default_factory=list)
    words: list[SpeechWord] = field(default_factory=list)


class AppleSpeechAnalyzer:
    _server_process: subprocess.Popen[bytes] | None = None
    _server_lock = threading.Lock()

    def __init__(self) -> None:
        self.executable = shutil.which("whisperkit-cli")
        self.endpoint = os.environ.get(
            "LORASUITE_WHISPERKIT_URL",
            "http://127.0.0.1:50060",
        ).rstrip("/")
        self.model = os.environ.get(
            "LORASUITE_WHISPERKIT_MODEL",
            "large-v3-v20240930_626MB",
        )
        cache_root = Path(
            os.environ.get(
                "LORASUITE_MODEL_CACHE",
                Path.home() / ".cache" / "lorasuite" / "models",
            )
        )
        self.whisper_cache = cache_root / "whisperkit"
        self.speaker_cache = cache_root / "speakerkit"

    def analyze(self, path: Path, duration: float | None) -> AudioSpeechEvidence:
        if self.executable is None:
            return AudioSpeechEvidence(warnings=["WhisperKit CLI is not installed"])

        evidence = AudioSpeechEvidence()
        try:
            transcription = self._transcribe(path)
            evidence.transcript = _clean_text(transcription.get("text"))
            evidence.language = _clean_text(transcription.get("language"))
            words = transcription.get("words")
            evidence.word_count = len(words) if isinstance(words, list) else 0
            if isinstance(words, list):
                evidence.words = [
                    SpeechWord(
                        text=text,
                        start_seconds=max(0.0, _number(word.get("start"))),
                        end_seconds=max(0.0, _number(word.get("end"))),
                        confidence=(
                            _number(word.get("probability"))
                            if word.get("probability") is not None
                            else None
                        ),
                    )
                    for word in words
                    if isinstance(word, dict)
                    and (text := _clean_text(word.get("word") or word.get("text"))) is not None
                    and _number(word.get("end")) > _number(word.get("start"))
                ]
            segments = transcription.get("segments")
            if isinstance(segments, list):
                speech_seconds = sum(
                    max(0.0, _number(segment.get("end")) - _number(segment.get("start")))
                    for segment in segments
                    if isinstance(segment, dict)
                )
                audio_duration = duration or _number(transcription.get("duration"))
                if audio_duration > 0:
                    evidence.speech_duration_ratio = min(1.0, speech_seconds / audio_duration)
                weighted_logprob = [
                    (
                        max(0.01, _number(segment.get("end")) - _number(segment.get("start"))),
                        _number(segment.get("avg_logprob")),
                    )
                    for segment in segments
                    if isinstance(segment, dict) and segment.get("avg_logprob") is not None
                ]
                if weighted_logprob:
                    total_weight = sum(weight for weight, _value in weighted_logprob)
                    average_logprob = sum(
                        weight * value for weight, value in weighted_logprob
                    ) / total_weight
                    evidence.transcript_confidence = min(1.0, max(0.0, math.exp(average_logprob)))
        except (OSError, RuntimeError, URLError, ValueError, json.JSONDecodeError) as error:
            evidence.warnings.append(f"speech transcription unavailable: {str(error)}")

        try:
            speakers, speaker_seconds = self._diarize(path)
            evidence.speaker_count = len(speakers)
            if duration is not None and duration > 0:
                evidence.speaker_duration_ratio = min(1.0, speaker_seconds / duration)
        except (OSError, RuntimeError, ValueError) as error:
            evidence.warnings.append(f"speaker diarization unavailable: {str(error)}")
        return evidence

    def speaker_count(self, path: Path) -> int | None:
        if self.executable is None:
            return None
        speakers, _speaker_seconds = self._diarize(path)
        return len(speakers)

    def _transcribe(self, path: Path) -> dict[str, object]:
        self._ensure_server()
        boundary = f"lorasuite-{uuid4().hex}"
        data = _multipart_body(
            boundary,
            fields={
                "model": self.model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "word",
            },
            file_path=path,
        )
        request = Request(
            f"{self.endpoint}/v1/audio/transcriptions",
            data=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("WhisperKit returned an invalid response")
        return payload

    def _ensure_server(self) -> None:
        if self._server_ready():
            return
        with self._server_lock:
            if self._server_ready():
                return
            if self.executable is None:
                raise RuntimeError("WhisperKit CLI is not installed")
            self.whisper_cache.mkdir(parents=True, exist_ok=True)
            self.__class__._server_process = subprocess.Popen(
                [
                    self.executable,
                    "serve",
                    "--model",
                    self.model,
                    "--download-model-path",
                    str(self.whisper_cache),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "50060",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if self._server_ready():
                    return
                process = self.__class__._server_process
                if process is not None and process.poll() is not None:
                    raise RuntimeError("WhisperKit server exited during startup")
                time.sleep(0.25)
            raise RuntimeError("WhisperKit server did not become ready")

    def _server_ready(self) -> bool:
        try:
            with urlopen(f"{self.endpoint}/health", timeout=0.75) as response:
                return response.status == 200
        except (OSError, URLError):
            return False

    def _diarize(self, path: Path) -> tuple[set[str], float]:
        if self.executable is None:
            raise RuntimeError("WhisperKit CLI is not installed")
        self.speaker_cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lorasuite-speakers-") as directory:
            rttm_path = Path(directory) / "speakers.rttm"
            result = subprocess.run(
                [
                    self.executable,
                    "diarize",
                    "--audio-path",
                    str(path),
                    "--download-model-path",
                    str(self.speaker_cache),
                    "--rttm-path",
                    str(rttm_path),
                ],
                capture_output=True,
                check=False,
                shell=False,
                timeout=180,
            )
            if result.returncode != 0 or not rttm_path.exists():
                message = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(message or "SpeakerKit did not produce diarization output")
            speakers: set[str] = set()
            speaker_seconds = 0.0
            for line in rttm_path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) < 8 or parts[0] != "SPEAKER":
                    continue
                speaker_seconds += max(0.0, float(parts[4]))
                speakers.add(parts[7])
            return speakers, speaker_seconds


def _multipart_body(boundary: str, fields: dict[str, str], file_path: Path) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            ).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks)


def _clean_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0
