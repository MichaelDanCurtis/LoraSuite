"""Isolated, offline H3 appearance-training qualification; never edits the vault.

Run with the dedicated DiffSynth venv. Photos are repeated for five frames:
this checks training mechanics, not learned motion, voice, or identity quality.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def prepare(vault: Path, destination: Path, snapshot_id: str) -> None:
    snapshots = json.loads((vault / "dataset_snapshots.json").read_text())["snapshots"]
    snapshot = next(s for s in snapshots if s["id"] == snapshot_id)
    media = {m["id"]: m for m in json.loads((vault / "vault.json").read_text())["media_items"]}
    candidates = sorted(
        ((key, item) for key, item in snapshot["items"].items() if item["status"] == "approved"),
        key=lambda pair: pair[1].get("strongest_set_rank") or 100000,
    )
    selected, sources = [], set()
    for item_id, item in candidates:
        source = item["source_id"]
        m = media[item["training_media_item_id"]]
        path = Path(m["raw_path"])
        if source in sources or not path.is_file() or not item.get("caption"):
            continue
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        sources.add(source)
        selected.append({"item_id": item_id, "media_id": m["id"], "source_id": source,
                         "video": str(path), "prompt": item["caption"], "input_audio": None,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        if len(selected) == 5:
            break
    if len(selected) != 5:
        raise ValueError("Need five approved photos from distinct sources with captions")
    destination.mkdir(parents=True, exist_ok=False)
    for name, rows in (("train", selected[:4]), ("heldout", selected[4:])):
        (destination / f"{name}.json").write_text(json.dumps(rows, indent=2) + "\n")
    manifest = {"snapshot_id": snapshot_id, "trigger": snapshot["intent"]["trigger_token"],
                "train_count": 4, "heldout_count": 1, "frames": 5, "height": 256, "width": 256,
                "purpose": "appearance-only mechanics smoke; no motion or voice training",
                "selection": "approved rank order, distinct source IDs; last one held out",
                "status": "prepared; no training completed"}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest), flush=True)


def worker(runtime: Path, run: Path, weights: Path, stage: str) -> None:
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                      DIFFSYNTH_SKIP_DOWNLOAD="True")
    import torch
    import accelerate
    from diffsynth.core import UnifiedDataset
    from diffsynth.diffusion import ModelLogger, launch_data_process_task, launch_training_task
    from diffsynth.pipelines.minimax_h3_audio_video import MiniMaxH3Unit_PackedSequenceBuilder

    # Accelerator's module.to() restores a torch.device even if construction
    # used a string. Apply the upstream intended float32 guard at transfer time.
    MiniMaxH3Unit_PackedSequenceBuilder._to_device = staticmethod(packed_to_device)

    torch.manual_seed(42)
    torch.set_num_threads(8)
    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS GPU unavailable; no implicit CPU fallback")
    torch.mps.set_per_process_memory_fraction(0.75)
    spec = importlib.util.spec_from_file_location("upstream_h3_train", runtime / "examples/minimax_h3/model_training/train.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class PhotoSmoke(module.MiniMaxH3TrainingModule):
        def get_pipeline_inputs(self, data):
            data = dict(data)
            data["video"] = data["video"] * 5
            return super().get_pipeline_inputs(data)

    if stage == "cache":
        model_paths = [sorted(str(p) for p in (weights / "text_encoder").glob("model-*.safetensors")),
                       str(weights / "video_vae/source/model.safetensors"),
                       str(weights / "audio_vae/model.safetensors")]
    else:
        model_paths = [sorted(str(p) for p in (weights / "transformer").glob("*.safetensors"))]
    if not model_paths[0]:
        raise ValueError("Missing local model shards")
    args = module.minimax_h3_parser().parse_args([
        "--dataset_base_path", str(run if stage == "cache" else run / "cache"),
        "--task", "sft:data_process" if stage == "cache" else "sft:train",
        "--model_paths", json.dumps(model_paths),
        "--processor_path", str(weights / "text_encoder"),
        "--output_path", str(run / ("cache" if stage == "cache" else "adapter")),
        "--height", "256", "--width", "256", "--num_frames", "5",
        "--lora_base_model", "dit", "--lora_rank", "2",
        "--lora_target_modules", "attn.qkv_proj,attn.out_proj,mlp.fc1,mlp.fc2",
        "--use_gradient_checkpointing", "--learning_rate", "0.0001",
        "--num_epochs", "1", "--save_steps", "1", "--enable_csv_log",
        "--audio_loss_weight", "0", "--silent_on_missing_audio", "--extra_inputs", "input_audio",
    ])
    accelerator = accelerate.Accelerator()
    dataset = UnifiedDataset(
        base_path=args.dataset_base_path,
        metadata_path=str(run / "train.json") if stage == "cache" else None,
        data_file_keys=("video",),
        main_data_operator=UnifiedDataset.default_video_operator(height=256, width=256),
    )
    if stage == "train" and len(dataset) != 4:
        raise ValueError(f"Expected four cached training samples, got {len(dataset)}")
    model = PhotoSmoke(model_paths=args.model_paths, processor_path=args.processor_path,
                       lora_base_model="dit", lora_target_modules=args.lora_target_modules,
                       lora_rank=2, use_gradient_checkpointing=True, silent_on_missing_audio=True,
                       # Upstream H3 uses string comparisons for its MPS float32
                       # position-ID guard; torch.device('mps') bypasses that guard.
                       extra_inputs="input_audio", audio_loss_weight=0, device=str(accelerator.device),
                       task=args.task)
    logger = ModelLogger(args.output_path, remove_prefix_in_ckpt="pipe.dit.", enable_csv_log=True)
    launcher = launch_data_process_task if stage == "cache" else launch_training_task
    launcher(accelerator, dataset, model, logger, args=args)


def packed_to_device(packed, device):
    import torch
    result = {}
    for key, value in packed.items():
        if torch.is_tensor(value):
            if torch.device(device).type == "mps" and value.dtype == torch.float64:
                value = value.float()
            value = value.to(device)
        result[key] = value
    return result


def monitor(args) -> None:
    import psutil
    command = [sys.executable, __file__, "worker", "--runtime", str(args.runtime),
               "--run", str(args.run), "--weights", str(args.weights), "--stage", args.stage]
    report_path = args.run / f"{args.stage}-result.json"
    if report_path.exists():
        raise ValueError("Use a new run directory for a retry; preserve previous evidence")
    start, peak = time.monotonic(), 0
    reason = None
    with (args.run / f"{args.stage}.log").open("x") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
        try:
            while child.poll() is None:
                try:
                    rss = psutil.Process(child.pid).memory_info().rss
                    peak = max(peak, rss)
                    if rss > 90 * 1024**3 or psutil.virtual_memory().available < 12 * 1024**3:
                        reason = "memory safety reserve reached"
                    elif time.monotonic() - start > 1800:
                        reason = "30 minute stage limit reached"
                    if reason:
                        child.terminate()
                        break
                except psutil.NoSuchProcess:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            reason = "user cancellation"
            child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    report = {"stage": args.stage, "exit_code": child.returncode, "stop_reason": reason,
              "elapsed_seconds": round(time.monotonic() - start, 2), "peak_process_rss_bytes": peak,
              "measurement_note": "One-second process RSS samples, not total GPU memory",
              "runtime_revision": subprocess.check_output(
                  ["git", "-C", str(args.runtime), "rev-parse", "HEAD"], text=True).strip(),
              "packages": {name: importlib.metadata.version(name) for name in
                           ("torch", "transformers", "diffsynth", "accelerate", "peft")}}
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    sys.exit(0 if child.returncode == 0 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "worker"])
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--snapshot")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--stage", choices=["cache", "train"])
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.vault, args.run, args.snapshot)
    elif args.action == "worker":
        worker(args.runtime, args.run, args.weights, args.stage)
    else:
        monitor(args)
