from __future__ import annotations

import json
import os
import ssl
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
from pydantic import BaseModel, Field

from lorasuite_engine.models import new_id, utc_now
from lorasuite_engine.storage import atomic_write_json, json_file_lock


InfrastructureStatus = Literal["draft", "provisioning", "ready", "failed"]


class RunPodInfrastructureProfile(BaseModel):
    id: str = Field(default_factory=lambda: new_id("runpod_infrastructure"))
    provider: Literal["runpod"] = "runpod"
    name: str
    image_name: str
    data_center_id: str
    network_volume_id: str | None = None
    network_volume_name: str
    network_volume_size_gb: int = 500
    template_id: str | None = None
    template_name: str
    container_disk_gb: int = 50
    endpoint_id: str | None = None
    endpoint_name: str
    gpu_type_ids: list[str] = Field(default_factory=lambda: ["NVIDIA H100 80GB HBM3"])
    workers_min: int = 0
    workers_max: int = 1
    idle_timeout_seconds: int = 5
    execution_timeout_ms: int = 86_400_000
    status: InfrastructureStatus = "draft"
    progress_message: str = "Ready to provision"
    error: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)
    completed_at: Any | None = None


class RunPodInfrastructureRequest(BaseModel):
    profile_id: str | None = None
    name: str = "LoraSuite Training"
    image_name: str
    data_center_id: str
    network_volume_id: str | None = None
    network_volume_name: str = "lorasuite-models"
    network_volume_size_gb: int = Field(default=500, ge=1, le=4000)
    template_id: str | None = None
    template_name: str = "LoraSuite Serverless Worker"
    container_disk_gb: int = Field(default=50, ge=10, le=1000)
    endpoint_id: str | None = None
    endpoint_name: str = "LoraSuite Training"
    gpu_type_ids: list[str] = Field(default_factory=lambda: ["NVIDIA H100 80GB HBM3"], min_length=1)
    workers_min: int = Field(default=0, ge=0)
    workers_max: int = Field(default=1, ge=1)
    idle_timeout_seconds: int = Field(default=5, ge=1, le=3600)
    execution_timeout_ms: int = Field(default=86_400_000, ge=60_000)
    runtime_environment: dict[str, str] = Field(default_factory=dict)


class RunPodInfrastructureProvider(Protocol):
    def create_network_volume(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def create_endpoint(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class RunPodRestProvider:
    base_url = "https://rest.runpod.io/v1"

    def __init__(self, token: str):
        token = token.strip()
        if not token:
            raise ValueError("RunPod API token is required")
        self.token = token
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def create_network_volume(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/networkvolumes", payload)

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/templates", payload)

    def create_endpoint(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/endpoints", payload)

    def _json(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=120, context=self.ssl_context) as response:
                raw = response.read()
                value = json.loads(raw) if raw else {}
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(_http_error(error)) from error
        if not isinstance(value, dict):
            raise RuntimeError("RunPod returned a non-object response")
        return value


class RunPodInfrastructureService:
    def __init__(
        self,
        vault_root: Path,
        *,
        provider_factory: Callable[[str], RunPodInfrastructureProvider] = RunPodRestProvider,
    ):
        self.vault_root = Path(vault_root)
        self.provider_factory = provider_factory

    @property
    def profiles_path(self) -> Path:
        return self.vault_root / "runpod_infrastructure_profiles.json"

    def list_profiles(self) -> list[RunPodInfrastructureProfile]:
        return sorted(self._read_profiles().values(), key=lambda item: item.updated_at, reverse=True)

    def get_profile(self, profile_id: str) -> RunPodInfrastructureProfile | None:
        return self._read_profiles().get(profile_id)

    def provision(
        self,
        request: RunPodInfrastructureRequest,
        token: str,
    ) -> RunPodInfrastructureProfile:
        provider = self.provider_factory(token)
        profile = self._profile_for_request(request)
        profile.status = "provisioning"
        profile.error = None
        self._save(profile, "Provisioning RunPod infrastructure")
        try:
            if not profile.network_volume_id:
                created = provider.create_network_volume({
                    "dataCenterId": profile.data_center_id,
                    "name": profile.network_volume_name,
                    "size": profile.network_volume_size_gb,
                })
                profile.network_volume_id = _required_id(created, "network volume")
                self._save(profile, "Network volume ready; creating Serverless template")

            if not profile.template_id:
                created = provider.create_template({
                    "imageName": profile.image_name,
                    "name": profile.template_name,
                    "category": "NVIDIA",
                    "containerDiskInGb": profile.container_disk_gb,
                    "dockerEntrypoint": [],
                    "dockerStartCmd": [],
                    "env": _clean_environment(request.runtime_environment),
                    "isPublic": False,
                    "isServerless": True,
                    "ports": [],
                    "readme": "LoraSuite versioned training and ID-LoRA worker.",
                    "volumeInGb": 0,
                    "volumeMountPath": "/runpod-volume",
                })
                profile.template_id = _required_id(created, "Serverless template")
                self._save(profile, "Serverless template ready; creating endpoint")

            if not profile.endpoint_id:
                created = provider.create_endpoint({
                    "templateId": profile.template_id,
                    "computeType": "GPU",
                    "dataCenterIds": [profile.data_center_id],
                    "executionTimeoutMs": profile.execution_timeout_ms,
                    "flashboot": True,
                    "gpuCount": 1,
                    "gpuTypeIds": profile.gpu_type_ids,
                    "idleTimeout": profile.idle_timeout_seconds,
                    "minCudaVersion": "12.8",
                    "name": profile.endpoint_name,
                    "networkVolumeId": profile.network_volume_id,
                    "networkVolumeIds": [profile.network_volume_id],
                    "scalerType": "QUEUE_DELAY",
                    "scalerValue": 4,
                    "workersMax": profile.workers_max,
                    "workersMin": profile.workers_min,
                })
                profile.endpoint_id = _required_id(created, "Serverless endpoint")

            profile.status = "ready"
            profile.progress_message = "RunPod volume, worker template, and endpoint are ready"
            profile.completed_at = utc_now()
            return self._save(profile)
        except Exception as error:
            profile.status = "failed"
            profile.error = str(error)
            profile.progress_message = "RunPod infrastructure provisioning failed"
            self._save(profile)
            return profile

    def _profile_for_request(self, request: RunPodInfrastructureRequest) -> RunPodInfrastructureProfile:
        if request.workers_min > request.workers_max:
            raise ValueError("workers_min cannot exceed workers_max")
        if request.profile_id:
            profile = self.get_profile(request.profile_id)
            if profile is None:
                raise KeyError(request.profile_id)
            return profile
        profile = RunPodInfrastructureProfile(
            name=_required_text(request.name, "profile name"),
            image_name=_required_text(request.image_name, "worker image"),
            data_center_id=_required_text(request.data_center_id, "data center"),
            network_volume_id=_optional_text(request.network_volume_id),
            network_volume_name=_required_text(request.network_volume_name, "network volume name"),
            network_volume_size_gb=request.network_volume_size_gb,
            template_id=_optional_text(request.template_id),
            template_name=_required_text(request.template_name, "template name"),
            container_disk_gb=request.container_disk_gb,
            endpoint_id=_optional_text(request.endpoint_id),
            endpoint_name=_required_text(request.endpoint_name, "endpoint name"),
            gpu_type_ids=[_required_text(value, "GPU type") for value in request.gpu_type_ids],
            workers_min=request.workers_min,
            workers_max=request.workers_max,
            idle_timeout_seconds=request.idle_timeout_seconds,
            execution_timeout_ms=request.execution_timeout_ms,
        )
        return profile

    def _save(
        self,
        profile: RunPodInfrastructureProfile,
        message: str | None = None,
    ) -> RunPodInfrastructureProfile:
        profiles = self._read_profiles()
        if message is not None:
            profile.progress_message = message
        profile.updated_at = utc_now()
        profiles[profile.id] = profile
        with json_file_lock(self.profiles_path):
            atomic_write_json(
                self.profiles_path,
                {"version": 1, "profiles": [item.model_dump(mode="json") for item in profiles.values()]},
            )
        return profile

    def _read_profiles(self) -> dict[str, RunPodInfrastructureProfile]:
        with json_file_lock(self.profiles_path):
            if not self.profiles_path.exists():
                return {}
            payload = json.loads(self.profiles_path.read_text(encoding="utf-8"))
            return {
                item["id"]: RunPodInfrastructureProfile.model_validate(item)
                for item in payload.get("profiles", [])
            }


def resolve_runpod_infrastructure_token(request_token: str | None) -> str:
    token = (request_token or os.environ.get("RUNPOD_API_KEY") or "").strip()
    if not token:
        raise ValueError("Enter a RunPod API key or set RUNPOD_API_KEY")
    return token


def _required_id(payload: dict[str, Any], label: str) -> str:
    value = str(payload.get("id") or "").strip()
    if not value:
        raise RuntimeError(f"RunPod did not return a {label} id")
    return value


def _clean_environment(values: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in values.items():
        name = key.strip()
        secret = value.strip()
        if not name or not secret:
            continue
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            raise ValueError(f"Invalid environment variable name: {key}")
        cleaned[name] = secret
    return cleaned


def _required_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _http_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        try:
            body = error.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        return f"RunPod infrastructure request failed with HTTP {error.code}: {body[:1000] or error.reason}"
    return f"RunPod infrastructure request failed: {error}"
