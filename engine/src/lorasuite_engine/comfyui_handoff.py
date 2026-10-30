from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request

from pydantic import BaseModel, Field

from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock


COMFY_HANDOFF_FORMAT = "lorasuite.comfy-handoff.v1"
COMFY_EXTENSION_VERSION = "0.1.0"
COMFY_EXTENSION_FILES = (
    "__init__.py",
    "nodes.py",
    "README.md",
    "pyproject.toml",
)
COMFY_REQUIRED_NODES = (
    "LoraSuiteArtifactInfo",
    "LoraSuiteArtifactLoader",
    "LoraSuiteArtifactLoaderModelOnly",
    "LoraSuiteEvaluationReport",
)


class ComfyCompatibilityCheck(BaseModel):
    check_id: str
    label: str
    status: Literal["passed", "warning", "blocked"]
    detail: str


class ComfyModelBinding(BaseModel):
    binding_id: str
    label: str
    model_directory: str
    required: bool = True
    selected_name: str | None = None
    candidates: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)


class ComfyWorkflowRecord(BaseModel):
    workflow_id: str
    label: str
    purpose: Literal["inference", "evaluation", "component"]
    path: Path
    runnable: bool = False
    required_nodes: list[str] = Field(default_factory=list)
    missing_bindings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComfyCompatibilityReport(BaseModel):
    status: Literal["ready", "review", "blocked"]
    model_family: str
    modality: str
    checks: list[ComfyCompatibilityCheck] = Field(default_factory=list)
    model_bindings: list[ComfyModelBinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ComfyHandoffManifest(BaseModel):
    format: Literal["lorasuite.comfy-handoff.v1"] = COMFY_HANDOFF_FORMAT
    contract_version: int = 1
    generated_at: Any = Field(default_factory=utc_now)
    artifact: dict[str, Any]
    inference: dict[str, Any]
    compatibility: ComfyCompatibilityReport
    workflows: list[ComfyWorkflowRecord] = Field(default_factory=list)
    extension: dict[str, Any]
    evaluation_report: dict[str, Any]


class ComfyRuntimeStatus(BaseModel):
    root: Path
    base_url: str
    reachable: bool = False
    extension_installed: bool = False
    extension_version: str | None = None
    required_nodes: list[str] = Field(default_factory=lambda: list(COMFY_REQUIRED_NODES))
    loaded_nodes: list[str] = Field(default_factory=list)
    missing_nodes: list[str] = Field(default_factory=lambda: list(COMFY_REQUIRED_NODES))
    restart_required: bool = False
    error: str | None = None
    checked_at: Any = Field(default_factory=utc_now)


class ComfyEvaluationReportRequest(BaseModel):
    artifact_id: str
    checkpoint_sha256: str
    workflow_id: str = ""
    verdict: Literal["pass", "review", "fail"] = "review"
    rating: int = Field(default=0, ge=0, le=5)
    prompt: str = ""
    seed: int | None = None
    output_paths: list[Path] = Field(default_factory=list)
    notes: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    comfy_root: Path | None = None


class ComfyEvaluationReport(ComfyEvaluationReportRequest):
    id: str = Field(default_factory=lambda: new_id("comfy_evaluation"))
    project_id: str = ""
    created_at: Any = Field(default_factory=utc_now)


class ComfyEvaluationReportService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def reports_path(self) -> Path:
        return self.vault_root / "comfyui_evaluation_reports.json"

    def list_reports(
        self,
        *,
        artifact_id: str | None = None,
        project_id: str | None = None,
    ) -> list[ComfyEvaluationReport]:
        reports = self._read_reports()
        return [
            report
            for report in sorted(reports, key=lambda item: item.created_at, reverse=True)
            if (artifact_id is None or report.artifact_id == artifact_id)
            and (project_id is None or report.project_id == project_id)
        ]

    def record(
        self,
        request: ComfyEvaluationReportRequest,
        *,
        project_id: str,
        expected_checkpoint_sha256: str,
    ) -> ComfyEvaluationReport:
        if request.checkpoint_sha256 != expected_checkpoint_sha256:
            raise ValueError("evaluation report checkpoint SHA-256 does not match the registered artifact")
        report = ComfyEvaluationReport(
            **request.model_dump(),
            project_id=project_id,
        )
        reports = self._read_reports()
        reports.append(report)
        self._write_reports(reports)
        return report

    def _read_reports(self) -> list[ComfyEvaluationReport]:
        with json_file_lock(self.reports_path):
            if not self.reports_path.exists():
                return []
            payload = json.loads(self.reports_path.read_text(encoding="utf-8"))
            return [
                ComfyEvaluationReport.model_validate(item)
                for item in payload.get("reports", [])
            ]

    def _write_reports(self, reports: list[ComfyEvaluationReport]) -> None:
        with json_file_lock(self.reports_path):
            atomic_write_json(
                self.reports_path,
                {
                    "version": 1,
                    "reports": [report.model_dump(mode="json") for report in reports],
                },
            )


def install_comfy_extension(comfy_root: Path) -> Path:
    source_root = Path(__file__).with_name("comfyui_extension")
    destination = Path(comfy_root) / "custom_nodes" / "LoraSuite"
    destination.mkdir(parents=True, exist_ok=True)
    for relative_name in COMFY_EXTENSION_FILES:
        source = source_root / relative_name
        if not source.is_file():
            raise ValueError(f"LoraSuite ComfyUI extension source is missing: {relative_name}")
        _atomic_copy(source, destination / relative_name)
    atomic_write_json(
        destination / "install.json",
        {
            "name": "LoraSuite",
            "version": COMFY_EXTENSION_VERSION,
            "contract": COMFY_HANDOFF_FORMAT,
            "installed_at": utc_now().isoformat(),
        },
    )
    return destination


def inspect_comfy_runtime(
    comfy_root: Path,
    *,
    base_url: str = "http://127.0.0.1:8188",
    timeout_seconds: float = 3.0,
) -> ComfyRuntimeStatus:
    root = Path(comfy_root).expanduser()
    extension_path = root / "custom_nodes" / "LoraSuite"
    install_path = extension_path / "install.json"
    extension_installed = install_path.is_file()
    extension_version = None
    if extension_installed:
        try:
            install_payload = json.loads(install_path.read_text(encoding="utf-8"))
            version = install_payload.get("version")
            if isinstance(version, str) and version.strip():
                extension_version = version.strip()
        except (OSError, ValueError, TypeError):
            extension_version = None

    normalized_url = base_url.strip().rstrip("/")
    status = ComfyRuntimeStatus(
        root=root,
        base_url=normalized_url,
        extension_installed=extension_installed,
        extension_version=extension_version,
    )
    if not normalized_url:
        status.error = "ComfyUI base URL is required."
        return status

    request = urllib_request.Request(
        f"{normalized_url}/object_info",
        headers={"Accept": "application/json", "User-Agent": "LoraSuite"},
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("ComfyUI /object_info did not return an object")
    except urllib_error.HTTPError as error:
        status.error = f"ComfyUI returned HTTP {error.code}."
        return status
    except urllib_error.URLError as error:
        reason = getattr(error, "reason", error)
        status.error = f"ComfyUI runtime is unreachable: {reason}"
        return status
    except (OSError, ValueError) as error:
        status.error = f"ComfyUI runtime probe failed: {error}"
        return status

    status.reachable = True
    status.loaded_nodes = [node for node in COMFY_REQUIRED_NODES if node in payload]
    status.missing_nodes = [node for node in COMFY_REQUIRED_NODES if node not in payload]
    status.restart_required = extension_installed and bool(status.missing_nodes)
    return status


def build_and_write_handoff(
    *,
    record: Any,
    installation: Any,
    checkpoint_path: Path,
    extension_path: Path,
    engine_url: str,
) -> tuple[ComfyHandoffManifest, Path]:
    workflows_dir = Path(installation.workflows_path) / "LoraSuite"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    inventory = _model_inventory(Path(installation.models_path))
    compatibility, workflow_specs = _compatibility_and_workflows(
        record=record,
        inventory=inventory,
        workflows_dir=workflows_dir,
        checkpoint_path=checkpoint_path,
    )
    workflow_records: list[ComfyWorkflowRecord] = []
    for workflow_record, payload in workflow_specs:
        atomic_write_json(workflow_record.path, payload)
        workflow_records.append(workflow_record)
    manifest = ComfyHandoffManifest(
        artifact={
            "id": record.id,
            "project_id": record.project_id,
            "training_run_id": record.training_run_id,
            "dataset_snapshot_id": record.snapshot_id,
            "dataset_fingerprint": record.dataset_fingerprint,
            "checkpoint_name": checkpoint_path.name,
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256": record.checkpoint_sha256,
            "modality": record.modality,
            "model_family": record.model_family,
            "base_model": record.base_model,
            "model_card": record.model_card.model_dump(mode="json")
            if record.model_card is not None
            else None,
        },
        inference={
            "trigger_token": record.trigger_token,
            "recommended_strength": _recommended_strength(record),
            "sample_prompts": _sample_prompts(record),
        },
        compatibility=compatibility,
        workflows=workflow_records,
        extension={
            "name": "LoraSuite",
            "version": COMFY_EXTENSION_VERSION,
            "path": str(extension_path),
            "required_nodes": list(COMFY_REQUIRED_NODES),
            "runtime_verified": False,
            "restart_required": None,
        },
        evaluation_report={
            "method": "POST",
            "url": f"{engine_url.rstrip('/')}/comfyui/evaluation-reports",
            "artifact_id": record.id,
            "checkpoint_sha256": record.checkpoint_sha256,
        },
    )
    handoff_path = checkpoint_path.with_suffix(
        checkpoint_path.suffix + ".lorasuite-handoff.json"
    )
    atomic_write_json(handoff_path, manifest.model_dump(mode="json"))
    return manifest, handoff_path


def preview_handoff(
    *,
    record: Any,
    installation: Any,
    engine_url: str,
) -> ComfyHandoffManifest:
    checkpoint_path = Path(installation.models_path) / "loras" / record.checkpoint_name
    extension_path = Path(installation.root) / "custom_nodes" / "LoraSuite"
    inventory = _model_inventory(Path(installation.models_path))
    compatibility, workflow_specs = _compatibility_and_workflows(
        record=record,
        inventory=inventory,
        workflows_dir=Path(installation.workflows_path) / "LoraSuite",
        checkpoint_path=checkpoint_path,
    )
    return ComfyHandoffManifest(
        artifact={
            "id": record.id,
            "project_id": record.project_id,
            "training_run_id": record.training_run_id,
            "dataset_snapshot_id": record.snapshot_id,
            "dataset_fingerprint": record.dataset_fingerprint,
            "checkpoint_name": checkpoint_path.name,
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256": record.checkpoint_sha256,
            "modality": record.modality,
            "model_family": record.model_family,
            "base_model": record.base_model,
            "model_card": record.model_card.model_dump(mode="json")
            if record.model_card is not None
            else None,
        },
        inference={
            "trigger_token": record.trigger_token,
            "recommended_strength": _recommended_strength(record),
            "sample_prompts": _sample_prompts(record),
        },
        compatibility=compatibility,
        workflows=[item for item, _payload in workflow_specs],
        extension={
            "name": "LoraSuite",
            "version": COMFY_EXTENSION_VERSION,
            "path": str(extension_path),
            "required_nodes": list(COMFY_REQUIRED_NODES),
            "installed": (extension_path / "install.json").is_file(),
            "runtime_verified": False,
            "restart_required": None,
        },
        evaluation_report={
            "method": "POST",
            "url": f"{engine_url.rstrip('/')}/comfyui/evaluation-reports",
            "artifact_id": record.id,
            "checkpoint_sha256": record.checkpoint_sha256,
        },
    )


def _compatibility_and_workflows(
    *,
    record: Any,
    inventory: dict[str, list[str]],
    workflows_dir: Path,
    checkpoint_path: Path,
) -> tuple[
    ComfyCompatibilityReport,
    list[tuple[ComfyWorkflowRecord, dict[str, Any]]],
]:
    checks = [
        ComfyCompatibilityCheck(
            check_id="artifact_modality",
            label="Artifact modality",
            status="passed" if record.modality in {"image", "video"} else "blocked",
            detail=(
                f"{record.modality} artifacts can be applied as ComfyUI LoRAs."
                if record.modality in {"image", "video"}
                else f"{record.modality} artifacts require a different runtime."
            ),
        ),
        ComfyCompatibilityCheck(
            check_id="checkpoint",
            label="Checkpoint",
            status="passed",
            detail=f"{checkpoint_path.name} will be installed with SHA-256 proof.",
        ),
        ComfyCompatibilityCheck(
            check_id="extension",
            label="LoraSuite nodes",
            status="passed",
            detail=f"LoraSuite ComfyUI extension {COMFY_EXTENSION_VERSION} will be installed.",
        ),
    ]
    workflow_specs: list[tuple[ComfyWorkflowRecord, dict[str, Any]]] = []
    bindings: list[ComfyModelBinding] = []
    warnings: list[str] = []

    component_path = workflows_dir / f"{checkpoint_path.stem}-loader.json"
    component = ComfyWorkflowRecord(
        workflow_id=f"lorasuite-loader-{record.id}",
        label="LoraSuite artifact loader",
        purpose="component",
        path=component_path,
        runnable=False,
        required_nodes=["LoraSuiteArtifactInfo", "LoraSuiteArtifactLoaderModelOnly"],
        warnings=["Connect the loader to a compatible base-model workflow before queueing."],
    )
    workflow_specs.append((component, _loader_component_workflow(record, checkpoint_path.name)))

    if record.modality == "image" and record.model_family == "flux1":
        bindings = _flux_bindings(inventory)
        missing = [binding.label for binding in bindings if binding.required and not binding.selected_name]
        workflow_path = workflows_dir / f"{checkpoint_path.stem}-flux-evaluation.json"
        runnable = not missing
        workflow = ComfyWorkflowRecord(
            workflow_id=f"lorasuite-flux-evaluation-{record.id}",
            label="FLUX baseline LoRA evaluation",
            purpose="evaluation",
            path=workflow_path,
            runnable=runnable,
            required_nodes=[
                "UNETLoader",
                "DualCLIPLoader",
                "VAELoader",
                "LoraSuiteArtifactLoaderModelOnly",
                "CLIPTextEncode",
                "FluxGuidance",
                "ConditioningZeroOut",
                "EmptySD3LatentImage",
                "KSampler",
                "VAEDecode",
                "SaveImage",
                "LoraSuiteEvaluationReport",
            ],
            missing_bindings=missing,
            warnings=[] if runnable else ["Select or install the missing FLUX base-model components."],
        )
        workflow_specs.append((workflow, _flux_evaluation_workflow(record, checkpoint_path.name, bindings)))
        checks.append(
            ComfyCompatibilityCheck(
                check_id="model_bindings",
                label="FLUX model bindings",
                status="passed" if runnable else "warning",
                detail=(
                    "All required FLUX diffusion, text encoder, and VAE files were detected."
                    if runnable
                    else f"Missing model bindings: {', '.join(missing)}."
                ),
            )
        )
    elif record.modality == "video" and record.model_family == "wan22_14b_t2v":
        bindings = _wan22_bindings(inventory)
        missing = [binding.label for binding in bindings if binding.required and not binding.selected_name]
        workflow_path = workflows_dir / f"{checkpoint_path.stem}-wan22-evaluation.json"
        runnable = not missing
        workflow = ComfyWorkflowRecord(
            workflow_id=f"lorasuite-wan22-evaluation-{record.id}",
            label="WAN 2.2 14B T2V LoRA evaluation",
            purpose="evaluation",
            path=workflow_path,
            runnable=runnable,
            required_nodes=[
                "UNETLoader",
                "CLIPLoader",
                "VAELoader",
                "LoraSuiteArtifactLoaderModelOnly",
                "ModelSamplingSD3",
                "CLIPTextEncode",
                "EmptyHunyuanLatentVideo",
                "KSamplerAdvanced",
                "VAEDecode",
                "CreateVideo",
                "SaveVideo",
                "LoraSuiteEvaluationReport",
            ],
            missing_bindings=missing,
            warnings=[] if runnable else ["Select or install the missing WAN 2.2 base-model components."],
        )
        workflow_specs.append((workflow, _wan22_evaluation_workflow(record, checkpoint_path.name, bindings)))
        checks.append(
            ComfyCompatibilityCheck(
                check_id="model_bindings",
                label="WAN 2.2 model bindings",
                status="passed" if runnable else "warning",
                detail=(
                    "Both WAN 2.2 experts, UMT5 encoder, and VAE were detected."
                    if runnable
                    else f"Missing model bindings: {', '.join(missing)}."
                ),
            )
        )
    else:
        warnings.append(
            f"Ready-to-run workflow generation is not yet qualified for {record.model_family}; "
            "the installed LoraSuite loader can be inserted into an existing compatible graph."
        )
        checks.append(
            ComfyCompatibilityCheck(
                check_id="target_workflow",
                label="Target workflow",
                status="warning",
                detail=warnings[-1],
            )
        )

    blocked = any(check.status == "blocked" for check in checks)
    review = any(check.status == "warning" for check in checks)
    return (
        ComfyCompatibilityReport(
            status="blocked" if blocked else "review" if review else "ready",
            model_family=record.model_family,
            modality=record.modality,
            checks=checks,
            model_bindings=bindings,
            warnings=warnings,
        ),
        workflow_specs,
    )


def _flux_bindings(inventory: dict[str, list[str]]) -> list[ComfyModelBinding]:
    return [
        _binding(
            "diffusion_model",
            "FLUX.1 Dev diffusion model",
            "diffusion_models",
            inventory.get("diffusion_models", []),
            [
                r"^(?!.*krea).*flux.?1.*dev",
                r"^(?!.*krea).*flux.*dev",
            ],
        ),
        _binding(
            "clip_l",
            "CLIP-L text encoder",
            "text_encoders",
            inventory.get("text_encoders", []),
            [r"(^|[/_-])clip.?l([/_.-]|$)"],
        ),
        _binding(
            "t5xxl",
            "T5 XXL text encoder",
            "text_encoders",
            inventory.get("text_encoders", []),
            [r"t5.*xxl", r"t5xxl"],
        ),
        _binding(
            "vae",
            "FLUX VAE",
            "vae",
            inventory.get("vae", []),
            [r"(^|/)ae\.(safetensors|sft|pt|pth)$", r"flux.*vae"],
        ),
    ]


def _wan22_bindings(inventory: dict[str, list[str]]) -> list[ComfyModelBinding]:
    return [
        _binding(
            "high_noise_model",
            "WAN 2.2 high-noise expert",
            "diffusion_models",
            inventory.get("diffusion_models", []),
            [r"wan.?2\.?2.*t2v.*high.?noise.*14b"],
        ),
        _binding(
            "low_noise_model",
            "WAN 2.2 low-noise expert",
            "diffusion_models",
            inventory.get("diffusion_models", []),
            [r"wan.?2\.?2.*t2v.*low.?noise.*14b"],
        ),
        _binding(
            "text_encoder",
            "WAN UMT5 XXL text encoder",
            "text_encoders",
            inventory.get("text_encoders", []),
            [r"umt5.*xxl"],
        ),
        _binding(
            "vae",
            "WAN 2.1 VAE",
            "vae",
            inventory.get("vae", []),
            [r"wan.?2\.?1.*vae", r"wan.*vae"],
        ),
    ]


def _binding(
    binding_id: str,
    label: str,
    model_directory: str,
    candidates: list[str],
    patterns: list[str],
) -> ComfyModelBinding:
    selected = next(
        (
            candidate
            for pattern in patterns
            for candidate in candidates
            if re.search(pattern, candidate, flags=re.IGNORECASE)
        ),
        None,
    )
    return ComfyModelBinding(
        binding_id=binding_id,
        label=label,
        model_directory=model_directory,
        selected_name=selected,
        candidates=candidates,
        patterns=patterns,
    )


def _model_inventory(models_path: Path) -> dict[str, list[str]]:
    aliases = {
        "diffusion_models": ("diffusion_models", "unet"),
        "text_encoders": ("text_encoders", "clip"),
        "vae": ("vae",),
        "checkpoints": ("checkpoints",),
    }
    inventory: dict[str, list[str]] = {}
    for category, directories in aliases.items():
        names: list[str] = []
        for directory_name in directories:
            root = models_path / directory_name
            if not root.is_dir():
                continue
            names.extend(
                str(path.relative_to(root))
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in {
                    ".safetensors",
                    ".sft",
                    ".ckpt",
                    ".pt",
                    ".pth",
                    ".bin",
                }
            )
        inventory[category] = sorted(dict.fromkeys(names))
    return inventory


def _loader_component_workflow(record: Any, lora_name: str) -> dict[str, Any]:
    prompt = _sample_prompts(record)[0]
    nodes = [
        _workflow_node(
            1,
            "LoraSuiteArtifactInfo",
            "LoraSuite Artifact",
            [lora_name],
            [80, 100],
            [],
            [
                _output("trigger_token", "STRING", [], 0),
                _output("sample_prompt", "STRING", [], 1),
                _output("artifact_id", "STRING", [], 2),
                _output("manifest_json", "STRING", [], 3),
            ],
            size=[320, 150],
        ),
    ]
    payload = _workflow_payload(record, nodes, [])
    payload["extra"]["lorasuite"]["instructions"] = (
        "Connect a compatible MODEL to LoraSuite Artifact Loader, then use "
        f"the trigger token in your prompt. Suggested prompt: {prompt}"
    )
    return payload


def _flux_evaluation_workflow(
    record: Any,
    lora_name: str,
    bindings: list[ComfyModelBinding],
) -> dict[str, Any]:
    selected = {binding.binding_id: binding.selected_name for binding in bindings}
    prompt = _sample_prompts(record)[0]
    workflow_id = f"lorasuite-flux-evaluation-{record.id}"
    nodes = [
        _workflow_node(1, "UNETLoader", "FLUX.1 Dev", [selected.get("diffusion_model") or "SELECT_FLUX1_DEV.safetensors", "default"], [40, 120], [], [_output("MODEL", "MODEL", [1], 0)], size=[300, 100]),
        _workflow_node(2, "DualCLIPLoader", "FLUX Text Encoders", [selected.get("clip_l") or "SELECT_CLIP_L.safetensors", selected.get("t5xxl") or "SELECT_T5XXL.safetensors", "flux", "default"], [40, 300], [], [_output("CLIP", "CLIP", [2], 0)], size=[320, 130]),
        _workflow_node(3, "VAELoader", "FLUX VAE", [selected.get("vae") or "SELECT_AE.safetensors"], [40, 500], [], [_output("VAE", "VAE", [11], 0)], size=[300, 80]),
        _workflow_node(4, "LoraSuiteArtifactLoaderModelOnly", "LoraSuite LoRA", [lora_name, _recommended_strength(record)], [400, 120], [_input("model", "MODEL", 1)], [_output("MODEL", "MODEL", [3], 0), _output("trigger_token", "STRING", [], 1), _output("sample_prompt", "STRING", [], 2), _output("artifact_id", "STRING", [], 3), _output("manifest_json", "STRING", [], 4)], size=[340, 180]),
        _workflow_node(5, "CLIPTextEncode", "Evaluation Prompt", [prompt], [400, 340], [_input("clip", "CLIP", 2)], [_output("CONDITIONING", "CONDITIONING", [4], 0)], size=[360, 170]),
        _workflow_node(6, "FluxGuidance", "Guidance", [3.5], [800, 330], [_input("conditioning", "CONDITIONING", 4)], [_output("CONDITIONING", "CONDITIONING", [5, 6], 0)], size=[250, 90]),
        _workflow_node(7, "ConditioningZeroOut", "Zero Negative", [], [800, 470], [_input("conditioning", "CONDITIONING", 6)], [_output("CONDITIONING", "CONDITIONING", [8], 0)], size=[250, 70]),
        _workflow_node(8, "EmptySD3LatentImage", "1024 Latent", [1024, 1024, 1], [800, 600], [], [_output("LATENT", "LATENT", [9], 0)], size=[260, 110]),
        _workflow_node(9, "KSampler", "Fixed Evaluation Seed", [123456789, "fixed", 24, 1.0, "euler", "simple", 1.0], [1110, 250], [_input("model", "MODEL", 3), _input("positive", "CONDITIONING", 5), _input("negative", "CONDITIONING", 8), _input("latent_image", "LATENT", 9)], [_output("LATENT", "LATENT", [10], 0)], size=[300, 290]),
        _workflow_node(10, "VAEDecode", "Decode", [], [1450, 300], [_input("samples", "LATENT", 10), _input("vae", "VAE", 11)], [_output("IMAGE", "IMAGE", [12], 0)], size=[220, 80]),
        _workflow_node(11, "SaveImage", "LoraSuite Evaluation", ["LoraSuite/evaluation", False], [1710, 300], [_input("images", "IMAGE", 12)], [_output("images", "IMAGE", [], 0)], size=[250, 100]),
        _workflow_node(12, "LoraSuiteEvaluationReport", "Return Evaluation", [workflow_id, "review", 0, prompt, 123456789, "", "", "http://127.0.0.1:8765", False], [1450, 520], [_input("manifest_json", "STRING", 13)], [_output("report_status", "STRING", [], 0)], size=[510, 300]),
    ]
    links = [
        [1, 1, 0, 4, 0, "MODEL"],
        [2, 2, 0, 5, 0, "CLIP"],
        [3, 4, 0, 9, 0, "MODEL"],
        [4, 5, 0, 6, 0, "CONDITIONING"],
        [5, 6, 0, 9, 1, "CONDITIONING"],
        [6, 6, 0, 7, 0, "CONDITIONING"],
        [8, 7, 0, 9, 2, "CONDITIONING"],
        [9, 8, 0, 9, 3, "LATENT"],
        [10, 9, 0, 10, 0, "LATENT"],
        [11, 3, 0, 10, 1, "VAE"],
        [12, 10, 0, 11, 0, "IMAGE"],
        [13, 4, 4, 12, 0, "STRING"],
    ]
    return _workflow_payload(record, nodes, links)


def _wan22_evaluation_workflow(
    record: Any,
    lora_name: str,
    bindings: list[ComfyModelBinding],
) -> dict[str, Any]:
    selected = {binding.binding_id: binding.selected_name for binding in bindings}
    prompt = _sample_prompts(record)[0]
    workflow_id = f"lorasuite-wan22-evaluation-{record.id}"
    negative = (
        "static, blurry, low quality, compression artifacts, distorted anatomy, "
        "identity drift, temporal flicker, subtitles, watermark"
    )
    nodes = [
        _workflow_node(1, "UNETLoader", "WAN High Noise", [selected.get("high_noise_model") or "SELECT_WAN22_HIGH_NOISE.safetensors", "default"], [40, 60], [], [_output("MODEL", "MODEL", [1], 0)], size=[330, 100]),
        _workflow_node(2, "UNETLoader", "WAN Low Noise", [selected.get("low_noise_model") or "SELECT_WAN22_LOW_NOISE.safetensors", "default"], [40, 210], [], [_output("MODEL", "MODEL", [2], 0)], size=[330, 100]),
        _workflow_node(3, "CLIPLoader", "WAN UMT5", [selected.get("text_encoder") or "SELECT_UMT5_XXL.safetensors", "wan", "default"], [40, 370], [], [_output("CLIP", "CLIP", [3, 4], 0)], size=[330, 110]),
        _workflow_node(4, "VAELoader", "WAN VAE", [selected.get("vae") or "SELECT_WAN_VAE.safetensors"], [40, 530], [], [_output("VAE", "VAE", [16], 0)], size=[330, 80]),
        _workflow_node(5, "LoraSuiteArtifactLoaderModelOnly", "LoRA High Expert", [lora_name, _recommended_strength(record)], [430, 60], [_input("model", "MODEL", 1)], [_output("MODEL", "MODEL", [5], 0), _output("trigger_token", "STRING", [], 1), _output("sample_prompt", "STRING", [], 2), _output("artifact_id", "STRING", [], 3), _output("manifest_json", "STRING", [19], 4)], size=[350, 180]),
        _workflow_node(6, "LoraSuiteArtifactLoaderModelOnly", "LoRA Low Expert", [lora_name, _recommended_strength(record)], [430, 260], [_input("model", "MODEL", 2)], [_output("MODEL", "MODEL", [6], 0), _output("trigger_token", "STRING", [], 1), _output("sample_prompt", "STRING", [], 2), _output("artifact_id", "STRING", [], 3), _output("manifest_json", "STRING", [], 4)], size=[350, 180]),
        _workflow_node(7, "ModelSamplingSD3", "High Expert Shift", [5.0], [830, 90], [_input("model", "MODEL", 5)], [_output("MODEL", "MODEL", [7], 0)], size=[250, 90]),
        _workflow_node(8, "ModelSamplingSD3", "Low Expert Shift", [5.0], [830, 280], [_input("model", "MODEL", 6)], [_output("MODEL", "MODEL", [8], 0)], size=[250, 90]),
        _workflow_node(9, "CLIPTextEncode", "Evaluation Prompt", [prompt], [430, 500], [_input("clip", "CLIP", 3)], [_output("CONDITIONING", "CONDITIONING", [9, 13], 0)], size=[430, 180]),
        _workflow_node(10, "CLIPTextEncode", "Negative", [negative], [430, 720], [_input("clip", "CLIP", 4)], [_output("CONDITIONING", "CONDITIONING", [10, 14], 0)], size=[430, 180]),
        _workflow_node(11, "EmptyHunyuanLatentVideo", "640 x 640 x 81", [640, 640, 81, 1], [900, 500], [], [_output("LATENT", "LATENT", [11], 0)], size=[300, 130]),
        _workflow_node(12, "KSamplerAdvanced", "High Noise 0-10", ["enable", 123456789, "fixed", 20, 3.5, "euler", "simple", 0, 10, "enable"], [1240, 80], [_input("model", "MODEL", 7), _input("positive", "CONDITIONING", 9), _input("negative", "CONDITIONING", 10), _input("latent_image", "LATENT", 11)], [_output("LATENT", "LATENT", [12], 0)], size=[330, 320]),
        _workflow_node(13, "KSamplerAdvanced", "Low Noise 10-20", ["disable", 0, "fixed", 20, 3.5, "euler", "simple", 10, 20, "disable"], [1620, 80], [_input("model", "MODEL", 8), _input("positive", "CONDITIONING", 13), _input("negative", "CONDITIONING", 14), _input("latent_image", "LATENT", 12)], [_output("LATENT", "LATENT", [15], 0)], size=[330, 320]),
        _workflow_node(14, "VAEDecode", "Decode Frames", [], [2010, 110], [_input("samples", "LATENT", 15), _input("vae", "VAE", 16)], [_output("IMAGE", "IMAGE", [17], 0)], size=[240, 80]),
        _workflow_node(15, "CreateVideo", "Create Video", [16], [2300, 100], [_input("images", "IMAGE", 17)], [_output("VIDEO", "VIDEO", [18], 0)], size=[260, 100]),
        _workflow_node(16, "SaveVideo", "LoraSuite WAN Evaluation", ["video/LoraSuite/evaluation", "auto", "auto"], [2600, 90], [_input("video", "VIDEO", 18)], [], size=[300, 120]),
        _workflow_node(17, "LoraSuiteEvaluationReport", "Return Evaluation", [workflow_id, "review", 0, prompt, 123456789, "", "", "http://127.0.0.1:8765", False], [2010, 360], [_input("manifest_json", "STRING", 19)], [_output("report_status", "STRING", [], 0)], size=[510, 300]),
    ]
    links = [
        [1, 1, 0, 5, 0, "MODEL"],
        [2, 2, 0, 6, 0, "MODEL"],
        [3, 3, 0, 9, 0, "CLIP"],
        [4, 3, 0, 10, 0, "CLIP"],
        [5, 5, 0, 7, 0, "MODEL"],
        [6, 6, 0, 8, 0, "MODEL"],
        [7, 7, 0, 12, 0, "MODEL"],
        [8, 8, 0, 13, 0, "MODEL"],
        [9, 9, 0, 12, 1, "CONDITIONING"],
        [10, 10, 0, 12, 2, "CONDITIONING"],
        [11, 11, 0, 12, 3, "LATENT"],
        [12, 12, 0, 13, 3, "LATENT"],
        [13, 9, 0, 13, 1, "CONDITIONING"],
        [14, 10, 0, 13, 2, "CONDITIONING"],
        [15, 13, 0, 14, 0, "LATENT"],
        [16, 4, 0, 14, 1, "VAE"],
        [17, 14, 0, 15, 0, "IMAGE"],
        [18, 15, 0, 16, 0, "VIDEO"],
        [19, 5, 4, 17, 0, "STRING"],
    ]
    return _workflow_payload(record, nodes, links)


def _workflow_payload(
    record: Any,
    nodes: list[dict[str, Any]],
    links: list[list[Any]],
) -> dict[str, Any]:
    return {
        "id": new_id("workflow"),
        "revision": 0,
        "last_node_id": max((int(node["id"]) for node in nodes), default=0),
        "last_link_id": max((int(link[0]) for link in links), default=0),
        "nodes": nodes,
        "links": links,
        "groups": [],
        "definitions": {"subgraphs": []},
        "config": {},
        "extra": {
            "ds": {"scale": 0.8, "offset": [0, 0]},
            "lorasuite": {
                "contract": COMFY_HANDOFF_FORMAT,
                "artifact_id": record.id,
                "dataset_fingerprint": record.dataset_fingerprint,
                "checkpoint_sha256": record.checkpoint_sha256,
            },
        },
        "version": 0.4,
    }


def _workflow_node(
    node_id: int,
    node_type: str,
    title: str,
    widgets: list[Any],
    pos: list[int],
    inputs: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
    *,
    size: list[int],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "pos": pos,
        "size": size,
        "flags": {},
        "order": node_id - 1,
        "mode": 0,
        "inputs": inputs,
        "outputs": outputs,
        "properties": {"Node name for S&R": node_type},
        "widgets_values": widgets,
        "title": title,
    }


def _input(name: str, input_type: str, link: int) -> dict[str, Any]:
    return {"name": name, "type": input_type, "link": link}


def _output(
    name: str,
    output_type: str,
    links: list[int],
    slot_index: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": output_type,
        "links": links,
        "slot_index": slot_index,
    }


def _recommended_strength(record: Any) -> float:
    if record.model_card is not None:
        value = record.model_card.usage.get("recommended_strength")
        if isinstance(value, (float, int)):
            return float(value)
    return 1.0


def _sample_prompts(record: Any) -> list[str]:
    if record.model_card is not None:
        values = record.model_card.usage.get("sample_prompts")
        if isinstance(values, list):
            prompts = [str(value).strip() for value in values if str(value).strip()]
            if prompts:
                return prompts
    token = record.trigger_token.strip()
    return [f"{token}, character portrait, natural expression".strip(", ")]


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
