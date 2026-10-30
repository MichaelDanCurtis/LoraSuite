from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from tempfile import mkdtemp
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.training_targets import TrainingTargetProfile, get_training_target_profile


RunPodModality = Literal["image", "video", "voice", "audio_visual"]


class RunPodBundle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("runpod_bundle"))
    provider: str = "runpod"
    modality: RunPodModality
    fingerprint: str = ""
    config_digest: str = ""
    project_id: str | None = None
    snapshot_id: str | None = None
    source_export_path: Path
    output_path: Path
    archive_path: Path
    manifest_path: Path
    input_path: Path
    config_path: Path
    serverless_config_path: Path
    pod_template_path: Path
    pod_launcher_path: Path
    trainer_launcher_path: Path
    remote_root: str
    remote_dataset_path: str
    serverless_root: str
    serverless_dataset_path: str
    training_target_profile_id: str | None = None
    ready: bool
    available: bool = True
    warnings: list[str] = Field(default_factory=list)
    created_at: Any = Field(default_factory=utc_now)


class RunPodBundleService:
    def __init__(self, vault_root: Path | None = None):
        self.vault_root = Path(vault_root) if vault_root is not None else None

    @property
    def registry_path(self) -> Path | None:
        return self.vault_root / "runpod_bundles.json" if self.vault_root is not None else None

    def list_bundles(
        self,
        *,
        source_export_path: Path | None = None,
        training_target_profile_id: str | None = None,
        project_id: str | None = None,
    ) -> list[RunPodBundle]:
        bundles = self._read().values()
        if source_export_path is not None:
            source = Path(source_export_path).expanduser().resolve(strict=False)
            bundles = (bundle for bundle in bundles if bundle.source_export_path == source)
        if training_target_profile_id is not None:
            bundles = (bundle for bundle in bundles if bundle.training_target_profile_id == training_target_profile_id)
        if project_id is not None:
            bundles = (bundle for bundle in bundles if bundle.project_id == project_id)
        values = list(bundles)
        for bundle in values:
            bundle.available = bundle.output_path.is_dir() and bundle.manifest_path.is_file() and bundle.input_path.is_file()
        return sorted(values, key=lambda bundle: bundle.created_at, reverse=True)

    def create_bundle(
        self,
        *,
        source_export_path: Path,
        output_path: Path,
        modality: RunPodModality,
        trigger_token: str,
        fingerprint: str,
        training_target_profile_id: str | None = None,
        remote_root: str = "/workspace/lorasuite",
        endpoint_id: str | None = None,
    ) -> RunPodBundle:
        source = Path(source_export_path).expanduser().resolve(strict=False)
        if not source.is_dir() or not (source / "manifest.json").is_file():
            raise ValueError("source dataset export must contain manifest.json")
        source_manifest = _read_source_manifest(source / "manifest.json")
        output = Path(output_path).expanduser().resolve(strict=False)
        if output == source or source in output.parents or output in source.parents:
            raise ValueError("RunPod bundle must be outside the source dataset export")
        if output.exists() and not _is_runpod_bundle(output):
            raise ValueError("RunPod output folder is not empty or is not a LoraSuite RunPod bundle")
        output.parent.mkdir(parents=True, exist_ok=True)
        bundle_name = _slug(f"{modality}-{fingerprint[:12] or 'dataset'}")
        normalized_root = _remote_root(remote_root)
        remote_bundle = str(PurePosixPath(normalized_root) / bundle_name)
        volume_mount_path, volume_key = _volume_layout(remote_bundle)
        serverless_bundle = str(PurePosixPath("/runpod-volume") / volume_key)
        data_subdir = _dataset_subdir(source, modality)
        remote_dataset = str(PurePosixPath(remote_bundle) / "dataset" / data_subdir) if data_subdir else str(PurePosixPath(remote_bundle) / "dataset")
        serverless_dataset = str(PurePosixPath(serverless_bundle) / "dataset" / data_subdir) if data_subdir else str(PurePosixPath(serverless_bundle) / "dataset")
        model_card_name = source_manifest.get("model_card_path")
        source_model_card = (
            source / model_card_name
            if isinstance(model_card_name, str)
            and model_card_name
            and not Path(model_card_name).is_absolute()
            and ".." not in Path(model_card_name).parts
            else None
        )
        if source_model_card is not None and not source_model_card.is_file():
            source_model_card = None
        remote_model_card = (
            str(PurePosixPath(remote_bundle) / "dataset" / "model_card.json")
            if source_model_card is not None
            else None
        )
        serverless_model_card = (
            str(PurePosixPath(serverless_bundle) / "dataset" / "model_card.json")
            if source_model_card is not None
            else None
        )
        profile = get_training_target_profile(training_target_profile_id) if training_target_profile_id else None
        source_warnings = _source_readiness_warnings(source, source_manifest, modality, profile)
        warnings = [*_warnings(profile, modality), *source_warnings]
        ready = (
            profile is not None
            and profile.ready
            and profile.modality == modality
            and bool(profile.config_template.strip())
            and not source_warnings
        )
        requirements = _serverless_requirements(profile)

        staged = Path(mkdtemp(prefix=f".{output.name}.runpod.", dir=output.parent))
        moved = False
        try:
            shutil.copytree(source, staged / "dataset", dirs_exist_ok=True)
            config_dir = staged / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            if profile and profile.config_template.strip():
                config_path = config_dir / "train.yaml"
                config_path.write_text(
                    _render_config(profile, remote_dataset, remote_bundle, trigger_token, bundle_name),
                    encoding="utf-8",
                )
                serverless_config_path = config_dir / "serverless_train.yaml"
                serverless_config_path.write_text(
                    _render_config(profile, serverless_dataset, serverless_bundle, trigger_token, bundle_name),
                    encoding="utf-8",
                )
            else:
                config_path = config_dir / "worker_contract.json"
                atomic_write_json(config_path, {
                    "format": "lorasuite-runpod-worker-v1",
                    "modality": modality,
                    "training_target_profile_id": training_target_profile_id,
                    "dataset_path": remote_dataset,
                    "manifest_path": str(PurePosixPath(remote_bundle) / "dataset" / "manifest.json"),
                    "output_path": str(PurePosixPath(remote_bundle) / "output"),
                    "trigger_token": trigger_token,
                    "implementation_required": True,
                    "reason": "No validated standard trainer configuration exists for this modality.",
                })
                serverless_config_path = config_path
            config_digest = _sha256(serverless_config_path)
            remote_config = str(PurePosixPath(remote_bundle) / "config" / config_path.name)
            action = "run_id_lora" if profile and profile.launcher_kind == "id_lora_ltx23_inference" else "train_lora"
            runpod_input = {
                "input": {
                    "action": action,
                    "bundle_format": "lorasuite-runpod-v1",
                    "worker_contract_version": 1,
                    "modality": modality,
                    "training_target_profile_id": training_target_profile_id,
                    "dataset_path": serverless_dataset,
                    "manifest_path": str(PurePosixPath(serverless_bundle) / "dataset" / "manifest.json"),
                    "model_card_path": serverless_model_card,
                    "config_path": str(PurePosixPath(serverless_bundle) / "config" / serverless_config_path.name),
                    "output_path": str(PurePosixPath(serverless_bundle) / "output"),
                    "pod_dataset_path": remote_dataset,
                    "pod_config_path": remote_config,
                    "trigger_token": trigger_token,
                    "fingerprint": fingerprint,
                    "config_digest": config_digest,
                    "requirements": requirements,
                }
            }
            input_path = staged / "runpod_input.json"
            atomic_write_json(input_path, runpod_input)
            trainer_path = _write_scripts(
                staged,
                endpoint_id=endpoint_id,
                remote_bundle=remote_bundle,
                volume_mount_path=volume_mount_path,
                volume_key=volume_key,
                ready=ready,
                profile=profile,
            )
            bundle_manifest = {
                "created_by": "LoraSuite",
                "format": "lorasuite-runpod-v1",
                "provider": "runpod",
                "modality": modality,
                "fingerprint": fingerprint,
                "config_digest": config_digest,
                "trigger_token": trigger_token,
                "training_target_profile_id": training_target_profile_id,
                "source_manifest": source_manifest,
                "model_card_path": remote_model_card,
                "model_card": source_manifest.get("model_card"),
                "remote_root": remote_bundle,
                "remote_dataset_path": remote_dataset,
                "serverless_root": serverless_bundle,
                "serverless_dataset_path": serverless_dataset,
                "ready": ready,
                "worker_contract_version": 1,
                "requirements": requirements,
                "warnings": warnings,
            }
            manifest_path = staged / "bundle_manifest.json"
            atomic_write_json(manifest_path, bundle_manifest)
            _write_file_index(staged)
            if output.exists():
                shutil.rmtree(output)
            staged.replace(output)
            moved = True
        finally:
            if not moved and staged.exists():
                shutil.rmtree(staged)

        archive_base = output.with_name(f"{output.name}-runpod")
        archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=output))
        bundle = RunPodBundle(
            modality=modality,
            fingerprint=fingerprint,
            config_digest=config_digest,
            project_id=_first_string(source_manifest, "project_id", "character_project_id"),
            snapshot_id=_first_string(source_manifest, "dataset_snapshot_id", "snapshot_id", "video_snapshot_id"),
            source_export_path=source,
            output_path=output,
            archive_path=archive_path,
            manifest_path=output / "bundle_manifest.json",
            input_path=output / "runpod_input.json",
            config_path=output / "config" / config_path.name,
            serverless_config_path=output / "config" / serverless_config_path.name,
            pod_template_path=output / "pod_template.json",
            pod_launcher_path=output / "launch_pod.sh",
            trainer_launcher_path=output / trainer_path.name,
            remote_root=remote_bundle,
            remote_dataset_path=remote_dataset,
            serverless_root=serverless_bundle,
            serverless_dataset_path=serverless_dataset,
            training_target_profile_id=training_target_profile_id,
            ready=ready,
            warnings=warnings,
        )
        self._save(bundle)
        return bundle

    def _save(self, bundle: RunPodBundle) -> None:
        if self.registry_path is None:
            return
        bundles = self._read()
        existing = next((
            item for item in bundles.values()
            if item.output_path == bundle.output_path
            or (
                item.fingerprint == bundle.fingerprint
                and item.training_target_profile_id == bundle.training_target_profile_id
                and item.source_export_path == bundle.source_export_path
            )
        ), None)
        if existing is not None:
            bundle.id = existing.id
            bundles.pop(existing.id, None)
        bundles[bundle.id] = bundle
        with json_file_lock(self.registry_path):
            atomic_write_json(self.registry_path, {
                "version": 1,
                "bundles": [item.model_dump(mode="json") for item in bundles.values()],
            })

    def _read(self) -> dict[str, RunPodBundle]:
        if self.registry_path is None:
            return {}
        with json_file_lock(self.registry_path):
            if not self.registry_path.exists():
                return {}
            try:
                payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        return {
            item["id"]: RunPodBundle.model_validate(item)
            for item in payload.get("bundles", [])
            if isinstance(item, dict) and item.get("id")
        }


def _read_source_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("source dataset manifest is unreadable") from error
    if not isinstance(payload, dict) or payload.get("created_by") != "LoraSuite":
        raise ValueError("source dataset is not a LoraSuite export")
    return payload


def _first_string(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _render_config(profile: TrainingTargetProfile, dataset_path: str, bundle_path: str, trigger_token: str, job_name: str) -> str:
    template = profile.config_template.replace('/app/ai-toolkit/datasets/{dataset_name}', "{dataset_path}")
    template = template.replace('/app/ai-toolkit/output', str(PurePosixPath(bundle_path) / "output"))
    try:
        return template.format(
            dataset_name=dataset_path,
            dataset_path=dataset_path,
            job_name=job_name,
            trigger_token=trigger_token,
            sample_prompt=f"{trigger_token}, high quality character portrait".strip(", "),
            bundle_path=bundle_path,
        )
    except KeyError as error:
        raise ValueError(f"training target config contains an unsupported placeholder: {error}") from error


def _dataset_subdir(source: Path, modality: RunPodModality) -> str:
    preferred = {"image": "images", "video": "videos"}.get(modality)
    return preferred if preferred and (source / preferred).is_dir() else ""


def _warnings(profile: TrainingTargetProfile | None, modality: RunPodModality) -> list[str]:
    if profile is None:
        return [f"A custom RunPod worker must implement the {modality} training contract."]
    warnings = list(profile.warnings)
    if profile.modality != modality:
        warnings.append(f"Training target modality {profile.modality} does not match bundle modality {modality}.")
    if not profile.ready or not profile.config_template.strip():
        warnings.append("Training target is not validated for automatic RunPod execution.")
    return list(dict.fromkeys(warnings))


def _source_readiness_warnings(
    source: Path,
    manifest: dict[str, Any],
    modality: RunPodModality,
    profile: TrainingTargetProfile | None,
) -> list[str]:
    if profile is None:
        return []
    if modality == "audio_visual" and profile.launcher_kind == "id_lora_ltx23_inference":
        target = manifest.get("inference_target")
        if not isinstance(target, dict) or target.get("profile_id") != profile.profile_id or target.get("ready") is not True:
            return ["The source export has not passed the ID-LoRA zero-shot inference gate."]
        dataset_name = target.get("dataset")
        dataset_path = source / dataset_name if isinstance(dataset_name, str) else source / "trainer_dataset.json"
        try:
            entries = json.loads(dataset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ["The ID-LoRA inference package is missing trainer_dataset.json."]
        if not isinstance(entries, list) or not entries:
            return ["The ID-LoRA inference package has no synchronized identity references."]
        required = ("caption", "video", "reference_audio")
        for entry in entries:
            if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) or not entry[key] for key in required):
                return ["An ID-LoRA inference example is incomplete."]
            for key in ("video", "reference_audio"):
                relative = Path(entry[key])
                if relative.is_absolute() or ".." in relative.parts or not (source / relative).is_file():
                    return [f"An ID-LoRA inference example references a missing or unsafe {key} file."]
        return []
    if modality == "voice" and profile.launcher_kind == "fish_speech_s2":
        target = manifest.get("training_target")
        if not isinstance(target, dict) or target.get("profile_id") != profile.profile_id or target.get("ready") is not True:
            details = target.get("warnings") if isinstance(target, dict) else None
            return list(details) if isinstance(details, list) and details else [
                "The source export has not passed the Fish Speech voice-data gate."
            ]
        dataset_name = target.get("dataset_root")
        dataset_root = source / dataset_name if isinstance(dataset_name, str) else source / "voice_cloning/fish_speech"
        if dataset_root.is_symlink() or not dataset_root.is_dir():
            return ["The source export is missing the Fish Speech dataset folder."]
        audio_files = sorted(dataset_root.rglob("*.wav"))
        if not audio_files:
            return ["The Fish Speech dataset contains no WAV files."]
        if any(not audio.with_suffix(".lab").is_file() for audio in audio_files):
            return ["Every Fish Speech WAV file must have a matching .lab transcript."]
        return []
    if modality != "audio_visual" or profile.launcher_kind != "id_lora_ltx23":
        return []
    target = manifest.get("training_target")
    if not isinstance(target, dict) or target.get("profile_id") != profile.profile_id or target.get("ready") is not True:
        return ["The source export has not passed the ID-LoRA pairing and split-isolation gate."]
    dataset_name = target.get("trainer_dataset")
    dataset_path = source / dataset_name if isinstance(dataset_name, str) else source / "trainer_dataset.json"
    try:
        entries = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["The source export is missing a readable ID-LoRA trainer_dataset.json contract."]
    if not isinstance(entries, list) or not entries:
        return ["The ID-LoRA trainer dataset has no synchronized target/reference pairs."]
    required = ("caption", "video", "audio", "reference_audio", "split")
    for entry in entries:
        if not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) or not entry[key] for key in required):
            return ["An ID-LoRA trainer pair is incomplete."]
        for key in ("video", "audio", "reference_audio"):
            relative = Path(entry[key])
            if relative.is_absolute() or ".." in relative.parts or not (source / relative).is_file():
                return [f"An ID-LoRA trainer pair references a missing or unsafe {key} file."]
    splits = {entry["split"] for entry in entries}
    if "train" not in splits or "validation" not in splits:
        return ["ID-LoRA requires source-isolated train and validation pairs before cloud training."]
    return []


def _write_scripts(
    root: Path,
    *,
    endpoint_id: str | None,
    remote_bundle: str,
    volume_mount_path: str,
    volume_key: str,
    ready: bool,
    profile: TrainingTargetProfile | None,
) -> Path:
    endpoint = endpoint_id.strip() if endpoint_id else "${RUNPOD_ENDPOINT_ID}"
    upload = root / "upload_to_volume.sh"
    upload.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        ': "${RUNPOD_NETWORK_VOLUME_ID:?Set RUNPOD_NETWORK_VOLUME_ID}"\n'
        ': "${RUNPOD_S3_ENDPOINT:?Set RUNPOD_S3_ENDPOINT}"\n'
        ': "${RUNPOD_DATACENTER:?Set RUNPOD_DATACENTER}"\n'
        f'aws s3 sync . "s3://${{RUNPOD_NETWORK_VOLUME_ID}}/{volume_key}" '
        '--endpoint-url "$RUNPOD_S3_ENDPOINT" --region "$RUNPOD_DATACENTER"\n',
        encoding="utf-8",
    )
    launcher_kind = profile.launcher_kind if profile else "ai_toolkit"
    trainer_name = {
        "id_lora_ltx23": "train_id_lora_ltx23.sh",
        "id_lora_ltx23_inference": "run_id_lora_ltx23.sh",
        "fish_speech_s2": "train_fish_speech_s2.sh",
    }.get(launcher_kind, "train_ai_toolkit.sh")
    trainer = root / trainer_name
    if ready:
        if launcher_kind == "fish_speech_s2" and profile is not None:
            _write_fish_evaluation_renderer(root / "render_fish_speech_evaluation.py")
            atomic_write_json(root / "evaluation_phrases.json", {
                "phrases": [
                    "This is a LoraSuite voice identity evaluation.",
                    "Can this voice stay clear and consistent while asking a question?",
                    "Today I am speaking naturally, with calm emphasis and a steady pace.",
                ],
            })
            trainer.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                ': "${FISH_SPEECH_MODEL_PATH:=/workspace/models/fish-speech-s2}"\n'
                'export FISH_SPEECH_MODEL_PATH\n'
                '[[ -f "$FISH_SPEECH_MODEL_PATH/codec.pth" ]] || { echo "Fish Speech codec.pth is missing" >&2; exit 2; }\n'
                'command -v uv >/dev/null || python -m pip install --no-cache-dir uv\n'
                'TRAINER_ROOT="${FISH_SPEECH_ROOT:-/workspace/fish-speech}"\n'
                'if [[ ! -d "$TRAINER_ROOT/.git" ]]; then\n'
                f'  git clone {profile.trainer_repository} "$TRAINER_ROOT"\n'
                'fi\n'
                f'git -C "$TRAINER_ROOT" checkout {profile.trainer_revision}\n'
                'git -C "$TRAINER_ROOT" submodule update --init --recursive\n'
                'cd "$TRAINER_ROOT"\n'
                'uv sync --frozen\n'
                f'DATASET="{remote_bundle}/dataset/voice_cloning/fish_speech"\n'
                f'OUTPUT="{remote_bundle}/output"\n'
                'mkdir -p "$OUTPUT"\n'
                'uv run python tools/vqgan/extract_vq.py "$DATASET" --num-workers 2 --batch-size 8 '
                '--config-name modded_dac_vq --checkpoint-path "$FISH_SPEECH_MODEL_PATH/codec.pth"\n'
                'uv run python tools/llama/build_dataset.py --input "$DATASET" --output "$DATASET/protos" '
                '--text-extension .lab --num-workers 8\n'
                'uv run python fish_speech/train.py --config-name text2semantic_finetune '
                f'project="{PurePosixPath(remote_bundle).name}" '
                'pretrained_ckpt_path="$FISH_SPEECH_MODEL_PATH" paths.run_dir="$OUTPUT" '
                'train_dataset.proto_files="[$DATASET/protos]" val_dataset.proto_files="[$DATASET/protos]" '
                'trainer.max_steps=2000 data.batch_size=2 trainer.accumulate_grad_batches=4 '
                'callbacks.model_checkpoint.every_n_train_steps=250 +lora@model.model.lora_config=r_8_alpha_16\n'
                'mapfile -t LORA_WEIGHTS < <(find "$OUTPUT/checkpoints" -type f -name "*.ckpt" | sort -V)\n'
                '[[ "${#LORA_WEIGHTS[@]}" -gt 0 ]] || { echo "No Fish Speech LoRA checkpoint was produced" >&2; exit 3; }\n'
                'for LORA_WEIGHT in "${LORA_WEIGHTS[@]}"; do\n'
                '  CHECKPOINT_KEY="$(basename "$LORA_WEIGHT" .ckpt)"\n'
                '  MERGED="$OUTPUT/merged/$CHECKPOINT_KEY"\n'
                '  mkdir -p "$MERGED"\n'
                '  cp -a "$FISH_SPEECH_MODEL_PATH/." "$MERGED/"\n'
                '  uv run python tools/llama/merge_lora.py --lora-config r_8_alpha_16 '
                '--base-weight "$FISH_SPEECH_MODEL_PATH" --lora-weight "$LORA_WEIGHT" --output "$MERGED"\n'
                f'  uv run python "{remote_bundle}/render_fish_speech_evaluation.py" '
                f'--phrases "{remote_bundle}/evaluation_phrases.json" --dataset "$DATASET" '
                '--checkpoint "$MERGED" --output "$OUTPUT/evaluation/$CHECKPOINT_KEY"\n'
                'done\n',
                encoding="utf-8",
            )
        elif launcher_kind == "id_lora_ltx23_inference" and profile is not None:
            _write_id_lora_inference_preparer(root / "prepare_id_lora_inference.py")
            trainer.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                ': "${ID_LORA_MODEL_ROOT:=/workspace/models/id-lora-ltx23}"\n'
                ': "${ID_LORA_WEIGHTS:=$ID_LORA_MODEL_ROOT/id-lora-celebvhq-ltx2.3/lora_weights.safetensors}"\n'
                ': "${LTX_MODEL_PATH:=$ID_LORA_MODEL_ROOT/ltx-2.3-22b-dev.safetensors}"\n'
                ': "${GEMMA_MODEL_PATH:=$ID_LORA_MODEL_ROOT/gemma-3-12b-it-qat-q4_0-unquantized}"\n'
                ': "${LTX_UPSAMPLER_PATH:=$ID_LORA_MODEL_ROOT/ltx-2.3-spatial-upscaler-x2-1.1.safetensors}"\n'
                ': "${LTX_DISTILLED_LORA_PATH:=$ID_LORA_MODEL_ROOT/ltx-2.3-22b-distilled-lora-384.safetensors}"\n'
                'for REQUIRED in "$ID_LORA_WEIGHTS" "$LTX_MODEL_PATH" "$GEMMA_MODEL_PATH" "$LTX_UPSAMPLER_PATH" "$LTX_DISTILLED_LORA_PATH"; do\n'
                '  [[ -e "$REQUIRED" ]] || { echo "Required ID-LoRA model is missing: $REQUIRED" >&2; exit 2; }\n'
                'done\n'
                'command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 2; }\n'
                'command -v uv >/dev/null || python -m pip install --no-cache-dir uv\n'
                'REPO="${ID_LORA_ROOT:-/workspace/ID-LoRA}"\n'
                'if [[ ! -d "$REPO/.git" ]]; then\n'
                f'  git clone {profile.trainer_repository} "$REPO"\n'
                'fi\n'
                f'git -C "$REPO" checkout {profile.trainer_revision}\n'
                'cd "$REPO"\n'
                'python - <<\'PY\'\n'
                'from pathlib import Path\n'
                'path = Path("pyproject.toml")\n'
                'content = path.read_text(encoding="utf-8")\n'
                'base = \'members = ["packages/*"]\'\n'
                'ltx23 = \'members = ["ID-LoRA-2.3/packages/*"]\'\n'
                'if ltx23 not in content:\n'
                '    if base not in content:\n'
                '        raise SystemExit("Pinned ID-LoRA workspace layout changed")\n'
                '    path.write_text(content.replace(base, ltx23, 1), encoding="utf-8")\n'
                'PY\n'
                'uv sync\n'
                f'python "{remote_bundle}/prepare_id_lora_inference.py" "{remote_bundle}/dataset" "{remote_bundle}/inference_requests.json"\n'
                f'mkdir -p "{remote_bundle}/output"\n'
                'uv run python ID-LoRA-2.3/scripts/inference_two_stage_hq.py '
                '--lora-path "$ID_LORA_WEIGHTS" '
                f'--prompts-file "{remote_bundle}/inference_requests.json" '
                '--checkpoint "$LTX_MODEL_PATH" --text-encoder-path "$GEMMA_MODEL_PATH" '
                '--upsampler-path "$LTX_UPSAMPLER_PATH" --distilled-lora-path "$LTX_DISTILLED_LORA_PATH" '
                f'--output-dir "{remote_bundle}/output" --quantize\n'
                f'cp "{remote_bundle}/inference_requests.json" "{remote_bundle}/output/inference_contract.json"\n',
                encoding="utf-8",
            )
        elif launcher_kind == "id_lora_ltx23" and profile is not None:
            _write_id_lora_preparer(root / "prepare_id_lora_dataset.py")
            trainer.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                ': "${LTX_MODEL_PATH:=/workspace/models/ltx-2.3-22b-dev.safetensors}"\n'
                ': "${GEMMA_MODEL_PATH:=/workspace/models/gemma-3-12b-it-qat-q4_0-unquantized}"\n'
                'export LTX_MODEL_PATH GEMMA_MODEL_PATH\n'
                'command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 2; }\n'
                'command -v uv >/dev/null || python -m pip install --no-cache-dir uv\n'
                'TRAINER_ROOT="${ID_LORA_ROOT:-/workspace/ID-LoRA}"\n'
                'if [[ ! -d "$TRAINER_ROOT/.git" ]]; then\n'
                f'  git clone {profile.trainer_repository} "$TRAINER_ROOT"\n'
                'fi\n'
                f'git -C "$TRAINER_ROOT" checkout {profile.trainer_revision}\n'
                'cd "$TRAINER_ROOT"\n'
                'python - <<\'PY\'\n'
                'from pathlib import Path\n'
                'path = Path("pyproject.toml")\n'
                'content = path.read_text(encoding="utf-8")\n'
                'base = \'members = ["packages/*"]\'\n'
                'ltx23 = \'members = ["ID-LoRA-2.3/packages/*"]\'\n'
                'if ltx23 not in content:\n'
                '    if base not in content:\n'
                '        raise SystemExit("Pinned ID-LoRA workspace layout changed")\n'
                '    path.write_text(content.replace(base, ltx23, 1), encoding="utf-8")\n'
                'PY\n'
                'uv sync\n'
                f'uv run python "{remote_bundle}/prepare_id_lora_dataset.py" "{remote_bundle}/dataset"\n'
                f'uv run python "ID-LoRA-2.3/packages/ltx-trainer/scripts/process_dataset.py" "{remote_bundle}/dataset/trainer_input.json" '
                '--resolution-buckets "512x512x121" --model-path "$LTX_MODEL_PATH" '
                '--text-encoder-path "$GEMMA_MODEL_PATH" --caption-column caption --video-column media_path '
                '--reference-column reference_path --with-audio --output-dir '
                f'"{remote_bundle}/dataset/.precomputed"\n'
                f'uv run python "{remote_bundle}/prepare_id_lora_dataset.py" "{remote_bundle}/dataset" '
                f'--patch-config "{remote_bundle}/config/train.yaml"\n'
                f'uv run python "ID-LoRA-2.3/packages/ltx-trainer/scripts/train.py" "{remote_bundle}/config/train.yaml"\n',
                encoding="utf-8",
            )
        else:
            repository = profile.trainer_repository if profile else "https://github.com/ostris/ai-toolkit.git"
            revision = profile.trainer_revision if profile else "64663c8575b7a9ac3b946611724f76d015c941bc"
            trainer.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                'TOOLKIT_ROOT="${AI_TOOLKIT_ROOT:-/workspace/ai-toolkit}"\n'
                'if [[ ! -d "$TOOLKIT_ROOT/.git" ]]; then\n'
                f'  git clone {repository} "$TOOLKIT_ROOT"\n'
                'fi\n'
                f'git -C "$TOOLKIT_ROOT" cat-file -e {revision}^{{commit}} 2>/dev/null || git -C "$TOOLKIT_ROOT" fetch --depth 1 origin {revision}\n'
                f'git -C "$TOOLKIT_ROOT" checkout {revision}\n'
                'git -C "$TOOLKIT_ROOT" submodule update --init --recursive\n'
                'python -m pip install --no-cache-dir -r "$TOOLKIT_ROOT/requirements.txt"\n'
                'cd "$TOOLKIT_ROOT"\n'
                f'python run.py "{remote_bundle}/config/train.yaml"\n',
                encoding="utf-8",
            )
    else:
        trainer.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "echo 'No validated trainer is configured for this modality.' >&2\n"
            "exit 2\n",
            encoding="utf-8",
        )
    serverless_bundle = str(PurePosixPath("/runpod-volume") / volume_key)
    serverless_trainer = root / "train_serverless.sh"
    serverless_content = trainer.read_text(encoding="utf-8").replace(remote_bundle, serverless_bundle)
    serverless_content = serverless_content.replace("/config/train.yaml", "/config/serverless_train.yaml")
    serverless_content = serverless_content.replace("/workspace/models/", "/runpod-volume/models/")
    serverless_trainer.write_text(serverless_content, encoding="utf-8")
    atomic_write_json(root / "pod_template.json", {
        "name": f"lorasuite-{PurePosixPath(remote_bundle).name}",
        "cloudType": "SECURE",
        "computeType": "GPU",
        "containerDiskInGb": 100,
        "dockerEntrypoint": [],
        "dockerStartCmd": ["bash", f"{remote_bundle}/{trainer.name}"],
        "env": {"PYTHONUNBUFFERED": "1"},
        "gpuCount": 1,
        "gpuTypeIds": ["NVIDIA H100 80GB HBM3", "NVIDIA H200"],
        "gpuTypePriority": "availability",
        "imageName": "runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851",
        "interruptible": False,
        "networkVolumeId": None,
        "ports": ["8888/http", "22/tcp"],
        "supportPublicIp": False,
        "volumeMountPath": volume_mount_path,
        "lorasuiteReady": ready,
    })
    pod_launcher = root / "launch_pod.sh"
    blocked_guard = "" if ready else "echo 'Trainer selection is required before launching a Pod.' >&2\nexit 2\n"
    pod_launcher.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        ': "${RUNPOD_API_KEY:?Set RUNPOD_API_KEY}"\n'
        ': "${RUNPOD_NETWORK_VOLUME_ID:?Set RUNPOD_NETWORK_VOLUME_ID}"\n'
        f"{blocked_guard}"
        'cd "$(dirname "$0")"\n'
        'PAYLOAD="$(mktemp)"\n'
        'trap \'rm -f "$PAYLOAD"\' EXIT\n'
        "python3 - \"$RUNPOD_NETWORK_VOLUME_ID\" >\"$PAYLOAD\" <<'PY'\n"
        "import json, sys\n"
        "with open('pod_template.json', encoding='utf-8') as handle:\n"
        "    payload = json.load(handle)\n"
        "payload.pop('lorasuiteReady', None)\n"
        "payload['networkVolumeId'] = sys.argv[1]\n"
        "print(json.dumps(payload))\n"
        "PY\n"
        'curl --fail-with-body --request POST "https://rest.runpod.io/v1/pods" '
        '--header "Authorization: Bearer ${RUNPOD_API_KEY}" --header "Content-Type: application/json" '
        '--data-binary @"$PAYLOAD"\n',
        encoding="utf-8",
    )
    submit = root / "submit_serverless.sh"
    submit.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        ': "${RUNPOD_API_KEY:?Set RUNPOD_API_KEY}"\n'
        f'ENDPOINT_ID="{endpoint}"\n'
        'curl --fail-with-body --request POST "https://api.runpod.ai/v2/${ENDPOINT_ID}/run" '
        '--header "Authorization: Bearer ${RUNPOD_API_KEY}" --header "Content-Type: application/json" '
        '--data @runpod_input.json\n',
        encoding="utf-8",
    )
    for path in (upload, trainer, serverless_trainer, pod_launcher, submit):
        path.chmod(0o755)
    return trainer


def _write_fish_evaluation_renderer(path: Path) -> None:
    path.write_text(
        '''#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--phrases", type=Path, required=True)
parser.add_argument("--dataset", type=Path, required=True)
parser.add_argument("--checkpoint", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

audio = next(iter(sorted(args.dataset.rglob("*.wav"))), None)
if audio is None or not audio.with_suffix(".lab").is_file():
    raise SystemExit("A Fish Speech reference WAV with matching LAB transcript is required")
prompt_text = audio.with_suffix(".lab").read_text(encoding="utf-8").strip()
phrases = json.loads(args.phrases.read_text(encoding="utf-8")).get("phrases", [])
if len(phrases) < 3:
    raise SystemExit("At least three evaluation phrases are required")
args.output.mkdir(parents=True, exist_ok=True)
work = args.output / ".codes"
work.mkdir(exist_ok=True)
for index, phrase in enumerate(phrases, start=1):
    target = args.output / f"phrase_{index:02d}.wav"
    subprocess.run([
        "python", "fish_speech/models/text2semantic/inference.py",
        "--text", str(phrase),
        "--prompt-text", prompt_text,
        "--prompt-audio", str(audio),
        "--checkpoint-path", str(args.checkpoint),
        "--output", str(target),
        "--output-dir", str(work / f"phrase_{index:02d}"),
        "--seed", str(4200 + index),
    ], check=True)
    target.with_suffix(".txt").write_text(str(phrase).rstrip() + "\\n", encoding="utf-8")
''',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_id_lora_inference_preparer(path: Path) -> None:
    path.write_text(
        '''#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path


root = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
entries = json.loads((root / "trainer_dataset.json").read_text(encoding="utf-8"))
candidates = [entry for entry in entries if entry.get("split") == "validation"] or entries
requests = []
work = root / "inference_inputs"
work.mkdir(parents=True, exist_ok=True)
for index, entry in enumerate(candidates[:4], start=1):
    video = (root / entry["video"]).resolve()
    reference = (root / entry["reference_audio"]).resolve()
    if root not in video.parents or root not in reference.parents:
        raise SystemExit("ID-LoRA inference inputs must stay inside the dataset")
    frame = work / f"first_frame_{index:02d}.png"
    voice = work / f"reference_voice_{index:02d}.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(video), "-frames:v", "1", str(frame),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(reference), "-t", "5", "-ac", "1", str(voice),
    ], check=True)
    requests.append({
        "prompt": entry["caption"],
        "reference_path": str(voice),
        "first_frame_path": str(frame),
        "output_name": f"id_lora_{index:02d}",
    })
if not requests:
    raise SystemExit("No ID-LoRA inference requests were prepared")
output.write_text(json.dumps(requests, indent=2) + "\\n", encoding="utf-8")
''',
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_id_lora_preparer(path: Path) -> None:
    path.write_text(
        '''#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from pathlib import Path


def mux(video: Path, audio: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "apad", "-shortest",
        str(output),
    ], check=True)


def prepare(root: Path) -> None:
    entries = json.loads((root / "trainer_dataset.json").read_text(encoding="utf-8"))
    output = []
    for entry in entries:
        if entry["split"] != "train":
            continue
        target = root / "trainer_media" / f'{entry["id"]}.mp4'
        reference = root / "trainer_references" / f'{entry["id"]}.mp4'
        mux(root / entry["video"], root / entry["audio"], target)
        mux(root / entry["video"], root / entry["reference_audio"], reference)
        output.append({
            "caption": entry["caption"],
            "media_path": str(target),
            "reference_path": str(reference),
        })
    if not output:
        raise SystemExit("No train-split ID-LoRA pairs were found")
    (root / "trainer_input.json").write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")


def patch_config(config: Path) -> None:
    text = config.read_text(encoding="utf-8")
    text = text.replace("/workspace/models/ltx-2.3-22b-dev.safetensors", os.environ["LTX_MODEL_PATH"])
    text = text.replace("/workspace/models/gemma-3-12b-it-qat-q4_0-unquantized", os.environ["GEMMA_MODEL_PATH"])
    config.write_text(text, encoding="utf-8")


parser = argparse.ArgumentParser()
parser.add_argument("dataset_root", type=Path)
parser.add_argument("--patch-config", type=Path)
args = parser.parse_args()
if args.patch_config:
    patch_config(args.patch_config)
else:
    prepare(args.dataset_root)
''',
        encoding="utf-8",
    )


def _write_file_index(root: Path) -> None:
    entries = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file() and candidate.name != "file_index.json"):
        entries.append({
            "path": str(path.relative_to(root)),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    atomic_write_json(root / "file_index.json", {"files": entries})


def _serverless_requirements(profile: TrainingTargetProfile | None) -> dict[str, Any]:
    if profile is None:
        return {
            "commands": ["bash", "git", "python"],
            "environment": [],
            "model_paths": [],
            "minimum_gpu_memory_gb": 24,
        }
    return {
        "commands": list(profile.required_commands),
        "environment": list(profile.required_environment),
        "model_paths": [path.replace("/workspace/models/", "/runpod-volume/models/") for path in profile.required_model_paths],
        "minimum_gpu_memory_gb": profile.minimum_gpu_memory_gb,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remote_root(value: str) -> str:
    normalized = "/" + value.strip().strip("/")
    if normalized == "/":
        raise ValueError("RunPod remote root must not be empty")
    if ".." in PurePosixPath(normalized).parts:
        raise ValueError("RunPod remote root must not contain parent traversal")
    return normalized


def _volume_layout(remote_bundle: str) -> tuple[str, str]:
    parts = PurePosixPath(remote_bundle).parts
    if len(parts) < 3 or parts[0] != "/":
        raise ValueError("RunPod remote root must include a volume mount and folder")
    return f"/{parts[1]}", str(PurePosixPath(*parts[2:]))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-._")
    return cleaned[:80] or "lorasuite-dataset"


def _is_runpod_bundle(path: Path) -> bool:
    manifest = path / "bundle_manifest.json"
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("created_by") == "LoraSuite" and payload.get("format") == "lorasuite-runpod-v1"
