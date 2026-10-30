from __future__ import annotations

import json
import shutil
import ssl
import urllib.request
from hashlib import sha256
from pathlib import Path

import certifi
import numpy as np
import sherpa_onnx
import soundfile as sf

from lorasuite_engine.ffmpeg import prepare_speaker_audio
from lorasuite_engine.models import (
    CurationRecommendation,
    IdentityRuntimeStatus,
    MediaItem,
    MediaType,
    VoiceIdentityEvidence,
    VoiceIdentityProfile,
    utc_now,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService


MODEL_NAME = "wespeaker_en_voxceleb_CAM++.onnx"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B.onnx"
)
MODEL_SHA256 = "c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef"


class SpeakerIdentityModelService:
    @property
    def model_path(self) -> Path:
        return Path.home() / ".cache" / "lorasuite" / "models" / "speaker-identity" / MODEL_NAME

    def status(self) -> IdentityRuntimeStatus:
        installed = self.model_path.is_file() and self._valid_checksum(self.model_path)
        return IdentityRuntimeStatus(
            backend="sherpa-onnx-wespeaker-campp",
            model_version="wespeaker-en-voxceleb-campp",
            installed=installed,
            ready=installed,
            download_size_bytes=29_292_684,
            message="Voice identity model ready" if installed else "Voice identity model is not installed",
        )

    def install(self) -> IdentityRuntimeStatus:
        if self.status().ready:
            return self.status()
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.model_path.with_suffix(".download")
        try:
            with urllib.request.urlopen(
                MODEL_URL,
                context=ssl.create_default_context(cafile=certifi.where()),
                timeout=120,
            ) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if not self._valid_checksum(temporary):
                raise RuntimeError("Voice identity model checksum verification failed")
            temporary.replace(self.model_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self.status()

    @staticmethod
    def _valid_checksum(path: Path) -> bool:
        if not path.is_file():
            return False
        digest = sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == MODEL_SHA256


class SpeakerEmbeddingEngine:
    def __init__(self, vault_root: Path, model_path: Path):
        self.vault_root = Path(vault_root)
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(model_path),
            num_threads=2,
            provider="cpu",
        )
        if not config.validate():
            raise RuntimeError("Voice identity model configuration is invalid")
        self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def embedding(self, item: MediaItem) -> np.ndarray:
        cache_dir = self.vault_root / "derivatives" / "voice_identity" / "embeddings"
        cache_path = cache_dir / f"{item.sha256}.npy"
        if cache_path.exists():
            return np.load(cache_path)
        wav_path = self.vault_root / "derivatives" / "voice_identity" / "input" / f"{item.sha256}.wav"
        if not wav_path.exists():
            prepare_speaker_audio(item.raw_path, wav_path)
        samples, sample_rate = sf.read(wav_path, always_2d=True, dtype="float32")
        stream = self.extractor.create_stream()
        stream.accept_waveform(
            sample_rate=sample_rate,
            waveform=np.ascontiguousarray(samples[:, 0]),
        )
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            raise RuntimeError("Audio is too short to compute a speaker embedding")
        embedding = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.save(cache_path, embedding)
        return embedding


class VoiceIdentityService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.vault = VaultService(self.vault_root)

    @property
    def profiles_path(self) -> Path:
        return self.vault_root / "voice_identity_profiles.json"

    def get_profile(self, project_id: str) -> VoiceIdentityProfile:
        payload = self._read_profiles().get(project_id)
        return (
            VoiceIdentityProfile.model_validate(payload)
            if payload is not None
            else VoiceIdentityProfile(project_id=project_id)
        )

    def set_anchors(self, project_id: str, media_item_ids: list[str]) -> VoiceIdentityProfile:
        for media_item_id in media_item_ids:
            self._audio_item(media_item_id)
        profile = self.get_profile(project_id)
        profile.anchor_media_item_ids = list(dict.fromkeys(media_item_ids))
        profile.evidence = {
            item_id: evidence
            for item_id, evidence in profile.evidence.items()
            if item_id in profile.anchor_media_item_ids
        }
        profile.updated_at = utc_now()
        self._save_profile(profile)
        return profile

    def analyze(self, project_id: str, media_item_ids: list[str]) -> VoiceIdentityProfile:
        profile = self.get_profile(project_id)
        if not profile.anchor_media_item_ids:
            raise ValueError("Select at least one trusted voice anchor")
        model_status = SpeakerIdentityModelService().status()
        if not model_status.ready:
            raise RuntimeError("Voice identity model is not installed")
        engine = SpeakerEmbeddingEngine(self.vault_root, SpeakerIdentityModelService().model_path)
        anchor_embeddings = [
            engine.embedding(self._audio_item(media_item_id))
            for media_item_id in profile.anchor_media_item_ids
        ]
        consensus = np.mean(anchor_embeddings, axis=0)
        consensus /= max(float(np.linalg.norm(consensus)), 1e-12)
        evidence: dict[str, VoiceIdentityEvidence] = {}
        for media_item_id in dict.fromkeys([*profile.anchor_media_item_ids, *media_item_ids]):
            item = self._audio_item(media_item_id)
            candidate = engine.embedding(item)
            candidate /= max(float(np.linalg.norm(candidate)), 1e-12)
            similarity = float(np.dot(consensus, candidate))
            is_anchor = media_item_id in profile.anchor_media_item_ids
            if is_anchor:
                recommendation = CurationRecommendation.KEEP
                reasons = ["trusted voice anchor selected by user"]
            elif similarity >= 0.70:
                recommendation = CurationRecommendation.KEEP
                reasons = ["speaker embedding closely matches the trusted voice consensus"]
            elif similarity >= 0.55:
                recommendation = CurationRecommendation.REVIEW
                reasons = ["speaker similarity is plausible but requires human confirmation"]
            else:
                recommendation = CurationRecommendation.REJECT
                reasons = ["speaker embedding does not match the trusted voice consensus"]
            warnings = []
            if len(profile.anchor_media_item_ids) < 3:
                warnings.append("Use at least three varied voice anchors for a stronger consensus")
            evidence[media_item_id] = VoiceIdentityEvidence(
                media_item_id=media_item_id,
                similarity=similarity,
                recommendation=recommendation,
                is_anchor=is_anchor,
                anchor_count=len(profile.anchor_media_item_ids),
                reasons=reasons,
                warnings=warnings,
            )
        profile.evidence = evidence
        profile.updated_at = utc_now()
        self._save_profile(profile)
        return profile

    def _audio_item(self, media_item_id: str) -> MediaItem:
        item = self.vault.get_media_item(media_item_id)
        if item is None:
            raise KeyError(media_item_id)
        if item.media_type != MediaType.AUDIO:
            raise ValueError(f"voice identity requires audio media: {media_item_id}")
        return item

    def _save_profile(self, profile: VoiceIdentityProfile) -> None:
        with json_file_lock(self.profiles_path):
            profiles = self._read_profiles_unlocked()
            profiles[profile.project_id] = profile.model_dump(mode="json")
            atomic_write_json(self.profiles_path, profiles)

    def _read_profiles(self) -> dict[str, object]:
        with json_file_lock(self.profiles_path):
            return self._read_profiles_unlocked()

    def _read_profiles_unlocked(self) -> dict[str, object]:
        if not self.profiles_path.exists():
            return {}
        try:
            payload = json.loads(self.profiles_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
