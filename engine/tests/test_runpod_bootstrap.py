from lorasuite_engine.runpod_bootstrap import RunPodModelBootstrapService


class FakeProvider:
    def __init__(self):
        self.submissions = []
        self.status_payload = {"status": "IN_PROGRESS", "progress": "Downloading 1/3"}
        self.canceled = []

    def submit(self, endpoint_id, payload):
        self.submissions.append((endpoint_id, payload))
        return {"id": "bootstrap-job-1"}

    def run_sync(self, endpoint_id, payload):
        raise AssertionError("bootstrap must be asynchronous")

    def status(self, endpoint_id, job_id):
        return self.status_payload

    def cancel(self, endpoint_id, job_id):
        self.canceled.append((endpoint_id, job_id))
        return {"status": "CANCELLED"}


def test_bootstrap_run_submits_allowlisted_contract_and_tracks_progress(tmp_path):
    provider = FakeProvider()
    service = RunPodModelBootstrapService(tmp_path / "vault", provider_factory=lambda _token: provider)

    run = service.create_run(
        endpoint_id="endpoint-1",
        training_target_profile_id="runpod_id_lora_ltx23_inference",
    )
    submitted = service.submit_run(run.id, "session-token")
    running = service.refresh_run(run.id, "session-token")

    assert submitted.status == "in_queue"
    assert running.status == "running"
    assert running.progress_message == "Downloading 1/3"
    endpoint_id, payload = provider.submissions[0]
    assert endpoint_id == "endpoint-1"
    assert payload["input"] == {
        "action": "bootstrap_models",
        "bundle_format": "lorasuite-runpod-v1",
        "worker_contract_version": 1,
        "training_target_profile_id": "runpod_id_lora_ltx23_inference",
    }
    assert "session-token" not in service.runs_path.read_text(encoding="utf-8")


def test_bootstrap_completion_requires_exact_safe_model_contract(tmp_path):
    provider = FakeProvider()
    service = RunPodModelBootstrapService(tmp_path / "vault", provider_factory=lambda _token: provider)
    run = service.create_run(
        endpoint_id="endpoint-1",
        training_target_profile_id="runpod_fish_speech_s2_voice_lora",
    )
    service.submit_run(run.id, "token")
    provider.status_payload = {
        "status": "COMPLETED",
        "output": {
            "status": "success",
            "action": "bootstrap_models",
            "bundle_format": "lorasuite-runpod-v1",
            "worker_contract_version": 1,
            "training_target_profile_id": "runpod_fish_speech_s2_voice_lora",
            "required_paths": ["/runpod-volume/models/fish-speech-s2/codec.pth"],
            "manifest_path": "/runpod-volume/models/.lorasuite/runpod_fish_speech_s2_voice_lora.json",
            "reused": False,
        },
    }

    completed = service.refresh_run(run.id, "token")

    assert completed.status == "completed"
    assert completed.manifest_path.endswith(".json")
    assert completed.required_paths == ["/runpod-volume/models/fish-speech-s2/codec.pth"]


def test_bootstrap_rejects_mismatched_completion_paths(tmp_path):
    provider = FakeProvider()
    service = RunPodModelBootstrapService(tmp_path / "vault", provider_factory=lambda _token: provider)
    run = service.create_run(
        endpoint_id="endpoint-1",
        training_target_profile_id="runpod_fish_speech_s2_voice_lora",
    )
    service.submit_run(run.id, "token")
    provider.status_payload = {
        "status": "COMPLETED",
        "output": {
            "status": "success",
            "action": "bootstrap_models",
            "bundle_format": "lorasuite-runpod-v1",
            "worker_contract_version": 1,
            "training_target_profile_id": "runpod_fish_speech_s2_voice_lora",
            "required_paths": ["/runpod-volume/models/../escape"],
            "manifest_path": "/runpod-volume/models/.lorasuite/profile.json",
        },
    }

    failed = service.refresh_run(run.id, "token")

    assert failed.status == "failed"
    assert "unsafe" in (failed.error or "")


def test_bootstrap_rejects_profiles_without_validated_install_plan(tmp_path):
    service = RunPodModelBootstrapService(tmp_path / "vault")
    try:
        service.create_run(endpoint_id="endpoint-1", training_target_profile_id="runcomfy_flux1_dev_character")
    except ValueError as error:
        assert "does not support" in str(error)
    else:
        raise AssertionError("Expected unsupported bootstrap profile to fail")
