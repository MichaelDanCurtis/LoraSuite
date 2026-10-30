import json

from lorasuite_engine.runpod_infrastructure import (
    RunPodInfrastructureRequest,
    RunPodInfrastructureService,
)


class FakeInfrastructureProvider:
    def __init__(self, *, fail_endpoint: bool = False):
        self.fail_endpoint = fail_endpoint
        self.calls: list[tuple[str, dict]] = []

    def create_network_volume(self, payload):
        self.calls.append(("volume", payload))
        return {"id": "volume-1", **payload}

    def create_template(self, payload):
        self.calls.append(("template", payload))
        return {"id": "template-1", **payload}

    def create_endpoint(self, payload):
        self.calls.append(("endpoint", payload))
        if self.fail_endpoint:
            raise RuntimeError("endpoint capacity unavailable")
        return {"id": "endpoint-1", **payload}


def request(**updates):
    values = {
        "name": "LoraSuite Test",
        "image_name": "docker.io/example/lorasuite-worker:sha-123",
        "data_center_id": "US-KS-2",
        "runtime_environment": {"HF_TOKEN": "secret-hf-token"},
    }
    values.update(updates)
    return RunPodInfrastructureRequest(**values)


def test_provision_creates_volume_template_and_endpoint_without_persisting_secrets(tmp_path):
    provider = FakeInfrastructureProvider()
    service = RunPodInfrastructureService(
        tmp_path / "vault",
        provider_factory=lambda token: provider,
    )

    profile = service.provision(request(), "secret-runpod-token")

    assert profile.status == "ready"
    assert profile.network_volume_id == "volume-1"
    assert profile.template_id == "template-1"
    assert profile.endpoint_id == "endpoint-1"
    assert [name for name, _payload in provider.calls] == ["volume", "template", "endpoint"]
    assert provider.calls[1][1]["isServerless"] is True
    assert provider.calls[1][1]["env"] == {"HF_TOKEN": "secret-hf-token"}
    assert provider.calls[2][1]["networkVolumeId"] == "volume-1"
    persisted = service.profiles_path.read_text(encoding="utf-8")
    assert "secret-hf-token" not in persisted
    assert "secret-runpod-token" not in persisted


def test_failed_provision_can_resume_without_duplicate_billable_resources(tmp_path):
    failing = FakeInfrastructureProvider(fail_endpoint=True)
    service = RunPodInfrastructureService(
        tmp_path / "vault",
        provider_factory=lambda token: failing,
    )
    failed = service.provision(request(), "token")

    assert failed.status == "failed"
    assert failed.network_volume_id == "volume-1"
    assert failed.template_id == "template-1"
    assert failed.endpoint_id is None

    recovered = FakeInfrastructureProvider()
    service.provider_factory = lambda token: recovered
    resumed = service.provision(request(profile_id=failed.id), "token")

    assert resumed.status == "ready"
    assert resumed.endpoint_id == "endpoint-1"
    assert [name for name, _payload in recovered.calls] == ["endpoint"]


def test_existing_resource_ids_are_adopted_without_creation(tmp_path):
    provider = FakeInfrastructureProvider()
    service = RunPodInfrastructureService(
        tmp_path / "vault",
        provider_factory=lambda token: provider,
    )

    profile = service.provision(
        request(
            network_volume_id="existing-volume",
            template_id="existing-template",
            endpoint_id="existing-endpoint",
        ),
        "token",
    )

    assert profile.status == "ready"
    assert provider.calls == []
    payload = json.loads(service.profiles_path.read_text(encoding="utf-8"))
    assert payload["profiles"][0]["endpoint_id"] == "existing-endpoint"


def test_worker_minimum_cannot_exceed_maximum(tmp_path):
    service = RunPodInfrastructureService(tmp_path / "vault")
    try:
        service.provision(request(workers_min=2, workers_max=1), "token")
    except ValueError as error:
        assert "workers_min" in str(error)
    else:
        raise AssertionError("Expected invalid worker range to fail")
