"""Bounded CUDA appearance pilot using the pinned upstream H3 trainer.

No provider calls. Package only reviewed training rows; never upload held-out data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

TRAINER_REVISION = "183007ec38a55151673b99232567928611e53a8c"
WEIGHTS_REVISION = "42ed227ee7df40d41602854ae760620d6eb651fe"
PROPOSAL_SHA = "fd7d1f27fee5b4d7912963a419f604f74431348a4ae8aa8f95873d48e383f482"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def prepare(proposal, output):
    if digest(proposal) != PROPOSAL_SHA:
        raise ValueError("Proposal changed; do not silently change the approved pilot")
    data = json.loads(proposal.read_text())
    train = data["train"]
    if len(train) != 27 or len({r["sha256"] for r in train}) != 27:
        raise ValueError("Expected 27 distinct reviewed photos")
    if {r["sha256"] for r in train} & {r["sha256"] for r in data["heldout"]}:
        raise ValueError("Held-out leak")
    for row in train:
        if digest(row["path"]) != row["sha256"] or not row["caption"].strip():
            raise ValueError("Source changed or caption absent")
    output.mkdir(parents=True, exist_ok=False)
    (output / "images").mkdir()
    rows = []
    for index, row in enumerate(train):
        relative = f"images/{index:02d}{Path(row['path']).suffix.lower()}"
        shutil.copyfile(row["path"], output / relative)
        rows.append({"video": relative, "prompt": row["caption"], "input_audio": None,
                     "sha256": row["sha256"], "media_id": row["media_id"]})
    write_json(output / "train.json", rows)
    write_json(output / "recipe.json", {
        "proposal_sha256": PROPOSAL_SHA, "trainer_revision": TRAINER_REVISION,
        "weights_revision": WEIGHTS_REVISION, "train_count": 27, "heldout_uploaded": False,
        "rank": 16, "max_steps": 500, "save_steps": 100, "learning_rate": 0.0001,
        "max_pixels": 512 * 512, "frames": 5, "audio_loss_weight": 0,
        "training_cfg_scale": 1, "seed": 42,
        "framing": "Full image fitted into nearest 32-pixel bucket; no center crop",
        "purpose": "Face and body appearance pilot; no motion or voice training",
    })
    print(json.dumps({"prepared": str(output), "train_count": len(rows)}))


def bucket_size(width, height):
    scale = min(1, math.sqrt(512 * 512 / (width * height)))
    return max(32, int(width * scale) // 32 * 32), max(32, int(height * scale) // 32 * 32)


def worker(runtime, run, weights, stage, deadline):
    actual = subprocess.check_output(["git", "-C", str(runtime), "rev-parse", "HEAD"], text=True).strip()
    if actual != TRAINER_REVISION:
        raise ValueError("Unqualified trainer revision")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                      DIFFSYNTH_SKIP_DOWNLOAD="True")
    import torch
    import accelerate
    import psutil
    from PIL import Image, ImageOps
    from diffsynth.core import UnifiedDataset
    from diffsynth.diffusion import ModelLogger, launch_data_process_task, launch_training_task

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("Pilot requires exactly one CUDA GPU")
    if time.time() >= deadline:
        raise RuntimeError("Training deadline already passed")
    torch.manual_seed(42)
    torch.cuda.reset_peak_memory_stats()
    spec = importlib.util.spec_from_file_location("upstream_h3_train", runtime / "examples/minimax_h3/model_training/train.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = json.loads((run / "train.json").read_text())
    if len(rows) != 27:
        raise ValueError("Training count mismatch")
    for row in rows:
        if digest(run / row["video"]) != row["sha256"]:
            raise ValueError("Training payload hash mismatch")

    def load_photo(relative):
        with Image.open(run / relative) as source:
            photo = ImageOps.exif_transpose(source).convert("RGB")
        # Contain preserves the entire visible body, even for very tall photos.
        size = bucket_size(*photo.size)
        return [ImageOps.pad(photo, size, method=Image.Resampling.LANCZOS, color=(24, 24, 24))] * 5

    model_paths = ([sorted(str(p) for p in (weights / "text_encoder").glob("model-*.safetensors")),
                    str(weights / "video_vae/source/model.safetensors"), str(weights / "audio_vae/model.safetensors")]
                   if stage == "cache" else [sorted(str(p) for p in (weights / "transformer").glob("*.safetensors"))])
    if not model_paths[0]:
        raise ValueError("Missing model shards")
    args = module.minimax_h3_parser().parse_args([
        "--dataset_base_path", str(run if stage == "cache" else run / "cache"),
        "--task", "sft:data_process" if stage == "cache" else "sft:train",
        "--model_paths", json.dumps(model_paths), "--processor_path", str(weights / "text_encoder"),
        "--output_path", str(run / ("cache" if stage == "cache" else "adapter")),
        "--height", "512", "--width", "512", "--num_frames", "5",
        "--lora_base_model", "dit", "--lora_rank", "16",
        "--lora_target_modules", "attn.qkv_proj,attn.out_proj,mlp.fc1,mlp.fc2",
        "--use_gradient_checkpointing", "--learning_rate", "0.0001",
        "--num_epochs", "19", "--save_steps", "100", "--enable_csv_log",
        "--audio_loss_weight", "0", "--silent_on_missing_audio", "--extra_inputs", "input_audio",
    ])
    accelerator = accelerate.Accelerator()
    dataset = UnifiedDataset(base_path=args.dataset_base_path,
        metadata_path=str(run / "train.json") if stage == "cache" else None,
        data_file_keys=("video",), main_data_operator=load_photo)
    if len(dataset) != 27:
        raise ValueError(f"Expected 27 cached or source samples, got {len(dataset)}")
    model = module.MiniMaxH3TrainingModule(model_paths=args.model_paths, processor_path=args.processor_path,
        lora_base_model="dit", lora_target_modules=args.lora_target_modules, lora_rank=16,
        use_gradient_checkpointing=True, silent_on_missing_audio=True, training_cfg_scale=1.0,
        extra_inputs="input_audio", audio_loss_weight=0, device=str(accelerator.device), task=args.task)
    start = time.time()

    class PilotLimit(Exception):
        pass

    class PilotLogger(ModelLogger):
        def save_model(self, accelerator, model, file_name):
            # Mark complete only after upstream's safetensors write and checksum finish.
            super().save_model(accelerator, model, file_name)
            p = Path(self.output_path) / file_name
            write_json(p.with_suffix(".complete.json"), {"file": file_name, "sha256": digest(p), "bytes": p.stat().st_size})

        def on_step_end(self, accelerator, model, save_steps=None, **kwargs):
            loss = float(kwargs["loss"].detach().float().cpu())
            if not math.isfinite(loss):
                raise RuntimeError("Nonfinite loss; no automatic retry")
            super().on_step_end(accelerator, model, save_steps, **kwargs)
            elapsed = time.time() - start
            write_json(run / "progress.json", {"stage": "train", "step": self.num_steps, "max_steps": 500,
                "loss": loss, "elapsed_seconds": elapsed, "seconds_per_step": elapsed / self.num_steps,
                "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                "process_rss_bytes": psutil.Process().memory_info().rss})
            if self.num_steps >= 500 or time.time() >= deadline or (run / "CANCEL").exists():
                raise PilotLimit("step ceiling" if self.num_steps >= 500 else "deadline or cancellation")

    logger = PilotLogger(args.output_path, remove_prefix_in_ckpt="pipe.dit.", enable_csv_log=True)
    outcome = "completed"
    try:
        launcher = launch_data_process_task if stage == "cache" else launch_training_task
        launcher(accelerator, dataset, model, logger, args=args)
    except PilotLimit as limit:
        outcome = str(limit)
        logger.on_training_end(accelerator, model, save_steps=100)
    write_json(run / f"{stage}-result.json", {"outcome": outcome, "steps": logger.num_steps,
        "elapsed_seconds": time.time() - start, "gpu_name": torch.cuda.get_device_name(),
        "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "gpu_peak_reserved_bytes": torch.cuda.max_memory_reserved(), "trainer_revision": actual,
        "packages": {p: importlib.metadata.version(p) for p in ("torch", "transformers", "peft", "accelerate", "diffsynth")}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "worker"))
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--stage", choices=("cache", "train"))
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.proposal, args.run)
    else:
        worker(args.runtime, args.run, args.weights, args.stage, args.deadline)
