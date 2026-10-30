#!/usr/bin/env python3
"""Read-only H3 checkpoint/base and ComfyUI loader preflight.

Consumes a captured /object_info response. Never installs models, converts
weights, launches a server, submits a workflow, or claims render quality.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from lorasuite_engine.h3_lora import SafeFile, adapter_pairs, base_inventory
from lorasuite_engine.vault import sha256_file

BINDINGS = {
    'transformer': ('UNETLoader', 'unet_name'),
    'text_encoder': ('CLIPLoader', 'clip_name'),
    'video_vae': ('VAELoader', 'vae_name'),
    'audio_vae': ('VAELoader', 'vae_name'),
    'adapter': ('LoraLoaderModelOnly', 'lora_name'),
}


def loader_report(object_info, selected):
    blockers, bindings = [], {}
    required_nodes = ['MiniMaxH3ReferenceToVideo', 'EmptyMiniMaxH3LatentAV', 'MiniMaxH3SigmaShift', 'LoraLoaderModelOnly']
    for name in required_nodes:
        if name not in object_info:
            blockers.append(f'Missing ComfyUI node: {name}')
    for role, (node, field) in BINDINGS.items():
        value = object_info.get(node, {}).get('input', {}).get('required', {}).get(field, [])
        choices = value[0] if value and isinstance(value[0], list) else []
        name = selected.get(role)
        present = bool(name and name in choices)
        bindings[role] = {'selected': name, 'listed_by_loader': present, 'candidate_hints': [v for v in choices if any(term in v.lower() for term in ('minimax', 'h3', 'qwen3'))]}
        if not present:
            blockers.append(f'{role}: choose the exact compatible model listed by {node}; the selected binding is missing.')
    clip_types = object_info.get('CLIPLoader', {}).get('input', {}).get('required', {}).get('type', [[]])[0]
    if 'minimax' not in clip_types:
        blockers.append('CLIPLoader does not expose the minimax text-encoder type.')
    return {'bindings': bindings, 'blockers': blockers, 'loader_bindings_present': not blockers}


def qualify(checkpoint, model_dir, variant, object_info, selected):
    adapter = SafeFile(checkpoint)
    pairs = adapter_pairs(adapter)
    inventory, base_id = base_inventory(model_dir, variant)
    mismatched = [name for name, pair in pairs.items() if name + '.weight' not in inventory or inventory[name + '.weight'][1]['shape'] != pair['shape']]
    nonzero_b = 0
    for name in adapter.tensors:
        values = adapter.read(name)
        if '.lora_B.' in name and np.count_nonzero(values):
            nonzero_b += 1
    report = loader_report(object_info, selected)
    if mismatched:
        report['blockers'].append(f'{len(mismatched)} targets do not match the supplied base tensor shapes.')
    if not nonzero_b:
        report['blockers'].append('The adapter has no learned B-matrix updates.')
    report.update(checkpoint=str(checkpoint.resolve()), checkpoint_sha256=sha256_file(checkpoint), checkpoint_bytes=checkpoint.stat().st_size,
                  base_variant=variant, base_inventory_id=base_id, target_pairs=len(pairs), ranks=sorted({pair['rank'] for pair in pairs.values()}),
                  native_base_shapes_match=not mismatched, mismatched_targets=mismatched, all_adapter_values_finite=True, nonzero_b_matrices=nonzero_b,
                  runtime_render_verified=False, likeness_gain_verified=False, workflow_submitted=False,
                  qualification='structural_preflight_only', next_action='Bind the exact H3 transformer, minimax text encoder, both VAEs and adapter in ComfyUI; then run a recorded baseline/adapter comparison.')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--model-dir', required=True, type=Path)
    parser.add_argument('--variant', choices=['Ref2VA', 'FL2VA'], default='Ref2VA')
    parser.add_argument('--object-info', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    for role in BINDINGS:
        parser.add_argument('--' + role.replace('_', '-'))
    args = parser.parse_args()
    report = qualify(args.checkpoint, args.model_dir, args.variant, json.loads(args.object_info.read_text()), {role: getattr(args, role) for role in BINDINGS})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(2 if report['blockers'] else 0)
