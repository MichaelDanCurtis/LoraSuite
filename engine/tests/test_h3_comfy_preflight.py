import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/qualify_h3_comfy.py'
spec = importlib.util.spec_from_file_location('h3_comfy_qualifier', SCRIPT)
qualifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualifier)


def test_loader_hints_are_not_accepted_as_explicit_bindings():
    info = {'UNETLoader': {'input': {'required': {'unet_name': [['minimax_h3.safetensors']]}}}}
    report = qualifier.loader_report(info, {})
    assert not report['loader_bindings_present']
    assert report['bindings']['transformer']['candidate_hints'] == ['minimax_h3.safetensors']
    assert not report['bindings']['transformer']['listed_by_loader']
    assert any('Missing ComfyUI node' in blocker for blocker in report['blockers'])


def test_explicit_loader_bindings_require_exact_current_names():
    info = {name: {} for name in ['MiniMaxH3ReferenceToVideo', 'EmptyMiniMaxH3LatentAV', 'MiniMaxH3SigmaShift', 'LoraLoaderModelOnly']}
    selected = {}
    for role, (node, field) in qualifier.BINDINGS.items():
        selected[role] = role + '.safetensors'
        required = info.setdefault(node, {}).setdefault('input', {}).setdefault('required', {})
        required.setdefault(field, [[]])[0].append(selected[role])
    info['CLIPLoader']['input']['required']['type'] = [['minimax']]
    assert qualifier.loader_report(info, selected)['loader_bindings_present']
    selected['transformer'] = 'old-renamed-transformer.safetensors'
    report = qualifier.loader_report(info, selected)
    assert not report['loader_bindings_present']
    assert len(report['blockers']) == 1
    assert report['blockers'][0].startswith('transformer:')
