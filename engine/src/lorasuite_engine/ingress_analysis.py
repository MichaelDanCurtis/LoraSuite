from __future__ import annotations

from pathlib import Path
from typing import Literal

from lorasuite_engine.dataset_analysis import DatasetImageAnalyzer
from lorasuite_engine.models import (
    CurationRecommendation,
    IngressCandidate,
    MediaType,
)


IngressAnalysisTarget = Literal["image", "video", "voice", "id_lora"]


class IngressCandidateAnalyzer:
    """Fast preflight analysis for retrieved candidates.

    This deliberately evaluates cached posters and metadata. Original video and audio
    analysis remains a curation task after the user approves the download.
    """

    def __init__(self) -> None:
        self.image_analyzer = DatasetImageAnalyzer()

    def analyze(
        self,
        candidates: list[IngressCandidate],
        target: IngressAnalysisTarget,
    ) -> list[dict[str, object]]:
        return [self._analyze_candidate(candidate, target) for candidate in candidates]

    def _analyze_candidate(
        self,
        candidate: IngressCandidate,
        target: IngressAnalysisTarget,
    ) -> dict[str, object]:
        if candidate.status.value != "ready":
            return self._result(
                candidate,
                CurationRecommendation.REJECT,
                0.99,
                ["candidate is not ready for retrieval"],
                "ingress-readiness-v1",
            )
        if candidate.media_type == MediaType.AUDIO:
            return self._analyze_audio_metadata(candidate, target)
        return self._analyze_visual(candidate, target)

    def _analyze_visual(
        self,
        candidate: IngressCandidate,
        target: IngressAnalysisTarget,
    ) -> dict[str, object]:
        preview_path = candidate.thumbnail_path or candidate.poster_asset_path
        if preview_path is None or not Path(preview_path).exists():
            return self._result(
                candidate,
                CurationRecommendation.REVIEW,
                0.55,
                ["cached preview is unavailable for visual preflight"],
                "ingress-visual-preflight-v1",
            )
        try:
            evidence = self.image_analyzer.analyze(Path(preview_path))
        except (OSError, ValueError) as error:
            return self._result(
                candidate,
                CurationRecommendation.REVIEW,
                0.62,
                ["cached preview could not be measured"],
                "ingress-visual-preflight-v1",
                warnings=[str(error)],
            )

        person_signal = max(
            min(1.0, evidence.face_area / 0.1),
            min(1.0, evidence.body_coverage / 0.3),
            evidence.pose_coverage,
        )
        reasons: list[str]
        if evidence.quality_score < 0.22:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.92
            reasons = ["cached preview has very low usable visual quality"]
        elif evidence.face_count > 1 and target in {"image", "id_lora"}:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.82
            reasons = ["multiple faces require identity confirmation"]
        elif person_signal < 0.06:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.84
            reasons = ["no useful face, body, or pose signal was detected"]
        elif candidate.media_type == MediaType.VIDEO and candidate.duration is not None and candidate.duration < 1.0:
            recommendation = CurationRecommendation.REJECT
            confidence = 0.9
            reasons = ["video is too short for useful temporal evidence"]
        elif evidence.quality_score < 0.42 or evidence.face_count == 0:
            recommendation = CurationRecommendation.REVIEW
            confidence = 0.74
            reasons = ["visual evidence is plausible but requires human confirmation"]
        else:
            recommendation = CurationRecommendation.KEEP
            confidence = 0.88 if evidence.face_count == 1 else 0.79
            reasons = ["strong person signal with sufficient visual quality"]

        return self._result(
            candidate,
            recommendation,
            confidence,
            reasons,
            evidence.analyzer,
            metrics={
                "quality_score": evidence.quality_score,
                "face_count": evidence.face_count,
                "face_area": evidence.face_area,
                "body_coverage": evidence.body_coverage,
                "pose_coverage": evidence.pose_coverage,
                "aesthetic_score": evidence.aesthetic_score,
            },
        )

    def _analyze_audio_metadata(
        self,
        candidate: IngressCandidate,
        target: IngressAnalysisTarget,
    ) -> dict[str, object]:
        original = candidate.metadata_json.get("audio_original")
        audio_kind = str(candidate.metadata_json.get("audio_kind") or "").lower()
        if candidate.duration is not None and candidate.duration < 1.5:
            return self._result(
                candidate,
                CurationRecommendation.REJECT,
                0.9,
                ["audio is too short for useful speech evidence"],
                "ingress-audio-metadata-v2",
            )
        if target in {"voice", "id_lora"}:
            if original is False or audio_kind in {"music", "reused_or_music"}:
                return self._result(
                    candidate,
                    CurationRecommendation.REVIEW,
                    0.55,
                    ["source metadata suggests music or reused audio; review for usable target speech"],
                    "ingress-audio-metadata-v2",
                )
            if original is True:
                return self._result(
                    candidate,
                    CurationRecommendation.REVIEW,
                    0.78,
                    ["original audio may contain target speech; speaker ownership requires confirmation"],
                    "ingress-audio-metadata-v2",
                )
            return self._result(
                candidate,
                CurationRecommendation.REVIEW,
                0.68,
                ["speaker ownership and speech content require detailed analysis"],
                "ingress-audio-metadata-v2",
            )
        if original is False or audio_kind in {"music", "reused_or_music"}:
            return self._result(
                candidate,
                CurationRecommendation.REJECT,
                0.96,
                ["source metadata identifies reused or musical audio"],
                "ingress-audio-metadata-v2",
            )
        return self._result(
            candidate,
            CurationRecommendation.REVIEW,
            0.68,
            ["audio relevance requires detailed analysis"],
            "ingress-audio-metadata-v2",
        )

    @staticmethod
    def _result(
        candidate: IngressCandidate,
        recommendation: CurationRecommendation,
        confidence: float,
        reasons: list[str],
        analyzer: str,
        *,
        warnings: list[str] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "candidate_id": candidate.id,
            "recommendation": recommendation.value,
            "confidence": confidence,
            "reasons": reasons,
            "warnings": warnings or [],
            "analyzer": analyzer,
            **(metrics or {}),
        }
