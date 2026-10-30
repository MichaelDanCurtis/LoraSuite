from __future__ import annotations

import json
import os
import shutil
import ssl
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import certifi
from pydantic import BaseModel, Field

from lorasuite_engine.evaluation_harness import EvaluationHarnessService, default_benchmark_suite
from lorasuite_engine.image_evaluation import ImageEvaluationHarnessService, default_image_benchmark_suite
from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.runpod_runs import RunPodServerlessProvider
from lorasuite_engine.storage import atomic_write_json, json_file_lock


class BenchmarkGenerationItem(BaseModel):
    id: str
    case_id: str
    variant: Literal["baseline", "lora"]
    media_type: Literal["image", "video"] = "video"
    filename: str
    prompt: str
    seed: int
    status: Literal["queued", "in_queue", "running", "completed", "failed"] = "queued"
    request_id: str | None = None
    output_path: Path | None = None
    remote_url: str | None = None
    error: str | None = None


class BenchmarkGenerationRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("benchmark_generation"))
    provider: str = "runcomfy_model_api"
    benchmark_kind: Literal["audio_visual", "image"] = "audio_visual"
    endpoint_id: str | None = None
    project_id: str
    model_id: str
    lora_path: str
    artifact_id: str | None = None
    workspace_root: Path
    baseline_dir: Path
    lora_dir: Path
    baseline_payload: dict[str, Any] = Field(default_factory=dict)
    lora_payload: dict[str, Any] = Field(default_factory=dict)
    seed_base: int = 424242
    auto_evaluate: bool = True
    benchmark_run_id: str | None = None
    parent_run_id: str | None = None
    case_ids: list[str] = Field(default_factory=list)
    evaluation_error: str | None = None
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    progress_current: int = 0
    progress_total: int = 0
    progress_message: str = "Queued"
    items: list[BenchmarkGenerationItem] = Field(default_factory=list)
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class BenchmarkGenerationProvider(Protocol):
    def submit(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def status(self, request_id: str) -> dict[str, Any]: ...
    def result(self, request_id: str) -> dict[str, Any]: ...
    def download(self, url: str, destination: Path) -> None: ...


class RunComfyModelProvider:
    base_url = "https://model-api.runcomfy.net"

    def __init__(self, token: str):
        token = token.strip()
        if not token:
            raise ValueError("RunComfy API token is required")
        self.token = token
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def submit(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        encoded_model = quote(model_id.strip(), safe="/")
        return self._json("POST", f"/v1/models/{encoded_model}", payload)

    def status(self, request_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/requests/{quote(request_id, safe='')}/status")

    def result(self, request_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/requests/{quote(request_id, safe='')}/result")

    def download(self, url: str, destination: Path) -> None:
        request = Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urlopen(request, timeout=300, context=self.ssl_context) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.read())
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(_http_error(error)) from error

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}", data=body, method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=120, context=self.ssl_context) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(_http_error(error)) from error


class RunPodBenchmarkProvider:
    def __init__(self, token: str):
        self.token = token.strip()
        self.provider = RunPodServerlessProvider(self.token)
        self.endpoint_id = ""

    def submit(self, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.endpoint_id = endpoint_id.strip()
        if not self.endpoint_id:
            raise ValueError("RunPod Serverless endpoint ID is required")
        return self.provider.submit(self.endpoint_id, payload)

    def status(self, request_id: str) -> dict[str, Any]:
        return self.provider.status(self.endpoint_id, request_id)

    def result(self, request_id: str) -> dict[str, Any]:
        return self.provider.status(self.endpoint_id, request_id)

    def download(self, url: str, destination: Path) -> None:
        request = Request(url, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urlopen(request, timeout=300, context=self.provider.ssl_context) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.read())
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(_runpod_http_error(error)) from error


class BenchmarkGenerationService:
    def __init__(
        self,
        vault_root: Path,
        *,
        provider_factory: Callable[[str], BenchmarkGenerationProvider] = RunComfyModelProvider,
        runpod_provider_factory: Callable[[str], BenchmarkGenerationProvider] = RunPodBenchmarkProvider,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.vault_root = Path(vault_root)
        self.provider_factory = provider_factory
        self.runpod_provider_factory = runpod_provider_factory
        self.sleep = sleep

    @property
    def runs_path(self) -> Path:
        return self.vault_root / "benchmark_generation_runs.json"

    def list_runs(
        self,
        project_id: str | None = None,
        benchmark_kind: Literal["audio_visual", "image"] | None = None,
    ) -> list[BenchmarkGenerationRun]:
        runs = self._read().values()
        if project_id:
            runs = (run for run in runs if run.project_id == project_id)
        if benchmark_kind:
            runs = (run for run in runs if run.benchmark_kind == benchmark_kind)
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    def get_run(self, run_id: str) -> BenchmarkGenerationRun | None:
        return self._read().get(run_id)

    def create_run(
        self,
        *,
        project_id: str,
        model_id: str,
        lora_path: str,
        workspace_root: Path,
        provider: Literal["runcomfy_model_api", "runpod_serverless"] = "runcomfy_model_api",
        benchmark_kind: Literal["audio_visual", "image"] = "audio_visual",
        endpoint_id: str | None = None,
        artifact_id: str | None = None,
        baseline_payload: dict[str, Any] | None = None,
        lora_payload: dict[str, Any] | None = None,
        seed_base: int = 424242,
        auto_evaluate: bool = True,
        case_ids: list[str] | None = None,
        source_run: BenchmarkGenerationRun | None = None,
    ) -> BenchmarkGenerationRun:
        model_id = model_id.strip()
        lora_path = lora_path.strip()
        endpoint_id = (endpoint_id or "").strip() or None
        if provider == "runcomfy_model_api" and not model_id:
            raise ValueError("RunComfy Model API model id is required")
        if provider == "runpod_serverless" and not endpoint_id:
            raise ValueError("RunPod Serverless endpoint ID is required")
        if not lora_path:
            raise ValueError("LoRA asset name or public URL is required")
        if baseline_payload is not None:
            _validate_reproducible_template(baseline_payload)
        if lora_payload is not None:
            _validate_reproducible_template(lora_payload)
        if benchmark_kind == "image":
            workspace = ImageEvaluationHarnessService(self.vault_root).prepare_workspace(project_id, workspace_root)
            suite = default_image_benchmark_suite()
            media_type = "image"
        else:
            workspace = EvaluationHarnessService(self.vault_root).prepare_workspace(project_id, workspace_root)
            suite = default_benchmark_suite()
            media_type = "video"
        requested_case_ids = list(dict.fromkeys(case_ids or [definition.id for definition in suite]))
        known_case_ids = {definition.id for definition in suite}
        unknown = [case_id for case_id in requested_case_ids if case_id not in known_case_ids]
        if unknown:
            raise ValueError(f"unknown benchmark case: {unknown[0]}")
        if source_run and (source_run.project_id != project_id or source_run.benchmark_kind != benchmark_kind):
            raise ValueError("benchmark retry source does not match the project and evaluation mode")
        items: list[BenchmarkGenerationItem] = []
        for index, definition in enumerate(suite):
            prompt = definition.prompt.replace("{trigger}", _trigger_from_contract(workspace.contract_path))
            for variant in ("baseline", "lora"):
                key = f"{definition.id}:{variant}"
                items.append(BenchmarkGenerationItem(
                    id=key,
                    case_id=definition.id,
                    variant=variant,
                    media_type=media_type,
                    filename=definition.filename,
                    prompt=prompt,
                    seed=seed_base + index,
                ))
        if source_run:
            for item in items:
                if item.case_id in requested_case_ids:
                    continue
                source_item = next((candidate for candidate in source_run.items if candidate.id == item.id), None)
                if source_item is None or source_item.status != "completed" or not source_item.output_path or not source_item.output_path.is_file():
                    raise ValueError(f"cannot reuse missing benchmark output: {item.id}")
                destination = (workspace.baseline_dir if item.variant == "baseline" else workspace.lora_dir) / item.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_item.output_path, destination)
                item.status = "completed"
                item.output_path = destination
                item.remote_url = source_item.remote_url
        effective_baseline = baseline_payload or {}
        effective_lora = lora_payload or {}
        if provider == "runpod_serverless":
            effective_baseline = baseline_payload or {"input": {"prompt": "$PROMPT", "seed": "$SEED"}}
            effective_lora = lora_payload or {"input": {"prompt": "$PROMPT", "seed": "$SEED", "lora": {"path": "$LORA_PATH"}}}
        run = BenchmarkGenerationRun(
            provider=provider,
            benchmark_kind=benchmark_kind,
            endpoint_id=endpoint_id,
            project_id=project_id,
            model_id=model_id or endpoint_id or "",
            lora_path=lora_path,
            artifact_id=artifact_id,
            workspace_root=workspace.root,
            baseline_dir=workspace.baseline_dir,
            lora_dir=workspace.lora_dir,
            baseline_payload=effective_baseline,
            lora_payload=effective_lora,
            seed_base=seed_base,
            auto_evaluate=auto_evaluate,
            parent_run_id=source_run.id if source_run else None,
            case_ids=requested_case_ids,
            progress_current=sum(item.status == "completed" for item in items),
            progress_total=len(items),
            items=items,
        )
        runs = self._read()
        runs[run.id] = run
        self._write(runs)
        return run

    def create_retry_run(self, source_run_id: str, case_ids: list[str]) -> BenchmarkGenerationRun:
        source = self._require(source_run_id)
        if source.status != "completed":
            raise ValueError("benchmark generation must complete before targeted regeneration")
        if not case_ids:
            raise ValueError("select at least one benchmark case to regenerate")
        retry_root = source.workspace_root / "reruns" / new_id("retry")
        return self.create_run(
            project_id=source.project_id,
            model_id=source.model_id if source.provider == "runcomfy_model_api" else "",
            endpoint_id=source.endpoint_id,
            lora_path=source.lora_path,
            workspace_root=retry_root,
            provider=source.provider,
            benchmark_kind=source.benchmark_kind,
            artifact_id=source.artifact_id,
            baseline_payload=source.baseline_payload or None,
            lora_payload=source.lora_payload or None,
            seed_base=source.seed_base,
            auto_evaluate=source.auto_evaluate,
            case_ids=case_ids,
            source_run=source,
        )

    def process_run(self, run_id: str, token: str) -> BenchmarkGenerationRun:
        run = self._require(run_id)
        provider = self.runpod_provider_factory(token) if run.provider == "runpod_serverless" else self.provider_factory(token)
        run.status = "running"
        noun = "images" if run.benchmark_kind == "image" else "clips"
        run.progress_message = f"Generating matched baseline and LoRA {noun}"
        self._save(run)
        try:
            for item in run.items:
                if item.status == "completed" and item.output_path and item.output_path.is_file():
                    continue
                template = run.baseline_payload if item.variant == "baseline" else run.lora_payload
                payload = _generation_payload(template, item, run.lora_path, provider=run.provider)
                target_id = run.endpoint_id if run.provider == "runpod_serverless" else run.model_id
                submitted = provider.submit(target_id or "", payload)
                item.request_id = str(submitted.get("request_id") or submitted.get("id") or "")
                if not item.request_id:
                    raise RuntimeError(f"{_provider_label(run.provider)} did not return a request ID")
                item.status = "in_queue"
                self._save(run)
                result = self._wait_for_result(provider, run, item)
                output_url = _find_media_url(result, item.media_type)
                if not output_url:
                    raise RuntimeError(f"{_provider_label(run.provider)} result for {item.case_id} contained no {item.media_type} URL")
                destination = (run.baseline_dir if item.variant == "baseline" else run.lora_dir) / item.filename
                provider.download(output_url, destination)
                item.remote_url = output_url
                item.output_path = destination
                item.status = "completed"
                run.progress_current = sum(value.status == "completed" for value in run.items)
                run.progress_message = f"Generated {run.progress_current} of {run.progress_total} {noun}"
                self._save(run)
            run.status = "completed"
            run.progress_message = "Matched benchmark suite ready for evaluation"
            run.completed_at = utc_now()
            if run.auto_evaluate:
                evaluator = (
                    ImageEvaluationHarnessService(self.vault_root)
                    if run.benchmark_kind == "image"
                    else EvaluationHarnessService(self.vault_root)
                )
                try:
                    benchmark = evaluator.create_run(
                        project_id=run.project_id,
                        baseline_dir=run.baseline_dir,
                        lora_dir=run.lora_dir,
                        artifact_id=run.artifact_id,
                    )
                    run.benchmark_run_id = benchmark.id
                    self._save(run)
                    evaluated = evaluator.process_run(benchmark.id)
                    run.progress_message = (
                        "Generation and acceptance evaluation complete"
                        if evaluated.status == "complete"
                        else "Generation complete; acceptance evaluation needs attention"
                    )
                    run.evaluation_error = evaluated.error
                except (KeyError, OSError, ValueError) as error:
                    run.evaluation_error = str(error)
                    run.progress_message = "Generation complete; acceptance evaluation could not start"
        except Exception as error:
            failed = next((item for item in run.items if item.status not in {"completed"}), None)
            if failed:
                failed.status = "failed"
                failed.error = str(error)
            run.status = "failed"
            run.error = str(error)
            run.progress_message = "Benchmark generation failed"
            run.completed_at = utc_now()
        self._save(run)
        return run

    def _wait_for_result(self, provider, run, item) -> dict[str, Any]:
        for _ in range(720):
            payload = provider.status(item.request_id or "")
            status = str(payload.get("status") or "").lower()
            if status in {"completed", "complete", "succeeded", "success"}:
                return provider.result(item.request_id or "")
            if status in {"failed", "error", "canceled", "cancelled"}:
                raise RuntimeError(str(payload.get("error") or f"{_provider_label(run.provider)} generation {status}"))
            item.status = "running" if status in {"in_progress", "running", "processing"} else "in_queue"
            run.progress_message = f"{item.variant.title()} {item.case_id}: {status or 'queued'}"
            self._save(run)
            self.sleep(5)
        raise TimeoutError(f"{_provider_label(run.provider)} generation exceeded the one hour monitoring window")

    def _require(self, run_id: str) -> BenchmarkGenerationRun:
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _save(self, run: BenchmarkGenerationRun) -> None:
        run.updated_at = utc_now()
        runs = self._read()
        runs[run.id] = run
        self._write(runs)

    def _read(self) -> dict[str, BenchmarkGenerationRun]:
        with json_file_lock(self.runs_path):
            if not self.runs_path.exists():
                return {}
            payload = json.loads(self.runs_path.read_text(encoding="utf-8"))
            return {item["id"]: BenchmarkGenerationRun.model_validate(item) for item in payload.get("runs", [])}

    def _write(self, runs: dict[str, BenchmarkGenerationRun]) -> None:
        with json_file_lock(self.runs_path):
            atomic_write_json(self.runs_path, {"version": 1, "runs": [run.model_dump(mode="json") for run in runs.values()]})


def resolve_runcomfy_model_token(request_token: str | None) -> str:
    token = (request_token or os.environ.get("RUNCOMFY_TOKEN") or "").strip()
    if not token:
        raise ValueError("Enter a RunComfy token or set RUNCOMFY_TOKEN")
    return token


def _generation_payload(
    template: dict[str, Any],
    item: BenchmarkGenerationItem,
    lora_path: str,
    *,
    provider: str = "runcomfy_model_api",
) -> dict[str, Any]:
    payload = _replace_tokens(template, item.prompt, item.seed, lora_path)
    if not isinstance(payload, dict):
        raise ValueError("generation inputs must be a JSON object")
    if provider == "runpod_serverless":
        inputs = payload.get("input")
        if not isinstance(inputs, dict):
            raise ValueError("RunPod generation payload must contain an input object")
        inputs.setdefault("prompt", item.prompt)
        inputs.setdefault("seed", item.seed)
        if item.variant == "lora":
            inputs.setdefault("lora", {"path": lora_path})
    else:
        payload.setdefault("prompt", item.prompt)
        payload.setdefault("seed", item.seed)
        if item.variant == "lora":
            payload.setdefault("lora", {"path": lora_path})
    return payload


def _validate_reproducible_template(template: dict[str, Any]) -> None:
    serialized = json.dumps(template, sort_keys=True)
    if "$PROMPT" not in serialized or "$SEED" not in serialized:
        raise ValueError("custom generation payload must include $PROMPT and $SEED placeholders")


def _replace_tokens(value: Any, prompt: str, seed: int, lora_path: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_tokens(item, prompt, seed, lora_path) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_tokens(item, prompt, seed, lora_path) for item in value]
    if value == "$PROMPT":
        return prompt
    if value == "$SEED":
        return seed
    if value == "$LORA_PATH":
        return lora_path
    return value


def _find_media_url(payload: Any, media_type: Literal["image", "video"] = "video") -> str | None:
    suffixes = {".png", ".jpg", ".jpeg", ".webp", ".avif"} if media_type == "image" else {".mp4", ".mov", ".webm", ".mkv"}
    if isinstance(payload, str):
        parsed = urlparse(payload)
        if parsed.scheme in {"http", "https"} and Path(parsed.path).suffix.lower() in suffixes:
            return payload
        return None
    if isinstance(payload, dict):
        preferred = (("image_url", "images") if media_type == "image" else ("video_url", "videos")) + ("url", "path", "output", "outputs", "result", "files")
        for key in preferred:
            if key in payload and (found := _find_media_url(payload[key], media_type)):
                return found
        for value in payload.values():
            if found := _find_media_url(value, media_type):
                return found
    if isinstance(payload, list):
        for value in payload:
            if found := _find_media_url(value, media_type):
                return found
    return None


def _trigger_from_contract(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload.get("trigger_token") or "trigger_token")


def _http_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            detail = error.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return f"RunComfy Model API HTTP {error.code}: {detail or error.reason}"
    return f"RunComfy Model API request failed: {error}"


def _runpod_http_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            detail = error.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return f"RunPod output download HTTP {error.code}: {detail or error.reason}"
    return f"RunPod output download failed: {error}"


def _provider_label(provider: str) -> str:
    return "RunPod Serverless" if provider == "runpod_serverless" else "RunComfy Model API"
