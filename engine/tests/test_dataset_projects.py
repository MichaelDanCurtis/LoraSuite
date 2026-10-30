from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

import lorasuite_engine.dataset_projects as dataset_projects_module
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.identity_engine import FaceEmbedding
from lorasuite_engine.models import (
    CropKind,
    CropRecipeStatus,
    DatasetDecisionSource,
    DatasetReviewStatus,
    DatasetView,
    DerivativeType,
    IdentityFace,
    IdentityRuntimeStatus,
    NormalizedRect,
)
from lorasuite_engine.vault import VaultService


def make_portrait(path: Path, *, offset: int = 0) -> Path:
    image = Image.new("RGB", (320, 480), color=(42 + offset, 58, 70))
    draw = ImageDraw.Draw(image)
    draw.ellipse((95 + offset, 70, 225 + offset, 205), fill=(220, 170, 130))
    draw.rectangle((80 + offset, 205, 240 + offset, 455), fill=(105, 145, 185))
    image.save(path)
    return path


def test_character_project_persists_intent_candidates_anchors_and_health(tmp_path):
    vault_root = tmp_path / "vault"
    imported = VaultService(vault_root).import_local_paths(
        [
            make_portrait(tmp_path / "portrait-a.png"),
            make_portrait(tmp_path / "portrait-b.png", offset=8),
        ]
    ).media_items
    service = CharacterProjectService(vault_root)

    project = service.create_project(name="Mary Sue Character")
    project.intent.subject_name = "Mary Sue"
    project.intent.trigger_token = "example_person"
    project = service.update_project(project.id, intent=project.intent)
    project = service.add_candidates(project.id, [item.id for item in imported])
    project = service.set_anchors(project.id, [imported[0].id])
    project = service.analyze_project(project.id)

    restored = CharacterProjectService(vault_root).get_project(project.id)
    assert restored is not None
    assert restored.name == "Mary Sue Character"
    assert restored.intent.subject_name == "Mary Sue"
    assert restored.intent.trigger_token == "example_person"
    assert restored.candidate_media_item_ids == [item.id for item in imported]
    assert restored.observations[imported[0].id].is_anchor is True
    assert restored.observations[imported[0].id].review_status == DatasetReviewStatus.ACCEPTED
    assert restored.health.candidate_count == 2
    assert restored.health.anchor_count == 1
    assert restored.health.source_count == 1
    assert restored.health.analyzer != "pending"
    assert (vault_root / "character_projects.json").exists()


def test_user_review_decision_survives_subsequent_automatic_analysis(tmp_path):
    vault_root = tmp_path / "vault"
    item = VaultService(vault_root).import_local_paths(
        [make_portrait(tmp_path / "candidate.png")]
    ).media_items[0]
    service = CharacterProjectService(vault_root)
    project = service.create_project()
    project = service.add_candidates(project.id, [item.id])
    project = service.update_observation(
        project.id,
        item.id,
        review_status=DatasetReviewStatus.ACCEPTED,
        view=DatasetView.FULL_BODY,
    )

    analyzed = service.analyze_project(project.id)

    observation = analyzed.observations[item.id]
    assert observation.review_status == DatasetReviewStatus.ACCEPTED
    assert observation.decision_source == DatasetDecisionSource.USER
    assert observation.view == DatasetView.FULL_BODY
    assert analyzed.health.accepted_count == 1


def test_character_project_rejects_non_image_candidates(tmp_path):
    vault_root = tmp_path / "vault"
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"RIFF-test")
    item = VaultService(vault_root).import_local_paths([audio_path]).media_items[0]
    service = CharacterProjectService(vault_root)
    project = service.create_project()

    try:
        service.add_candidates(project.id, [item.id])
    except ValueError as error:
        assert "Identify accepts image media only" in str(error)
    else:
        raise AssertionError("expected non-image candidate to be rejected")


def test_identity_compile_preserves_subject_face_and_materializes_crop_lineage(
    monkeypatch, tmp_path
):
    vault_root = tmp_path / "vault"
    wide_path = tmp_path / "wide-candidate.png"
    Image.new("RGB", (640, 480), color=(30, 70, 100)).save(wide_path)
    source_items = VaultService(vault_root).import_local_paths(
        [make_portrait(tmp_path / "two-face-candidate.png"), wide_path]
    ).media_items
    source_item = source_items[0]

    class FakeIdentityEngine:
        backend = "test-sface"

        def __init__(self, _paths):
            pass

        def analyze(self, _path):
            return [
                FaceEmbedding(
                    face=IdentityFace(
                        index=0,
                        confidence=0.98,
                        bounding_box=NormalizedRect(
                            x=0.15, y=0.12, width=0.25, height=0.22
                        ),
                    ),
                    embedding=np.array([1.0, 0.0], dtype=np.float32),
                ),
                FaceEmbedding(
                    face=IdentityFace(
                        index=1,
                        confidence=0.96,
                        bounding_box=NormalizedRect(
                            x=0.58, y=0.14, width=0.22, height=0.20
                        ),
                    ),
                    embedding=np.array([0.0, 1.0], dtype=np.float32),
                ),
            ]

    monkeypatch.setattr(
        dataset_projects_module.IdentityModelService,
        "status",
        lambda _self: IdentityRuntimeStatus(installed=True, ready=True),
    )
    monkeypatch.setattr(dataset_projects_module, "SFaceIdentityEngine", FakeIdentityEngine)

    service = CharacterProjectService(vault_root)
    project = service.create_project()
    project = service.add_candidates(project.id, [item.id for item in source_items])
    project = service.analyze_project(project.id)

    observation = project.observations[source_item.id]
    assert observation.face_count == 2
    assert observation.selected_face_index == 0
    assert len(observation.crop_recipe_ids) == 3
    assert {project.crop_recipes[recipe_id].kind for recipe_id in observation.crop_recipe_ids} == {
        CropKind.FACE,
        CropKind.UPPER_BODY,
        CropKind.FULL_BODY,
    }
    for recipe_id in observation.crop_recipe_ids:
        recipe = project.crop_recipes[recipe_id]
        expected_aspect = {
            CropKind.FACE: 1.0,
            CropKind.UPPER_BODY: 4 / 5,
            CropKind.FULL_BODY: 2 / 3,
        }[recipe.kind]
        pixel_aspect = (recipe.rect.width * 320) / (recipe.rect.height * 480)
        assert pixel_aspect == pytest.approx(expected_aspect)

    project = service.select_subject_face(project.id, source_item.id, 1)
    observation = project.observations[source_item.id]
    assert observation.selected_face_index == 1
    assert [face.index for face in observation.faces if face.selected] == [1]
    assert all(
        project.crop_recipes[recipe_id].face_index == 1
        for recipe_id in observation.crop_recipe_ids
    )

    face_recipe = next(
        project.crop_recipes[recipe_id]
        for recipe_id in observation.crop_recipe_ids
        if project.crop_recipes[recipe_id].kind == CropKind.FACE
    )
    crop_rect = NormalizedRect(x=0.25, y=1 / 3, width=0.5, height=1 / 3)
    project = service.update_crop_recipe(
        project.id,
        face_recipe.id,
        rect=crop_rect,
        status=CropRecipeStatus.APPROVED,
    )
    project, derivative = service.materialize_crop(project.id, face_recipe.id)

    materialized = project.crop_recipes[face_recipe.id]
    assert materialized.status == CropRecipeStatus.MATERIALIZED
    assert materialized.output_media_item_id == derivative.id
    assert derivative.raw_path.is_file()
    assert (derivative.width, derivative.height) == (160, 160)
    assert derivative.metadata_json["derivative_type"] == DerivativeType.FACE_CROP
    assert derivative.metadata_json["source_media_item_id"] == source_item.id
    assert derivative.metadata_json["character_project_id"] == project.id
    assert derivative.metadata_json["face_index"] == 1

    restored_project, restored_derivative = service.materialize_crop(
        project.id, face_recipe.id
    )
    assert restored_project.crop_recipes[face_recipe.id].output_media_item_id == derivative.id
    assert restored_derivative.id == derivative.id
