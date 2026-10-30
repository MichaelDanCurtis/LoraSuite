import json
from pathlib import Path

from lorasuite_engine.evaluation_harness import BenchmarkMetrics
from lorasuite_engine.id_lora_evaluation import IdLoraEvaluationService
from lorasuite_engine.runpod_runs import RunPodRunArtifact, RunPodTrainingRun
from lorasuite_engine.storage import atomic_write_json


def test_scores_downloaded_zero_shot_id_lora_outputs(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    contract = tmp_path / "downloads" / "contract" / "inference_contract.json"
    video = tmp_path / "downloads" / "sample" / "id_lora_01.mp4"
    contract.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    contract.write_text(json.dumps([{
        "prompt": "[VISUAL]: A person speaks. [SPEECH]: Hello from the evaluation. [SOUNDS]: Calm voice.",
        "output_name": "id_lora_01",
    }]))
    video.write_bytes(b"video")
    source = RunPodTrainingRun(
        id="id-lora-runpod-1",
        bundle_path=tmp_path / "bundle",
        bundle_fingerprint="id-fingerprint",
        modality="audio_visual",
        training_target_profile_id="runpod_id_lora_ltx23_inference",
        action="run_id_lora",
        endpoint_id="endpoint-1",
        project_id="project-1",
        status="completed",
        artifacts=[
            RunPodRunArtifact(kind="contract", name=contract.name, local_path=contract),
            RunPodRunArtifact(kind="sample", name=video.name, local_path=video),
        ],
    )
    atomic_write_json(vault_root / "runpod_training_runs.json", {"version": 1, "runs": [source.model_dump(mode="json")]})

    def analyzer(path, variant, definition, work_dir, project_id):
        assert definition.expected_transcript == "Hello from the evaluation."
        assert project_id == "project-1"
        return _metrics()

    service = IdLoraEvaluationService(vault_root, analyzer=analyzer)
    run = service.process_run(service.create_run(source.id).id)

    assert run.status == "complete"
    assert run.summary.screening_ready is True
    assert run.summary.release_ready is True
    assert run.summary.average_identity == 0.82
    assert run.cases["id_lora_01"].expected_transcript == "Hello from the evaluation."
    assert service.create_run(source.id).id == run.id


def test_marks_id_lora_screening_blocked_when_identity_models_are_unavailable(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    contract = tmp_path / "contract.json"
    video = tmp_path / "id_lora_01.mp4"
    contract.write_text('[{"prompt":"[SPEECH]: Hello. [SOUNDS]: Quiet.","output_name":"id_lora_01"}]')
    video.write_bytes(b"video")
    source = RunPodTrainingRun(
        bundle_path=tmp_path / "bundle", bundle_fingerprint="fingerprint", modality="audio_visual",
        training_target_profile_id="runpod_id_lora_ltx23_inference", action="run_id_lora", endpoint_id="endpoint",
        project_id="project-1", status="completed",
        artifacts=[RunPodRunArtifact(kind="contract", name=contract.name, local_path=contract), RunPodRunArtifact(kind="sample", name=video.name, local_path=video)],
    )
    atomic_write_json(vault_root / "runpod_training_runs.json", {"version": 1, "runs": [source.model_dump(mode="json")]})
    metrics = _metrics()
    metrics.identity_similarity = None
    service = IdLoraEvaluationService(vault_root, analyzer=lambda *_args: metrics)

    run = service.process_run(service.create_run(source.id).id)

    assert run.summary.blocked_count == 1
    assert run.summary.screening_ready is False
    assert "identity similarity unavailable" in run.cases["id_lora_01"].reasons


def test_rejects_unsafe_or_ambiguous_inference_output_names(tmp_path: Path) -> None:
    for payload, message in [
        ([{"prompt": "test", "output_name": "../escape"}], "unsafe output name"),
        ([{"prompt": "one", "output_name": "sample"}, {"prompt": "two", "output_name": "sample"}], "duplicate output names"),
    ]:
        vault_root = tmp_path / message.replace(" ", "-")
        contract = vault_root / "contract.json"
        contract.parent.mkdir(parents=True)
        contract.write_text(json.dumps(payload))
        video = vault_root / "sample.mp4"
        video.write_bytes(b"video")
        source = RunPodTrainingRun(
            bundle_path=tmp_path / "bundle", bundle_fingerprint="fingerprint", modality="audio_visual",
            training_target_profile_id="runpod_id_lora_ltx23_inference", action="run_id_lora", endpoint_id="endpoint",
            project_id="project-1", status="completed",
            artifacts=[RunPodRunArtifact(kind="contract", name=contract.name, local_path=contract), RunPodRunArtifact(kind="sample", name=video.name, local_path=video)],
        )
        atomic_write_json(vault_root / "runpod_training_runs.json", {"version": 1, "runs": [source.model_dump(mode="json")]})

        try:
            IdLoraEvaluationService(vault_root).create_run(source.id)
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("invalid inference contract was accepted")


def _metrics() -> BenchmarkMetrics:
    return BenchmarkMetrics(
        visual_quality=0.8,
        temporal_stability=0.75,
        motion_score=0.5,
        subject_coverage=0.9,
        identity_similarity=0.82,
        identity_frame_coverage=0.9,
        audio_quality=0.8,
        speaker_similarity=0.78,
        transcript_similarity=0.92,
        av_sync_proxy=0.7,
        syncnet_lse_c=4.5,
        syncnet_lse_d=7.0,
        syncnet_offset_frames=1,
        duration_seconds=5.0,
    )
