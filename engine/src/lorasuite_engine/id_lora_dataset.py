from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.models import ExportPackage, ExportType, MediaItem, VoiceSegmentStatus, new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import (
    ModelIntentRecipe,
    RecipeCheck,
    RecipeCompliance,
    get_training_target_profile,
)
from lorasuite_engine.vault import VaultService
from lorasuite_engine.video_dataset import VideoDatasetItem, VideoDatasetService
from lorasuite_engine.voice_dataset import VoiceDatasetService


IdLoraPairingKind = Literal["synchronized_av", "visual_only"]
IdLoraSplit = Literal["train", "validation"]


class IdLoraExample(BaseModel):
    id: str = Field(default_factory=lambda: new_id("id_lora_example"))
    video_dataset_item_id: str
    video_media_item_id: str
    video_source_media_item_id: str
    video_start_seconds: float
    video_end_seconds: float
    visual_caption: str
    voice_segment_id: str | None = None
    audio_media_item_id: str | None = None
    audio_source_media_item_id: str | None = None
    audio_start_seconds: float | None = None
    audio_end_seconds: float | None = None
    transcript: str | None = None
    reference_voice_segment_id: str | None = None
    reference_audio_media_item_id: str | None = None
    reference_audio_source_media_item_id: str | None = None
    multimodal_caption: str
    pairing_kind: IdLoraPairingKind
    split: IdLoraSplit
    identity_score: float = 0.0
    speaker_similarity: float | None = None
    warnings: list[str] = Field(default_factory=list)


class IdLoraVoiceReference(BaseModel):
    voice_segment_id: str
    audio_media_item_id: str
    audio_source_media_item_id: str
    transcript: str
    split: IdLoraSplit
    speaker_similarity: float | None = None
    quality_score: float | None = None


class IdLoraBalance(BaseModel):
    visual_example_count: int = 0
    synchronized_pair_count: int = 0
    visual_only_count: int = 0
    voice_reference_count: int = 0
    train_count: int = 0
    validation_count: int = 0
    source_count: int = 0
    average_identity: float = 0.0
    average_speaker_similarity: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    recipe_compliance: RecipeCompliance | None = None


class IdLoraManifest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("id_lora_manifest"))
    project_id: str
    video_snapshot_id: str
    video_fingerprint: str
    target_profile_id: str = "runpod_id_lora_ltx23_inference"
    target_label: str = "ID-LoRA LTX-2.3 Zero-Shot"
    workflow_kind: Literal["inference"] = "inference"
    status: Literal["ready", "blocked"]
    examples: dict[str, IdLoraExample] = Field(default_factory=dict)
    voice_references: dict[str, IdLoraVoiceReference] = Field(default_factory=dict)
    balance: IdLoraBalance = Field(default_factory=IdLoraBalance)
    fingerprint: str
    export_path: Path | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)


class IdLoraDatasetService:
    """Builds an explicit visual, synchronized AV, and voice-reference contract."""

    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.vault = VaultService(self.vault_root)

    @property
    def manifests_path(self) -> Path:
        return self.vault_root / "id_lora_manifests.json"

    def list_manifests(self, project_id: str | None = None) -> list[IdLoraManifest]:
        manifests = self._read().values()
        if project_id:
            manifests = (item for item in manifests if item.project_id == project_id)
        return sorted(manifests, key=lambda item: item.updated_at, reverse=True)

    def get_manifest(self, manifest_id: str) -> IdLoraManifest | None:
        return self._read().get(manifest_id)

    def compile_project(self, project_id: str, video_snapshot_id: str | None = None) -> IdLoraManifest:
        video_service = VideoDatasetService(self.vault_root)
        snapshots = video_service.list_snapshots(project_id)
        if video_snapshot_id:
            snapshot = video_service.get_snapshot(video_snapshot_id)
            if snapshot is None or snapshot.project_id != project_id:
                raise KeyError(video_snapshot_id)
        else:
            snapshot = next((item for item in snapshots if item.status in {"frozen", "exported"}), None)
        if snapshot is None or snapshot.status not in {"frozen", "exported"} or not snapshot.fingerprint:
            raise ValueError("freeze a reviewed video dataset before compiling ID-LoRA inputs")

        approved_videos = [item for item in snapshot.items.values() if item.status == "approved"]
        if not approved_videos:
            raise ValueError("the video dataset has no approved clips")
        voice = VoiceDatasetService(self.vault_root).get(project_id)
        approved_voice = [
            segment for segment in voice.segments.values()
            if segment.status == VoiceSegmentStatus.APPROVED
        ]
        media_by_id = {item.id: item for item in self.vault.list_media_items()}
        source_splits = {
            item.source_media_item_id: item.split
            for item in approved_videos
        }
        voice_references: dict[str, IdLoraVoiceReference] = {}
        voice_ranges: dict[str, tuple[str, float, float]] = {}
        for segment in approved_voice:
            source = media_by_id.get(segment.source_media_item_id)
            if source is None:
                continue
            root_id, offset = _root_and_offset(source, media_by_id)
            start = offset + segment.start_seconds
            end = offset + segment.end_seconds
            split = source_splits.get(root_id) or _stable_split(root_id, source_splits)
            voice_ranges[segment.id] = (root_id, start, end)
            voice_references[segment.id] = IdLoraVoiceReference(
                voice_segment_id=segment.id,
                audio_media_item_id=segment.media_item_id,
                audio_source_media_item_id=root_id,
                transcript=segment.transcript,
                split=split,
                speaker_similarity=segment.speaker_similarity,
                quality_score=segment.quality.quality_score if segment.quality else None,
            )

        examples: dict[str, IdLoraExample] = {}
        for video in approved_videos:
            media = media_by_id.get(video.media_item_id)
            if media is None:
                raise ValueError(f"video media is missing: {video.media_item_id}")
            root_id, offset = _root_and_offset(media, media_by_id)
            video_start = offset
            video_end = offset + video.duration_seconds
            match = _best_synchronized_voice(root_id, video_start, video_end, approved_voice, voice_ranges)
            warnings: list[str] = []
            if match is None:
                warnings.append("No approved same-source speech overlaps this clip; kept as visual-only evidence.")
            transcript = match.transcript if match else None
            caption = _multimodal_caption(video.caption, transcript)
            record = IdLoraExample(
                video_dataset_item_id=video.id,
                video_media_item_id=video.media_item_id,
                video_source_media_item_id=root_id,
                video_start_seconds=video_start,
                video_end_seconds=video_end,
                visual_caption=video.caption,
                voice_segment_id=match.id if match else None,
                audio_media_item_id=match.media_item_id if match else None,
                audio_source_media_item_id=root_id if match else None,
                audio_start_seconds=voice_ranges[match.id][1] if match else None,
                audio_end_seconds=voice_ranges[match.id][2] if match else None,
                transcript=transcript,
                multimodal_caption=caption,
                pairing_kind="synchronized_av" if match else "visual_only",
                split=video.split,
                identity_score=video.identity_score,
                speaker_similarity=match.speaker_similarity if match else None,
                warnings=warnings,
            )
            examples[record.id] = record

        _assign_voice_references(examples, voice_references)

        target = get_training_target_profile("runpod_id_lora_ltx23_inference")
        if target.recipe is None:
            raise ValueError("ID-LoRA inference target has no versioned reference recipe")
        compliance = _recipe_compliance(examples, voice_references, target.recipe)
        warnings = [
            check.detail for check in compliance.checks
            if not check.passed
        ]
        balance = IdLoraBalance(
            visual_example_count=len(examples),
            synchronized_pair_count=sum(item.pairing_kind == "synchronized_av" for item in examples.values()),
            visual_only_count=sum(item.pairing_kind == "visual_only" for item in examples.values()),
            voice_reference_count=len(voice_references),
            train_count=sum(item.split == "train" for item in examples.values()),
            validation_count=sum(item.split == "validation" for item in examples.values()),
            source_count=len({item.video_source_media_item_id for item in examples.values()}),
            average_identity=_average(
                [item.identity_score for item in examples.values()]
            ),
            average_speaker_similarity=_average([
                item.speaker_similarity
                for item in examples.values()
                if item.speaker_similarity is not None
            ]),
            warnings=warnings,
            recipe_compliance=compliance,
        )
        fingerprint = _fingerprint(
            snapshot.fingerprint,
            examples,
            voice_references,
            target.profile_id,
            target.recipe_id,
            target.recipe_version,
        )
        prior = next((item for item in self.list_manifests(project_id) if item.video_snapshot_id == snapshot.id), None)
        manifest = IdLoraManifest(
            id=prior.id if prior else new_id("id_lora_manifest"),
            project_id=project_id,
            video_snapshot_id=snapshot.id,
            video_fingerprint=snapshot.fingerprint,
            target_profile_id=target.profile_id,
            target_label=target.label,
            status="ready" if compliance.status == "ready" else "blocked",
            examples=examples,
            voice_references=voice_references,
            balance=balance,
            fingerprint=fingerprint,
            created_at=prior.created_at if prior else utc_now(),
            updated_at=utc_now(),
        )
        manifests = self._read()
        manifests[manifest.id] = manifest
        self._write(manifests)
        return manifest

    def export(self, manifest_id: str, output_dir: Path) -> tuple[IdLoraManifest, ExportPackage]:
        manifest = self.get_manifest(manifest_id)
        if manifest is None:
            raise KeyError(manifest_id)
        if manifest.status != "ready":
            raise ValueError("resolve ID-LoRA blocking warnings before export")
        inference_target = get_training_target_profile(manifest.target_profile_id)
        inference_recipe = inference_target.recipe
        if inference_recipe is None or inference_recipe.workflow_kind != "inference":
            raise ValueError("ID-LoRA target must use a versioned inference recipe")
        video_snapshot = VideoDatasetService(self.vault_root).get_snapshot(manifest.video_snapshot_id)
        if video_snapshot is None or video_snapshot.status != "exported" or not video_snapshot.export_path:
            raise ValueError("export the frozen video dataset before exporting ID-LoRA inputs")
        normalized_videos = _normalized_video_paths(Path(video_snapshot.export_path))
        media_by_id = {item.id: item for item in self.vault.list_media_items()}
        output_dir = Path(output_dir).expanduser().resolve(strict=False)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(mkdtemp(prefix=f".{output_dir.name}.staging.", dir=output_dir.parent))
        moved = False
        manifest_examples: list[dict[str, Any]] = []
        try:
            for index, example in enumerate(sorted(manifest.examples.values(), key=lambda item: item.id), start=1):
                split_dir = staged / example.split
                video_path = normalized_videos.get(example.video_dataset_item_id)
                if video_path is None or not video_path.is_file():
                    raise ValueError(f"normalized video is missing: {example.video_dataset_item_id}")
                basename = f"example_{index:06d}"
                target_video = split_dir / "video" / f"{basename}.mp4"
                target_caption = split_dir / "captions" / f"{basename}.txt"
                target_video.parent.mkdir(parents=True, exist_ok=True)
                target_caption.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(video_path, target_video)
                target_caption.write_text(example.multimodal_caption.rstrip() + "\n", encoding="utf-8")
                target_audio = None
                if example.audio_media_item_id:
                    audio_item = media_by_id.get(example.audio_media_item_id)
                    if audio_item is None or not audio_item.raw_path.is_file():
                        raise ValueError(f"synchronized audio is missing: {example.audio_media_item_id}")
                    target_audio = split_dir / "audio" / f"{basename}.wav"
                    target_audio.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(audio_item.raw_path, target_audio)
                manifest_examples.append({
                    **example.model_dump(mode="json"),
                    "video": str(target_video.relative_to(staged)),
                    "audio": str(target_audio.relative_to(staged)) if target_audio else None,
                    "caption": str(target_caption.relative_to(staged)),
                })

            manifest_references: list[dict[str, Any]] = []
            reference_paths: dict[str, str] = {}
            for index, reference in enumerate(sorted(manifest.voice_references.values(), key=lambda item: item.voice_segment_id), start=1):
                audio_item = media_by_id.get(reference.audio_media_item_id)
                if audio_item is None or not audio_item.raw_path.is_file():
                    raise ValueError(f"voice reference is missing: {reference.audio_media_item_id}")
                basename = f"voice_{index:06d}"
                target_audio = staged / "voice_references" / reference.split / f"{basename}.wav"
                target_text = staged / "voice_references" / reference.split / f"{basename}.txt"
                target_audio.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(audio_item.raw_path, target_audio)
                target_text.write_text(reference.transcript.rstrip() + "\n", encoding="utf-8")
                manifest_references.append({
                    **reference.model_dump(mode="json"),
                    "audio": str(target_audio.relative_to(staged)),
                    "transcript_file": str(target_text.relative_to(staged)),
                })
                reference_paths[reference.voice_segment_id] = str(target_audio.relative_to(staged))

            trainer_examples = []
            for example in manifest_examples:
                reference_id = example.get("reference_voice_segment_id")
                if example.get("pairing_kind") != "synchronized_av" or not reference_id:
                    continue
                trainer_examples.append({
                    "id": example["id"],
                    "caption": example["multimodal_caption"],
                    "video": example["video"],
                    "audio": example["audio"],
                    "reference_audio": reference_paths[reference_id],
                    "split": example["split"],
                    "target_source_id": example["video_source_media_item_id"],
                    "reference_source_id": example["reference_audio_source_media_item_id"],
                })
            atomic_write_json(staged / "trainer_dataset.json", trainer_examples)
            (staged / "manifest.json").write_text(json.dumps({
                "created_by": "LoraSuite",
                "format": "id-lora-av-v1",
                "project_id": manifest.project_id,
                "manifest_id": manifest.id,
                "fingerprint": manifest.fingerprint,
                "recipe_compliance": (
                    manifest.balance.recipe_compliance.model_dump(mode="json")
                    if manifest.balance.recipe_compliance
                    else None
                ),
                "training_target": {
                    "profile_id": "runpod_id_lora_ltx23",
                    "ready": False,
                    "trainer_dataset": "trainer_dataset.json",
                    "evaluation_required": True,
                    "reason": "Per-person data is packaged for ID-LoRA zero-shot inference and evaluation, not generic adapter retraining.",
                },
                "inference_target": {
                    "profile_id": inference_target.profile_id,
                    "label": inference_target.label,
                    "workflow_kind": inference_recipe.workflow_kind,
                    "model_family": inference_target.model_family,
                    "base_model": inference_target.base_model,
                    "recipe_id": inference_target.recipe_id,
                    "recipe_version": inference_target.recipe_version,
                    "recipe_status": inference_recipe.status,
                    "ready": (
                        manifest.balance.recipe_compliance is not None
                        and manifest.balance.recipe_compliance.status == "ready"
                    ),
                    "pipeline": inference_recipe.inference.pipeline if inference_recipe.inference else "two_stage_hq",
                    "dataset": "trainer_dataset.json",
                    "reference_audio_seconds": (
                        inference_recipe.inference.reference_audio_seconds
                        if inference_recipe.inference
                        else 5
                    ),
                    "evaluation_required": True,
                },
                "examples": manifest_examples,
                "voice_references": manifest_references,
            }, indent=2) + "\n", encoding="utf-8")
            if output_dir.exists():
                shutil.rmtree(output_dir)
            staged.replace(output_dir)
            moved = True
        finally:
            if not moved and staged.exists():
                shutil.rmtree(staged)
        package = ExportPackage(
            export_type=ExportType.ID_LORA_AV,
            output_path=output_dir,
            manifest_path=output_dir / "manifest.json",
            status="complete",
        )
        manifests = self._read()
        manifest.export_path = output_dir
        manifest.updated_at = utc_now()
        manifests[manifest.id] = manifest
        self._write(manifests)
        return manifest, package

    def _read(self) -> dict[str, IdLoraManifest]:
        with json_file_lock(self.manifests_path):
            if not self.manifests_path.exists():
                return {}
            try:
                payload = json.loads(self.manifests_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return {
                item["id"]: IdLoraManifest.model_validate(item)
                for item in payload.get("manifests", [])
            }

    def _write(self, manifests: dict[str, IdLoraManifest]) -> None:
        with json_file_lock(self.manifests_path):
            atomic_write_json(self.manifests_path, {
                "version": 1,
                "manifests": [item.model_dump(mode="json") for item in manifests.values()],
            })


def _root_and_offset(item: MediaItem, media_by_id: dict[str, MediaItem]) -> tuple[str, float]:
    current = item
    offset = 0.0
    visited: set[str] = set()
    while current.id not in visited:
        visited.add(current.id)
        time_range = current.metadata_json.get("time_range")
        if isinstance(time_range, dict):
            try:
                offset += float(time_range.get("start_seconds", 0.0))
            except (TypeError, ValueError):
                pass
        parent_id = current.metadata_json.get("source_media_item_id")
        parent = media_by_id.get(parent_id) if isinstance(parent_id, str) else None
        if parent is None:
            return current.id, offset
        current = parent
    return current.id, offset


def _stable_split(root_id: str, known_source_splits: dict[str, str]) -> IdLoraSplit:
    validation_roots = {source for source, split in known_source_splits.items() if split == "validation"}
    if root_id in validation_roots:
        return "validation"
    return "train"


def _best_synchronized_voice(root_id, start, end, segments, ranges):
    matches = []
    for segment in segments:
        interval = ranges.get(segment.id)
        if interval is None or interval[0] != root_id:
            continue
        overlap = max(0.0, min(end, interval[2]) - max(start, interval[1]))
        if overlap < 0.2:
            continue
        quality = segment.quality.quality_score if segment.quality else 0.0
        matches.append((overlap, segment.speaker_similarity or 0.0, quality, segment))
    return max(matches, default=(0, 0, 0, None), key=lambda item: item[:3])[3]


def _multimodal_caption(visual_caption: str, transcript: str | None) -> str:
    speech = transcript.strip() if transcript else "none"
    return f"[VISUAL] {visual_caption.strip()} [SPEECH] {speech} [SOUNDS] unverified"


def _assign_voice_references(examples, references) -> None:
    for example in examples.values():
        if example.pairing_kind != "synchronized_av":
            continue
        candidates = [
            reference
            for reference in references.values()
            if reference.split == example.split and reference.voice_segment_id != example.voice_segment_id
        ]
        if not candidates:
            example.warnings.append(
                "No distinct same-split voice sample is available for reference conditioning."
            )
            continue
        reference = max(
            candidates,
            key=lambda item: (
                item.audio_source_media_item_id != example.audio_source_media_item_id,
                item.speaker_similarity or 0.0,
                item.quality_score or 0.0,
                item.voice_segment_id,
            ),
        )
        example.reference_voice_segment_id = reference.voice_segment_id
        example.reference_audio_media_item_id = reference.audio_media_item_id
        example.reference_audio_source_media_item_id = reference.audio_source_media_item_id


def _recipe_compliance(
    examples: dict[str, IdLoraExample],
    references: dict[str, IdLoraVoiceReference],
    recipe: ModelIntentRecipe,
) -> RecipeCompliance:
    policy = recipe.dataset
    synchronized = [
        item for item in examples.values()
        if item.pairing_kind == "synchronized_av"
    ]
    source_counts: dict[str, int] = {}
    for item in examples.values():
        source_counts[item.video_source_media_item_id] = (
            source_counts.get(item.video_source_media_item_id, 0) + 1
        )
    largest_source_share = (
        max(source_counts.values(), default=0) / len(examples)
        if examples
        else 0.0
    )
    validation_count = sum(
        item.split == "validation" for item in examples.values()
    )
    average_identity = _average([
        item.identity_score for item in examples.values()
    ])
    average_speaker = _average([
        item.speaker_similarity
        for item in synchronized
        if item.speaker_similarity is not None
    ])
    missing_references = sum(
        not item.reference_voice_segment_id
        for item in synchronized
    )
    train_audio = {
        item.audio_source_media_item_id
        for item in references.values()
        if item.split == "train"
    }
    validation_audio = {
        item.audio_source_media_item_id
        for item in references.values()
        if item.split == "validation"
    }
    leakage = train_audio.intersection(validation_audio)
    checks = [
        RecipeCheck(
            check_id="workflow-kind",
            label="Workflow kind",
            passed=recipe.workflow_kind == "inference",
            severity="blocker",
            detail="ID-LoRA references must use an inference recipe, not a per-person training recipe.",
            current=recipe.workflow_kind,
            target="inference",
        ),
        RecipeCheck(
            check_id="visual-examples",
            label="Visual examples",
            passed=len(examples) >= (policy.minimum_visual_examples or 1),
            severity="blocker",
            detail=f"Package at least {policy.minimum_visual_examples or 1} reviewed visual identity examples.",
            current=len(examples),
            target=policy.minimum_visual_examples,
        ),
        RecipeCheck(
            check_id="synchronized-pairs",
            label="Synchronized AV",
            passed=len(synchronized) >= (policy.minimum_synchronized_pairs or 1),
            severity="blocker",
            detail=f"Package at least {policy.minimum_synchronized_pairs or 1} source-aligned audio-visual examples.",
            current=len(synchronized),
            target=policy.minimum_synchronized_pairs,
        ),
        RecipeCheck(
            check_id="voice-references",
            label="Voice references",
            passed=len(references) >= (policy.minimum_voice_references or 1),
            severity="blocker",
            detail=f"Package at least {policy.minimum_voice_references or 1} approved voice references.",
            current=len(references),
            target=policy.minimum_voice_references,
        ),
        RecipeCheck(
            check_id="distinct-references",
            label="Distinct references",
            passed=missing_references == 0,
            severity="blocker",
            detail=f"{missing_references} synchronized targets lack a distinct same-split reference voice sample.",
            current=missing_references,
            target=0,
        ),
        RecipeCheck(
            check_id="validation-examples",
            label="Validation examples",
            passed=validation_count >= (policy.minimum_validation_examples or 1),
            severity="blocker",
            detail=f"Hold out at least {policy.minimum_validation_examples or 1} source-safe validation example.",
            current=validation_count,
            target=policy.minimum_validation_examples,
        ),
        RecipeCheck(
            check_id="source-count",
            label="Independent sources",
            passed=len(source_counts) >= policy.minimum_sources,
            severity="blocker",
            detail=f"Represent at least {policy.minimum_sources} independent video sources.",
            current=len(source_counts),
            target=policy.minimum_sources,
        ),
        RecipeCheck(
            check_id="source-balance",
            label="Source balance",
            passed=not examples or largest_source_share <= policy.maximum_source_share,
            severity="blocker",
            detail=f"One video source contributes more than {round(policy.maximum_source_share * 100)}% of examples.",
            current=round(largest_source_share, 3),
            target=policy.maximum_source_share,
        ),
        RecipeCheck(
            check_id="identity",
            label="Visual identity",
            passed=(
                policy.minimum_average_identity is None
                or average_identity >= policy.minimum_average_identity
            ),
            severity="blocker",
            detail=f"Average visual identity evidence is below {round((policy.minimum_average_identity or 0) * 100)}%.",
            current=round(average_identity, 3),
            target=policy.minimum_average_identity,
        ),
        RecipeCheck(
            check_id="speaker",
            label="Speaker identity",
            passed=(
                policy.minimum_average_speaker_similarity is None
                or average_speaker >= policy.minimum_average_speaker_similarity
            ),
            severity="blocker",
            detail=f"Average synchronized speaker similarity is below {round((policy.minimum_average_speaker_similarity or 0) * 100)}%.",
            current=round(average_speaker, 3),
            target=policy.minimum_average_speaker_similarity,
        ),
        RecipeCheck(
            check_id="split-leakage",
            label="Split isolation",
            passed=not leakage,
            severity="blocker",
            detail="Voice source leakage exists between train and validation references.",
            current=len(leakage),
            target=0,
        ),
    ]
    failed = [check for check in checks if not check.passed]
    return RecipeCompliance(
        recipe_id=recipe.recipe_id,
        recipe_version=recipe.version,
        recipe_label=recipe.label,
        status="blocked" if failed else "ready",
        score=sum(check.passed for check in checks) / len(checks),
        blocker_count=len(failed),
        warning_count=0,
        checks=checks,
    )


def _average(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _fingerprint(
    video_fingerprint,
    examples,
    references,
    target_profile_id,
    recipe_id,
    recipe_version,
) -> str:
    payload = {
        "video_fingerprint": video_fingerprint,
        "inference_target": {
            "profile_id": target_profile_id,
            "recipe_id": recipe_id,
            "recipe_version": recipe_version,
        },
        "examples": [item.model_dump(mode="json") for item in sorted(examples.values(), key=lambda value: value.id)],
        "voice_references": [item.model_dump(mode="json") for item in sorted(references.values(), key=lambda value: value.voice_segment_id)],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _normalized_video_paths(export_path: Path) -> dict[str, Path]:
    manifest_path = export_path / "manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(item["dataset_item_id"]): export_path / str(item["video"])
        for item in payload.get("files", [])
        if isinstance(item, dict) and item.get("dataset_item_id") and item.get("video")
    }
