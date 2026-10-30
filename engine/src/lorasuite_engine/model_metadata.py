from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from lorasuite_engine.training_targets import (
    get_training_target_profile,
    recipe_for_training_target,
)


class ModelCardCheck(BaseModel):
    check_id: str
    label: str
    passed: bool
    severity: Literal["blocker", "warning"]
    message: str


class ModelCardValidation(BaseModel):
    status: Literal["ready", "review", "blocked"] = "review"
    blocker_count: int = 0
    warning_count: int = 0
    checks: list[ModelCardCheck] = Field(default_factory=list)


class LoraModelCardOverrides(BaseModel):
    name: str | None = None
    display_name: str | None = None
    description: str | None = None
    license: str | None = None
    tags: list[str] | None = None
    intended_use: list[str] | None = None
    limitations: list[str] | None = None
    sample_prompts: list[str] | None = None
    recommended_strength: float | None = Field(default=None, ge=0.0, le=2.0)

    @field_validator("name", "display_name", "description", "license")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("metadata text fields must not be empty")
        return cleaned

    @field_validator("tags", "intended_use", "limitations", "sample_prompts")
    @classmethod
    def clean_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = item.strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                cleaned.append(normalized)
                seen.add(key)
        return cleaned


class LoraModelCard(BaseModel):
    schema_version: str = "lorasuite.model-card.v1"
    name: str
    display_name: str
    description: str
    license: str = "unspecified"
    tags: list[str] = Field(default_factory=list)
    modality: Literal["image", "video", "voice", "audio_visual"] = "image"
    target_type: str
    subject_name: str = ""
    trigger_token: str = ""
    base_model: str
    model_family: str
    recipe_id: str | None = None
    recipe_version: int | None = None
    recipe_status: str | None = None
    training_target_profile_id: str
    dataset: dict[str, Any] = Field(default_factory=dict)
    captions: dict[str, Any] = Field(default_factory=dict)
    training: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    artifact: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    validation: ModelCardValidation = Field(default_factory=ModelCardValidation)


def build_snapshot_model_card(snapshot: Any) -> LoraModelCard:
    target = snapshot.training_target
    profile = get_training_target_profile(target.profile_id)
    recipe = recipe_for_training_target(target)
    intent = snapshot.intent
    subject = intent.subject_name.strip() or snapshot.project_name.strip() or "Subject"
    display_name = f"{subject} - {profile.label}"
    description = intent.description.strip() or (
        f"{intent.target_type.value.title()} LoRA for {subject}, prepared for "
        f"{profile.label} with LoraSuite."
    )
    balance = snapshot.balance
    compliance = balance.recipe_compliance
    warnings = list(dict.fromkeys([
        *balance.warnings,
        *profile.warnings,
    ]))
    captions = {
        "format": target.caption_format,
        "trigger_token_required": bool(recipe and recipe.captions.trigger_token_required),
        "required_evidence": recipe.captions.required_evidence if recipe else [],
        "controllable_attributes": intent.controllable_attributes,
        "learned_attributes": intent.learned_attributes,
        "excluded_attributes": intent.excluded_attributes,
        "policy_guidance": recipe.captions.guidance if recipe else [],
    }
    training = {
        "provider": target.provider,
        "trainer": target.trainer,
        "compiler_version": target.compiler_version,
        "output_format": target.output_format,
        "resolution_buckets": target.resolution_buckets,
        "parameters": (
            recipe.training.model_dump(mode="json")
            if recipe and recipe.training
            else {}
        ),
    }
    evaluation = {
        "status": "pending",
        "policy": recipe.evaluation.model_dump(mode="json") if recipe else {},
        "recipe_compliance": compliance.model_dump(mode="json") if compliance else None,
        "results": {},
    }
    trigger_token = intent.trigger_token.strip()
    usage = {
        "activation": trigger_token or None,
        "sample_prompts": _sample_prompts(trigger_token, intent.target_type.value),
        "recommended_strength": None,
        "intended_use": [
            f"Generate {intent.target_type.value} content using {profile.label}.",
            "Use the trigger token with explicit controllable attributes.",
        ],
        "limitations": [
            "Dataset coverage and evaluation results determine actual capability.",
            "Attributes omitted from captions may become entangled with the trigger token.",
        ],
    }
    card = LoraModelCard(
        name=_slug(f"{subject}-{profile.model_family}-{intent.target_type.value}"),
        display_name=display_name,
        description=description,
        tags=_clean_tags([
            "lorasuite",
            "lora",
            profile.model_family,
            intent.target_type.value,
            *intent.learned_attributes,
        ]),
        modality=target.modality,
        target_type=intent.target_type.value,
        subject_name=subject,
        trigger_token=trigger_token,
        base_model=target.base_model,
        model_family=target.model_family,
        recipe_id=target.recipe_id,
        recipe_version=target.recipe_version,
        recipe_status=recipe.status if recipe else None,
        training_target_profile_id=target.profile_id,
        dataset={
            "snapshot_id": snapshot.id,
            "project_id": snapshot.project_id,
            "version": snapshot.version,
            "status": snapshot.status.value,
            "fingerprint": snapshot.fingerprint,
            "approved_items": balance.approved_count,
            "excluded_items": balance.excluded_count,
            "source_count": balance.source_count,
            "cropped_items": balance.cropped_count,
            "average_quality": balance.average_quality,
            "average_diversity": balance.average_diversity,
            "view_counts": balance.view_counts,
            "crop_counts": balance.crop_counts,
        },
        captions=captions,
        training=training,
        evaluation=evaluation,
        usage=usage,
        provenance={
            "created_by": "LoraSuite",
            "project_id": snapshot.project_id,
            "dataset_snapshot_id": snapshot.id,
            "dataset_fingerprint": snapshot.fingerprint,
            "parent_dataset_snapshot_id": getattr(
                snapshot,
                "parent_snapshot_id",
                None,
            ),
            "parent_dataset_fingerprint": getattr(
                snapshot,
                "parent_fingerprint",
                None,
            ),
            "improvement_request_id": getattr(
                snapshot,
                "improvement_request_id",
                None,
            ),
            "source_artifact_id": getattr(
                snapshot,
                "source_artifact_id",
                None,
            ),
            "source_checkpoint_sha256": getattr(
                snapshot,
                "source_checkpoint_sha256",
                None,
            ),
            "generated_at": snapshot.updated_at,
        },
        warnings=warnings,
    )
    raw_overrides = getattr(snapshot, "model_card_overrides", None)
    if raw_overrides is not None:
        overrides = (
            raw_overrides
            if isinstance(raw_overrides, LoraModelCardOverrides)
            else LoraModelCardOverrides.model_validate(raw_overrides)
        )
        card = apply_model_card_overrides(card, overrides)
    card.validation = validate_model_card(card)
    card.warnings = list(dict.fromkeys([
        *card.warnings,
        *(
            check.message
            for check in card.validation.checks
            if not check.passed
        ),
    ]))
    return card


def apply_model_card_overrides(
    card: LoraModelCard,
    overrides: LoraModelCardOverrides,
) -> LoraModelCard:
    updated = card.model_copy(deep=True)
    if overrides.name is not None:
        normalized_name = _slug(overrides.name)
        if not normalized_name:
            raise ValueError("artifact name must contain at least one letter or number")
        updated.name = normalized_name
    if overrides.display_name is not None:
        updated.display_name = overrides.display_name
    if overrides.description is not None:
        updated.description = overrides.description
    if overrides.license is not None:
        updated.license = overrides.license
    if overrides.tags is not None:
        updated.tags = _clean_tags(overrides.tags)
    usage = dict(updated.usage)
    if overrides.intended_use is not None:
        usage["intended_use"] = overrides.intended_use
    if overrides.limitations is not None:
        usage["limitations"] = overrides.limitations
    if overrides.sample_prompts is not None:
        usage["sample_prompts"] = overrides.sample_prompts
    if "recommended_strength" in overrides.model_fields_set:
        usage["recommended_strength"] = overrides.recommended_strength
    updated.usage = usage
    return updated


def validate_model_card(card: LoraModelCard) -> ModelCardValidation:
    sample_prompts = card.usage.get("sample_prompts")
    intended_use = card.usage.get("intended_use")
    strength = card.usage.get("recommended_strength")
    checks = [
        ModelCardCheck(
            check_id="artifact_name",
            label="Artifact name",
            passed=bool(card.name.strip()),
            severity="blocker",
            message="Set a portable artifact name.",
        ),
        ModelCardCheck(
            check_id="description",
            label="Description",
            passed=bool(card.description.strip()),
            severity="blocker",
            message="Describe what the LoRA is intended to represent.",
        ),
        ModelCardCheck(
            check_id="base_model",
            label="Base model",
            passed=bool(card.base_model.strip()),
            severity="blocker",
            message="The exact base model is required.",
        ),
        ModelCardCheck(
            check_id="trigger_token",
            label="Trigger token",
            passed=card.target_type != "character" or bool(card.trigger_token.strip()),
            severity="blocker",
            message="Character LoRAs require a trigger token.",
        ),
        ModelCardCheck(
            check_id="license",
            label="License",
            passed=card.license.strip().casefold() not in {"", "unspecified", "unknown"},
            severity="warning",
            message="Output license is unspecified. Set an explicit license before publishing.",
        ),
        ModelCardCheck(
            check_id="sample_prompts",
            label="Sample prompts",
            passed=isinstance(sample_prompts, list) and bool(sample_prompts),
            severity="warning",
            message="Add at least one reproducible sample prompt.",
        ),
        ModelCardCheck(
            check_id="intended_use",
            label="Intended use",
            passed=isinstance(intended_use, list) and bool(intended_use),
            severity="warning",
            message="Document the intended use before release.",
        ),
        ModelCardCheck(
            check_id="recommended_strength",
            label="Recommended strength",
            passed=isinstance(strength, (int, float)),
            severity="warning",
            message="Recommended LoRA strength has not been verified.",
        ),
    ]
    blockers = [check for check in checks if not check.passed and check.severity == "blocker"]
    warnings = [check for check in checks if not check.passed and check.severity == "warning"]
    return ModelCardValidation(
        status="blocked" if blockers else "review" if warnings else "ready",
        blocker_count=len(blockers),
        warning_count=len(warnings),
        checks=checks,
    )


def enrich_artifact_model_card(
    card: LoraModelCard,
    *,
    artifact_id: str,
    training_run_id: str,
    checkpoint_name: str,
    checkpoint_sha256: str,
    checkpoint_size_bytes: int,
    evaluation: dict[str, Any],
    acceptance: dict[str, Any],
    source_checkpoint_sha256: str | None = None,
) -> LoraModelCard:
    enriched = card.model_copy(deep=True)
    enriched.artifact = {
        "artifact_id": artifact_id,
        "training_run_id": training_run_id,
        "checkpoint_name": checkpoint_name,
        "checkpoint_sha256": checkpoint_sha256,
        "source_checkpoint_sha256": (
            source_checkpoint_sha256 or checkpoint_sha256
        ),
        "checkpoint_size_bytes": checkpoint_size_bytes,
    }
    enriched.evaluation = {
        **enriched.evaluation,
        "status": acceptance.get("status") or evaluation.get("status") or "pending",
        "checkpoint_validation": evaluation,
        "results": acceptance,
    }
    enriched.provenance = {
        **enriched.provenance,
        "training_run_id": training_run_id,
        "artifact_id": artifact_id,
        "checkpoint_sha256": checkpoint_sha256,
        "source_checkpoint_sha256": (
            source_checkpoint_sha256 or checkpoint_sha256
        ),
    }
    return enriched


def render_model_card_markdown(card: LoraModelCard) -> str:
    trigger = f"`{card.trigger_token}`" if card.trigger_token else "Not defined"
    recipe = (
        f"`{card.recipe_id}` v{card.recipe_version}"
        if card.recipe_id and card.recipe_version is not None
        else "Custom target"
    )
    dataset = card.dataset
    training_parameters = card.training.get("parameters")
    parameter_lines = ""
    if isinstance(training_parameters, dict) and training_parameters:
        parameter_lines = "\n".join(
            f"- {key.replace('_', ' ').title()}: `{value}`"
            for key, value in training_parameters.items()
        )
    else:
        parameter_lines = "- Custom provider configuration"
    warnings = "\n".join(f"- {warning}" for warning in card.warnings) or "- None"
    prompts = card.usage.get("sample_prompts")
    prompt_lines = (
        "\n".join(f"- `{prompt}`" for prompt in prompts)
        if isinstance(prompts, list) and prompts
        else "- No sample prompts defined"
    )
    return (
        f"# {card.display_name}\n\n"
        f"{card.description}\n\n"
        "## Usage\n\n"
        f"- Trigger token: {trigger}\n"
        f"- Base model: `{card.base_model}`\n"
        f"- Model family: `{card.model_family}`\n"
        f"- LoRA type: `{card.target_type}`\n"
        f"- Recipe: {recipe}\n"
        f"- License: `{card.license}`\n\n"
        "### Sample prompts\n\n"
        f"{prompt_lines}\n\n"
        "## Dataset\n\n"
        f"- Snapshot: `{dataset.get('snapshot_id')}`\n"
        f"- Fingerprint: `{dataset.get('fingerprint') or 'not frozen'}`\n"
        f"- Approved items: {dataset.get('approved_items', 0)}\n"
        f"- Sources: {dataset.get('source_count', 0)}\n"
        f"- Cropped items: {dataset.get('cropped_items', 0)}\n"
        f"- Average quality: {_percent(dataset.get('average_quality'))}\n"
        f"- Average diversity: {_percent(dataset.get('average_diversity'))}\n\n"
        "## Training\n\n"
        f"- Provider: `{card.training.get('provider')}`\n"
        f"- Trainer: `{card.training.get('trainer')}`\n"
        f"- Output format: `{card.training.get('output_format')}`\n"
        f"{parameter_lines}\n\n"
        "## Evaluation\n\n"
        f"- Status: `{card.evaluation.get('status', 'pending')}`\n"
        f"- Required gates: {', '.join(card.evaluation.get('policy', {}).get('required_gates', [])) or 'Not defined'}\n\n"
        "## Provenance\n\n"
        f"- Created by: `{card.provenance.get('created_by', 'LoraSuite')}`\n"
        f"- Project: `{card.provenance.get('project_id')}`\n"
        f"- Dataset fingerprint: `{card.provenance.get('dataset_fingerprint') or 'not frozen'}`\n"
        f"- Artifact SHA-256: `{card.provenance.get('checkpoint_sha256') or 'not trained'}`\n\n"
        "## Warnings\n\n"
        f"{warnings}\n"
    )


def _sample_prompts(trigger_token: str, target_type: str) -> list[str]:
    subject = trigger_token or "subject"
    if target_type == "character":
        return [
            f"portrait photo of {subject}, natural light, neutral expression",
            f"full-body photo of {subject}, standing, simple background",
            f"{subject}, three-quarter view, different clothing, cinematic light",
        ]
    return [
        f"{subject}, high quality",
        f"{subject}, controlled lighting and composition",
    ]


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.casefold())).strip("-")


def _clean_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = _slug(value)
        if tag and tag not in seen:
            result.append(tag)
            seen.add(tag)
    return result


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "0%"
