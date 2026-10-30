from pathlib import Path

from PIL import Image

from lorasuite_engine.benchmark_generation import BenchmarkGenerationService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.evaluation_harness import EvaluationHarnessService
from lorasuite_engine.models import TrainingIntent


class FakeProvider:
    def __init__(self):
        self.submissions = []

    def submit(self, model_id, payload):
        self.submissions.append((model_id, payload))
        return {"request_id": f"request-{len(self.submissions)}"}

    def status(self, request_id):
        return {"request_id": request_id, "status": "completed"}

    def result(self, request_id):
        return {"outputs": [{"video_url": f"https://outputs.test/{request_id}.mp4"}]}

    def download(self, url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(url.encode("utf-8"))


class FakeRunPodProvider(FakeProvider):
    def status(self, request_id):
        return {
            "id": request_id,
            "status": "COMPLETED",
            "output": {"video_url": f"https://outputs.test/{request_id}.mp4"},
        }

    def result(self, request_id):
        return self.status(request_id)


class FakeImageProvider(FakeProvider):
    def result(self, request_id):
        return {"outputs": [{"image_url": f"https://outputs.test/{request_id}.png"}]}

    def download(self, _url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "green").save(destination)


class FakeRunPodImageProvider(FakeRunPodProvider):
    def status(self, request_id):
        return {
            "id": request_id,
            "status": "COMPLETED",
            "output": {"image_url": f"https://outputs.test/{request_id}.png"},
        }

    def download(self, _url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "blue").save(destination)


def test_generates_matched_baseline_and_lora_benchmark_clips(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="mary_token"),
    )
    provider = FakeProvider()
    service = BenchmarkGenerationService(
        vault_root,
        provider_factory=lambda _token: provider,
        sleep=lambda _seconds: None,
    )

    queued = service.create_run(
        project_id=project.id,
        workspace_root=tmp_path / "evaluation",
        model_id="runcomfy/video-model",
        lora_path="mary-video-lora.safetensors",
        seed_base=100,
    )
    completed = service.process_run(queued.id, "session-token")

    assert completed.status == "completed"
    assert completed.progress_current == 8
    assert len(provider.submissions) == 8
    assert provider.submissions[0] == (
        "runcomfy/video-model",
        {
            "prompt": "mary_token, close-up portrait, natural expression, subtle head movement, steady camera",
            "seed": 100,
        },
    )
    assert provider.submissions[1][1]["seed"] == 100
    assert provider.submissions[1][1]["lora"] == {"path": "mary-video-lora.safetensors"}
    assert all(item.output_path and item.output_path.is_file() for item in completed.items)
    assert completed.benchmark_run_id is not None
    assert EvaluationHarnessService(vault_root).get_run(completed.benchmark_run_id).status == "failed"
    assert service.get_run(queued.id).status == "completed"


def test_regenerates_one_matched_case_and_reuses_the_other_outputs(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(intent=TrainingIntent(trigger_token="retry_person"))
    provider = FakeProvider()
    service = BenchmarkGenerationService(vault_root, provider_factory=lambda _token: provider, sleep=lambda _seconds: None)
    source = service.create_run(
        project_id=project.id,
        workspace_root=tmp_path / "evaluation",
        model_id="runcomfy/video-model",
        lora_path="person.safetensors",
        auto_evaluate=False,
    )
    source = service.process_run(source.id, "session-token")
    original_closeup = next(item for item in source.items if item.id == "identity_closeup:lora")

    retry = service.create_retry_run(source.id, ["camera_motion"])

    assert retry.parent_run_id == source.id
    assert retry.case_ids == ["camera_motion"]
    assert retry.progress_current == 6
    assert sum(item.status == "queued" for item in retry.items) == 2
    reused_closeup = next(item for item in retry.items if item.id == "identity_closeup:lora")
    assert reused_closeup.output_path.read_bytes() == original_closeup.output_path.read_bytes()

    completed = service.process_run(retry.id, "session-token")
    assert completed.status == "completed"
    assert completed.progress_current == 8
    assert len(provider.submissions) == 10


def test_rejects_generation_templates_without_reproducible_placeholders(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project()
    service = BenchmarkGenerationService(vault_root)

    try:
        service.create_run(
            project_id=project.id,
            workspace_root=tmp_path / "evaluation",
            model_id="video-model",
            lora_path="identity.safetensors",
            baseline_payload={"prompt": "$PROMPT"},
        )
    except ValueError as error:
        assert "$PROMPT and $SEED" in str(error)
    else:
        raise AssertionError("Expected missing seed placeholder to fail")


def test_generates_the_same_matched_suite_through_runpod_serverless(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="runpod_person"),
    )
    provider = FakeRunPodProvider()
    service = BenchmarkGenerationService(
        vault_root,
        runpod_provider_factory=lambda _token: provider,
        sleep=lambda _seconds: None,
    )

    queued = service.create_run(
        project_id=project.id,
        workspace_root=tmp_path / "evaluation",
        model_id="",
        endpoint_id="endpoint-video-1",
        lora_path="https://assets.test/person.safetensors",
        provider="runpod_serverless",
        seed_base=200,
        auto_evaluate=False,
    )
    completed = service.process_run(queued.id, "runpod-secret")

    assert completed.status == "completed"
    assert completed.provider == "runpod_serverless"
    assert completed.endpoint_id == "endpoint-video-1"
    assert completed.progress_current == 8
    assert provider.submissions[0] == (
        "endpoint-video-1",
        {
            "input": {
                "prompt": "runpod_person, close-up portrait, natural expression, subtle head movement, steady camera",
                "seed": 200,
            },
        },
    )
    assert provider.submissions[1][1]["input"]["lora"] == {
        "path": "https://assets.test/person.safetensors",
    }
    assert all(item.output_path and item.output_path.is_file() for item in completed.items)


def test_generates_matched_image_suite_through_both_cloud_providers(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    project = CharacterProjectService(vault_root).create_project(
        intent=TrainingIntent(trigger_token="image_person"),
    )
    runcomfy = FakeImageProvider()
    runpod = FakeRunPodImageProvider()
    service = BenchmarkGenerationService(
        vault_root,
        provider_factory=lambda _token: runcomfy,
        runpod_provider_factory=lambda _token: runpod,
        sleep=lambda _seconds: None,
    )

    runcomfy_run = service.create_run(
        project_id=project.id,
        workspace_root=tmp_path / "runcomfy-image-evaluation",
        model_id="provider/image-model",
        lora_path="person.safetensors",
        benchmark_kind="image",
        auto_evaluate=False,
    )
    runcomfy_completed = service.process_run(runcomfy_run.id, "runcomfy-secret")
    runpod_run = service.create_run(
        project_id=project.id,
        workspace_root=tmp_path / "runpod-image-evaluation",
        model_id="",
        endpoint_id="endpoint-image-1",
        lora_path="https://assets.test/person.safetensors",
        provider="runpod_serverless",
        benchmark_kind="image",
        auto_evaluate=False,
    )
    runpod_completed = service.process_run(runpod_run.id, "runpod-secret")

    assert runcomfy_completed.status == "completed"
    assert runpod_completed.status == "completed"
    assert len(runcomfy.submissions) == 12
    assert len(runpod.submissions) == 12
    assert all(item.media_type == "image" for item in runcomfy_completed.items)
    assert all(item.output_path and item.output_path.suffix == ".png" for item in runpod_completed.items)
    assert len(service.list_runs(project.id, "image")) == 2
    assert service.list_runs(project.id, "audio_visual") == []
