from types import SimpleNamespace

from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.provider_readiness import ProviderReadinessService, _bundle_state, _runcomfy_item, _runpod_source_item, _id_lora_item
from lorasuite_engine.runpod_bundle import RunPodBundle
from lorasuite_engine.runpod_runs import RunPodPreflightCheck, RunPodPreflightReport, RunPodTrainingRun


def test_empty_project_reports_all_provider_handoff_blockers(tmp_path) -> None:
    vault = tmp_path / "vault"
    project = CharacterProjectService(vault).create_project(name="Provider Matrix")

    matrix = ProviderReadinessService(vault).status(project.id)

    assert matrix.total_count == 6
    assert matrix.ready_count == 0
    assert {(item.lane, item.provider) for item in matrix.items} == {
        ("image", "runcomfy"), ("image", "runpod"),
        ("video", "runcomfy"), ("video", "runpod"),
        ("voice", "runpod"), ("id_lora", "runpod"),
    }
    assert all(item.state == "blocked" for item in matrix.items)


def test_runcomfy_progresses_from_export_to_registered_artifact(tmp_path) -> None:
    snapshot = SimpleNamespace(id="snapshot-1", export_path=tmp_path / "export")
    snapshot.export_path.mkdir()
    (snapshot.export_path / "manifest.json").write_text("{}")
    ready = _runcomfy_item("image", "profile", snapshot, [], set())
    assert ready.state == "dataset_ready"

    run = SimpleNamespace(id="run-1", snapshot_id="snapshot-1", status="running", progress_message="Training", error=None)
    assert _runcomfy_item("image", "profile", snapshot, [run], set()).state == "running"
    run.status = "stopped"
    stopped = _runcomfy_item("image", "profile", snapshot, [run], set())
    assert stopped.state == "running"
    assert stopped.action_label == "Resume RunComfy training"
    run.status = "completed"
    assert _runcomfy_item("image", "profile", snapshot, [run], set()).state == "outputs_ready"
    assert _runcomfy_item("image", "profile", snapshot, [run], {"run-1"}).state == "complete"
    selected = _runcomfy_item("image", "profile", snapshot, [run], {"run-1"}, {"run-1": "artifact-1"})
    assert selected.release_selected is True
    assert selected.release_artifact_id == "artifact-1"


def test_missing_export_blocks_new_work_without_hiding_remote_run(tmp_path) -> None:
    snapshot = SimpleNamespace(id="snapshot-1", export_path=tmp_path / "missing")
    missing = _runcomfy_item("image", "profile", snapshot, [], set())
    assert missing.state == "blocked"
    assert missing.action_label == "Re-export image dataset"
    run = SimpleNamespace(id="run-1", snapshot_id=snapshot.id, status="running", progress_message="Training", error=None)
    assert _runcomfy_item("image", "profile", snapshot, [run], set()).state == "running"
    run.status = "completed"
    assert _runcomfy_item("image", "profile", snapshot, [run], {run.id}).state == "complete"


def test_missing_export_blocks_runpod_packaging(tmp_path) -> None:
    source = tmp_path / "missing"
    item = _runpod_source_item("image", "profile", source, "project", [], [], [], [], set(), source_ready=True, source_blocker="Export first")
    assert item.state == "blocked"
    assert "Re-export" in item.action_label
    manifest = SimpleNamespace(export_path=source)
    assert _id_lora_item(manifest, [], [], [], [], []).state == "blocked"


def test_h3_reference_export_cannot_become_cloud_training_ready(tmp_path) -> None:
    source = tmp_path / "references"
    source.mkdir()
    (source / "manifest.json").write_text("{}")
    profile = "comfyui_minimax_h3_ref2va"
    snapshot = SimpleNamespace(id="h3-references", export_path=source)
    runcomfy = _runcomfy_item("video", profile, snapshot, [], set())
    runpod = _runpod_source_item("video", profile, source, "project", [], [], [], [], set(), source_ready=True, source_blocker="")
    for item in (runcomfy, runpod):
        assert item.state == "blocked"
        assert "does not train a LoRA" in item.summary
        assert item.action_label == "Open reference package"


def test_runpod_requires_available_bundle_preflight_and_registered_output(tmp_path) -> None:
    output = tmp_path / "bundle"
    output.mkdir()
    for name in ("bundle_manifest.json", "runpod_input.json"):
        (output / name).write_text("{}")
    bundle = RunPodBundle(
        modality="image", fingerprint="fingerprint", source_export_path=tmp_path / "source",
        output_path=output, archive_path=tmp_path / "bundle.zip", manifest_path=output / "bundle_manifest.json",
        input_path=output / "runpod_input.json", config_path=output / "config.yaml", serverless_config_path=output / "serverless.yaml",
        pod_template_path=output / "pod.json", pod_launcher_path=output / "pod.sh", trainer_launcher_path=output / "train.sh",
        remote_root="/workspace/bundle", remote_dataset_path="/workspace/bundle/data", serverless_root="/runpod-volume/bundle",
        serverless_dataset_path="/runpod-volume/bundle/data", training_target_profile_id="profile", ready=True,
    )
    assert _bundle_state("image", "profile", bundle, [], [], set()).state == "bundle_ready"

    upload = SimpleNamespace(bundle_path=output, status="complete", files_uploaded=2, files_total=2, error=None)

    report = RunPodPreflightReport(
        bundle_path=output, bundle_fingerprint="fingerprint", training_target_profile_id="profile", endpoint_id="endpoint",
        ready=True, checks=[RunPodPreflightCheck(id="gpu", passed=True, detail="ready")],
    )
    assert _bundle_state("image", "profile", bundle, [], [report], set(), uploads=[upload]).state == "endpoint_ready"

    run = RunPodTrainingRun(
        id="run-1", bundle_path=output, bundle_fingerprint="fingerprint", modality="image",
        training_target_profile_id="profile", endpoint_id="endpoint", project_id="project", status="completed",
    )
    assert _bundle_state("image", "profile", bundle, [run], [report], set(), uploads=[upload]).state == "outputs_ready"
    assert _bundle_state("image", "profile", bundle, [run], [report], {"run-1"}, uploads=[upload]).state == "complete"
    selected = _bundle_state("image", "profile", bundle, [run], [report], {"run-1"}, uploads=[upload], selected_by_run={"run-1": "artifact-1"})
    assert selected.release_selected is True


def test_runpod_reports_model_bootstrap_before_endpoint_preflight(tmp_path) -> None:
    output = tmp_path / "bundle"
    output.mkdir()
    for name in ("bundle_manifest.json", "runpod_input.json"):
        (output / name).write_text("{}")
    profile_id = "runpod_fish_speech_s2_voice_lora"
    bundle = RunPodBundle(
        modality="voice", fingerprint="fingerprint", source_export_path=tmp_path / "source",
        output_path=output, archive_path=tmp_path / "bundle.zip", manifest_path=output / "bundle_manifest.json",
        input_path=output / "runpod_input.json", config_path=output / "config.yaml", serverless_config_path=output / "serverless.yaml",
        pod_template_path=output / "pod.json", pod_launcher_path=output / "pod.sh", trainer_launcher_path=output / "train.sh",
        remote_root="/workspace/bundle", remote_dataset_path="/workspace/bundle/data", serverless_root="/runpod-volume/bundle",
        serverless_dataset_path="/runpod-volume/bundle/data", training_target_profile_id=profile_id, ready=True,
    )
    upload = SimpleNamespace(bundle_path=output, status="complete", files_uploaded=2, files_total=2, error=None)

    missing = _bundle_state("voice", profile_id, bundle, [], [], set(), uploads=[upload])
    assert missing.state == "bundle_ready"
    assert missing.action_label == "Install or verify models"

    running_bootstrap = SimpleNamespace(
        training_target_profile_id=profile_id, endpoint_id="endpoint", status="running",
        progress_message="Downloading Fish Speech", error=None,
    )
    running = _bundle_state("voice", profile_id, bundle, [], [], set(), uploads=[upload], bootstrap_runs=[running_bootstrap])
    assert running.state == "running"
    assert running.endpoint_id == "endpoint"
    assert running.action_label == "Monitor model installation"

    running_bootstrap.status = "completed"
    complete = _bundle_state("voice", profile_id, bundle, [], [], set(), uploads=[upload], bootstrap_runs=[running_bootstrap])
    assert complete.state == "bundle_ready"
    assert complete.action_label == "Verify RunPod endpoint"
