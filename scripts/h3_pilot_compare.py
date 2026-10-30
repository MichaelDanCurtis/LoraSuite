"""Frozen local H3 pilot comparison; reuses native renderer and overlay cache.

Four clothed scenes, two seeds, duplicate baselines and checkpoints 100/300/500.
Creates review evidence, never auto-rates identity or changes original media.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from h3_cloud_pilot import digest, write_json
from lorasuite_engine.h3_lora import H3LoRAService, H3LoRAImport, cached_overlay

SCENES = [
    ("face", "example_person, the person in the reference image, wearing a plain navy crew-neck shirt. Eye-level face close-up in soft studio light, a gentle head turn, relaxed expression. Neutral gray studio background. Fixed camera, no zoom. Quiet room ambience, no speech."),
    ("upper", "example_person, the person in the reference image, wearing a plain fitted navy shirt. Waist-up daylight view, relaxed arms at her sides, standing naturally. Simple park background, even daylight. Fixed eye-level camera, no zoom. Gentle outdoor ambience, no speech."),
    ("front", "example_person, the person in the reference image, wearing a plain fitted navy shirt and straight-leg trousers. Full-length head-to-toe frontal view, neutral relaxed standing posture. Both feet fully visible with space above the head and below the shoes. Neutral studio background, even lighting. Fixed camera, no zoom. Quiet room ambience, no speech."),
    ("turn", "example_person, the person in the reference image, wearing a plain fitted burgundy T-shirt and straight-leg blue jeans. Full-length head-to-toe view, slowly turning from a three-quarter pose toward a side view. Both feet fully visible, no body occlusion. Simple studio, even lighting. Fixed camera, no zoom. Quiet room ambience, no speech."),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    args.executable = args.executable.resolve(strict=True)
    args.models = args.models.resolve(strict=True)
    run = args.run.resolve()
    output = run / "comparison"
    output.mkdir(exist_ok=True)
    proposal = json.loads(args.proposal.read_text())
    ref = proposal["heldout"][0]
    if digest(ref["path"]) != ref["sha256"]:
        raise ValueError("Held-out reference changed")
    reference = output / ("reference" + Path(ref["path"]).suffix)
    if not reference.exists():
        shutil.copyfile(ref["path"], reference)
    recipe = {"reference_sha256": ref["sha256"], "reference_media_id": ref["media_id"],
        "heldout_limitations": ref["coverage"]["limitations"], "proposal_sha256": digest(args.proposal),
        "renderer_sha256": digest(args.executable), "width": 256, "height": 384, "frames": 22,
        "steps": 6, "seeds": [714, 2718], "adapter_strength": 1.0,
        "conditions": ["baseline-a", "baseline-b", "step-100", "step-300", "step-500"],
        "scenes": [list(scene) for scene in SCENES], "status": "Short-preview screening; not final video quality proof",
        "limits": "No automated likeness rating. Same seed is not bitwise deterministic. Review visible face and body separately."}
    manifest = output / "protocol.json"
    if manifest.exists() and json.loads(manifest.read_text()) != recipe:
        raise ValueError("Frozen comparison settings changed; use a separate revision")
    write_json(manifest, recipe)
    service = H3LoRAService(output / "adapter-vault")
    for condition in recipe["conditions"]:
        overlay = None
        if condition.startswith("step-"):
            checkpoint = run / "received/package/adapter" / (condition + ".safetensors")
            complete = json.loads(checkpoint.with_suffix(".complete.json").read_text())
            if digest(checkpoint) != complete["sha256"]:
                raise ValueError("Checkpoint retrieval is incomplete")
            adapter = service.import_adapter(H3LoRAImport(path=str(checkpoint),
                label=f"Example Subject 27-photo pilot {condition}; evaluation pending", base_variant="Ref2VA",
                provenance="500-step bounded cloud pilot; face/body appearance, no motion/voice training"), args.models)
            overlay = cached_overlay([{**adapter, "strength": 1.0}], args.models, "Ref2VA", output / "overlay-cache", progress=print)
            write_json(output / (condition + "-overlay.json"), overlay)
        for scene, prompt in SCENES:
            for seed in recipe["seeds"]:
                name = f"{condition}-{scene}-{seed}"
                folder = output / name
                folder.mkdir(exist_ok=True)
                result_file = folder / "result.json"
                if result_file.exists() and json.loads(result_file.read_text()).get("verified_decode"):
                    continue
                if (folder / "render.log").exists():
                    raise ValueError("Incomplete previous attempt; explicit review before retry")
                write_json(output / "progress.json", {"condition": condition, "scene": scene, "seed": seed, "status": "rendering"})
                target = folder / "output.mp4"
                command = [str(args.executable), "-d", str(args.models), "-p", prompt,
                    "--width", "256", "--height", "384", "--frames", "22", "--steps", "6",
                    "--layers", "50", "--reuse", "1", "--seed", str(seed), "--profile",
                    "--ref-image", str(reference), "-o", str(target)]
                if overlay:
                    command += ["--lora-overlay", overlay["path"]]
                start = time.time()
                with (folder / "render.log").open("x") as log:
                    result = subprocess.run(["/usr/bin/time", "-l", *command], cwd=args.executable.parent,
                                            stdout=log, stderr=subprocess.STDOUT, timeout=900)
                if result.returncode:
                    raise RuntimeError(f"Native render failed: {name}; inspect its log")
                probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)]))
                subprocess.run(["ffmpeg", "-v", "error", "-i", str(target), "-f", "null", "-"], check=True, capture_output=True)
                write_json(result_file, {"condition": condition, "scene": scene, "seed": seed,
                    "elapsed_seconds": time.time() - start, "output_sha256": digest(target),
                    "verified_decode": True, "metadata": probe, "quality_rating": None})
                print(json.dumps({"completed": name, "elapsed_seconds": time.time() - start}), flush=True)
    write_json(output / "progress.json", {"status": "40 preview renders complete; human review required"})


if __name__ == "__main__":
    main()
