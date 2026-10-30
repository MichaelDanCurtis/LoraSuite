from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DatasetRecipePolicy(BaseModel):
    minimum_approved_items: int = 20
    recommended_approved_items: int = 35
    maximum_approved_items: int = 80
    minimum_sources: int = 2
    maximum_source_share: float = 0.65
    minimum_face_views: int = 4
    minimum_upper_body_views: int = 4
    minimum_full_body_views: int = 4
    minimum_materialized_crops: int = 3
    minimum_average_quality: float = 0.60
    minimum_average_diversity: float = 0.35
    allowed_image_extensions: list[str] = Field(
        default_factory=lambda: [".jpg", ".jpeg", ".png"]
    )
    allowed_video_extensions: list[str] = Field(default_factory=list)
    allowed_audio_extensions: list[str] = Field(default_factory=list)
    minimum_total_duration_seconds: float | None = None
    recommended_total_duration_seconds: float | None = None
    maximum_total_duration_seconds: float | None = None
    minimum_clip_duration_seconds: float | None = None
    maximum_clip_duration_seconds: float | None = None
    target_fps: int | None = None
    target_num_frames: int | None = None
    maximum_normalized_dimension: int | None = None
    minimum_average_identity: float | None = None
    minimum_average_stability: float | None = None
    minimum_average_motion: float | None = None
    maximum_average_motion: float | None = None
    minimum_average_speaker_similarity: float | None = None
    minimum_average_transcript_confidence: float | None = None
    minimum_average_active_audio_ratio: float | None = None
    maximum_average_silence_ratio: float | None = None
    maximum_average_clipping_ratio: float | None = None
    maximum_average_background_music_risk: float | None = None
    maximum_multi_speaker_segments: int | None = None
    minimum_visual_examples: int | None = None
    minimum_synchronized_pairs: int | None = None
    minimum_voice_references: int | None = None
    minimum_validation_examples: int | None = None
    guidance: list[str] = Field(default_factory=list)


class CaptionRecipePolicy(BaseModel):
    trigger_token_required: bool = True
    caption_format: str = "paired_txt"
    render_style: Literal["concise", "narrative", "tags"] = "concise"
    required_evidence: list[str] = Field(default_factory=lambda: ["framing"])
    controllable_attributes: list[str] = Field(
        default_factory=lambda: [
            "expression",
            "pose",
            "clothing",
            "environment",
            "camera",
        ]
    )
    excluded_identity_attributes: list[str] = Field(
        default_factory=lambda: ["background", "other people", "watermark"]
    )
    guidance: list[str] = Field(default_factory=list)


class TrainingRecipeDefaults(BaseModel):
    network_rank: int = 16
    network_alpha: int = 16
    steps: int = 2000
    minimum_steps: int = 500
    maximum_steps: int = 4000
    learning_rate: float = 1e-4
    optimizer: str = "adamw8bit"
    precision: str = "bf16"
    batch_size: int = 1
    save_every: int = 250
    sample_every: int = 250
    caption_dropout_rate: float = 0.05
    train_text_encoder: bool = False
    gradient_checkpointing: bool = True
    cache_text_embeddings: bool = False
    sample_steps: int = 20
    sample_guidance_scale: float = 4.0


class InferenceRecipeDefaults(BaseModel):
    pipeline: str
    reference_audio_seconds: float | None = None
    inference_steps: int = 30
    guidance_scale: float = 4.0
    output_width: int | None = None
    output_height: int | None = None
    output_frames: int | None = None


class TrainingDurationBaseline(BaseModel):
    gpu_family: Literal["h100", "h200"]
    baseline_steps: int = Field(default=2000, ge=1)
    low_hours: float = Field(gt=0)
    expected_hours: float = Field(gt=0)
    high_hours: float = Field(gt=0)
    confidence: Literal["low", "medium", "high"] = "low"
    basis: str
    assumptions: list[str] = Field(default_factory=list)


class EvaluationRecipePolicy(BaseModel):
    required_gates: list[str] = Field(
        default_factory=lambda: [
            "identity_similarity",
            "prompt_adherence",
            "attribute_control",
            "artifact_rate",
        ]
    )
    minimum_identity_score: float = 0.72
    minimum_prompt_adherence: float = 0.65
    minimum_temporal_stability: float | None = None
    minimum_motion_quality: float | None = None
    minimum_speaker_similarity: float | None = None
    minimum_transcript_similarity: float | None = None
    minimum_audio_quality: float | None = None
    maximum_artifact_rate: float = 0.15
    benchmark_prompt_count: int = 12
    guidance: list[str] = Field(default_factory=list)


class MetadataRecipePolicy(BaseModel):
    schema_version: str = "lorasuite.model-card.v1"
    required_fields: list[str] = Field(
        default_factory=lambda: [
            "name",
            "description",
            "trigger_token",
            "base_model",
            "target_type",
            "recipe_id",
            "recipe_version",
            "dataset_fingerprint",
            "training_parameters",
            "license",
        ]
    )


class ModelIntentRecipe(BaseModel):
    recipe_id: str
    version: int = Field(default=1, ge=1)
    label: str
    status: Literal["baseline", "validated", "experimental"] = "baseline"
    workflow_kind: Literal["training", "inference"] = "training"
    modality: Literal["image", "video", "voice", "audio_visual"] = "image"
    model_family: str
    base_model: str
    intent: Literal[
        "character",
        "style",
        "concept",
        "pose",
        "clothing",
        "object",
    ]
    dataset: DatasetRecipePolicy = Field(default_factory=DatasetRecipePolicy)
    captions: CaptionRecipePolicy = Field(default_factory=CaptionRecipePolicy)
    training: TrainingRecipeDefaults | None = Field(default_factory=TrainingRecipeDefaults)
    inference: InferenceRecipeDefaults | None = None
    evaluation: EvaluationRecipePolicy = Field(default_factory=EvaluationRecipePolicy)
    metadata: MetadataRecipePolicy = Field(default_factory=MetadataRecipePolicy)
    rationale: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)


class RecipeCheck(BaseModel):
    check_id: str
    label: str
    passed: bool
    severity: Literal["blocker", "warning"] = "warning"
    detail: str
    current: float | int | str | None = None
    target: float | int | str | None = None


class RecipeCompliance(BaseModel):
    recipe_id: str
    recipe_version: int
    recipe_label: str
    status: Literal["ready", "review", "blocked"] = "review"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    blocker_count: int = 0
    warning_count: int = 0
    checks: list[RecipeCheck] = Field(default_factory=list)


class TrainingTargetSpec(BaseModel):
    profile_id: str = "runcomfy_flux1_dev_character"
    label: str = "FLUX.1 Dev Character"
    provider: str = "runcomfy"
    trainer: str = "ai_toolkit"
    modality: Literal["image", "video", "voice", "audio_visual"] = "image"
    model_family: str = "flux1"
    base_model: str = "black-forest-labs/FLUX.1-dev"
    compiler_version: str = "image-pairs-v1"
    resolution_buckets: list[int] = Field(default_factory=lambda: [512, 768, 1024])
    caption_format: str = "paired_txt"
    output_format: str = "safetensors_lora"
    recipe_id: str | None = None
    recipe_version: int | None = None


AI_TOOLKIT_TRAINER_REVISION = "64663c8575b7a9ac3b946611724f76d015c941bc"
KREA2_AI_TOOLKIT_REVISION = "c2864bba48a6f94ab1171d9df47b1335f8306355"


class TrainingTargetProfile(TrainingTargetSpec):
    description: str
    ready: bool = True
    config_template: str = ""
    trainer_repository: str = "https://github.com/ostris/ai-toolkit.git"
    trainer_revision: str = AI_TOOLKIT_TRAINER_REVISION
    launcher_kind: Literal[
        "ai_toolkit",
        "id_lora_ltx23",
        "id_lora_ltx23_inference",
        "fish_speech_s2",
        "minimax_h3_reference",
    ] = "ai_toolkit"
    required_commands: list[str] = Field(default_factory=lambda: ["bash", "git", "python"])
    required_environment: list[str] = Field(default_factory=list)
    required_model_paths: list[str] = Field(default_factory=list)
    minimum_gpu_memory_gb: int = 24
    warnings: list[str] = Field(default_factory=list)
    recipe: ModelIntentRecipe | None = None
    duration_baselines: list[TrainingDurationBaseline] = Field(default_factory=list)

    def spec(self) -> TrainingTargetSpec:
        return TrainingTargetSpec.model_validate(
            self.model_dump(exclude={
                "description",
                "ready",
                "config_template",
                "trainer_repository",
                "trainer_revision",
                "launcher_kind",
                "required_commands",
                "required_environment",
                "required_model_paths",
                "minimum_gpu_memory_gb",
                "warnings",
                "recipe",
                "duration_baselines",
            })
        )


FLUX1_DEV_CHARACTER_RECIPE = ModelIntentRecipe(
    recipe_id="flux1_dev_character",
    version=2,
    label="FLUX.1 Dev Character",
    model_family="flux1",
    base_model="black-forest-labs/FLUX.1-dev",
    intent="character",
    dataset=DatasetRecipePolicy(
        minimum_approved_items=20,
        recommended_approved_items=35,
        maximum_approved_items=80,
        minimum_sources=2,
        maximum_source_share=0.65,
        minimum_face_views=4,
        minimum_upper_body_views=4,
        minimum_full_body_views=4,
        minimum_materialized_crops=3,
        minimum_average_quality=0.60,
        minimum_average_diversity=0.35,
        guidance=[
            "Prefer identity-consistent images over raw volume.",
            "Represent close face, upper-body, and full-body views.",
            "Keep controllable attributes in captions instead of binding them to the trigger token.",
            "Use multiple independent sources and remove hard or near duplicates.",
        ],
    ),
    captions=CaptionRecipePolicy(
        guidance=[
            "Start each caption with the project trigger token.",
            "Describe visible framing, expression, pose, clothing, environment, and camera attributes when known.",
            "Do not omit recurring attributes that should remain prompt-controllable.",
        ],
    ),
    training=TrainingRecipeDefaults(),
    evaluation=EvaluationRecipePolicy(
        guidance=[
            "Evaluate identity across close, medium, and full-body prompts.",
            "Test both seen and unseen clothing, expressions, poses, and environments.",
            "Reject checkpoints that memorize backgrounds or leak recurring source artifacts.",
        ],
    ),
    rationale=[
        "The dataset thresholds are a LoraSuite baseline and remain versioned so benchmark evidence can change them without rewriting history.",
        "The training defaults follow the official AI Toolkit FLUX LoRA example and are emitted as editable provider configuration.",
        "Evaluation gates separate identity fidelity from prompt control and visual artifact rate.",
    ],
    evidence_urls=[
        "https://github.com/ostris/ai-toolkit",
        "https://raw.githubusercontent.com/ostris/ai-toolkit/main/config/examples/train_lora_flux_24gb.yaml",
    ],
)


QWEN_IMAGE_CHARACTER_RECIPE = ModelIntentRecipe(
    recipe_id="qwen_image_character",
    version=2,
    label="Qwen Image Character",
    status="experimental",
    model_family="qwen_image",
    base_model="Qwen/Qwen-Image",
    intent="character",
    dataset=DatasetRecipePolicy(
        minimum_approved_items=20,
        recommended_approved_items=35,
        maximum_approved_items=80,
        minimum_sources=2,
        maximum_source_share=0.65,
        minimum_face_views=4,
        minimum_upper_body_views=4,
        minimum_full_body_views=4,
        minimum_materialized_crops=3,
        minimum_average_quality=0.60,
        minimum_average_diversity=0.35,
        guidance=[
            "Use multiple aspect ratios; AI Toolkit buckets Qwen images at 512, 768, and 1024.",
            "Preserve close face, upper-body, and full-body identity evidence.",
            "Keep captions concrete and visually grounded because text embeddings are cached before training.",
            "Remove hard and near duplicates before the text-embedding cache is built.",
        ],
    ),
    captions=CaptionRecipePolicy(
        render_style="narrative",
        required_evidence=[
            "framing",
            "expression",
            "pose",
            "clothing",
            "environment",
            "camera",
        ],
        guidance=[
            "Write the literal project trigger token into every approved caption.",
            "Do not rely on AI Toolkit trigger-word insertion when text embeddings are cached.",
            "Describe visible controllable attributes explicitly and keep identity-only wording stable.",
        ],
    ),
    training=TrainingRecipeDefaults(
        cache_text_embeddings=True,
        sample_steps=25,
        sample_guidance_scale=3.0,
    ),
    evaluation=EvaluationRecipePolicy(
        guidance=[
            "Test identity with simple portraits before complex compositions.",
            "Measure prompt control across clothing, pose, environment, camera, and text-heavy scenes.",
            "Compare multiple checkpoints because cached captions make caption quality failures persistent for a run.",
        ],
    ),
    rationale=[
        "Training defaults follow the official AI Toolkit Qwen Image 24 GB example.",
        "Qwen uses cached text embeddings in the supported configuration, so LoraSuite requires literal trigger tokens in the caption files.",
        "Dataset thresholds intentionally match the initial FLUX character baseline until comparative LoraSuite evaluations justify model-specific counts.",
        "This recipe remains experimental until a real Qwen training run passes the recorded evaluation gates.",
    ],
    evidence_urls=[
        "https://github.com/ostris/ai-toolkit",
        "https://raw.githubusercontent.com/ostris/ai-toolkit/main/config/examples/train_lora_qwen_image_24gb.yaml",
    ],
)


WAN22_T2V_CHARACTER_RECIPE = ModelIntentRecipe(
    recipe_id="wan22_14b_t2v_character",
    version=1,
    label="WAN 2.2 14B T2V Character Video",
    status="experimental",
    modality="video",
    model_family="wan22_14b_t2v",
    base_model="ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16",
    intent="character",
    dataset=DatasetRecipePolicy(
        minimum_approved_items=8,
        recommended_approved_items=16,
        maximum_approved_items=48,
        minimum_sources=3,
        maximum_source_share=0.50,
        minimum_face_views=0,
        minimum_upper_body_views=0,
        minimum_full_body_views=0,
        minimum_materialized_crops=0,
        minimum_average_quality=0.60,
        minimum_average_diversity=0.0,
        allowed_image_extensions=[],
        allowed_video_extensions=[".mp4", ".mov", ".m4v", ".webm"],
        minimum_total_duration_seconds=20.0,
        recommended_total_duration_seconds=60.0,
        maximum_total_duration_seconds=240.0,
        minimum_clip_duration_seconds=2.5625,
        maximum_clip_duration_seconds=12.0,
        target_fps=16,
        target_num_frames=41,
        maximum_normalized_dimension=1024,
        minimum_average_identity=0.65,
        minimum_average_stability=0.60,
        minimum_average_motion=0.20,
        maximum_average_motion=0.85,
        guidance=[
            "Use stable, identity-visible motion ranges instead of entire source videos.",
            "Represent multiple independent source videos, camera distances, actions, and environments.",
            "Keep every approved range long enough to provide 41 frames at 16 FPS.",
            "Reject hard duplicates, severe cuts, face occlusion, heavy motion blur, and clips dominated by other people.",
        ],
    ),
    captions=CaptionRecipePolicy(
        required_evidence=[
            "framing",
            "expression",
            "pose",
            "action",
            "camera",
            "environment",
        ],
        controllable_attributes=[
            "expression",
            "pose",
            "action",
            "motion",
            "clothing",
            "environment",
            "camera",
        ],
        guidance=[
            "Start every approved clip caption with the literal project trigger token.",
            "Describe visible action, body motion, camera motion, framing, clothing, and environment.",
            "Do not bind recurring source backgrounds, other people, overlays, or watermarks to the identity token.",
        ],
    ),
    training=TrainingRecipeDefaults(
        network_rank=32,
        network_alpha=32,
        cache_text_embeddings=True,
        sample_steps=25,
        sample_guidance_scale=3.5,
    ),
    evaluation=EvaluationRecipePolicy(
        required_gates=[
            "identity_similarity",
            "temporal_stability",
            "motion_quality",
            "prompt_adherence",
            "artifact_rate",
        ],
        minimum_identity_score=0.70,
        minimum_prompt_adherence=0.65,
        minimum_temporal_stability=0.65,
        minimum_motion_quality=0.60,
        maximum_artifact_rate=0.15,
        benchmark_prompt_count=8,
        guidance=[
            "Evaluate close, medium, and full-body motion with fixed seeds.",
            "Test both low-motion identity retention and deliberate body or camera motion.",
            "Reject checkpoints with temporal face drift, frozen motion, duplicated limbs, or source-background memorization.",
        ],
    ),
    rationale=[
        "The target uses the same 41-frame, 16 FPS contract as the pinned AI Toolkit WAN configuration.",
        "Clip and source thresholds are versioned LoraSuite baselines and remain experimental until real cloud runs pass the evaluation harness.",
        "Readiness separates blocking format failures from quality and coverage warnings so experts can deliberately override conservative baselines.",
    ],
    evidence_urls=[
        "https://github.com/ostris/ai-toolkit",
        "https://huggingface.co/ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16",
    ],
)


MINIMAX_H3_REFERENCE_RECIPE = ModelIntentRecipe(
    recipe_id="minimax_h3_ref2va_character",
    version=1,
    label="MiniMax H3 Reference-to-Video Character",
    status="experimental",
    workflow_kind="inference",
    modality="video",
    model_family="minimax_h3_ref2va",
    base_model="MiniMaxAI/MiniMax-H3",
    intent="character",
    dataset=DatasetRecipePolicy(
        minimum_approved_items=1,
        recommended_approved_items=3,
        maximum_approved_items=3,
        minimum_sources=1,
        maximum_source_share=1.0,
        minimum_face_views=0,
        minimum_upper_body_views=0,
        minimum_full_body_views=0,
        minimum_materialized_crops=0,
        minimum_average_quality=0.50,
        minimum_average_diversity=0.0,
        allowed_image_extensions=[".jpg", ".jpeg", ".png", ".webp"],
        allowed_video_extensions=[".mp4", ".mov", ".m4v", ".webm"],
        allowed_audio_extensions=[".wav", ".mp3", ".m4a", ".flac"],
        minimum_average_identity=0.60,
        minimum_average_stability=0.50,
        guidance=[
            "Choose up to three reviewed video references and give each reference one explicit job: identity, motion, camera, style, or voice.",
            "Prefer clips where the intended subject is clearly visible and any useful voice remains audible in the source video.",
            "MiniMax H3 Reference-to-Video is zero-shot conditioning; this package does not train a per-person LoRA.",
        ],
    ),
    captions=CaptionRecipePolicy(
        trigger_token_required=False,
        caption_format="structured_reference_prompt",
        render_style="narrative",
        required_evidence=["subject", "identity", "motion", "camera", "audio"],
        controllable_attributes=[
            "identity",
            "style",
            "motion",
            "camera",
            "voice",
            "environment",
        ],
        excluded_identity_attributes=["other people", "watermark", "unrelated background"],
        guidance=[
            "Refer to connected inputs in order, such as <Video 1>, and state what each reference controls.",
            "Describe the target scene, timed shots, camera movement, dialogue, sound effects, and music in one prompt block.",
            "Do not invent voice or identity evidence that was not confirmed during review.",
        ],
    ),
    training=None,
    inference=InferenceRecipeDefaults(
        pipeline="comfyui_minimax_h3_ref2va",
        inference_steps=30,
        guidance_scale=4.0,
        output_width=1344,
        output_height=768,
    ),
    evaluation=EvaluationRecipePolicy(
        required_gates=[
            "identity_similarity",
            "temporal_stability",
            "motion_quality",
            "prompt_adherence",
            "audio_quality",
            "artifact_rate",
        ],
        minimum_identity_score=0.68,
        minimum_prompt_adherence=0.65,
        minimum_temporal_stability=0.60,
        minimum_motion_quality=0.60,
        minimum_audio_quality=0.60,
        maximum_artifact_rate=0.15,
        benchmark_prompt_count=6,
        guidance=[
            "Evaluate the identity, motion, camera, and audio role assigned to every reference independently.",
            "Compare the result against the same prompt without references so reference retention is measured rather than assumed.",
        ],
    ),
    rationale=[
        "MiniMax H3 ships a dedicated Ref2VA model for reference-driven video with native stereo audio.",
        "The official ComfyUI contract accepts up to nine images, three videos, and three standalone audio references; this first LoraSuite package deliberately limits the reviewed video lane to the official three-video ceiling.",
        "No validated per-person H3 LoRA trainer is represented here, so the workflow is versioned as inference rather than training.",
    ],
    evidence_urls=[
        "https://huggingface.co/MiniMaxAI/MiniMax-H3",
        "https://docs.comfy.org/tutorials/video/minimax/minimax-h3",
    ],
)


FISH_SPEECH_S2_VOICE_RECIPE = ModelIntentRecipe(
    recipe_id="fish_speech_s2_voice_character",
    version=1,
    label="Fish Speech S2 Voice Character",
    status="experimental",
    modality="voice",
    model_family="fish_speech_s2",
    base_model="fishaudio/s2-pro",
    intent="character",
    dataset=DatasetRecipePolicy(
        minimum_approved_items=3,
        recommended_approved_items=12,
        maximum_approved_items=200,
        minimum_sources=2,
        maximum_source_share=0.65,
        minimum_face_views=0,
        minimum_upper_body_views=0,
        minimum_full_body_views=0,
        minimum_materialized_crops=0,
        minimum_average_quality=0.65,
        minimum_average_diversity=0.0,
        allowed_image_extensions=[],
        allowed_audio_extensions=[".wav"],
        minimum_total_duration_seconds=10.0,
        recommended_total_duration_seconds=60.0,
        maximum_total_duration_seconds=1800.0,
        minimum_clip_duration_seconds=1.2,
        maximum_clip_duration_seconds=12.0,
        minimum_average_speaker_similarity=0.70,
        minimum_average_transcript_confidence=0.70,
        minimum_average_active_audio_ratio=0.45,
        maximum_average_silence_ratio=0.45,
        maximum_average_clipping_ratio=0.01,
        maximum_average_background_music_risk=0.35,
        maximum_multi_speaker_segments=0,
        guidance=[
            "Use verified single-speaker speech from at least two independent recordings.",
            "Prefer clean, naturally paced phrases with accurate transcripts and minimal music, overlap, clipping, echo, or aggressive denoising.",
            "Keep segments between 1.2 and 12 seconds so each example contains useful speech without binding long source context.",
            "Treat ten seconds as a packaging floor, not a quality target; add diverse clean speech until evaluation stops improving.",
        ],
    ),
    captions=CaptionRecipePolicy(
        trigger_token_required=False,
        caption_format="wav_lab_pairs",
        required_evidence=["verbatim transcript", "language", "speaker identity"],
        controllable_attributes=[
            "speech style",
            "emotion",
            "pace",
            "language",
        ],
        excluded_identity_attributes=[
            "background music",
            "other speakers",
            "reused audio",
            "transcription artifacts",
        ],
        guidance=[
            "Write a faithful verbatim transcript for every approved WAV segment.",
            "Do not add a visual trigger token to spoken text unless it is literally spoken.",
            "Preserve punctuation that reflects phrasing while removing non-speech annotations.",
        ],
    ),
    training=TrainingRecipeDefaults(
        network_rank=8,
        network_alpha=16,
        batch_size=2,
        save_every=250,
        sample_every=250,
    ),
    evaluation=EvaluationRecipePolicy(
        required_gates=[
            "speaker_similarity",
            "transcript_similarity",
            "audio_quality",
            "single_speaker",
        ],
        minimum_identity_score=0.70,
        minimum_prompt_adherence=0.85,
        minimum_speaker_similarity=0.70,
        minimum_transcript_similarity=0.85,
        minimum_audio_quality=0.65,
        maximum_artifact_rate=0.15,
        benchmark_prompt_count=8,
        guidance=[
            "Render fixed phrases that cover neutral speech, pace changes, emotion, and phonetic variety.",
            "Select the earliest checkpoint that passes speaker, transcript, and signal gates to limit speech-pattern overfitting.",
            "Keep reference prompts and evaluation recordings outside the training split.",
        ],
    ),
    rationale=[
        "The packaging floor matches the existing LoraSuite Fish Speech gate while the recommended duration remains deliberately higher.",
        "Fish Speech training and evaluation are version-pinned, but this recipe remains experimental until a real returned checkpoint passes the voice harness.",
        "Speaker identity, transcript fidelity, and signal quality are separate gates so a clean but incorrect voice cannot pass.",
    ],
    evidence_urls=[
        "https://github.com/fishaudio/fish-speech",
        "https://huggingface.co/fishaudio/s2-pro",
    ],
)


ID_LORA_LTX23_ZERO_SHOT_RECIPE = ModelIntentRecipe(
    recipe_id="id_lora_ltx23_zero_shot_character",
    version=1,
    label="ID-LoRA LTX-2.3 Zero-Shot Character",
    status="experimental",
    workflow_kind="inference",
    modality="audio_visual",
    model_family="ltx2.3_id_lora",
    base_model="Lightricks/LTX-2.3-22b-dev",
    intent="character",
    dataset=DatasetRecipePolicy(
        minimum_approved_items=2,
        recommended_approved_items=8,
        maximum_approved_items=40,
        minimum_sources=2,
        maximum_source_share=0.65,
        minimum_face_views=0,
        minimum_upper_body_views=0,
        minimum_full_body_views=0,
        minimum_materialized_crops=0,
        minimum_average_quality=0.0,
        minimum_average_diversity=0.0,
        allowed_image_extensions=[],
        allowed_video_extensions=[".mp4"],
        allowed_audio_extensions=[".wav"],
        minimum_average_identity=0.70,
        minimum_average_speaker_similarity=0.70,
        minimum_visual_examples=2,
        minimum_synchronized_pairs=2,
        minimum_voice_references=2,
        minimum_validation_examples=1,
        guidance=[
            "Package reviewed video identity examples with source-aligned speech whenever synchronized evidence exists.",
            "Provide a distinct same-split reference voice sample for every synchronized target.",
            "Keep source recordings isolated between train and validation reference groups.",
            "This package conditions the official pre-trained multi-identity adapter at inference; it is not a per-person LoRA training corpus.",
        ],
    ),
    captions=CaptionRecipePolicy(
        trigger_token_required=False,
        caption_format="structured_visual_speech_sounds",
        required_evidence=["visual", "speech", "sounds"],
        controllable_attributes=[
            "appearance",
            "expression",
            "pose",
            "action",
            "speech",
            "sound",
            "camera",
        ],
        excluded_identity_attributes=[
            "other people",
            "background",
            "reused audio",
            "watermark",
        ],
        guidance=[
            "Keep visual, speech, and sound evidence in explicit structured fields.",
            "Use verbatim synchronized speech when present and mark unknown sound content as unverified.",
            "Do not invent synchronization between unrelated visual and audio sources.",
        ],
    ),
    training=None,
    inference=InferenceRecipeDefaults(
        pipeline="two_stage_hq",
        reference_audio_seconds=5,
        inference_steps=30,
        guidance_scale=4.0,
        output_width=512,
        output_height=512,
        output_frames=121,
    ),
    evaluation=EvaluationRecipePolicy(
        required_gates=[
            "identity_similarity",
            "speaker_similarity",
            "transcript_similarity",
            "av_sync",
            "temporal_stability",
            "artifact_rate",
        ],
        minimum_identity_score=0.70,
        minimum_prompt_adherence=0.65,
        minimum_temporal_stability=0.65,
        minimum_speaker_similarity=0.70,
        minimum_transcript_similarity=0.85,
        minimum_audio_quality=0.65,
        maximum_artifact_rate=0.15,
        benchmark_prompt_count=8,
        guidance=[
            "Evaluate appearance and speaker identity independently before accepting audio-visual synchronization.",
            "Require SyncNet or equivalent evidence for lip-sync certification instead of inferring synchronization from shared source metadata.",
            "Compare fixed prompts and references against the unconditioned LTX-2.3 baseline.",
        ],
    ),
    rationale=[
        "ID-LoRA provides a pre-trained multi-identity adapter used zero-shot; LoraSuite therefore versions an inference reference recipe rather than claiming per-person training.",
        "The recipe requires synchronized targets, distinct voice references, source-safe validation evidence, and explicit audio-visual evaluation.",
        "The profile remains experimental until the pinned RunPod inference path and evaluation harness pass with a real reference project.",
    ],
    evidence_urls=[
        "https://github.com/ID-LoRA/ID-LoRA",
        "https://huggingface.co/Lightricks/LTX-2.3-22b-dev",
    ],
)


def _catalog_character_recipe(
    *,
    recipe_id: str,
    label: str,
    model_family: str,
    base_model: str,
) -> ModelIntentRecipe:
    recipe = FLUX1_DEV_CHARACTER_RECIPE.model_copy(deep=True)
    recipe.recipe_id = recipe_id
    recipe.label = label
    recipe.status = "experimental"
    recipe.model_family = model_family
    recipe.base_model = base_model
    if model_family in {"qwen_image_2512"}:
        recipe.captions.render_style = "narrative"
    elif model_family in {"sdxl", "sd15"}:
        recipe.captions.render_style = "tags"
    recipe.rationale = [
        f"AI Toolkit lists {base_model} as a supported image-training model.",
        "The character dataset policy inherits LoraSuite's versioned identity, coverage, caption, and evaluation baseline.",
        "The provider launcher remains validation-pending until a real cloud run passes the recorded evaluation gates.",
    ]
    recipe.evidence_urls = [
        "https://github.com/ostris/ai-toolkit#supported-models",
        f"https://huggingface.co/{base_model}",
    ]
    return recipe


KREA2_RAW_CHARACTER_RECIPE = _catalog_character_recipe(
    recipe_id="krea2_raw_character",
    label="KREA 2 Character",
    model_family="krea2",
    base_model="krea/Krea-2-Raw",
)
KREA2_RAW_CHARACTER_RECIPE.rationale = [
    "KREA publishes Raw as the malleable KREA 2 checkpoint for LoRA training and post-training.",
    "Adapters trained on Raw are intended to run with the faster KREA 2 Turbo checkpoint.",
    "LoraSuite launches the current AI Toolkit KREA 2 architecture against Raw and preserves the resulting adapter for Turbo inference.",
]
KREA2_RAW_CHARACTER_RECIPE.captions.render_style = "narrative"
KREA2_RAW_CHARACTER_RECIPE.captions.required_evidence = [
    "framing",
    "expression",
    "pose",
    "clothing",
    "environment",
    "camera",
]
KREA2_RAW_CHARACTER_RECIPE.captions.guidance = [
    "Start with the project trigger token and subject class.",
    "Render the evidence as coherent natural language rather than a bare tag list.",
    "Describe visible action, garments, setting, lighting, and composition without inventing identity traits.",
]
KREA2_RAW_CHARACTER_RECIPE.evidence_urls = [
    "https://www.krea.ai/krea-2-open-source",
    "https://huggingface.co/krea/Krea-2-Raw",
    "https://huggingface.co/krea/Krea-2-Turbo",
]
KREA2_RAW_CHARACTER_RECIPE.training.sample_steps = 52
KREA2_RAW_CHARACTER_RECIPE.training.sample_guidance_scale = 3.5
KREA2_RAW_CHARACTER_RECIPE.training.network_rank = 32
KREA2_RAW_CHARACTER_RECIPE.training.network_alpha = 32


ADDITIONAL_IMAGE_CHARACTER_RECIPES = [
    KREA2_RAW_CHARACTER_RECIPE,
    _catalog_character_recipe(
        recipe_id="flux2_dev_character",
        label="FLUX.2 Dev Character",
        model_family="flux2",
        base_model="black-forest-labs/FLUX.2-dev",
    ),
    _catalog_character_recipe(
        recipe_id="flux2_klein_4b_character",
        label="FLUX.2 Klein 4B Character",
        model_family="flux2_klein",
        base_model="black-forest-labs/FLUX.2-klein-base-4B",
    ),
    _catalog_character_recipe(
        recipe_id="chroma1_character",
        label="Chroma1 Character",
        model_family="chroma1",
        base_model="lodestones/Chroma1-Base",
    ),
    _catalog_character_recipe(
        recipe_id="lumina2_character",
        label="Lumina Image 2 Character",
        model_family="lumina2",
        base_model="Alpha-VLLM/Lumina-Image-2.0",
    ),
    _catalog_character_recipe(
        recipe_id="qwen_image_2512_character",
        label="Qwen Image 2512 Character",
        model_family="qwen_image_2512",
        base_model="Qwen/Qwen-Image-2512",
    ),
    _catalog_character_recipe(
        recipe_id="hidream_i1_character",
        label="HiDream I1 Character",
        model_family="hidream_i1",
        base_model="HiDream-ai/HiDream-I1-Full",
    ),
    _catalog_character_recipe(
        recipe_id="omnigen2_character",
        label="OmniGen2 Character",
        model_family="omnigen2",
        base_model="OmniGen2/OmniGen2",
    ),
    _catalog_character_recipe(
        recipe_id="z_image_character",
        label="Z-Image Character",
        model_family="z_image",
        base_model="Tongyi-MAI/Z-Image",
    ),
    _catalog_character_recipe(
        recipe_id="z_image_turbo_character",
        label="Z-Image Turbo Character",
        model_family="z_image_turbo",
        base_model="Tongyi-MAI/Z-Image-Turbo",
    ),
    _catalog_character_recipe(
        recipe_id="sdxl_character",
        label="SDXL 1.0 Character",
        model_family="sdxl",
        base_model="stabilityai/stable-diffusion-xl-base-1.0",
    ),
    _catalog_character_recipe(
        recipe_id="sd15_character",
        label="Stable Diffusion 1.5 Character",
        model_family="sd15",
        base_model="stable-diffusion-v1-5/stable-diffusion-v1-5",
    ),
]


def _catalog_training_target_profiles() -> list[TrainingTargetProfile]:
    compact_models = {"flux2_klein", "sdxl", "sd15", "z_image_turbo"}
    return [
        TrainingTargetProfile(
            profile_id=f"runcomfy_{recipe.recipe_id}",
            label=recipe.label,
            model_family=recipe.model_family,
            base_model=recipe.base_model,
            resolution_buckets=[512] if recipe.model_family == "sd15" else [512, 768, 1024],
            description=f"Character identity dataset and evaluation recipe for {recipe.label.removesuffix(' Character')}.",
            ready=recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id,
            config_template=(
                KREA2_RAW_CONFIG
                if recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id
                else ""
            ),
            trainer_revision=(
                KREA2_AI_TOOLKIT_REVISION
                if recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id
                else AI_TOOLKIT_TRAINER_REVISION
            ),
            required_environment=(
                ["HF_TOKEN"]
                if recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id
                else []
            ),
            minimum_gpu_memory_gb=(
                80
                if recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id
                else 24 if recipe.model_family in compact_models else 48
            ),
            duration_baselines=(
                [
                    TrainingDurationBaseline(
                        gpu_family="h100",
                        low_hours=1.8,
                        expected_hours=3.0,
                        high_hours=6.0,
                        confidence="low",
                        basis="Provisional LoraSuite sizing baseline for the 2,000-step, quantized KREA 2 Raw recipe.",
                        assumptions=[
                            "One H100 80 GB GPU, batch size 1, qfloat8 transformer and text encoder, cached latents, and 512/768/1024 buckets.",
                            "The 12-billion-parameter KREA 2 Raw checkpoint and 52-step scheduled samples make this a conservative initial range.",
                            "Excludes provider queue, dataset upload, model download, retry, artifact download, and evaluation time.",
                            "No completed LoraSuite KREA 2 provider run is available yet; measured history will supersede this baseline.",
                        ],
                    ),
                    TrainingDurationBaseline(
                        gpu_family="h200",
                        low_hours=1.4,
                        expected_hours=2.4,
                        high_hours=5.0,
                        confidence="low",
                        basis="Provisional LoraSuite sizing baseline for the 2,000-step, quantized KREA 2 Raw recipe.",
                        assumptions=[
                            "One H200 GPU, batch size 1, qfloat8 transformer and text encoder, cached latents, and 512/768/1024 buckets.",
                            "The 12-billion-parameter KREA 2 Raw checkpoint and 52-step scheduled samples make this a conservative initial range.",
                            "Excludes provider queue, dataset upload, model download, retry, artifact download, and evaluation time.",
                            "No completed LoraSuite KREA 2 provider run is available yet; measured history will supersede this baseline.",
                        ],
                    ),
                ]
                if recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id
                else []
            ),
            recipe_id=recipe.recipe_id,
            recipe_version=recipe.version,
            recipe=recipe,
            warnings=(
                [
                    "KREA 2 Raw is gated; HF_TOKEN must have access to krea/Krea-2-Raw.",
                    "The launcher contract is implemented and smoke-tested; complete the first paid cloud run before treating its quality baseline as production-verified.",
                ]
                if recipe.recipe_id == KREA2_RAW_CHARACTER_RECIPE.recipe_id
                else [
                    "Dataset compilation is available; the provider-specific trainer configuration still requires a validated cloud run.",
                ]
            ),
        )
        for recipe in ADDITIONAL_IMAGE_CHARACTER_RECIPES
    ]


FLUX_CONFIG = """---
job: extension
config:
  name: "{job_name}"
  process:
    - type: "sd_trainer"
      training_folder: "/app/ai-toolkit/output"
      device: cuda:0
      trigger_word: "{trigger_token}"
      network:
        type: "lora"
        linear: 16
        linear_alpha: 16
      save:
        dtype: float16
        save_every: 250
        max_step_saves_to_keep: 4
        push_to_hub: false
      datasets:
        - folder_path: "/app/ai-toolkit/datasets/{dataset_name}"
          caption_ext: "txt"
          caption_dropout_rate: 0.05
          shuffle_tokens: false
          cache_latents_to_disk: true
          resolution: [512, 768, 1024]
      train:
        batch_size: 1
        steps: 2000
        gradient_accumulation_steps: 1
        train_unet: true
        train_text_encoder: false
        gradient_checkpointing: true
        noise_scheduler: "flowmatch"
        optimizer: "adamw8bit"
        lr: 1e-4
        ema_config:
          use_ema: true
          ema_decay: 0.99
        dtype: bf16
      model:
        name_or_path: "black-forest-labs/FLUX.1-dev"
        is_flux: true
        quantize: true
      sample:
        sampler: "flowmatch"
        sample_every: 250
        width: 1024
        height: 1024
        prompts:
          - "{sample_prompt}"
        neg: ""
        seed: 42
        walk_seed: true
        guidance_scale: 4
        sample_steps: 20
meta:
  name: "[name]"
  version: "1.0"
"""


QWEN_CONFIG = """---
job: extension
config:
  name: "{job_name}"
  process:
    - type: "sd_trainer"
      training_folder: "/app/ai-toolkit/output"
      device: cuda:0
      network:
        type: "lora"
        linear: 16
        linear_alpha: 16
      save:
        dtype: float16
        save_every: 250
        max_step_saves_to_keep: 4
      datasets:
        - folder_path: "/app/ai-toolkit/datasets/{dataset_name}"
          caption_ext: "txt"
          caption_dropout_rate: 0.05
          shuffle_tokens: false
          cache_latents_to_disk: true
          resolution: [512, 768, 1024]
      train:
        batch_size: 1
        cache_text_embeddings: true
        steps: 2000
        gradient_accumulation: 1
        train_unet: true
        train_text_encoder: false
        gradient_checkpointing: true
        noise_scheduler: "flowmatch"
        optimizer: "adamw8bit"
        lr: 1e-4
        dtype: bf16
      model:
        name_or_path: "Qwen/Qwen-Image"
        arch: "qwen_image"
        quantize: true
        qtype: "uint3|ostris/accuracy_recovery_adapters/qwen_image_torchao_uint3.safetensors"
        quantize_te: true
        qtype_te: "qfloat8"
        low_vram: true
      sample:
        sampler: "flowmatch"
        sample_every: 250
        width: 1024
        height: 1024
        prompts:
          - "{sample_prompt}"
        neg: ""
        seed: 42
        walk_seed: true
        guidance_scale: 3
        sample_steps: 25
meta:
  name: "[name]"
  version: "1.0"
"""


KREA2_RAW_CONFIG = """---
job: extension
config:
  name: "{job_name}"
  process:
    - type: "diffusion_trainer"
      training_folder: "/app/ai-toolkit/output"
      device: cuda:0
      trigger_word: "{trigger_token}"
      network:
        type: "lora"
        linear: 32
        linear_alpha: 32
      save:
        dtype: bf16
        save_every: 250
        max_step_saves_to_keep: 4
        push_to_hub: false
      datasets:
        - folder_path: "/app/ai-toolkit/datasets/{dataset_name}"
          caption_ext: "txt"
          caption_dropout_rate: 0.05
          shuffle_tokens: false
          cache_latents_to_disk: true
          resolution: [512, 768, 1024]
      train:
        batch_size: 1
        steps: 2000
        gradient_accumulation: 1
        train_unet: true
        train_text_encoder: false
        gradient_checkpointing: true
        noise_scheduler: "flowmatch"
        timestep_type: "linear"
        optimizer: "adamw8bit"
        lr: 1e-4
        dtype: bf16
      model:
        name_or_path: "krea/Krea-2-Raw"
        arch: "krea2"
        quantize: true
        qtype: "qfloat8"
        quantize_te: true
        qtype_te: "qfloat8"
        low_vram: false
      sample:
        sampler: "flowmatch"
        sample_every: 250
        width: 1024
        height: 1024
        prompts:
          - "{sample_prompt}"
        neg: ""
        seed: 42
        walk_seed: true
        guidance_scale: 3.5
        sample_steps: 52
meta:
  name: "[name]"
  version: "1.0"
"""


WAN22_VIDEO_CONFIG = """---
job: extension
config:
  name: "{job_name}"
  process:
    - type: "sd_trainer"
      training_folder: "/app/ai-toolkit/output"
      device: cuda:0
      network:
        type: "lora"
        linear: 32
        linear_alpha: 32
      save:
        dtype: float16
        save_every: 250
        max_step_saves_to_keep: 4
      datasets:
        - folder_path: "/app/ai-toolkit/datasets/{dataset_name}"
          caption_ext: "txt"
          caption_dropout_rate: 0.05
          cache_latents_to_disk: true
          resolution: [480]
          num_frames: 41
          shrink_video_to_frames: true
          fps: 16
      train:
        batch_size: 1
        steps: 2000
        gradient_accumulation: 1
        train_unet: true
        train_text_encoder: false
        gradient_checkpointing: true
        noise_scheduler: "flowmatch"
        timestep_type: "linear"
        optimizer: "adamw8bit"
        lr: 1e-4
        optimizer_params:
          weight_decay: 1e-4
        dtype: bf16
        switch_boundary_every: 10
        cache_text_embeddings: true
      model:
        name_or_path: "ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16"
        arch: "wan22_14b"
        quantize: true
        qtype: "uint4|ostris/accuracy_recovery_adapters/wan22_14b_t2i_torchao_uint4.safetensors"
        quantize_te: true
        qtype_te: "qfloat8"
        low_vram: true
        model_kwargs:
          train_high_noise: true
          train_low_noise: true
      sample:
        sampler: "flowmatch"
        sample_every: 250
        width: 832
        height: 480
        num_frames: 41
        fps: 16
        prompts:
          - "{sample_prompt}"
        neg: ""
        seed: 42
        walk_seed: true
        guidance_scale: 3.5
        sample_steps: 25
meta:
  name: "[name]"
  version: "1.0"
"""


ID_LORA_LTX23_CONFIG = """---
acceleration:
  load_text_encoder_in_8bit: false
  mixed_precision_mode: bf16
  quantization: null
checkpoints:
  interval: 200
  keep_last_n: 3
  precision: bfloat16
data:
  num_dataloader_workers: 2
  preprocessed_data_root: "{dataset_path}/.precomputed"
flow_matching:
  timestep_sampling_mode: shifted_logit_normal
  timestep_sampling_params: {{}}
hub:
  hub_model_id: null
  push_to_hub: false
lora:
  alpha: 128
  dropout: 0.0
  rank: 128
  target_modules:
    - audio_attn1.to_k
    - audio_attn1.to_q
    - audio_attn1.to_v
    - audio_attn1.to_out.0
    - audio_attn2.to_k
    - audio_attn2.to_q
    - audio_attn2.to_v
    - audio_attn2.to_out.0
    - audio_ff.net.0.proj
    - audio_ff.net.2
    - audio_to_video_attn.to_k
    - audio_to_video_attn.to_q
    - audio_to_video_attn.to_v
    - audio_to_video_attn.to_out.0
    - video_to_audio_attn.to_k
    - video_to_audio_attn.to_q
    - video_to_audio_attn.to_v
    - video_to_audio_attn.to_out.0
model:
  load_checkpoint: null
  model_path: /workspace/models/ltx-2.3-22b-dev.safetensors
  text_encoder_path: /workspace/models/gemma-3-12b-it-qat-q4_0-unquantized
  training_mode: lora
optimization:
  batch_size: 1
  enable_gradient_checkpointing: true
  gradient_accumulation_steps: 4
  learning_rate: 0.0002
  max_grad_norm: 1.0
  optimizer_type: adamw8bit
  scheduler_params: {{}}
  scheduler_type: linear
  steps: 3000
output_dir: "{bundle_path}/output"
seed: 42
training_strategy:
  audio_latents_dir: audio_latents
  first_frame_conditioning_p: 0.9
  mask_cross_attention_to_reference: true
  mask_reference_from_text_attention: true
  name: audio_ref_only_ic
  reference_audio_latents_dir: reference_audio_latents
  use_negative_ref_positions: true
validation:
  compute_metrics: true
  face_metric: arcface
  speaker_metric: wavlm_ecapa
  frame_rate: 25.0
  generate_audio: true
  guidance_scale: 4.0
  include_reference_in_output: true
  inference_steps: 30
  interval: 200
  mask_cross_attention_to_reference: false
  mask_ref_audio_to_text: false
  negative_prompt: worst quality, inconsistent motion, blurry, jittery, distorted
  seed: 42
  skip_initial_validation: true
  stg_blocks: [29]
  stg_mode: stg_av
  stg_scale: 1.0
  video_dims: [512, 512, 121]
  videos_per_prompt: 1
  prompts: []
  images: []
  reference_videos: []
  target_videos: []
  captions: []
wandb:
  enabled: false
  entity: null
  log_validation_videos: true
  project: id-lora
  tags: [ltx2.3, audio-ref-only-ic, lorasuite]
"""


ID_LORA_LTX23_INFERENCE_CONFIG = """---
mode: id_lora_ltx23_zero_shot
dataset_root: "{dataset_path}"
output_dir: "{bundle_path}/output"
pipeline: two_stage_hq
quantize: true
reference_audio_seconds: 5
adapter: /workspace/models/id-lora-ltx23/id-lora-celebvhq-ltx2.3/lora_weights.safetensors
"""


FISH_SPEECH_S2_CONFIG = """---
trainer: fish_speech_s2
project: "{job_name}"
dataset_root: "{dataset_path}/voice_cloning/fish_speech"
pretrained_checkpoint: /workspace/models/fish-speech-s2
output_dir: "{bundle_path}/output"
lora:
  config: r_8_alpha_16
  rank: 8
  alpha: 16
training:
  max_steps: 2000
  batch_size: 2
  gradient_accumulation_steps: 4
  precision: bf16-true
  checkpoint_interval: 250
artifacts:
  adapter_checkpoint: "{bundle_path}/output/checkpoints"
  merge_required_for_inference: true
"""


def training_target_profiles() -> list[TrainingTargetProfile]:
    return [
        TrainingTargetProfile(
            profile_id="runcomfy_flux1_dev_character",
            label="FLUX.1 Dev Character",
            description="General-purpose character identity LoRA for FLUX.1 Dev.",
            recipe_id=FLUX1_DEV_CHARACTER_RECIPE.recipe_id,
            recipe_version=FLUX1_DEV_CHARACTER_RECIPE.version,
            recipe=FLUX1_DEV_CHARACTER_RECIPE,
            config_template=FLUX_CONFIG,
            required_environment=["HF_TOKEN"],
            minimum_gpu_memory_gb=48,
            duration_baselines=[
                TrainingDurationBaseline(
                    gpu_family="h100",
                    low_hours=1.0,
                    expected_hours=1.7,
                    high_hours=3.0,
                    basis="LoraSuite engineering baseline for the versioned 2,000-step FLUX recipe.",
                    assumptions=[
                        "One GPU, batch size 1, cached latents, and 512/768/1024 buckets.",
                        "Includes model startup and scheduled samples; excludes queue, upload, download, retry, and evaluation time.",
                    ],
                ),
                TrainingDurationBaseline(
                    gpu_family="h200",
                    low_hours=0.8,
                    expected_hours=1.4,
                    high_hours=2.5,
                    basis="LoraSuite engineering baseline for the versioned 2,000-step FLUX recipe.",
                    assumptions=[
                        "One GPU, batch size 1, cached latents, and 512/768/1024 buckets.",
                        "Includes model startup and scheduled samples; excludes queue, upload, download, retry, and evaluation time.",
                    ],
                ),
            ],
            warnings=["FLUX.1 Dev uses a gated, non-commercial base-model license."],
        ),
        TrainingTargetProfile(
            profile_id="runcomfy_qwen_image_character",
            label="Qwen Image Character",
            model_family="qwen_image",
            base_model="Qwen/Qwen-Image",
            description="Character identity LoRA compiled for Qwen Image.",
            recipe_id=QWEN_IMAGE_CHARACTER_RECIPE.recipe_id,
            recipe_version=QWEN_IMAGE_CHARACTER_RECIPE.version,
            recipe=QWEN_IMAGE_CHARACTER_RECIPE,
            config_template=QWEN_CONFIG,
            minimum_gpu_memory_gb=48,
            duration_baselines=[
                TrainingDurationBaseline(
                    gpu_family="h100",
                    low_hours=1.5,
                    expected_hours=2.5,
                    high_hours=4.0,
                    basis="LoraSuite engineering baseline for the versioned 2,000-step Qwen Image recipe.",
                    assumptions=[
                        "One GPU, batch size 1, cached text embeddings, quantized transformer, and 512/768/1024 buckets.",
                        "Includes embedding cache creation and scheduled samples; excludes queue, upload, download, retry, and evaluation time.",
                    ],
                ),
                TrainingDurationBaseline(
                    gpu_family="h200",
                    low_hours=1.2,
                    expected_hours=2.0,
                    high_hours=3.2,
                    basis="LoraSuite engineering baseline for the versioned 2,000-step Qwen Image recipe.",
                    assumptions=[
                        "One GPU, batch size 1, cached text embeddings, quantized transformer, and 512/768/1024 buckets.",
                        "Includes embedding cache creation and scheduled samples; excludes queue, upload, download, retry, and evaluation time.",
                    ],
                ),
            ],
            warnings=[
                "Qwen Image text embeddings are cached; approved captions must contain the literal trigger token.",
                "The LoraSuite dataset policy is experimental until a real Qwen run passes the evaluation gates.",
            ],
        ),
        *_catalog_training_target_profiles(),
        TrainingTargetProfile(
            profile_id="runcomfy_custom_image",
            label="Custom RunComfy Image",
            model_family="custom",
            base_model="custom",
            description="Model-specific AI Toolkit YAML supplied by the user.",
            ready=False,
            config_template="",
            minimum_gpu_memory_gb=24,
            warnings=["Compatibility depends on the supplied AI Toolkit configuration."],
        ),
        TrainingTargetProfile(
            profile_id="runcomfy_wan22_14b_t2v_character",
            label="WAN 2.2 14B T2V Character Video",
            modality="video",
            model_family="wan22_14b_t2v",
            base_model="ai-toolkit/Wan2.2-T2V-A14B-Diffusers-bf16",
            compiler_version="video-pairs-v1",
            resolution_buckets=[480],
            description="Temporal character LoRA trained from reviewed video clips on WAN 2.2 14B T2V.",
            recipe_id=WAN22_T2V_CHARACTER_RECIPE.recipe_id,
            recipe_version=WAN22_T2V_CHARACTER_RECIPE.version,
            recipe=WAN22_T2V_CHARACTER_RECIPE,
            config_template=WAN22_VIDEO_CONFIG,
            required_commands=["bash", "git", "python", "ffmpeg"],
            minimum_gpu_memory_gb=80,
            duration_baselines=[
                TrainingDurationBaseline(
                    gpu_family="h100",
                    low_hours=10.0,
                    expected_hours=22.0,
                    high_hours=36.0,
                    basis="Conservative LoraSuite baseline scaled from RunComfy WAN 2.2 guidance for 41-frame training.",
                    assumptions=[
                        "One GPU, 2,000 steps, 41 frames, 480-pixel bucket, both noise experts, and scheduled 41-frame samples.",
                        "Video step time varies sharply with decoded frame shape and sampling; excludes queue, upload, download, retry, and evaluation time.",
                    ],
                ),
                TrainingDurationBaseline(
                    gpu_family="h200",
                    low_hours=8.0,
                    expected_hours=17.0,
                    high_hours=30.0,
                    basis="Conservative LoraSuite baseline scaled from RunComfy WAN 2.2 guidance for 41-frame training.",
                    assumptions=[
                        "One GPU, 2,000 steps, 41 frames, 480-pixel bucket, both noise experts, and scheduled 41-frame samples.",
                        "Video step time varies sharply with decoded frame shape and sampling; excludes queue, upload, download, retry, and evaluation time.",
                    ],
                ),
            ],
            warnings=[
                "Video training is GPU intensive; use RunComfy H100 or H200 capacity.",
                "Configuration tracks AI Toolkit main revision 64663c8575b7 (2026-07-11); execution quality still requires a real training run.",
            ],
        ),
        TrainingTargetProfile(
            profile_id="comfyui_minimax_h3_ref2va",
            label="MiniMax H3 Reference-to-Video",
            provider="comfyui",
            trainer="comfyui_inference",
            modality="video",
            model_family="minimax_h3_ref2va",
            base_model="MiniMaxAI/MiniMax-H3",
            compiler_version="minimax-h3-reference-v1",
            resolution_buckets=[768, 1344],
            caption_format="structured_reference_prompt",
            output_format="minimax_h3_reference_package",
            description="Zero-shot character, motion, camera, style, and voice conditioning through MiniMax H3 Ref2VA.",
            ready=False,
            recipe_id=MINIMAX_H3_REFERENCE_RECIPE.recipe_id,
            recipe_version=MINIMAX_H3_REFERENCE_RECIPE.version,
            recipe=MINIMAX_H3_REFERENCE_RECIPE,
            config_template="",
            trainer_repository="https://github.com/comfyanonymous/ComfyUI.git",
            trainer_revision="0.30.0+",
            launcher_kind="minimax_h3_reference",
            required_commands=["python", "ffmpeg"],
            required_model_paths=[
                "/ComfyUI/models/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                "/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors",
                "/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors",
            ],
            minimum_gpu_memory_gb=80,
            warnings=[
                "This is a zero-shot reference workflow, not a per-person LoRA trainer.",
                "LoraSuite packages reviewed references now; automatic ComfyUI workflow launch remains experimental.",
                "The open native canvas uses a 768-pixel short edge; hosted 2K regeneration is not part of the open local package.",
            ],
        ),
        TrainingTargetProfile(
            profile_id="runpod_fish_speech_s2_voice_lora",
            label="Fish Speech S2 Voice LoRA",
            provider="runpod",
            trainer="fish_speech",
            modality="voice",
            model_family="fish_speech_s2",
            base_model="fishaudio/s2-pro",
            compiler_version="voice-handoff-v1",
            resolution_buckets=[],
            caption_format="wav_lab_pairs",
            description="Per-speaker speech-pattern and voice adapter using the official Fish Speech LoRA trainer.",
            recipe_id=FISH_SPEECH_S2_VOICE_RECIPE.recipe_id,
            recipe_version=FISH_SPEECH_S2_VOICE_RECIPE.version,
            recipe=FISH_SPEECH_S2_VOICE_RECIPE,
            config_template=FISH_SPEECH_S2_CONFIG,
            trainer_repository="https://github.com/fishaudio/fish-speech.git",
            trainer_revision="e5e292632cb11e7a27b2b7487f58f612bc101e13",
            launcher_kind="fish_speech_s2",
            required_commands=["bash", "git", "python", "ffmpeg"],
            required_model_paths=["/workspace/models/fish-speech-s2/codec.pth"],
            minimum_gpu_memory_gb=48,
            duration_baselines=[
                TrainingDurationBaseline(
                    gpu_family="h100",
                    low_hours=2.0,
                    expected_hours=4.0,
                    high_hours=8.0,
                    basis="Initial LoraSuite baseline for the pinned 2,000-step Fish Speech S2 adapter recipe.",
                    assumptions=[
                        "One GPU, batch size 2, gradient accumulation 4, and a preinstalled Fish Speech S2 checkpoint.",
                        "Excludes model installation, queue, upload, download, retry, merge, and voice evaluation time.",
                    ],
                ),
                TrainingDurationBaseline(
                    gpu_family="h200",
                    low_hours=1.6,
                    expected_hours=3.2,
                    high_hours=6.5,
                    basis="Initial LoraSuite baseline for the pinned 2,000-step Fish Speech S2 adapter recipe.",
                    assumptions=[
                        "One GPU, batch size 2, gradient accumulation 4, and a preinstalled Fish Speech S2 checkpoint.",
                        "Excludes model installation, queue, upload, download, retry, merge, and voice evaluation time.",
                    ],
                ),
            ],
            warnings=[
                "Fish Speech notes that LoRA learns speech patterns before timbre; use reference prompts and stop at the earliest checkpoint that passes voice evaluation.",
                "Requires the Fish Speech S2 checkpoint mounted at /workspace/models/fish-speech-s2.",
            ],
        ),
        TrainingTargetProfile(
            profile_id="runpod_id_lora_ltx23_inference",
            label="ID-LoRA LTX-2.3 Zero-Shot",
            provider="runpod",
            trainer="id_lora_inference",
            modality="audio_visual",
            model_family="ltx2.3_id_lora",
            base_model="Lightricks/LTX-2.3-22b-dev",
            compiler_version="id-lora-av-v1",
            resolution_buckets=[512, 1024],
            caption_format="structured_visual_speech_sounds",
            output_format="mp4_audio_visual",
            description="Zero-shot joint appearance and voice generation using the official pre-trained ID-LoRA adapter.",
            recipe_id=ID_LORA_LTX23_ZERO_SHOT_RECIPE.recipe_id,
            recipe_version=ID_LORA_LTX23_ZERO_SHOT_RECIPE.version,
            recipe=ID_LORA_LTX23_ZERO_SHOT_RECIPE,
            config_template=ID_LORA_LTX23_INFERENCE_CONFIG,
            trainer_repository="https://github.com/ID-LoRA/ID-LoRA.git",
            trainer_revision="13dc9c286a2d3c1a21a7781f9ac0fe7727ec56cd",
            launcher_kind="id_lora_ltx23_inference",
            required_commands=["bash", "git", "python", "ffmpeg"],
            required_model_paths=[
                "/workspace/models/id-lora-ltx23/id-lora-celebvhq-ltx2.3/lora_weights.safetensors",
                "/workspace/models/id-lora-ltx23/ltx-2.3-22b-dev.safetensors",
                "/workspace/models/id-lora-ltx23/gemma-3-12b-it-qat-q4_0-unquantized",
                "/workspace/models/id-lora-ltx23/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
                "/workspace/models/id-lora-ltx23/ltx-2.3-22b-distilled-lora-384.safetensors",
            ],
            minimum_gpu_memory_gb=80,
            warnings=[
                "This runs the official pre-trained multi-identity adapter; it does not train a per-person LoRA.",
                "Two-stage HQ inference requires the LTX-2.3, Gemma, upscaler, distilled LoRA, and ID-LoRA weights on the RunPod network volume.",
            ],
        ),
        TrainingTargetProfile(
            profile_id="runpod_id_lora_ltx23",
            label="ID-LoRA LTX-2.3 Audio-Visual Identity",
            provider="runpod",
            trainer="id_lora",
            modality="audio_visual",
            model_family="ltx2.3_id_lora",
            base_model="Lightricks/LTX-2.3-22b-dev",
            compiler_version="id-lora-av-v1",
            resolution_buckets=[512],
            description="Identity-driven joint appearance and voice adapter for LTX-2.3.",
            ready=False,
            config_template=ID_LORA_LTX23_CONFIG,
            trainer_repository="https://github.com/ID-LoRA/ID-LoRA.git",
            trainer_revision="13dc9c286a2d3c1a21a7781f9ac0fe7727ec56cd",
            launcher_kind="id_lora_ltx23",
            required_commands=["bash", "git", "python", "ffmpeg"],
            required_model_paths=[
                "/workspace/models/ltx-2.3-22b-dev.safetensors",
                "/workspace/models/gemma-3-12b-it-qat-q4_0-unquantized",
            ],
            minimum_gpu_memory_gb=80,
            warnings=[
                "ID-LoRA is a multi-identity adapter used zero-shot at inference; a single-character project is not a validated retraining corpus.",
                "Requires a CUDA Pod with the LTX-2.3 checkpoint and Gemma 3 text encoder mounted under /workspace/models.",
                "The research configuration tracks ID-LoRA revision 13dc9c286a2d but automatic training remains blocked until LoraSuite supports a multi-identity corpus.",
            ],
        ),
    ]


def model_intent_recipes() -> list[ModelIntentRecipe]:
    return [
        FLUX1_DEV_CHARACTER_RECIPE.model_copy(deep=True),
        QWEN_IMAGE_CHARACTER_RECIPE.model_copy(deep=True),
        *(recipe.model_copy(deep=True) for recipe in ADDITIONAL_IMAGE_CHARACTER_RECIPES),
        WAN22_T2V_CHARACTER_RECIPE.model_copy(deep=True),
        MINIMAX_H3_REFERENCE_RECIPE.model_copy(deep=True),
        FISH_SPEECH_S2_VOICE_RECIPE.model_copy(deep=True),
        ID_LORA_LTX23_ZERO_SHOT_RECIPE.model_copy(deep=True),
    ]


def get_model_intent_recipe(
    recipe_id: str,
    recipe_version: int | None = None,
) -> ModelIntentRecipe:
    recipe = next(
        (
            candidate
            for candidate in model_intent_recipes()
            if candidate.recipe_id == recipe_id
            and (recipe_version is None or candidate.version == recipe_version)
        ),
        None,
    )
    if recipe is None:
        suffix = f" version {recipe_version}" if recipe_version is not None else ""
        raise ValueError(f"unknown model-intent recipe: {recipe_id}{suffix}")
    return recipe


def recipe_for_training_target(
    target: TrainingTargetSpec,
) -> ModelIntentRecipe | None:
    if not target.recipe_id:
        return None
    try:
        return get_model_intent_recipe(target.recipe_id, target.recipe_version)
    except ValueError:
        # Persisted dataset snapshots keep the recipe version they were compiled
        # with. Caption-policy-only recipe revisions remain compatible with
        # those snapshots, so resolve the current recipe instead of making an
        # existing draft unusable.
        return get_model_intent_recipe(target.recipe_id)


def get_training_target_profile(profile_id: str) -> TrainingTargetProfile:
    profile = next(
        (candidate for candidate in training_target_profiles() if candidate.profile_id == profile_id),
        None,
    )
    if profile is None:
        raise ValueError(f"unknown training target profile: {profile_id}")
    return profile
