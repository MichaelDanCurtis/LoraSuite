"""Check a real training checkpoint and register it in an explicit scratch vault."""
import argparse
import json
from pathlib import Path

import numpy as np

from lorasuite_engine.h3_lora import H3LoRAImport, H3LoRAService, SafeFile, adapter_pairs


def verify(checkpoint: Path, vault: Path, model_dir: Path, pilot_recipe: Path | None = None):
    source = SafeFile(checkpoint)
    pairs = adapter_pairs(source)
    nonzero_b = 0
    for name in source.tensors:
        values = source.read(name)  # Rejects nonfinite values.
        if ".lora_B." in name and np.count_nonzero(values):
            nonzero_b += 1
    if not nonzero_b:
        raise ValueError("No learned B-matrix updates; this is not a trained adapter")
    label = f"Example Subject H3 — {checkpoint.stem} SMOKE, quality unverified"
    provenance = f"Local DiffSynth H3 rank-2 appearance-only training; four approved photos, checkpoint {checkpoint.stem}. Not motion or voice training. Render quality unverified."
    if pilot_recipe:
        recipe = json.loads(pilot_recipe.read_text())
        if recipe.get("train_count") != 27 or recipe.get("rank") != 16 or recipe.get("heldout_uploaded") is not False:
            raise ValueError("Unexpected pilot recipe")
        label = f"Example Subject H3 — 27-photo pilot {checkpoint.stem}, quality unverified"
        provenance = f"RunPod DiffSynth H3 rank-16 face/body appearance pilot, 27 reviewed photos, checkpoint {checkpoint.stem}; recipe proposal SHA256 {recipe['proposal_sha256']}. Not motion or voice training; held-out quality evaluation pending."
    imported = H3LoRAService(vault).import_adapter(H3LoRAImport(
        path=str(checkpoint.resolve()), label=label,
        base_variant="Ref2VA", provenance=provenance,
    ), model_dir)
    report = {"checkpoint": str(checkpoint.resolve()), "bytes": checkpoint.stat().st_size,
              "target_pairs": len(pairs), "nonzero_b_matrices": nonzero_b,
              "all_values_finite": True, "import": imported,
              "quality": "unverified; requires held-out same-seed render comparison"}
    (vault / "trained-adapter-check.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--scratch-vault", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--pilot-recipe", type=Path)
    args = parser.parse_args()
    verify(args.checkpoint, args.scratch_vault, args.model_dir, args.pilot_recipe)
