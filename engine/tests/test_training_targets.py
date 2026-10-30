from lorasuite_engine.training_targets import (
    get_model_intent_recipe,
    get_training_target_profile,
    model_intent_recipes,
    recipe_for_training_target,
)


def test_flux_character_recipe_is_versioned_and_attached_to_target():
    recipe = get_model_intent_recipe("flux1_dev_character", 2)
    target = get_training_target_profile("runcomfy_flux1_dev_character")

    assert recipe.version == 2
    assert recipe.captions.render_style == "concise"
    assert recipe.intent == "character"
    assert recipe.model_family == "flux1"
    assert recipe.dataset.minimum_approved_items == 20
    assert recipe.dataset.minimum_face_views == 4
    assert recipe.training.network_rank == 16
    assert recipe.training.steps == 2000
    assert recipe.evaluation.benchmark_prompt_count == 12
    assert target.recipe_id == recipe.recipe_id
    assert target.recipe_version == recipe.version
    assert target.recipe == recipe
    assert target.spec().recipe_id == recipe.recipe_id
    assert "linear: 16" in target.config_template
    assert "linear_alpha: 16" in target.config_template
    assert {
        "flux1_dev_character",
        "qwen_image_character",
        "wan22_14b_t2v_character",
        "minimax_h3_ref2va_character",
        "fish_speech_s2_voice_character",
        "id_lora_ltx23_zero_shot_character",
    }.issubset({item.recipe_id for item in model_intent_recipes()})


def test_image_recipe_catalog_covers_major_ai_toolkit_model_families():
    recipe_ids = {item.recipe_id for item in model_intent_recipes()}

    assert {
        "krea2_raw_character",
        "flux2_dev_character",
        "flux2_klein_4b_character",
        "chroma1_character",
        "lumina2_character",
        "qwen_image_2512_character",
        "hidream_i1_character",
        "omnigen2_character",
        "z_image_character",
        "z_image_turbo_character",
        "sdxl_character",
        "sd15_character",
    }.issubset(recipe_ids)

    krea2 = get_training_target_profile("runcomfy_krea2_raw_character")
    assert krea2.base_model == "krea/Krea-2-Raw"
    assert krea2.recipe is not None
    assert krea2.recipe.model_family == "krea2"
    assert any("KREA 2 Turbo" in rationale for rationale in krea2.recipe.rationale)
    assert krea2.ready is True
    assert krea2.minimum_gpu_memory_gb == 80
    assert krea2.required_environment == ["HF_TOKEN"]
    assert krea2.trainer_revision == "c2864bba48a6f94ab1171d9df47b1335f8306355"
    assert 'arch: "krea2"' in krea2.config_template
    assert 'name_or_path: "krea/Krea-2-Raw"' in krea2.config_template
    assert 'folder_path: "/app/ai-toolkit/datasets/{dataset_name}"' in krea2.config_template
    assert krea2.recipe.training.sample_steps == 52
    assert krea2.recipe.training.sample_guidance_scale == 3.5
    assert krea2.recipe.training.network_rank == 32
    assert krea2.recipe.training.network_alpha == 32
    assert krea2.recipe.captions.render_style == "narrative"
    assert len(krea2.duration_baselines) == 2
    assert krea2.duration_baselines[0].gpu_family == "h100"
    assert krea2.duration_baselines[0].expected_hours == 3.0
    assert krea2.duration_baselines[0].confidence == "low"
    assert krea2.duration_baselines[1].gpu_family == "h200"
    assert krea2.duration_baselines[1].expected_hours == 2.4
    assert "linear: 32" in krea2.config_template
    assert "linear_alpha: 32" in krea2.config_template

    z_image = get_training_target_profile("runcomfy_z_image_character")
    assert z_image.base_model == "Tongyi-MAI/Z-Image"
    assert z_image.recipe is not None
    assert z_image.recipe.status == "experimental"
    assert z_image.ready is False
    assert z_image.config_template == ""


def test_qwen_character_recipe_requires_literal_cached_captions():
    recipe = get_model_intent_recipe("qwen_image_character", 2)
    target = get_training_target_profile("runcomfy_qwen_image_character")

    assert recipe.status == "experimental"
    assert recipe.model_family == "qwen_image"
    assert recipe.version == 2
    assert recipe.captions.render_style == "narrative"
    assert recipe.training.cache_text_embeddings is True
    assert recipe.training.sample_steps == 25
    assert recipe.training.sample_guidance_scale == 3.0
    assert any(
        "literal project trigger token" in guidance
        for guidance in recipe.captions.guidance
    )
    assert target.recipe == recipe
    assert target.spec().recipe_id == "qwen_image_character"
    assert 'trigger_word: "{trigger_token}"' not in target.config_template


def test_persisted_older_recipe_version_uses_current_compatible_recipe():
    target = get_training_target_profile("runcomfy_krea2_raw_character").spec()
    target.recipe_version = 1

    recipe = recipe_for_training_target(target)

    assert recipe is not None
    assert recipe.recipe_id == "krea2_raw_character"
    assert recipe.version == 2
    assert recipe.captions.render_style == "narrative"


def test_wan_character_recipe_matches_video_training_contract():
    recipe = get_model_intent_recipe("wan22_14b_t2v_character", 1)
    target = get_training_target_profile("runcomfy_wan22_14b_t2v_character")

    assert recipe.status == "experimental"
    assert recipe.modality == "video"
    assert recipe.model_family == "wan22_14b_t2v"
    assert recipe.dataset.target_num_frames == 41
    assert recipe.dataset.target_fps == 16
    assert recipe.dataset.minimum_clip_duration_seconds == 2.5625
    assert recipe.dataset.minimum_total_duration_seconds == 20
    assert recipe.training.network_rank == 32
    assert recipe.training.cache_text_embeddings is True
    assert recipe.evaluation.minimum_temporal_stability == 0.65
    assert "motion_quality" in recipe.evaluation.required_gates
    assert target.recipe == recipe
    assert target.spec().recipe_id == recipe.recipe_id
    assert target.spec().recipe_version == recipe.version


def test_minimax_h3_recipe_is_reference_inference_not_lora_training():
    recipe = get_model_intent_recipe("minimax_h3_ref2va_character", 1)
    target = get_training_target_profile("comfyui_minimax_h3_ref2va")

    assert recipe.status == "experimental"
    assert recipe.workflow_kind == "inference"
    assert recipe.modality == "video"
    assert recipe.model_family == "minimax_h3_ref2va"
    assert recipe.training is None
    assert recipe.inference is not None
    assert recipe.inference.pipeline == "comfyui_minimax_h3_ref2va"
    assert recipe.dataset.maximum_approved_items == 3
    assert recipe.captions.trigger_token_required is False
    assert target.recipe == recipe
    assert target.ready is False
    assert target.launcher_kind == "minimax_h3_reference"
    assert target.output_format == "minimax_h3_reference_package"


def test_fish_speech_recipe_matches_voice_training_contract():
    recipe = get_model_intent_recipe("fish_speech_s2_voice_character", 1)
    target = get_training_target_profile("runpod_fish_speech_s2_voice_lora")

    assert recipe.status == "experimental"
    assert recipe.modality == "voice"
    assert recipe.model_family == "fish_speech_s2"
    assert recipe.dataset.minimum_approved_items == 3
    assert recipe.dataset.minimum_total_duration_seconds == 10
    assert recipe.dataset.minimum_average_speaker_similarity == 0.70
    assert recipe.captions.trigger_token_required is False
    assert recipe.captions.caption_format == "wav_lab_pairs"
    assert recipe.training.network_rank == 8
    assert recipe.training.batch_size == 2
    assert recipe.evaluation.minimum_speaker_similarity == 0.70
    assert recipe.evaluation.minimum_transcript_similarity == 0.85
    assert target.recipe == recipe
    assert target.spec().recipe_id == recipe.recipe_id


def test_id_lora_recipe_is_explicitly_zero_shot_inference():
    recipe = get_model_intent_recipe("id_lora_ltx23_zero_shot_character", 1)
    target = get_training_target_profile("runpod_id_lora_ltx23_inference")

    assert recipe.status == "experimental"
    assert recipe.workflow_kind == "inference"
    assert recipe.modality == "audio_visual"
    assert recipe.training is None
    assert recipe.inference is not None
    assert recipe.inference.pipeline == "two_stage_hq"
    assert recipe.inference.reference_audio_seconds == 5
    assert recipe.dataset.minimum_synchronized_pairs == 2
    assert recipe.dataset.minimum_voice_references == 2
    assert target.recipe == recipe
    assert target.spec().recipe_id == recipe.recipe_id

    research_target = get_training_target_profile("runpod_id_lora_ltx23")
    assert research_target.ready is False
    assert research_target.recipe is None
