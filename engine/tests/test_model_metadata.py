from lorasuite_engine.model_metadata import (
    LoraModelCardOverrides,
    apply_model_card_overrides,
    build_snapshot_model_card,
    render_model_card_markdown,
    validate_model_card,
)
from lorasuite_engine.models import (
    DatasetBalance,
    DatasetSnapshot,
    DatasetSnapshotStatus,
)
from lorasuite_engine.training_targets import get_training_target_profile


def test_builds_readable_versioned_model_card_from_snapshot():
    target = get_training_target_profile("runcomfy_flux1_dev_character")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Mary Character",
        status=DatasetSnapshotStatus.FROZEN,
        training_target=target.spec(),
        balance=DatasetBalance(
            approved_count=32,
            source_count=3,
            cropped_count=8,
            average_quality=0.84,
            average_diversity=0.71,
            view_counts={"face": 10, "upper_body": 12, "full_body": 10},
        ),
        fingerprint="dataset-fingerprint",
    )
    snapshot.intent.subject_name = "Mary"
    snapshot.intent.trigger_token = "example_person"

    card = build_snapshot_model_card(snapshot)
    markdown = render_model_card_markdown(card)

    assert card.schema_version == "lorasuite.model-card.v1"
    assert card.name == "mary-flux1-character"
    assert card.recipe_id == "flux1_dev_character"
    assert card.recipe_version == 2
    assert card.dataset["approved_items"] == 32
    assert card.training["parameters"]["network_rank"] == 16
    assert card.usage["sample_prompts"][0].startswith("portrait photo of example_person")
    assert card.license == "unspecified"
    assert any("Output license is unspecified" in warning for warning in card.warnings)
    assert card.validation.status == "review"
    assert card.validation.warning_count == 2
    assert "# Mary - FLUX.1 Dev Character" in markdown
    assert "Dataset fingerprint: `dataset-fingerprint`" in markdown


def test_model_card_overrides_preserve_generated_facts_and_clear_release_checks():
    target = get_training_target_profile("runcomfy_flux1_dev_character")
    snapshot = DatasetSnapshot(
        project_id="project-1",
        project_name="Mary Character",
        training_target=target.spec(),
        balance=DatasetBalance(approved_count=35, source_count=3),
    )
    snapshot.intent.subject_name = "Mary"
    snapshot.intent.trigger_token = "example_person"
    card = build_snapshot_model_card(snapshot)

    updated = apply_model_card_overrides(
        card,
        LoraModelCardOverrides(
            name="Mary Portrait v1",
            display_name="Mary Portrait LoRA",
            description="A tested portrait identity LoRA.",
            license="CC-BY-4.0",
            tags=["Portrait", "portrait", "Mary"],
            sample_prompts=["portrait of example_person"],
            intended_use=["Portrait generation"],
            limitations=["Not evaluated for group scenes"],
            recommended_strength=0.85,
        ),
    )
    updated.validation = validate_model_card(updated)

    assert updated.name == "mary-portrait-v1"
    assert updated.base_model == card.base_model
    assert updated.recipe_id == card.recipe_id
    assert updated.dataset == card.dataset
    assert updated.tags == ["portrait", "mary"]
    assert updated.usage["recommended_strength"] == 0.85
    assert updated.validation.status == "ready"
