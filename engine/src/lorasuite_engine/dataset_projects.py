from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

from lorasuite_engine.dataset_analysis import (
    DatasetImageAnalyzer,
    DatasetImageEvidence,
    descriptor_distance,
    feature_similarity,
)
from lorasuite_engine.identity_engine import (
    FaceEmbedding,
    SFaceIdentityEngine,
    anchor_similarity,
    crop_proposals,
)
from lorasuite_engine.identity_models import IdentityModelService
from lorasuite_engine.models import (
    CharacterProject,
    CropKind,
    CropRecipeStatus,
    DatasetDecisionSource,
    DatasetHealth,
    DatasetObservation,
    DatasetReviewStatus,
    DatasetView,
    DerivativeType,
    MediaItem,
    MediaType,
    NormalizedRect,
    TrainingIntent,
    utc_now,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService


class CharacterProjectService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def projects_path(self) -> Path:
        return self.vault_root / "character_projects.json"

    def list_projects(self) -> list[CharacterProject]:
        return sorted(
            self._read_projects().values(),
            key=lambda project: project.updated_at,
            reverse=True,
        )

    def get_project(self, project_id: str) -> CharacterProject | None:
        return self._read_projects().get(project_id)

    def create_project(
        self,
        *,
        name: str = "Character Dataset",
        intent: TrainingIntent | None = None,
    ) -> CharacterProject:
        project = CharacterProject(name=name.strip() or "Character Dataset")
        if intent is not None:
            project.intent = intent
        with json_file_lock(self.projects_path):
            projects = self._read_projects_unlocked()
            projects[project.id] = project
            self._write_projects_unlocked(projects)
        return project

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        intent: TrainingIntent | None = None,
    ) -> CharacterProject:
        project, projects = self._require_project(project_id)
        if name is not None:
            project.name = name.strip() or project.name
        if intent is not None:
            project.intent = intent
        project.updated_at = utc_now()
        self._save_project(project, projects)
        return project

    def add_candidates(self, project_id: str, media_item_ids: list[str]) -> CharacterProject:
        project, projects = self._require_project(project_id)
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        for media_item_id in media_item_ids:
            item = media_by_id.get(media_item_id)
            if item is None:
                raise ValueError(f"media item not found: {media_item_id}")
            if item.media_type != MediaType.IMAGE:
                raise ValueError(f"Identify accepts image media only: {media_item_id}")
            if media_item_id not in project.candidate_media_item_ids:
                project.candidate_media_item_ids.append(media_item_id)
            project.observations.setdefault(
                media_item_id,
                DatasetObservation(media_item_id=media_item_id),
            )
        project.updated_at = utc_now()
        project.health = self._calculate_health(project, media_by_id)
        self._save_project(project, projects)
        return project

    def set_anchors(self, project_id: str, media_item_ids: list[str]) -> CharacterProject:
        project, projects = self._require_project(project_id)
        anchor_ids = set(media_item_ids)
        unknown_ids = anchor_ids.difference(project.candidate_media_item_ids)
        if unknown_ids:
            raise ValueError(f"anchor is not a project candidate: {sorted(unknown_ids)[0]}")
        for media_item_id in project.candidate_media_item_ids:
            observation = project.observations.setdefault(
                media_item_id,
                DatasetObservation(media_item_id=media_item_id),
            )
            observation.is_anchor = media_item_id in anchor_ids
            if observation.is_anchor:
                observation.review_status = DatasetReviewStatus.ACCEPTED
                observation.decision_source = DatasetDecisionSource.ANCHOR
                observation.reasons = ["identity anchor selected by user"]
            elif observation.decision_source == DatasetDecisionSource.ANCHOR:
                observation.review_status = DatasetReviewStatus.NEEDS_REVIEW
                observation.decision_source = DatasetDecisionSource.AUTOMATIC
                observation.reasons = ["anchor removed; analyze to refresh"]
            observation.updated_at = utc_now()
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        project.updated_at = utc_now()
        project.health = self._calculate_health(project, media_by_id)
        self._save_project(project, projects)
        return project

    def update_observation(
        self,
        project_id: str,
        media_item_id: str,
        *,
        review_status: DatasetReviewStatus,
        view: DatasetView | None = None,
    ) -> CharacterProject:
        project, projects = self._require_project(project_id)
        if media_item_id not in project.candidate_media_item_ids:
            raise ValueError(f"media item is not a project candidate: {media_item_id}")
        observation = project.observations.setdefault(
            media_item_id,
            DatasetObservation(media_item_id=media_item_id),
        )
        observation.review_status = review_status
        observation.decision_source = DatasetDecisionSource.USER
        observation.is_anchor = False
        if view is not None:
            observation.view = view
        observation.reasons = [f"marked {review_status.value} by user"]
        observation.updated_at = utc_now()
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        project.updated_at = utc_now()
        project.health = self._calculate_health(project, media_by_id)
        self._save_project(project, projects)
        return project

    def select_subject_face(
        self,
        project_id: str,
        media_item_id: str,
        face_index: int,
    ) -> CharacterProject:
        project, projects = self._require_project(project_id)
        observation = project.observations.get(media_item_id)
        if observation is None:
            raise ValueError(f"media item is not a project candidate: {media_item_id}")
        if face_index not in {face.index for face in observation.faces}:
            raise ValueError(f"face index was not detected: {face_index}")
        observation.selected_face_index = face_index
        for face in observation.faces:
            face.selected = face.index == face_index
        for recipe_id in observation.crop_recipe_ids:
            recipe = project.crop_recipes.get(recipe_id)
            if recipe is not None:
                recipe.face_index = face_index
                recipe.updated_at = utc_now()
        observation.updated_at = utc_now()
        project.updated_at = utc_now()
        self._save_project(project, projects)
        return project

    def update_crop_recipe(
        self,
        project_id: str,
        recipe_id: str,
        *,
        rect: NormalizedRect | None = None,
        status: CropRecipeStatus | None = None,
        kind: CropKind | None = None,
    ) -> CharacterProject:
        project, projects = self._require_project(project_id)
        recipe = project.crop_recipes.get(recipe_id)
        if recipe is None:
            raise ValueError(f"crop recipe not found: {recipe_id}")
        if recipe.status == CropRecipeStatus.MATERIALIZED:
            raise ValueError("materialized crop recipes are immutable")
        if rect is not None:
            recipe.rect = rect
        if status is not None:
            recipe.status = status
        if kind is not None:
            recipe.kind = kind
        recipe.updated_at = utc_now()
        project.updated_at = utc_now()
        self._save_project(project, projects)
        return project

    def materialize_crop(
        self,
        project_id: str,
        recipe_id: str,
    ) -> tuple[CharacterProject, MediaItem]:
        project, projects = self._require_project(project_id)
        recipe = project.crop_recipes.get(recipe_id)
        if recipe is None:
            raise ValueError(f"crop recipe not found: {recipe_id}")
        vault = VaultService(self.vault_root)
        if recipe.output_media_item_id is not None:
            existing = vault.get_media_item(recipe.output_media_item_id)
            if existing is not None:
                return project, existing
        source_item = vault.get_media_item(recipe.media_item_id)
        if source_item is None:
            raise ValueError(f"crop source media not found: {recipe.media_item_id}")
        if source_item.media_type != MediaType.IMAGE:
            raise ValueError("crop source must be an image")

        output_dir = self.vault_root / "derivatives" / "crops" / project.id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{recipe.id}.png"
        with Image.open(source_item.raw_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            width, height = image.size
            left = max(0, min(width - 1, round(recipe.rect.x * width)))
            top = max(0, min(height - 1, round(recipe.rect.y * height)))
            right = max(left + 1, min(width, round((recipe.rect.x + recipe.rect.width) * width)))
            bottom = max(top + 1, min(height, round((recipe.rect.y + recipe.rect.height) * height)))
            image.crop((left, top, right, bottom)).save(output_path, format="PNG")

        derivative_type = (
            DerivativeType.FACE_CROP
            if recipe.kind == CropKind.FACE
            else DerivativeType.PERSON_CROP
        )
        derivative = vault.build_derivative_media_item(
            source_item=source_item,
            derivative_path=output_path,
            media_type=MediaType.IMAGE,
            derivative_type=derivative_type,
            metadata={
                "character_project_id": project.id,
                "crop_recipe_id": recipe.id,
                "crop_kind": recipe.kind,
                "crop_rect": recipe.rect.model_dump(mode="json"),
                "aspect_ratio": recipe.aspect_ratio,
                "face_index": recipe.face_index,
                "generator": {
                    "name": "lorasuite-crop-compiler",
                    "settings": {"version": 1},
                },
            },
        )
        derivative = vault.append_media_items([derivative])[0]
        recipe.output_media_item_id = derivative.id
        recipe.status = CropRecipeStatus.MATERIALIZED
        recipe.updated_at = utc_now()
        project.updated_at = utc_now()
        self._save_project(project, projects)
        return project, derivative

    def analyze_project(self, project_id: str) -> CharacterProject:
        project, projects = self._require_project(project_id)
        media_by_id = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        analyzer = DatasetImageAnalyzer()
        evidence: dict[str, DatasetImageEvidence] = {}
        identity_analyses: dict[str, list[FaceEmbedding]] = {}
        identity_models = IdentityModelService(self.vault_root)
        identity_engine = (
            SFaceIdentityEngine(identity_models.paths)
            if identity_models.status().ready
            else None
        )
        for media_item_id in project.candidate_media_item_ids:
            item = media_by_id.get(media_item_id)
            if item is None or item.media_type != MediaType.IMAGE:
                continue
            try:
                evidence[media_item_id] = analyzer.analyze(item.raw_path)
            except (OSError, ValueError):
                continue
            if identity_engine is not None:
                try:
                    identity_analyses[media_item_id] = identity_engine.analyze(item.raw_path)
                except (OSError, ValueError):
                    identity_analyses[media_item_id] = []

        anchor_evidence = [
            evidence[media_item_id]
            for media_item_id, observation in project.observations.items()
            if observation.is_anchor and media_item_id in evidence
        ]
        anchor_embeddings = self._anchor_embeddings(project, identity_analyses)
        for media_item_id in project.candidate_media_item_ids:
            observation = project.observations.setdefault(
                media_item_id,
                DatasetObservation(media_item_id=media_item_id),
            )
            item_evidence = evidence.get(media_item_id)
            if item_evidence is None:
                observation.review_status = DatasetReviewStatus.REJECTED
                observation.decision_source = DatasetDecisionSource.AUTOMATIC
                observation.reasons = ["image could not be analyzed"]
                observation.warnings = ["missing or unreadable image"]
                observation.updated_at = utc_now()
                continue
            self._apply_evidence(
                observation,
                item_evidence,
                anchor_evidence if identity_engine is None else [],
            )
            if identity_engine is not None:
                self._apply_identity_evidence(
                    observation,
                    identity_analyses.get(media_item_id, []),
                    anchor_embeddings,
                )
                self._replace_crop_proposals(
                    project,
                    observation,
                    media_item=media_by_id[media_item_id],
                )

        self._apply_diversity(project, evidence)
        project.updated_at = utc_now()
        project.health = self._calculate_health(project, media_by_id)
        self._save_project(project, projects)
        return project

    def _anchor_embeddings(
        self,
        project: CharacterProject,
        identity_analyses: dict[str, list[FaceEmbedding]],
    ) -> list[object]:
        anchors: list[object] = []
        for media_item_id, observation in project.observations.items():
            if not observation.is_anchor:
                continue
            faces = identity_analyses.get(media_item_id, [])
            if not faces:
                continue
            selected = next(
                (
                    face
                    for face in faces
                    if face.face.index == observation.selected_face_index
                ),
                faces[0],
            )
            anchors.append(selected.embedding)
        return anchors

    def _apply_identity_evidence(
        self,
        observation: DatasetObservation,
        faces: list[FaceEmbedding],
        anchors: list[object],
    ) -> None:
        observation.identity_backend = SFaceIdentityEngine.backend
        observation.face_count = len(faces)
        if not faces:
            observation.faces = []
            observation.selected_face_index = None
            observation.identity_score = None
            if observation.decision_source != DatasetDecisionSource.USER:
                observation.review_status = DatasetReviewStatus.NEEDS_REVIEW
                observation.reasons = ["no recognizable face; inspect body-only use manually"]
            observation.warnings.append("SFace did not detect a recognizable face")
            return

        for face in faces:
            face.face.anchor_similarity = anchor_similarity(face.embedding, anchors)
        selected = next(
            (
                face
                for face in faces
                if face.face.index == observation.selected_face_index
            ),
            None,
        )
        if selected is None:
            selected = (
                max(
                    faces,
                    key=lambda face: face.face.anchor_similarity
                    if face.face.anchor_similarity is not None
                    else -1.0,
                )
                if anchors
                else faces[0]
            )
        observation.selected_face_index = selected.face.index
        observation.identity_score = selected.face.anchor_similarity
        for face in faces:
            face.face.selected = face.face.index == selected.face.index
        observation.faces = [face.face for face in faces]

        if observation.is_anchor:
            observation.review_status = DatasetReviewStatus.ACCEPTED
            observation.decision_source = DatasetDecisionSource.ANCHOR
            observation.reasons = ["trusted SFace identity anchor"]
        elif observation.decision_source == DatasetDecisionSource.USER:
            observation.reasons = [f"kept {observation.review_status.value} user decision"]
        elif len(anchors) < 3:
            observation.review_status = DatasetReviewStatus.NEEDS_REVIEW
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = ["at least 3 face anchors are required for consensus"]
        elif observation.identity_score is not None and observation.identity_score >= 0.42:
            observation.review_status = DatasetReviewStatus.ACCEPTED
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = ["SFace anchor consensus matched the selected face"]
        elif observation.identity_score is not None and observation.identity_score < 0.20:
            observation.review_status = DatasetReviewStatus.REJECTED
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = ["selected face conflicts with identity anchors"]
        else:
            observation.review_status = DatasetReviewStatus.NEEDS_REVIEW
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = ["identity score is ambiguous; confirm manually"]
        if len(faces) > 1:
            observation.warnings.append("multiple faces detected; confirm the selected subject")

    def _replace_crop_proposals(
        self,
        project: CharacterProject,
        observation: DatasetObservation,
        *,
        media_item: MediaItem,
    ) -> None:
        retained_ids: list[str] = []
        for recipe_id in observation.crop_recipe_ids:
            recipe = project.crop_recipes.get(recipe_id)
            if recipe is not None and recipe.status == CropRecipeStatus.MATERIALIZED:
                retained_ids.append(recipe_id)
            else:
                project.crop_recipes.pop(recipe_id, None)
        selected_face = next(
            (face for face in observation.faces if face.selected),
            None,
        )
        proposals = crop_proposals(
            media_item_id=observation.media_item_id,
            selected_face=selected_face,
            image_width=media_item.width,
            image_height=media_item.height,
        )
        for proposal in proposals:
            project.crop_recipes[proposal.id] = proposal
        observation.crop_recipe_ids = [*retained_ids, *(proposal.id for proposal in proposals)]

    def _apply_evidence(
        self,
        observation: DatasetObservation,
        evidence: DatasetImageEvidence,
        anchors: list[DatasetImageEvidence],
    ) -> None:
        observation.quality_score = evidence.quality_score
        observation.face_count = evidence.face_count
        observation.face_area = evidence.face_area
        observation.body_coverage = evidence.body_coverage
        observation.aesthetic_score = evidence.aesthetic_score
        observation.head_yaw = evidence.head_yaw
        if observation.decision_source != DatasetDecisionSource.USER:
            observation.view = _classify_view(evidence)
        observation.analyzer = evidence.analyzer
        observation.warnings = []
        similarities = [
            similarity
            for anchor in anchors
            if (similarity := feature_similarity(evidence, anchor)) is not None
        ]
        observation.identity_score = (
            sum(sorted(similarities, reverse=True)[:3]) / min(3, len(similarities))
            if similarities
            else None
        )

        if observation.is_anchor:
            observation.review_status = DatasetReviewStatus.ACCEPTED
            observation.decision_source = DatasetDecisionSource.ANCHOR
            observation.reasons = ["identity anchor selected by user"]
        elif observation.decision_source == DatasetDecisionSource.USER:
            observation.reasons = [f"kept {observation.review_status.value} user decision"]
        elif evidence.quality_score < 0.22:
            observation.review_status = DatasetReviewStatus.REJECTED
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = ["visual quality below dataset floor"]
        elif evidence.face_count == 0 and evidence.body_coverage < 0.03:
            observation.review_status = DatasetReviewStatus.REJECTED
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = ["no usable face or person signal"]
        elif observation.identity_score is not None and observation.identity_score >= 0.72:
            observation.review_status = DatasetReviewStatus.NEEDS_REVIEW
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = [
                "strong visual similarity to identity anchors",
                "confirm identity manually",
            ]
        else:
            observation.review_status = DatasetReviewStatus.NEEDS_REVIEW
            observation.decision_source = DatasetDecisionSource.AUTOMATIC
            observation.reasons = [
                "human identity review required"
                if anchors
                else "select identity anchors before automatic comparison"
            ]
        if evidence.face_count > 1:
            observation.warnings.append("multiple faces may confound identity")
        if observation.identity_score is None and anchors:
            observation.warnings.append("identity backend unavailable; similarity not inferred")
        observation.updated_at = utc_now()

    def _apply_diversity(
        self,
        project: CharacterProject,
        evidence: dict[str, DatasetImageEvidence],
    ) -> None:
        for media_item_id, item_evidence in evidence.items():
            peers = [
                other_evidence
                for other_id, other_evidence in evidence.items()
                if other_id != media_item_id
            ]
            project.observations[media_item_id].diversity_score = (
                min(descriptor_distance(item_evidence, peer) for peer in peers)
                if peers
                else 1.0
            )

    def _calculate_health(
        self,
        project: CharacterProject,
        media_by_id: dict[str, MediaItem],
    ) -> DatasetHealth:
        observations = [
            project.observations[media_item_id]
            for media_item_id in project.candidate_media_item_ids
            if media_item_id in project.observations
        ]
        status_counts = Counter(observation.review_status for observation in observations)
        view_counts = Counter(observation.view.value for observation in observations)
        source_counts = Counter(
            _logical_source(media_by_id[observation.media_item_id])
            for observation in observations
            if observation.media_item_id in media_by_id
        )
        candidate_count = len(observations)
        accepted = status_counts[DatasetReviewStatus.ACCEPTED]
        largest_source_share = (
            max(source_counts.values(), default=0) / candidate_count if candidate_count else 0.0
        )
        average_quality = (
            sum(observation.quality_score for observation in observations) / candidate_count
            if candidate_count
            else 0.0
        )
        average_diversity = (
            sum(observation.diversity_score for observation in observations) / candidate_count
            if candidate_count
            else 0.0
        )
        warnings: list[str] = []
        anchor_count = sum(observation.is_anchor for observation in observations)
        if anchor_count < 5:
            warnings.append("Select at least 5 clear identity anchors.")
        if accepted < 20:
            warnings.append("Fewer than 20 observations are accepted for training.")
        if largest_source_share > 0.65 and candidate_count >= 4:
            warnings.append("One source contributes more than 65% of the dataset.")
        if view_counts[DatasetView.FACE.value] == 0:
            warnings.append("No close face views are represented.")
        if view_counts[DatasetView.FULL_BODY.value] == 0:
            warnings.append("No full-body views are represented.")
        if average_quality and average_quality < 0.45:
            warnings.append("Average visual quality is below the recommended floor.")
        analyzer_names = sorted({observation.analyzer for observation in observations})
        return DatasetHealth(
            candidate_count=candidate_count,
            accepted_count=accepted,
            review_count=status_counts[DatasetReviewStatus.NEEDS_REVIEW],
            rejected_count=status_counts[DatasetReviewStatus.REJECTED],
            anchor_count=anchor_count,
            effective_observation_count=round(
                sum(
                    0.25 + 0.75 * observation.diversity_score
                    for observation in observations
                    if observation.review_status == DatasetReviewStatus.ACCEPTED
                ),
                1,
            ),
            source_count=len(source_counts),
            largest_source_share=largest_source_share,
            average_quality=average_quality,
            average_diversity=average_diversity,
            view_counts=dict(view_counts),
            analyzer=", ".join(analyzer_names) if analyzer_names else "pending",
            warnings=warnings,
        )

    def _require_project(
        self,
        project_id: str,
    ) -> tuple[CharacterProject, dict[str, CharacterProject]]:
        projects = self._read_projects()
        project = projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        return project, projects

    def _save_project(
        self,
        project: CharacterProject,
        projects: dict[str, CharacterProject],
    ) -> None:
        with json_file_lock(self.projects_path):
            current_projects = self._read_projects_unlocked()
            current_projects.update(projects)
            current_projects[project.id] = project
            self._write_projects_unlocked(current_projects)

    def _read_projects(self) -> dict[str, CharacterProject]:
        with json_file_lock(self.projects_path):
            return self._read_projects_unlocked()

    def _read_projects_unlocked(self) -> dict[str, CharacterProject]:
        if not self.projects_path.exists():
            return {}
        data = json.loads(self.projects_path.read_text(encoding="utf-8"))
        return {
            payload["id"]: CharacterProject.model_validate(payload)
            for payload in data.get("projects", [])
        }

    def _write_projects_unlocked(self, projects: dict[str, CharacterProject]) -> None:
        atomic_write_json(
            self.projects_path,
            {
                "version": 1,
                "projects": [
                    project.model_dump(mode="json") for project in projects.values()
                ],
            },
        )


def _classify_view(evidence: DatasetImageEvidence) -> DatasetView:
    if evidence.face_area >= 0.075:
        return DatasetView.FACE
    if evidence.pose_coverage >= 0.52 or evidence.body_coverage >= 0.24:
        return DatasetView.FULL_BODY
    if evidence.face_count or evidence.body_coverage > 0.03 or evidence.pose_coverage > 0.18:
        return DatasetView.UPPER_BODY
    return DatasetView.ENVIRONMENT


def _logical_source(item: MediaItem) -> str:
    metadata = item.metadata_json or {}
    source_media_item_id = metadata.get("source_media_item_id")
    return str(source_media_item_id or item.source_id)
