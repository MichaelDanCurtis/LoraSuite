import hashlib
import io
import json
import sys
import types
from pathlib import Path
from urllib.error import URLError

import pytest

from lorasuite_engine.comfyui_handoff import (
    COMFY_REQUIRED_NODES,
    ComfyEvaluationReportRequest,
    ComfyEvaluationReportService,
    _flux_bindings,
    inspect_comfy_runtime,
)
from lorasuite_engine.comfyui_extension import nodes


def test_records_comfy_evaluation_with_checkpoint_provenance(tmp_path):
    service = ComfyEvaluationReportService(tmp_path / "vault")
    request = ComfyEvaluationReportRequest(
        artifact_id="artifact-1",
        checkpoint_sha256="checkpoint-sha",
        workflow_id="workflow-1",
        verdict="pass",
        rating=5,
        prompt="person_token, portrait",
        seed=42,
        output_paths=[tmp_path / "output.png"],
        metrics={"identity_similarity": 0.91},
    )

    report = service.record(
        request,
        project_id="project-1",
        expected_checkpoint_sha256="checkpoint-sha",
    )

    assert report.project_id == "project-1"
    assert report.verdict == "pass"
    restored = service.list_reports(artifact_id="artifact-1")
    assert [item.id for item in restored] == [report.id]
    assert restored[0].metrics == {"identity_similarity": 0.91}
    assert service.list_reports(project_id="other-project") == []
    payload = json.loads(service.reports_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["reports"][0]["checkpoint_sha256"] == "checkpoint-sha"


def test_rejects_comfy_evaluation_for_different_checkpoint(tmp_path):
    service = ComfyEvaluationReportService(tmp_path / "vault")

    with pytest.raises(ValueError, match="SHA-256"):
        service.record(
            ComfyEvaluationReportRequest(
                artifact_id="artifact-1",
                checkpoint_sha256="wrong",
            ),
            project_id="project-1",
            expected_checkpoint_sha256="expected",
        )


def test_flux_binding_does_not_substitute_krea_for_flux1_dev():
    bindings = {
        binding.binding_id: binding
        for binding in _flux_bindings({
            "diffusion_models": [
                "Flux1-Krea-dev_fp8_scaled.safetensors",
                "Krea2_turbo_bf16.safetensors",
            ],
            "text_encoders": [
                "clip_l.safetensors",
                "t5xxl_fp16.safetensors",
            ],
            "vae": ["ae.safetensors"],
        })
    }

    assert bindings["diffusion_model"].selected_name is None
    assert bindings["diffusion_model"].candidates == [
        "Flux1-Krea-dev_fp8_scaled.safetensors",
        "Krea2_turbo_bf16.safetensors",
    ]
    assert bindings["clip_l"].selected_name == "clip_l.safetensors"
    assert bindings["t5xxl"].selected_name == "t5xxl_fp16.safetensors"
    assert bindings["vae"].selected_name == "ae.safetensors"


def test_runtime_status_requires_restart_when_installed_nodes_are_not_loaded(tmp_path, monkeypatch):
    install_path = tmp_path / "ComfyUI" / "custom_nodes" / "LoraSuite" / "install.json"
    install_path.parent.mkdir(parents=True)
    install_path.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    monkeypatch.setattr(
        "lorasuite_engine.comfyui_handoff.urllib_request.urlopen",
        lambda *_args, **_kwargs: _JsonResponse({"KSampler": {}}),
    )

    status = inspect_comfy_runtime(tmp_path / "ComfyUI")

    assert status.reachable is True
    assert status.extension_installed is True
    assert status.extension_version == "0.1.0"
    assert status.loaded_nodes == []
    assert status.missing_nodes == list(COMFY_REQUIRED_NODES)
    assert status.restart_required is True
    assert status.error is None


def test_runtime_status_reports_loaded_nodes_without_restart(tmp_path, monkeypatch):
    install_path = tmp_path / "ComfyUI" / "custom_nodes" / "LoraSuite" / "install.json"
    install_path.parent.mkdir(parents=True)
    install_path.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    monkeypatch.setattr(
        "lorasuite_engine.comfyui_handoff.urllib_request.urlopen",
        lambda *_args, **_kwargs: _JsonResponse({
            node: {"display_name": node}
            for node in COMFY_REQUIRED_NODES
        }),
    )

    status = inspect_comfy_runtime(tmp_path / "ComfyUI")

    assert status.reachable is True
    assert status.loaded_nodes == list(COMFY_REQUIRED_NODES)
    assert status.missing_nodes == []
    assert status.restart_required is False


def test_runtime_status_reports_unreachable_without_guessing_restart(tmp_path, monkeypatch):
    install_path = tmp_path / "ComfyUI" / "custom_nodes" / "LoraSuite" / "install.json"
    install_path.parent.mkdir(parents=True)
    install_path.write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")

    def fail(*_args, **_kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr(
        "lorasuite_engine.comfyui_handoff.urllib_request.urlopen",
        fail,
    )

    status = inspect_comfy_runtime(tmp_path / "ComfyUI")

    assert status.reachable is False
    assert status.extension_installed is True
    assert status.restart_required is False
    assert status.error == "ComfyUI runtime is unreachable: connection refused"


def test_extension_discovers_manifest_and_loads_registered_lora(tmp_path, monkeypatch):
    lora_path = tmp_path / "models" / "loras" / "person.safetensors"
    lora_path.parent.mkdir(parents=True)
    lora_path.write_bytes(b"lora")
    checkpoint_sha = hashlib.sha256(lora_path.read_bytes()).hexdigest()
    lora_path.with_suffix(".safetensors.lorasuite-handoff.json").write_text(
        json.dumps(
            {
                "format": "lorasuite.comfy-handoff.v1",
                "artifact": {
                    "id": "artifact-1",
                    "checkpoint_sha256": checkpoint_sha,
                },
                "inference": {
                    "trigger_token": "person_token",
                    "sample_prompts": ["person_token, portrait"],
                },
                "evaluation_report": {},
            }
        ),
        encoding="utf-8",
    )

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = lambda category: ["person.safetensors"]
    folder_paths.get_full_path_or_raise = lambda category, name: str(lora_path)
    comfy = types.ModuleType("comfy")
    comfy_sd = types.ModuleType("comfy.sd")
    comfy_utils = types.ModuleType("comfy.utils")
    comfy_utils.load_torch_file = lambda *args, **kwargs: ({"weight": 1}, {"meta": 1})
    comfy_sd.load_lora_for_models = (
        lambda model, clip, lora, strength_model, strength_clip, lora_metadata=None:
        (f"{model}+lora", f"{clip}+lora")
    )
    comfy.sd = comfy_sd
    comfy.utils = comfy_utils
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths)
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.sd", comfy_sd)
    monkeypatch.setitem(sys.modules, "comfy.utils", comfy_utils)

    assert nodes._artifact_choices() == ["person.safetensors"]
    assert nodes.LoraSuiteArtifactInfo().describe("person.safetensors")[:3] == (
        "person_token",
        "person_token, portrait",
        "artifact-1",
    )
    loaded = nodes.LoraSuiteArtifactLoader().load(
        "model",
        "clip",
        "person.safetensors",
        1.0,
        1.0,
    )
    assert loaded[:5] == (
        "model+lora",
        "clip+lora",
        "person_token",
        "person_token, portrait",
        "artifact-1",
    )

    lora_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        nodes.LoraSuiteArtifactInfo().describe("person.safetensors")


class _JsonResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
