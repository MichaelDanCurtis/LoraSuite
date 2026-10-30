from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from lorasuite_engine.ffmpeg import extract_audio_segment
from lorasuite_engine.models import (
    CurationRecommendation,
    DerivativeType,
    MediaItem,
    MediaType,
    VoiceDatasetCompilation,
    VoiceDatasetBalance,
    VoiceDatasetSegment,
    VoiceExportTarget,
    VoiceSegmentStatus,
    utc_now,
)
from lorasuite_engine.speaker_identity import VoiceIdentityService
from lorasuite_engine.speech_analysis import AppleSpeechAnalyzer, SpeechWord
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import (
    ModelIntentRecipe,
    RecipeCheck,
    RecipeCompliance,
    get_training_target_profile,
)
from lorasuite_engine.vault import VaultService, sha256_file
from lorasuite_engine.voice_quality import VoiceQualityAnalyzer


class VoiceDatasetService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.vault = VaultService(self.vault_root)
        self.speech_analyzer = AppleSpeechAnalyzer()
        self.quality_analyzer = VoiceQualityAnalyzer()

    @property
    def compilations_path(self) -> Path:
        return self.vault_root / "voice_datasets.json"

    def get(self, project_id: str) -> VoiceDatasetCompilation:
        payload = self._read_compilations().get(project_id)
        compilation = (
            VoiceDatasetCompilation.model_validate(payload)
            if payload is not None
            else VoiceDatasetCompilation(project_id=project_id)
        )
        return refresh_voice_dataset_contract(compilation)

    def compile(
        self,
        project_id: str,
        media_item_ids: list[str],
    ) -> VoiceDatasetCompilation:
        if not media_item_ids:
            raise ValueError("At least one approved audio source is required")
        voice_profile = VoiceIdentityService(self.vault_root).get_profile(project_id)
        if not voice_profile.anchor_media_item_ids:
            raise ValueError("Select trusted voice anchors in Identify before compiling")
        prior = self.get(project_id)
        existing_segments = prior.segments
        vault_items = self.vault.list_media_items()
        existing_derivatives = {
            item.metadata_json.get("voice_segment_id"): item
            for item in vault_items
            if item.metadata_json.get("derivative_type") == DerivativeType.VOICE_SEGMENT
        }
        generated_items: list[MediaItem] = []
        segments: dict[str, VoiceDatasetSegment] = {}
        source_ids = list(dict.fromkeys(media_item_ids))

        for source_id in source_ids:
            source = self._audio_item(source_id)
            speech = self.speech_analyzer.analyze(source.raw_path, source.duration)
            ranges = segment_speech_words(speech.words, source.duration)
            for index, (start, end, words) in enumerate(ranges, start=1):
                transcript = join_words(words)
                if not transcript:
                    continue
                segment_id = stable_segment_id(source.id, start, end, transcript)
                output_path = (
                    self.vault_root
                    / "derivatives"
                    / "voice_datasets"
                    / project_id
                    / source.id
                    / f"{index:04d}_{segment_id}.wav"
                )
                derivative = existing_derivatives.get(segment_id)
                if derivative is None:
                    if not output_path.exists():
                        extract_audio_segment(source.raw_path, output_path, start, end)
                    derivative = self.vault.build_derivative_media_item(
                        source_item=source,
                        derivative_path=output_path,
                        media_type=MediaType.AUDIO,
                        derivative_type=DerivativeType.VOICE_SEGMENT,
                        metadata={
                            "character_project_id": project_id,
                            "voice_segment_id": segment_id,
                            "transcript": transcript,
                            "language": speech.language,
                            "time_range": {
                                "start_seconds": start,
                                "end_seconds": end,
                            },
                            "generator": {"name": "whisperkit-voice-segmenter-v1"},
                        },
                    )
                    derivative.duration = end - start
                    generated_items.append(derivative)
                    existing_derivatives[segment_id] = derivative
                previous = existing_segments.get(segment_id)
                segment = VoiceDatasetSegment(
                    id=segment_id,
                    project_id=project_id,
                    source_media_item_id=source.id,
                    media_item_id=derivative.id,
                    audio_path=derivative.raw_path,
                    start_seconds=start,
                    end_seconds=end,
                    transcript=previous.transcript if previous else transcript,
                    language=speech.language,
                    transcript_confidence=speech.transcript_confidence,
                    status=previous.status if previous else VoiceSegmentStatus.NEEDS_REVIEW,
                    created_at=previous.created_at if previous else utc_now(),
                )
                segment.quality = self.quality_analyzer.analyze(
                    derivative.raw_path,
                    transcript_confidence=segment.transcript_confidence,
                    speaker_count=speech.speaker_count,
                    source_metadata=self._source_metadata(source),
                )
                segments[segment_id] = segment

        if generated_items:
            resolved_items = self.vault.append_media_items(generated_items)
            resolution_by_id = {
                candidate.id: resolved
                for candidate, resolved in zip(generated_items, resolved_items, strict=True)
            }
            for segment in segments.values():
                resolved = resolution_by_id.get(segment.media_item_id)
                if resolved is not None:
                    segment.media_item_id = resolved.id
                    segment.audio_path = resolved.raw_path
        if not segments:
            raise ValueError("No timestamped speech segments were detected")
        compilation = VoiceDatasetCompilation(
            project_id=project_id,
            source_media_item_ids=source_ids,
            segments=segments,
            updated_at=utc_now(),
        )
        self._apply_identity(compilation)
        self._save(compilation)
        return compilation

    def update_segment(
        self,
        project_id: str,
        segment_id: str,
        *,
        status: VoiceSegmentStatus | None = None,
        transcript: str | None = None,
    ) -> VoiceDatasetCompilation:
        compilation = self.get(project_id)
        segment = compilation.segments.get(segment_id)
        if segment is None:
            raise KeyError(segment_id)
        if status is not None:
            segment.status = status
        if transcript is not None:
            cleaned = transcript.strip()
            if not cleaned:
                raise ValueError("Segment transcript must not be empty")
            segment.transcript = cleaned
        segment.updated_at = utc_now()
        compilation.updated_at = utc_now()
        self._save(compilation)
        return compilation

    def bulk_update_segments(
        self,
        project_id: str,
        decisions: dict[str, VoiceSegmentStatus],
    ) -> VoiceDatasetCompilation:
        if not decisions:
            raise ValueError("At least one staged voice decision is required")
        compilation = self.get(project_id)
        missing = [segment_id for segment_id in decisions if segment_id not in compilation.segments]
        if missing:
            raise KeyError(missing[0])
        now = utc_now()
        for segment_id, status in decisions.items():
            segment = compilation.segments[segment_id]
            segment.status = status
            segment.updated_at = now
        compilation.updated_at = now
        self._save(compilation)
        return compilation

    def rescore(self, project_id: str) -> VoiceDatasetCompilation:
        compilation = self.get(project_id)
        if not compilation.segments:
            raise ValueError("Compile voice segments before rescoring")
        self._apply_identity(compilation)
        compilation.updated_at = utc_now()
        self._save(compilation)
        return compilation

    def analyze_quality(self, project_id: str) -> VoiceDatasetCompilation:
        compilation = self.get(project_id)
        if not compilation.segments:
            raise ValueError("Compile voice segments before running the quality gate")
        for segment in compilation.segments.values():
            source = self._audio_item(segment.source_media_item_id)
            speaker_count = segment.quality.speaker_count if segment.quality else None
            if speaker_count is None:
                try:
                    speaker_count = self.speech_analyzer.speaker_count(segment.audio_path)
                except (OSError, RuntimeError, ValueError):
                    speaker_count = None
            segment.quality = self.quality_analyzer.analyze(
                segment.audio_path,
                transcript_confidence=segment.transcript_confidence,
                speaker_count=speaker_count,
                source_metadata=self._source_metadata(source),
            )
            self._combine_recommendation(segment)
            segment.updated_at = utc_now()
        compilation.updated_at = utc_now()
        self._save(compilation)
        return compilation

    def mark_exported(
        self,
        project_id: str,
        output_path: Path,
        target: VoiceExportTarget = VoiceExportTarget.VOICE_CLONING,
    ) -> VoiceDatasetCompilation:
        compilation = self.get(project_id)
        compilation.export_path = output_path
        compilation.export_target = target
        compilation.updated_at = utc_now()
        self._save(compilation)
        return compilation

    def _audio_item(self, media_item_id: str) -> MediaItem:
        item = self.vault.get_media_item(media_item_id)
        if item is None:
            raise KeyError(media_item_id)
        if item.media_type != MediaType.AUDIO:
            raise ValueError(f"voice dataset source must be audio: {media_item_id}")
        return item

    def _apply_identity(self, compilation: VoiceDatasetCompilation) -> None:
        identity_profile = VoiceIdentityService(self.vault_root).analyze(
            compilation.project_id,
            [segment.media_item_id for segment in compilation.segments.values()],
        )
        for segment in compilation.segments.values():
            identity = identity_profile.evidence.get(segment.media_item_id)
            if identity is None:
                continue
            segment.speaker_similarity = identity.similarity
            segment.identity_recommendation = identity.recommendation
            segment.identity_reasons = identity.reasons
            segment.identity_warnings = identity.warnings
            self._combine_recommendation(segment)
            segment.updated_at = utc_now()

    def _combine_recommendation(self, segment: VoiceDatasetSegment) -> None:
        quality_recommendation = segment.quality.recommendation if segment.quality else None
        if segment.identity_recommendation == CurationRecommendation.REJECT or quality_recommendation == CurationRecommendation.REJECT:
            segment.recommendation = CurationRecommendation.REJECT
        elif segment.identity_recommendation == CurationRecommendation.KEEP and quality_recommendation == CurationRecommendation.KEEP:
            segment.recommendation = CurationRecommendation.KEEP
        else:
            segment.recommendation = CurationRecommendation.REVIEW
        segment.reasons = [
            *segment.identity_reasons,
            *(segment.quality.reasons if segment.quality else []),
        ]
        segment.warnings = list(dict.fromkeys([
            *segment.identity_warnings,
            *(segment.quality.warnings if segment.quality else []),
        ]))

    def _source_metadata(self, item: MediaItem) -> dict[str, object]:
        metadata: dict[str, object] = {}
        current: MediaItem | None = item
        visited: set[str] = set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            metadata = {**current.metadata_json, **metadata}
            parent_id = current.metadata_json.get("source_media_item_id")
            current = self.vault.get_media_item(parent_id) if isinstance(parent_id, str) else None
        return metadata

    def _save(self, compilation: VoiceDatasetCompilation) -> None:
        refresh_voice_dataset_contract(compilation)
        with json_file_lock(self.compilations_path):
            compilations = self._read_compilations_unlocked()
            compilations[compilation.project_id] = compilation.model_dump(mode="json")
            atomic_write_json(self.compilations_path, compilations)

    def _read_compilations(self) -> dict[str, object]:
        with json_file_lock(self.compilations_path):
            return self._read_compilations_unlocked()

    def _read_compilations_unlocked(self) -> dict[str, object]:
        if not self.compilations_path.exists():
            return {}
        try:
            payload = json.loads(self.compilations_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}


def refresh_voice_dataset_contract(
    compilation: VoiceDatasetCompilation,
) -> VoiceDatasetCompilation:
    target = get_training_target_profile(compilation.target_profile_id)
    recipe = target.recipe
    compilation.target_label = target.label
    compilation.balance = _voice_balance(compilation, recipe)
    compilation.dataset_fingerprint = _voice_fingerprint(compilation, target.recipe_id, target.recipe_version)
    return compilation


def _voice_balance(
    compilation: VoiceDatasetCompilation,
    recipe: ModelIntentRecipe | None,
) -> VoiceDatasetBalance:
    segments = list(compilation.segments.values())
    approved = [
        segment for segment in segments
        if segment.status == VoiceSegmentStatus.APPROVED
    ]
    source_count = len({segment.source_media_item_id for segment in approved})
    compliance = (
        _voice_recipe_compliance(compilation, recipe)
        if recipe is not None
        else None
    )
    warnings = (
        [check.detail for check in compliance.checks if not check.passed]
        if compliance is not None
        else []
    )
    return VoiceDatasetBalance(
        total_count=len(segments),
        approved_count=len(approved),
        review_count=sum(segment.status == VoiceSegmentStatus.NEEDS_REVIEW for segment in segments),
        rejected_count=sum(segment.status == VoiceSegmentStatus.REJECTED for segment in segments),
        source_count=source_count,
        total_duration_seconds=round(sum(_segment_duration(segment) for segment in approved), 3),
        average_quality=_segment_average(approved, lambda segment: segment.quality.quality_score if segment.quality else None),
        average_speaker_similarity=_segment_average(approved, lambda segment: segment.speaker_similarity),
        average_transcript_confidence=_segment_average(approved, lambda segment: segment.transcript_confidence),
        average_active_audio_ratio=_segment_average(approved, lambda segment: segment.quality.active_audio_ratio if segment.quality else None),
        average_silence_ratio=_segment_average(approved, lambda segment: segment.quality.silence_ratio if segment.quality else None),
        average_clipping_ratio=_segment_average(approved, lambda segment: segment.quality.clipping_ratio if segment.quality else None),
        average_background_music_risk=_segment_average(approved, lambda segment: segment.quality.background_music_risk if segment.quality else None),
        warnings=warnings,
        recipe_compliance=compliance,
    )


def _voice_recipe_compliance(
    compilation: VoiceDatasetCompilation,
    recipe: ModelIntentRecipe,
) -> RecipeCompliance:
    policy = recipe.dataset
    segments = list(compilation.segments.values())
    approved = [
        segment for segment in segments
        if segment.status == VoiceSegmentStatus.APPROVED
    ]
    source_counts = Counter(segment.source_media_item_id for segment in approved)
    largest_source_share = (
        max(source_counts.values(), default=0) / len(approved)
        if approved
        else 0.0
    )
    total_duration = sum(_segment_duration(segment) for segment in approved)
    average_quality = _segment_average(
        approved,
        lambda segment: segment.quality.quality_score if segment.quality else None,
    )
    average_speaker = _segment_average(
        approved,
        lambda segment: segment.speaker_similarity,
    )
    average_transcript = _segment_average(
        approved,
        lambda segment: segment.transcript_confidence,
    )
    average_active = _segment_average(
        approved,
        lambda segment: segment.quality.active_audio_ratio if segment.quality else None,
    )
    average_silence = _segment_average(
        approved,
        lambda segment: segment.quality.silence_ratio if segment.quality else None,
    )
    average_clipping = _segment_average(
        approved,
        lambda segment: segment.quality.clipping_ratio if segment.quality else None,
    )
    average_music = _segment_average(
        approved,
        lambda segment: segment.quality.background_music_risk if segment.quality else None,
    )
    missing_transcripts = sum(not segment.transcript.strip() for segment in approved)
    missing_audio = sum(not segment.audio_path.is_file() for segment in approved)
    missing_quality = sum(segment.quality is None for segment in approved)
    short_segments = sum(
        _segment_duration(segment) + 1e-6 < (policy.minimum_clip_duration_seconds or 0)
        for segment in approved
    )
    long_segments = sum(
        policy.maximum_clip_duration_seconds is not None
        and _segment_duration(segment) > policy.maximum_clip_duration_seconds
        for segment in approved
    )
    multi_speaker_segments = sum(
        segment.quality is not None
        and segment.quality.speaker_count is not None
        and segment.quality.speaker_count > 1
        for segment in approved
    )
    checks = [
        RecipeCheck(
            check_id="modality",
            label="Recipe modality",
            passed=recipe.modality == "voice",
            severity="blocker",
            detail=f"Recipe must target voice; {recipe.label} targets {recipe.modality}.",
            current=recipe.modality,
            target="voice",
        ),
        RecipeCheck(
            check_id="approved-present",
            label="Approved speech",
            passed=bool(approved),
            severity="blocker",
            detail="Approve at least one verified speech segment before export.",
            current=len(approved),
            target="at least 1",
        ),
        RecipeCheck(
            check_id="transcripts",
            label="Transcript coverage",
            passed=missing_transcripts == 0,
            severity="blocker",
            detail=f"{missing_transcripts} approved segments have an empty transcript.",
            current=missing_transcripts,
            target=0,
        ),
        RecipeCheck(
            check_id="audio-files",
            label="Audio files",
            passed=missing_audio == 0,
            severity="blocker",
            detail=f"{missing_audio} approved segment files are missing.",
            current=missing_audio,
            target=0,
        ),
        RecipeCheck(
            check_id="quality-gate",
            label="Quality evidence",
            passed=missing_quality == 0,
            detail=f"{missing_quality} approved segments have not passed the audio quality gate.",
            current=missing_quality,
            target=0,
        ),
        RecipeCheck(
            check_id="approved-segments",
            label="Approved segments",
            passed=len(approved) >= policy.minimum_approved_items,
            detail=f"Approve at least {policy.minimum_approved_items} segments for the {recipe.label} baseline.",
            current=len(approved),
            target=policy.minimum_approved_items,
        ),
        RecipeCheck(
            check_id="maximum-segments",
            label="Dataset size",
            passed=len(approved) <= policy.maximum_approved_items,
            detail=f"Keep no more than {policy.maximum_approved_items} segments without a deliberate recipe revision.",
            current=len(approved),
            target=policy.maximum_approved_items,
        ),
        RecipeCheck(
            check_id="source-count",
            label="Independent sources",
            passed=len(source_counts) >= policy.minimum_sources,
            detail=f"Use at least {policy.minimum_sources} independent source recordings.",
            current=len(source_counts),
            target=policy.minimum_sources,
        ),
        RecipeCheck(
            check_id="source-balance",
            label="Source balance",
            passed=not approved or largest_source_share <= policy.maximum_source_share,
            detail=f"One recording contributes more than {round(policy.maximum_source_share * 100)}% of approved speech.",
            current=round(largest_source_share, 3),
            target=policy.maximum_source_share,
        ),
        RecipeCheck(
            check_id="minimum-duration",
            label="Speech duration",
            passed=(
                policy.minimum_total_duration_seconds is None
                or total_duration >= policy.minimum_total_duration_seconds
            ),
            detail=f"Approve at least {policy.minimum_total_duration_seconds or 0:g} seconds of verified speech.",
            current=round(total_duration, 3),
            target=policy.minimum_total_duration_seconds,
        ),
        RecipeCheck(
            check_id="maximum-duration",
            label="Duration ceiling",
            passed=(
                policy.maximum_total_duration_seconds is None
                or total_duration <= policy.maximum_total_duration_seconds
            ),
            detail=f"Approved speech exceeds the {policy.maximum_total_duration_seconds or 0:g}-second recipe ceiling.",
            current=round(total_duration, 3),
            target=policy.maximum_total_duration_seconds,
        ),
        RecipeCheck(
            check_id="segment-duration-floor",
            label="Segment duration floor",
            passed=short_segments == 0,
            detail=f"{short_segments} approved segments are shorter than {policy.minimum_clip_duration_seconds or 0:g} seconds.",
            current=short_segments,
            target=0,
        ),
        RecipeCheck(
            check_id="segment-duration-ceiling",
            label="Segment duration ceiling",
            passed=long_segments == 0,
            detail=f"{long_segments} approved segments exceed {policy.maximum_clip_duration_seconds or 0:g} seconds.",
            current=long_segments,
            target=0,
        ),
        RecipeCheck(
            check_id="quality",
            label="Average quality",
            passed=average_quality >= policy.minimum_average_quality,
            detail=f"Average signal quality is below {round(policy.minimum_average_quality * 100)}%.",
            current=round(average_quality, 3),
            target=policy.minimum_average_quality,
        ),
        RecipeCheck(
            check_id="speaker-similarity",
            label="Speaker similarity",
            passed=(
                policy.minimum_average_speaker_similarity is None
                or average_speaker >= policy.minimum_average_speaker_similarity
            ),
            detail=f"Average speaker similarity is below {round((policy.minimum_average_speaker_similarity or 0) * 100)}%.",
            current=round(average_speaker, 3),
            target=policy.minimum_average_speaker_similarity,
        ),
        RecipeCheck(
            check_id="transcript-confidence",
            label="Transcript confidence",
            passed=(
                policy.minimum_average_transcript_confidence is None
                or average_transcript >= policy.minimum_average_transcript_confidence
            ),
            detail=f"Average transcript confidence is below {round((policy.minimum_average_transcript_confidence or 0) * 100)}%.",
            current=round(average_transcript, 3),
            target=policy.minimum_average_transcript_confidence,
        ),
        RecipeCheck(
            check_id="active-audio",
            label="Active speech",
            passed=(
                policy.minimum_average_active_audio_ratio is None
                or average_active >= policy.minimum_average_active_audio_ratio
            ),
            detail=f"Average active speech is below {round((policy.minimum_average_active_audio_ratio or 0) * 100)}%.",
            current=round(average_active, 3),
            target=policy.minimum_average_active_audio_ratio,
        ),
        RecipeCheck(
            check_id="silence",
            label="Silence ratio",
            passed=(
                policy.maximum_average_silence_ratio is None
                or average_silence <= policy.maximum_average_silence_ratio
            ),
            detail=f"Average silence exceeds {round((policy.maximum_average_silence_ratio or 0) * 100)}%.",
            current=round(average_silence, 3),
            target=policy.maximum_average_silence_ratio,
        ),
        RecipeCheck(
            check_id="clipping",
            label="Clipping ratio",
            passed=(
                policy.maximum_average_clipping_ratio is None
                or average_clipping <= policy.maximum_average_clipping_ratio
            ),
            detail=f"Average clipping exceeds {round((policy.maximum_average_clipping_ratio or 0) * 100)}%.",
            current=round(average_clipping, 4),
            target=policy.maximum_average_clipping_ratio,
        ),
        RecipeCheck(
            check_id="background-music",
            label="Background music",
            passed=(
                policy.maximum_average_background_music_risk is None
                or average_music <= policy.maximum_average_background_music_risk
            ),
            detail=f"Average background-music risk exceeds {round((policy.maximum_average_background_music_risk or 0) * 100)}%.",
            current=round(average_music, 3),
            target=policy.maximum_average_background_music_risk,
        ),
        RecipeCheck(
            check_id="single-speaker",
            label="Single speaker",
            passed=(
                policy.maximum_multi_speaker_segments is None
                or multi_speaker_segments <= policy.maximum_multi_speaker_segments
            ),
            detail=f"{multi_speaker_segments} approved segments contain multiple detected speakers.",
            current=multi_speaker_segments,
            target=policy.maximum_multi_speaker_segments,
        ),
    ]
    failed_blockers = [
        check for check in checks
        if not check.passed and check.severity == "blocker"
    ]
    failed_warnings = [
        check for check in checks
        if not check.passed and check.severity == "warning"
    ]
    return RecipeCompliance(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.version,
        recipe_label=recipe.label,
        status=(
            "blocked"
            if failed_blockers
            else "review"
            if failed_warnings
            else "ready"
        ),
        score=sum(check.passed for check in checks) / len(checks),
        blocker_count=len(failed_blockers),
        warning_count=len(failed_warnings),
        checks=checks,
    )


def _voice_fingerprint(
    compilation: VoiceDatasetCompilation,
    recipe_id: str | None,
    recipe_version: int | None,
) -> str | None:
    approved = [
        segment for segment in compilation.segments.values()
        if segment.status == VoiceSegmentStatus.APPROVED
    ]
    if not approved:
        return None
    payload = {
        "training_target": {
            "profile_id": compilation.target_profile_id,
            "recipe_id": recipe_id,
            "recipe_version": recipe_version,
        },
        "segments": [
            {
                "id": segment.id,
                "source_media_item_id": segment.source_media_item_id,
                "media_item_id": segment.media_item_id,
                "audio_sha256": (
                    sha256_file(segment.audio_path)
                    if segment.audio_path.is_file()
                    else None
                ),
                "start_seconds": segment.start_seconds,
                "end_seconds": segment.end_seconds,
                "transcript": segment.transcript,
                "language": segment.language,
            }
            for segment in sorted(approved, key=lambda candidate: candidate.id)
        ],
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _segment_duration(segment: VoiceDatasetSegment) -> float:
    return segment.end_seconds - segment.start_seconds


def _segment_average(
    segments: list[VoiceDatasetSegment],
    value_getter,
) -> float:
    values = [
        float(value)
        for segment in segments
        if (value := value_getter(segment)) is not None
    ]
    return sum(values) / len(values) if values else 0.0


def segment_speech_words(
    words: list[SpeechWord],
    duration: float | None,
    *,
    max_duration: float = 12.0,
    min_duration: float = 1.2,
    gap_seconds: float = 0.75,
) -> list[tuple[float, float, list[SpeechWord]]]:
    if not words:
        return []
    chunks: list[list[SpeechWord]] = []
    current: list[SpeechWord] = []
    for word in words:
        if current:
            gap = word.start_seconds - current[-1].end_seconds
            span = word.end_seconds - current[0].start_seconds
            punctuation_break = (
                current[-1].text.rstrip().endswith((".", "?", "!"))
                and current[-1].end_seconds - current[0].start_seconds >= 3.0
            )
            if gap >= gap_seconds or span > max_duration or punctuation_break:
                chunks.append(current)
                current = []
        current.append(word)
    if current:
        chunks.append(current)

    merged: list[list[SpeechWord]] = []
    for chunk in chunks:
        span = chunk[-1].end_seconds - chunk[0].start_seconds
        if merged and span < min_duration:
            combined_span = chunk[-1].end_seconds - merged[-1][0].start_seconds
            if combined_span <= max_duration:
                merged[-1].extend(chunk)
                continue
        merged.append(chunk)

    audio_end = duration if duration is not None and duration > 0 else words[-1].end_seconds
    return [
        (
            max(0.0, chunk[0].start_seconds - 0.12),
            min(audio_end, chunk[-1].end_seconds + 0.18),
            chunk,
        )
        for chunk in merged
        if chunk[-1].end_seconds > chunk[0].start_seconds
    ]


def join_words(words: list[SpeechWord]) -> str:
    text = " ".join(
        word.text.strip()
        for word in words
        if word.text.strip() and not is_non_speech_annotation(word.text)
    )
    for punctuation in (".", ",", "?", "!", ":", ";"):
        text = text.replace(f" {punctuation}", punctuation)
    return text.strip()


def is_non_speech_annotation(value: str) -> bool:
    text = value.strip()
    return len(text) >= 2 and (text[0], text[-1]) in {
        ("*", "*"),
        ("[", "]"),
        ("(", ")"),
    }


def stable_segment_id(source_id: str, start: float, end: float, transcript: str) -> str:
    payload = f"{source_id}|{start:.3f}|{end:.3f}|{transcript}".encode()
    return f"voice_segment_{sha256(payload).hexdigest()[:16]}"
