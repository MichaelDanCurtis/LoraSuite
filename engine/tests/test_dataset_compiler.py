import json
from pathlib import Path

import pytest
from PIL import Image

from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.model_metadata import LoraModelCardOverrides
from lorasuite_engine.training_targets import get_training_target_profile
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.models import (
    CropKind,
    CropRecipe,
    CropRecipeStatus,
    DatasetCaptionRecord,
    DatasetItemStatus,
    DatasetReviewStatus,
    DatasetSnapshot,
    DatasetSnapshotStatus,
    DatasetView,
    DerivativeType,
    VisionCaptionEvidence,
)
from lorasuite_engine.vault import VaultService


def make_image(path: Path, color: tuple[int, int, int]) -> Path:
    Image.new("RGB", (320, 480), color=color).save(path)
    return path


def make_project_with_accepted_media(tmp_path):
    vault_root = tmp_path / "vault"
    vault = VaultService(vault_root)
    source_items = vault.import_local_paths(
        [
            make_image(tmp_path / "face.png", (100, 30, 40)),
            make_image(tmp_path / "body.png", (20, 80, 120)),
        ]
    ).media_items
    projects = CharacterProjectService(vault_root)
    project = projects.create_project(name="Mary Character")
    project.intent.subject_name = "Mary"
    project.intent.trigger_token = "example_person"
    project = projects.update_project(project.id, intent=project.intent)
    project = projects.add_candidates(project.id, [item.id for item in source_items])
    project = projects.update_observation(
        project.id,
        source_items[0].id,
        review_status=DatasetReviewStatus.ACCEPTED,
        view=DatasetView.FACE,
    )
    project = projects.update_observation(
        project.id,
        source_items[1].id,
        review_status=DatasetReviewStatus.ACCEPTED,
        view=DatasetView.FULL_BODY,
    )

    crop_path = tmp_path / "face-crop.png"
    Image.new("RGB", (256, 256), color=(110, 35, 45)).save(crop_path)
    derivative = vault.build_derivative_media_item(
        source_item=source_items[0],
        derivative_path=crop_path,
        media_type=source_items[0].media_type,
        derivative_type=DerivativeType.FACE_CROP,
    )
    vault.append_media_items([derivative])
    recipe = CropRecipe(
        media_item_id=source_items[0].id,
        kind=CropKind.FACE,
        rect={"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
        aspect_ratio="1:1",
        status=CropRecipeStatus.MATERIALIZED,
        output_media_item_id=derivative.id,
    )
    project.crop_recipes[recipe.id] = recipe
    project.observations[source_items[0].id].crop_recipe_ids = [recipe.id]
    projects._save_project(project, {project.id: project})
    return vault_root, project, source_items, derivative, recipe


def test_dataset_compiler_persists_captions_prefers_crops_and_freezes(tmp_path):
    vault_root, project, source_items, derivative, recipe = make_project_with_accepted_media(
        tmp_path
    )
    service = DatasetCompilerService(vault_root)

    snapshot = service.compile_project(project.id)

    assert snapshot.status == DatasetSnapshotStatus.DRAFT
    assert snapshot.version == 1
    assert snapshot.balance.total_count == 2
    assert snapshot.balance.review_count == 2
    assert snapshot.balance.cropped_count == 1
    assert snapshot.training_target.recipe_id == "flux1_dev_character"
    assert snapshot.model_card is not None
    assert snapshot.model_card.recipe_id == "flux1_dev_character"
    assert snapshot.model_card.trigger_token == "example_person"
    assert snapshot.balance.recipe_compliance is not None
    assert snapshot.balance.recipe_compliance.recipe_version == 2
    assert snapshot.balance.recipe_compliance.status == "blocked"
    assert snapshot.balance.recipe_compliance.blocker_count == 1
    face_record = next(
        item
        for item in snapshot.items.values()
        if item.source_media_item_id == source_items[0].id
    )
    body_record = next(
        item
        for item in snapshot.items.values()
        if item.source_media_item_id == source_items[1].id
    )
    assert face_record.training_media_item_id == derivative.id
    assert face_record.crop_recipe_id == recipe.id
    assert face_record.caption == "example_person, person, close-up portrait"
    assert "clothing" in face_record.unresolved_attributes
    assert body_record.training_media_item_id == source_items[1].id
    assert body_record.caption == "example_person, person, full-body photo"

    snapshot = service.update_item(
        snapshot.id,
        face_record.id,
        caption="example_person, smiling person, close-up portrait",
        status=DatasetItemStatus.APPROVED,
    )
    assert snapshot.items[face_record.id].caption_source.value == "user"
    with pytest.raises(ValueError, match="resolve or exclude"):
        service.freeze_snapshot(snapshot.id)

    snapshot = service.bulk_update_status(
        snapshot.id,
        status=DatasetItemStatus.APPROVED,
        item_ids=[body_record.id],
    )
    frozen = service.freeze_snapshot(snapshot.id)

    assert frozen.status == DatasetSnapshotStatus.FROZEN
    assert frozen.fingerprint is not None and len(frozen.fingerprint) == 64
    assert frozen.balance.approved_count == 2
    assert frozen.balance.recipe_compliance is not None
    assert frozen.balance.recipe_compliance.status == "review"
    assert frozen.balance.recipe_compliance.blocker_count == 0
    with pytest.raises(ValueError, match="immutable"):
        service.update_item(frozen.id, face_record.id, caption="changed")
    restored = DatasetCompilerService(vault_root).get_snapshot(frozen.id)
    assert restored is not None
    assert restored.items[face_record.id].caption.startswith("example_person, smiling")


def test_frozen_dataset_exports_individual_captions_and_provenance(tmp_path):
    vault_root, project, source_items, _derivative, _recipe = make_project_with_accepted_media(
        tmp_path
    )
    service = DatasetCompilerService(vault_root)
    snapshot = service.compile_project(project.id)
    records = list(snapshot.items.values())
    snapshot = service.update_item(
        snapshot.id,
        records[0].id,
        caption="example_person, smiling, close-up portrait",
        status=DatasetItemStatus.APPROVED,
    )
    snapshot = service.update_item(
        snapshot.id,
        records[1].id,
        caption="example_person, standing, full-body photo",
        status=DatasetItemStatus.APPROVED,
    )
    frozen = service.freeze_snapshot(snapshot.id)

    exported, package = service.export_runcomfy(frozen.id, tmp_path / "runcomfy")

    assert exported.status == DatasetSnapshotStatus.EXPORTED
    assert package.status == "complete"
    captions = sorted(
        path.read_text(encoding="utf-8").strip()
        for path in (tmp_path / "runcomfy" / "images").glob("*.txt")
    )
    assert captions == sorted(
        [
            "example_person, smiling, close-up portrait",
            "example_person, standing, full-body photo",
        ]
    )
    manifest = json.loads(
        (tmp_path / "runcomfy" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["dataset_snapshot_id"] == frozen.id
    assert manifest["dataset_fingerprint"] == frozen.fingerprint
    assert manifest["character_project_id"] == project.id
    assert manifest["training_target"]["profile_id"] == "runcomfy_flux1_dev_character"
    assert manifest["training_target"]["recipe_id"] == "flux1_dev_character"
    assert manifest["training_target"]["recipe_version"] == 2
    assert manifest["revision_lineage"] == {}
    assert manifest["model_card"]["dataset"]["fingerprint"] == frozen.fingerprint
    assert manifest["model_card"]["trigger_token"] == "example_person"
    assert (tmp_path / "runcomfy" / "model_card.json").is_file()
    assert "FLUX.1 Dev Character" in (
        tmp_path / "runcomfy" / "README.md"
    ).read_text(encoding="utf-8")
    assert {item["source_media_item_id"] for item in manifest["files"]} == {
        item.id for item in source_items
    }

    updated = service.update_model_card(
        exported.id,
        LoraModelCardOverrides(
            display_name="Mary Character Release",
            license="CC-BY-4.0",
            recommended_strength=0.8,
        ),
    )
    refreshed_manifest = json.loads(
        (tmp_path / "runcomfy" / "manifest.json").read_text(encoding="utf-8")
    )
    assert updated.model_card is not None
    assert updated.model_card.display_name == "Mary Character Release"
    assert updated.model_card.license == "CC-BY-4.0"
    assert updated.model_card.usage["recommended_strength"] == 0.8
    assert refreshed_manifest["model_card"]["display_name"] == "Mary Character Release"
    assert "Mary Character Release" in (
        tmp_path / "runcomfy" / "README.md"
    ).read_text(encoding="utf-8")


def test_dataset_compiler_creates_model_specific_snapshots(tmp_path):
    vault_root, project, _source_items, _derivative, _recipe = make_project_with_accepted_media(
        tmp_path
    )
    service = DatasetCompilerService(vault_root)
    flux = get_training_target_profile("runcomfy_flux1_dev_character")
    qwen = get_training_target_profile("runcomfy_qwen_image_character")

    flux_snapshot = service.compile_project(project.id, flux.spec())
    qwen_snapshot = service.compile_project(project.id, qwen.spec())

    assert flux_snapshot.id != qwen_snapshot.id
    assert flux_snapshot.training_target.base_model == "black-forest-labs/FLUX.1-dev"
    assert qwen_snapshot.training_target.base_model == "Qwen/Qwen-Image"
    assert {snapshot.training_target.profile_id for snapshot in service.list_snapshots()} >= {
        "runcomfy_flux1_dev_character",
        "runcomfy_qwen_image_character",
    }


def test_model_specific_captions_reuse_canonical_vision_evidence(tmp_path):
    vault_root, project, source_items, _derivative, _recipe = make_project_with_accepted_media(
        tmp_path
    )
    service = DatasetCompilerService(vault_root)
    flux = get_training_target_profile("runcomfy_flux1_dev_character")
    krea = get_training_target_profile("runcomfy_krea2_raw_character")
    flux_snapshot = service.compile_project(project.id, flux.spec())
    flux_record = next(
        item
        for item in flux_snapshot.items.values()
        if item.source_media_item_id == source_items[1].id
    )
    evidence = VisionCaptionEvidence(
        expression="smiling",
        pose="standing with one hand raised",
        clothing="red sleeveless dress",
        environment="indoors beside large windows",
        camera="eye-level full-body view",
        lighting="soft natural daylight",
        visual_style="candid photograph",
        other_people="none",
        watermark="none",
        content="general",
        confidence=0.91,
    )

    flux_snapshot = service.apply_vision_evidence(
        flux_snapshot.id,
        flux_record.id,
        evidence=evidence,
        provider_label="Apple Local",
        model="system",
    )
    flux_record = flux_snapshot.items[flux_record.id]

    assert flux_record.caption == (
        "example_person, person, full-body photo, smiling, "
        "standing with one hand raised, red sleeveless dress, "
        "indoors beside large windows, eye-level full-body view, "
        "soft natural daylight, candid photograph"
    )
    assert flux_record.vision_evidence == evidence

    legacy_krea_target = krea.spec()
    legacy_krea_target.recipe_version = 1
    krea_snapshot = service.compile_project(project.id, legacy_krea_target)
    krea_record = next(
        item
        for item in krea_snapshot.items.values()
        if item.source_media_item_id == source_items[1].id
    )

    assert krea_record.caption == (
        "A full-body photo of example_person, a person, standing with one hand raised, "
        "wearing red sleeveless dress, with a smiling expression. "
        "The setting is indoors beside large windows, and the composition is "
        "eye-level full-body view, and the lighting is soft natural daylight, "
        "and the visual treatment is candid photograph."
    )
    assert krea_record.caption_source.value == "vision"
    assert krea_record.caption_provider == "Apple Local"
    assert krea_record.caption_model == "system"
    assert krea_record.caption_confidence == 0.91
    assert krea_record.vision_evidence == evidence
    assert krea_record.status == DatasetItemStatus.NEEDS_REVIEW
    assert krea_snapshot.balance.recipe_compliance is not None
    assert krea_snapshot.balance.recipe_compliance.recipe_version == 2


def test_krea_and_qwen_recipes_declare_narrative_caption_rendering():
    krea = get_training_target_profile("runcomfy_krea2_raw_character")
    qwen = get_training_target_profile("runcomfy_qwen_image_character")
    flux = get_training_target_profile("runcomfy_flux1_dev_character")

    assert krea.recipe is not None
    assert qwen.recipe is not None
    assert flux.recipe is not None
    assert krea.recipe.captions.render_style == "narrative"
    assert qwen.recipe.captions.render_style == "narrative"
    assert flux.recipe.captions.render_style == "concise"


def test_strongest_set_balances_views_sources_and_restores_only_its_exclusions(
    tmp_path,
):
    service = DatasetCompilerService(tmp_path / "vault")
    target = get_training_target_profile("runcomfy_krea2_raw_character").spec()
    snapshot = DatasetSnapshot(
        project_id="character_project_selection",
        project_name="Selection Character",
        training_target=target,
    )
    views = [DatasetView.FACE, DatasetView.UPPER_BODY, DatasetView.FULL_BODY]
    for index in range(30):
        view = views[index // 10]
        item = DatasetCaptionRecord(
            id=f"dataset_item_{index:02d}",
            source_media_item_id=f"media_{index:02d}",
            training_media_item_id=f"media_{index:02d}",
            caption=f"person_token, {view.value}, look {index % 4}",
            attributes={
                "framing": view.value,
                "clothing": f"outfit {index % 5}",
                "environment": f"setting {index % 4}",
                "expression": f"expression {index % 3}",
            },
            view=view,
            quality_score=0.55 + index * 0.02,
            diversity_score=0.20 + (index % 5) * 0.1,
            identity_score=0.40 + (index % 6) * 0.05,
            is_anchor=index == 0,
            source_id=f"source_{index % 2}",
        )
        snapshot.items[item.id] = item
    snapshot.items["dataset_item_29"].status = DatasetItemStatus.EXCLUDED
    service._write_snapshots({snapshot.id: snapshot})

    proposal = service.propose_strongest_set(snapshot.id, target_count=20)

    assert proposal.selected_count == 20
    assert proposal.excluded_count == 9
    assert proposal.already_excluded_count == 1
    assert "dataset_item_00" in {candidate.item_id for candidate in proposal.selected}
    assert proposal.view_counts[DatasetView.FACE.value] >= 4
    assert proposal.view_counts[DatasetView.FULL_BODY.value] >= 4
    assert proposal.view_counts[DatasetView.UPPER_BODY.value] >= 4
    assert all(candidate.group != DatasetView.UNKNOWN for candidate in proposal.selected)
    assert {
        group: sum(candidate.group.value == group for candidate in proposal.selected)
        for group in proposal.view_counts
    } == proposal.view_counts
    assert max(proposal.source_counts.values()) / proposal.selected_count <= 0.65
    assert all(
        item.status != DatasetItemStatus.EXCLUDED
        for item in service.get_snapshot(snapshot.id).items.values()
        if item.id != "dataset_item_29"
    )

    disqualified_id = next(
        candidate.item_id
        for candidate in proposal.selected
        if candidate.item_id != "dataset_item_00"
    )
    replacement_proposal = service.propose_strongest_set(
        snapshot.id,
        target_count=20,
        disqualified_item_ids=[disqualified_id],
    )
    assert replacement_proposal.selected_count == 20
    assert disqualified_id not in {
        candidate.item_id for candidate in replacement_proposal.selected
    }
    assert disqualified_id in replacement_proposal.excluded_item_ids

    included_id = proposal.excluded_item_ids[0]
    exchange_proposal = service.propose_strongest_set(
        snapshot.id,
        target_count=20,
        disqualified_item_ids=[disqualified_id],
        included_item_ids=[included_id],
    )
    assert exchange_proposal.selected_count == 20
    assert included_id in {
        candidate.item_id for candidate in exchange_proposal.selected
    }
    assert disqualified_id not in {
        candidate.item_id for candidate in exchange_proposal.selected
    }

    applied, applied_proposal = service.apply_strongest_set(
        snapshot.id,
        target_count=20,
        disqualified_item_ids=[disqualified_id],
        included_item_ids=[included_id],
    )

    assert applied_proposal.selected_count == 20
    assert applied.balance.excluded_count == 10
    assert sum(item.strongest_set_excluded for item in applied.items.values()) == 9
    assert sum(item.strongest_set_rank is not None for item in applied.items.values()) == 20
    assert applied.items[disqualified_id].status == DatasetItemStatus.EXCLUDED
    assert applied.items[disqualified_id].strongest_set_excluded is True
    assert applied.items[included_id].status == DatasetItemStatus.NEEDS_REVIEW
    assert applied.items[included_id].strongest_set_rank is not None

    restored = service.restore_strongest_set(snapshot.id)

    assert restored.items["dataset_item_29"].status == DatasetItemStatus.EXCLUDED
    assert restored.items["dataset_item_29"].strongest_set_excluded is False
    assert sum(item.status == DatasetItemStatus.NEEDS_REVIEW for item in restored.items.values()) == 29
    assert not any(item.strongest_set_excluded for item in restored.items.values())


def test_duplicate_proposal_keeps_the_strongest_copy_without_mutating_dataset(
    tmp_path,
):
    vault_root = tmp_path / "vault"
    vault = VaultService(vault_root)
    repeated_path = tmp_path / "repeated.png"
    unique_path = tmp_path / "unique.png"
    repeated = Image.new("RGB", (96, 96), color=(0, 0, 0))
    for x in range(0, 96, 16):
        for y in range(96):
            if (x // 16) % 2:
                repeated.putpixel((x, y), (255, 255, 255))
    repeated.save(repeated_path)
    unique = Image.new("RGB", (96, 96), color=(0, 0, 0))
    for y in range(0, 96, 12):
        for x in range(96):
            if (y // 12) % 2:
                unique.putpixel((x, y), (255, 255, 255))
    unique.save(unique_path)
    media = vault.import_local_paths([repeated_path, unique_path]).media_items
    snapshot = DatasetSnapshot(
        project_id="character_project_duplicates",
        project_name="Duplicate Character",
        training_target=get_training_target_profile(
            "runcomfy_flux1_dev_character"
        ).spec(),
    )
    snapshot.items = {
        "dataset_item_weaker": DatasetCaptionRecord(
            id="dataset_item_weaker",
            source_media_item_id=media[0].id,
            training_media_item_id=media[0].id,
            caption="person_token, repeated",
            quality_score=0.45,
        ),
        "dataset_item_keeper": DatasetCaptionRecord(
            id="dataset_item_keeper",
            source_media_item_id=media[0].id,
            training_media_item_id=media[0].id,
            caption="person_token, repeated anchor",
            quality_score=0.85,
            is_anchor=True,
        ),
        "dataset_item_unique": DatasetCaptionRecord(
            id="dataset_item_unique",
            source_media_item_id=media[1].id,
            training_media_item_id=media[1].id,
            caption="person_token, unique",
            quality_score=0.75,
        ),
    }
    service = DatasetCompilerService(vault_root)
    service._write_snapshots({snapshot.id: snapshot})

    proposal = service.propose_duplicate_groups(snapshot.id)

    assert proposal.scanned_count == 3
    assert proposal.duplicate_count == 1
    assert len(proposal.clusters) == 1
    assert proposal.clusters[0].recommended_keep_item_id == "dataset_item_keeper"
    assert {
        candidate.item_id for candidate in proposal.clusters[0].candidates
    } == {"dataset_item_keeper", "dataset_item_weaker"}
    assert all(
        item.status == DatasetItemStatus.NEEDS_REVIEW
        for item in service.get_snapshot(snapshot.id).items.values()
    )
