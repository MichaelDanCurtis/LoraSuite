from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lorasuite_engine.dataset_analysis import DatasetImageAnalyzer
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.identity_engine import SFaceIdentityEngine, anchor_similarity
from lorasuite_engine.identity_models import IdentityModelService
from lorasuite_engine.model_registry import ModelRegistryService
from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService


class ImageBenchmarkCaseDefinition(BaseModel):
    id: str
    label: str
    filename: str
    prompt: str
    composition: Literal["face", "upper_body", "full_body", "any"] = "any"


class ImageBenchmarkMetrics(BaseModel):
    visual_quality: float
    aesthetic_score: float
    subject_coverage: float
    face_count: int
    face_area: float
    body_coverage: float
    pose_coverage: float
    identity_similarity: float | None = None
    analyzer_notes: list[str] = Field(default_factory=list)


class ImageBenchmarkCaseResult(BaseModel):
    definition: ImageBenchmarkCaseDefinition
    baseline_path: Path
    lora_path: Path
    baseline: ImageBenchmarkMetrics
    lora: ImageBenchmarkMetrics
    passed: bool
    blocked: bool
    checks: dict[str, bool | None]
    reasons: list[str] = Field(default_factory=list)


class ImageBenchmarkSummary(BaseModel):
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    identity_gain: float | None = None
    average_lora_identity: float | None = None
    average_visual_quality: float = 0.0
    average_subject_coverage: float = 0.0
    screening_ready: bool = False
    release_ready: bool = False
    warnings: list[str] = Field(default_factory=list)


class ImageBenchmarkRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("image_benchmark"))
    project_id: str
    artifact_id: str | None = None
    baseline_dir: Path
    lora_dir: Path
    status: Literal["queued", "running", "complete", "failed"] = "queued"
    cases: dict[str, ImageBenchmarkCaseResult] = Field(default_factory=dict)
    summary: ImageBenchmarkSummary = Field(default_factory=ImageBenchmarkSummary)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class ImageBenchmarkWorkspace(BaseModel):
    project_id: str
    root: Path
    baseline_dir: Path
    lora_dir: Path
    contract_path: Path
    cases: list[ImageBenchmarkCaseDefinition]


def default_image_benchmark_suite() -> list[ImageBenchmarkCaseDefinition]:
    return [
        ImageBenchmarkCaseDefinition(
            id="neutral_closeup",
            label="Neutral close-up",
            filename="neutral_closeup.png",
            prompt="{trigger}, close-up portrait, neutral expression, front view, natural daylight, plain background",
            composition="face",
        ),
        ImageBenchmarkCaseDefinition(
            id="three_quarter",
            label="Three-quarter identity",
            filename="three_quarter.png",
            prompt="{trigger}, three-quarter portrait, looking away from camera, soft studio light",
            composition="face",
        ),
        ImageBenchmarkCaseDefinition(
            id="full_body",
            label="Full-body identity",
            filename="full_body.png",
            prompt="{trigger}, full body standing naturally, simple casual clothing, outdoor setting",
            composition="full_body",
        ),
        ImageBenchmarkCaseDefinition(
            id="expression",
            label="Expression control",
            filename="expression.png",
            prompt="{trigger}, upper-body portrait, broad natural smile, candid moment, warm indoor light",
            composition="upper_body",
        ),
        ImageBenchmarkCaseDefinition(
            id="difficult_light",
            label="Difficult lighting",
            filename="difficult_light.png",
            prompt="{trigger}, cinematic portrait, strong side lighting, deep shadows, detailed face",
            composition="face",
        ),
        ImageBenchmarkCaseDefinition(
            id="wardrobe_separation",
            label="Wardrobe separation",
            filename="wardrobe_separation.png",
            prompt="{trigger}, upper-body portrait, wearing a plain blue jacket, neutral background, natural expression",
            composition="upper_body",
        ),
    ]


ImageAnalyzer = Callable[[Path, str, ImageBenchmarkCaseDefinition, str], ImageBenchmarkMetrics]


class ImageEvaluationHarnessService:
    def __init__(self, vault_root: Path, *, analyzer: ImageAnalyzer | None = None):
        self.vault_root = Path(vault_root)
        self.analyzer = analyzer or self._analyze
        self._identity_engines: dict[str, tuple[SFaceIdentityEngine, list[Any]]] = {}

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "image_benchmark_runs.json"

    def list_runs(self, project_id: str | None = None) -> list[ImageBenchmarkRun]:
        runs = self._read().values()
        if project_id:
            runs = (run for run in runs if run.project_id == project_id)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> ImageBenchmarkRun | None:
        return self._read().get(run_id)

    def prepare_workspace(self, project_id: str, output_dir: Path) -> ImageBenchmarkWorkspace:
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        root = Path(output_dir).expanduser().resolve(strict=False)
        baseline_dir = root / "baseline"
        lora_dir = root / "lora"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        lora_dir.mkdir(parents=True, exist_ok=True)
        cases = default_image_benchmark_suite()
        expanded = []
        for definition in cases:
            prompt = definition.prompt.replace("{trigger}", project.intent.trigger_token or "trigger_token")
            expanded.append({**definition.model_dump(mode="json"), "prompt": prompt})
            for directory in (baseline_dir, lora_dir):
                (directory / f"{Path(definition.filename).stem}.prompt.txt").write_text(
                    prompt.rstrip() + "\n",
                    encoding="utf-8",
                )
        contract_path = root / "image_evaluation_contract.json"
        contract_path.write_text(json.dumps({
            "created_by": "LoraSuite",
            "format": "image-evaluation-v1",
            "project_id": project.id,
            "trigger_token": project.intent.trigger_token,
            "instructions": "Generate every named image twice with identical seeds and settings: base model, then LoRA.",
            "baseline_dir": str(baseline_dir),
            "lora_dir": str(lora_dir),
            "cases": expanded,
        }, indent=2) + "\n", encoding="utf-8")
        return ImageBenchmarkWorkspace(
            project_id=project.id,
            root=root,
            baseline_dir=baseline_dir,
            lora_dir=lora_dir,
            contract_path=contract_path,
            cases=cases,
        )

    def create_run(
        self,
        *,
        project_id: str,
        baseline_dir: Path,
        lora_dir: Path,
        artifact_id: str | None = None,
    ) -> ImageBenchmarkRun:
        if CharacterProjectService(self.vault_root).get_project(project_id) is None:
            raise KeyError(project_id)
        if artifact_id:
            artifact = ModelRegistryService(self.vault_root).get_artifact(artifact_id)
            if artifact is None:
                raise ValueError("model artifact is not registered")
            if artifact.project_id and artifact.project_id != project_id:
                raise ValueError("model artifact belongs to a different character project")
            if artifact.modality != "image":
                raise ValueError("still-image evaluation requires an image LoRA artifact")
        baseline_dir = Path(baseline_dir).expanduser().resolve(strict=False)
        lora_dir = Path(lora_dir).expanduser().resolve(strict=False)
        for definition in default_image_benchmark_suite():
            for directory, label in ((baseline_dir, "baseline"), (lora_dir, "LoRA")):
                path = directory / definition.filename
                if not path.is_file():
                    raise ValueError(f"{label} benchmark image is missing: {path}")
        run = ImageBenchmarkRun(
            project_id=project_id,
            artifact_id=artifact_id,
            baseline_dir=baseline_dir,
            lora_dir=lora_dir,
        )
        runs = self._read()
        runs[run.id] = run
        self._write(runs)
        return run

    def process_run(self, run_id: str) -> ImageBenchmarkRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        run.status = "running"
        run.error = None
        run.updated_at = utc_now()
        self._save(run)
        registry = ModelRegistryService(self.vault_root)
        if run.artifact_id:
            registry.begin_acceptance(run.artifact_id, run.id)
        try:
            results = {}
            for definition in default_image_benchmark_suite():
                baseline_path = run.baseline_dir / definition.filename
                lora_path = run.lora_dir / definition.filename
                baseline = self.analyzer(baseline_path, "baseline", definition, run.project_id)
                lora = self.analyzer(lora_path, "lora", definition, run.project_id)
                results[definition.id] = _compare(definition, baseline_path, lora_path, baseline, lora)
            run.cases = results
            run.summary = _summarize(results)
            run.status = "complete"
            run.completed_at = utc_now()
            if run.artifact_id:
                registry.record_acceptance(
                    run.artifact_id,
                    run.id,
                    screening_ready=run.summary.screening_ready,
                    release_ready=run.summary.release_ready,
                    passed_count=run.summary.passed_count,
                    failed_count=run.summary.failed_count,
                    blocked_count=run.summary.blocked_count,
                    identity_similarity=run.summary.average_lora_identity,
                    visual_quality=run.summary.average_visual_quality,
                    subject_coverage=run.summary.average_subject_coverage,
                    warnings=run.summary.warnings,
                )
        except Exception as error:
            run.status = "failed"
            run.error = str(error)
            run.completed_at = utc_now()
            if run.artifact_id:
                registry.record_acceptance(run.artifact_id, run.id, error=run.error)
        run.updated_at = utc_now()
        self._save(run)
        return run

    def _analyze(
        self,
        path: Path,
        _variant: str,
        _definition: ImageBenchmarkCaseDefinition,
        project_id: str,
    ) -> ImageBenchmarkMetrics:
        evidence = DatasetImageAnalyzer().analyze(path)
        notes = []
        identity_similarity = None
        face_count = evidence.face_count
        face_area = evidence.face_area
        identity = self._identity_engine(project_id, notes)
        if identity is not None:
            engine, anchors = identity
            faces = engine.analyze(path)
            face_count = max(face_count, len(faces))
            if faces:
                face_area = max(face_area, max(face.face.bounding_box.width * face.face.bounding_box.height for face in faces))
                scores = [anchor_similarity(face.embedding, anchors) for face in faces]
                valid = [score for score in scores if score is not None]
                identity_similarity = max(valid) if valid else None
        subject_coverage = max(
            min(1.0, face_area / 0.10),
            min(1.0, evidence.body_coverage / 0.30),
            evidence.pose_coverage,
        )
        return ImageBenchmarkMetrics(
            visual_quality=evidence.quality_score,
            aesthetic_score=evidence.aesthetic_score,
            subject_coverage=subject_coverage,
            face_count=face_count,
            face_area=face_area,
            body_coverage=evidence.body_coverage,
            pose_coverage=evidence.pose_coverage,
            identity_similarity=identity_similarity,
            analyzer_notes=notes,
        )

    def _identity_engine(self, project_id: str, notes: list[str]):
        if project_id in self._identity_engines:
            return self._identity_engines[project_id]
        project = CharacterProjectService(self.vault_root).get_project(project_id)
        models = IdentityModelService(self.vault_root)
        if project is None or not models.status().ready:
            notes.append("face identity model or project anchors are unavailable")
            return None
        engine = SFaceIdentityEngine(models.paths)
        media = {item.id: item for item in VaultService(self.vault_root).list_media_items()}
        anchors = []
        for media_id, observation in project.observations.items():
            if not observation.is_anchor or media_id not in media:
                continue
            faces = engine.analyze(media[media_id].raw_path)
            if faces:
                selected = next((face for face in faces if face.face.index == observation.selected_face_index), faces[0])
                anchors.append(selected.embedding)
        if not anchors:
            notes.append("no usable visual identity anchors are available")
            return None
        self._identity_engines[project_id] = (engine, anchors)
        return self._identity_engines[project_id]

    def _read(self) -> dict[str, ImageBenchmarkRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            return {item["id"]: ImageBenchmarkRun.model_validate(item) for item in payload.get("runs", [])}

    def _save(self, run: ImageBenchmarkRun) -> None:
        runs = self._read()
        runs[run.id] = run
        self._write(runs)

    def _write(self, runs: dict[str, ImageBenchmarkRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {"version": 1, "runs": [run.model_dump(mode="json") for run in runs.values()]})


def _compare(definition, baseline_path, lora_path, baseline, lora) -> ImageBenchmarkCaseResult:
    composition_check = lora.subject_coverage >= 0.25
    if definition.composition == "face":
        composition_check = lora.face_count >= 1 and lora.face_area >= 0.025
    elif definition.composition == "full_body":
        composition_check = lora.body_coverage >= 0.12 or lora.pose_coverage >= 0.22
    checks: dict[str, bool | None] = {
        "visual_quality": lora.visual_quality >= 0.38,
        "aesthetic_quality": lora.aesthetic_score >= 0.28,
        "composition": composition_check,
        "identity_similarity": None if lora.identity_similarity is None else lora.identity_similarity >= 0.45,
        "identity_gain": None if lora.identity_similarity is None or baseline.identity_similarity is None else lora.identity_similarity - baseline.identity_similarity >= 0.02,
    }
    blocked = any(value is None for value in checks.values())
    failed = [name for name, value in checks.items() if value is False]
    return ImageBenchmarkCaseResult(
        definition=definition,
        baseline_path=baseline_path,
        lora_path=lora_path,
        baseline=baseline,
        lora=lora,
        passed=not blocked and not failed,
        blocked=blocked,
        checks=checks,
        reasons=[*(f"failed {name.replace('_', ' ')}" for name in failed), *lora.analyzer_notes],
    )


def _summarize(results: dict[str, ImageBenchmarkCaseResult]) -> ImageBenchmarkSummary:
    values = list(results.values())
    lora_identity = [item.lora.identity_similarity for item in values if item.lora.identity_similarity is not None]
    base_identity = [item.baseline.identity_similarity for item in values if item.baseline.identity_similarity is not None]
    blocked = sum(item.blocked for item in values)
    failed = sum(not item.blocked and not item.passed for item in values)
    screening_ready = bool(values) and all(item.passed for item in values)
    warnings = []
    if blocked:
        warnings.append("Install the face identity models and select trusted visual anchors to resolve blocked identity checks.")
    return ImageBenchmarkSummary(
        passed_count=sum(item.passed for item in values),
        failed_count=failed,
        blocked_count=blocked,
        identity_gain=_mean(lora_identity) - _mean(base_identity) if lora_identity and base_identity else None,
        average_lora_identity=_mean(lora_identity) if lora_identity else None,
        average_visual_quality=_mean([item.lora.visual_quality for item in values]),
        average_subject_coverage=_mean([item.lora.subject_coverage for item in values]),
        screening_ready=screening_ready,
        release_ready=screening_ready,
        warnings=warnings,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / max(1, len(values))
