from pathlib import Path

from lorasuite_engine.models import (
    DatasetCaptionRecord,
    DatasetItemStatus,
    DatasetSnapshot,
    DatasetSnapshotStatus,
    TrainingIntent,
)
from lorasuite_engine.image_evaluation import (
    ImageBenchmarkCaseResult,
    ImageBenchmarkMetrics,
    ImageBenchmarkRun,
    default_image_benchmark_suite,
)
from lorasuite_engine.model_registry import ArtifactEvaluation, ModelArtifactRecord
from lorasuite_engine.storage import atomic_write_json
from lorasuite_engine.training_targets import get_training_target_profile


def _metrics(identity: float) -> ImageBenchmarkMetrics:
    return ImageBenchmarkMetrics(
        visual_quality=0.75,
        aesthetic_score=0.7,
        subject_coverage=0.8,
        face_count=1,
        face_area=0.1,
        body_coverage=0.3,
        pose_coverage=0.6,
        identity_similarity=identity,
    )


def test_artifact_comparison_and_improvement_request_routes(client, tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    artifact = ModelArtifactRecord(
        id="artifact-1",
        project_id="project-1",
        training_run_id="training-1",
        snapshot_id="snapshot-1",
        dataset_fingerprint="fingerprint-1",
        checkpoint_name="person.safetensors",
        checkpoint_path=tmp_path / "person.safetensors",
        checkpoint_sha256="checkpoint-sha",
        checkpoint_size_bytes=1024,
        modality="image",
        model_family="flux1",
        evaluation=ArtifactEvaluation(
            status="ready",
            checkpoint_valid=True,
            provenance_valid=True,
            config_present=True,
        ),
    )
    atomic_write_json(
        vault_root / "model_artifacts.json",
        {"version": 1, "artifacts": [artifact.model_dump(mode="json")]},
    )
    definition = default_image_benchmark_suite()[0]
    baseline_path = tmp_path / "baseline.png"
    lora_path = tmp_path / "lora.png"
    baseline_path.write_bytes(b"baseline")
    lora_path.write_bytes(b"lora")
    run = ImageBenchmarkRun(
        id="benchmark-1",
        project_id="project-1",
        artifact_id=artifact.id,
        baseline_dir=tmp_path,
        lora_dir=tmp_path,
        status="complete",
        cases={
            definition.id: ImageBenchmarkCaseResult(
                definition=definition,
                baseline_path=baseline_path,
                lora_path=lora_path,
                baseline=_metrics(0.3),
                lora=_metrics(0.75),
                passed=True,
                blocked=False,
                checks={"identity_similarity": True},
            )
        },
    )
    atomic_write_json(
        vault_root / "image_benchmark_runs.json",
        {"version": 1, "runs": [run.model_dump(mode="json")]},
    )
    source = DatasetSnapshot(
        id=artifact.snapshot_id,
        project_id="project-1",
        project_name="Person",
        version=1,
        status=DatasetSnapshotStatus.EXPORTED,
        intent=TrainingIntent(trigger_token="person_token"),
        training_target=get_training_target_profile(
            "runcomfy_flux1_dev_character"
        ).spec(),
        items={
            "item-1": DatasetCaptionRecord(
                id="item-1",
                source_media_item_id="media-1",
                training_media_item_id="media-1",
                caption="person_token, portrait",
                status=DatasetItemStatus.APPROVED,
            )
        },
        fingerprint=artifact.dataset_fingerprint,
        export_path=tmp_path / "exported-dataset",
    )
    atomic_write_json(
        vault_root / "dataset_snapshots.json",
        {"version": 1, "snapshots": [source.model_dump(mode="json")]},
    )

    created = client.post(
        "/artifact-comparisons",
        json={
            "project_id": "project-1",
            "benchmark_kind": "image",
            "candidate_artifact_id": artifact.id,
        },
    )

    assert created.status_code == 200
    comparison = created.json()
    assert comparison["comparison_kind"] == "baseline_vs_artifact"
    assert comparison["candidate"]["checkpoint_sha256"] == "checkpoint-sha"
    assert client.get(
        "/artifact-comparisons",
        params={"project_id": "project-1", "benchmark_kind": "image"},
    ).json()[0]["id"] == comparison["id"]

    staged = client.post(
        f"/artifact-comparisons/{comparison['id']}/improvement-request",
    )

    assert staged.status_code == 200
    request = staged.json()
    assert request["status"] == "draft"
    assert request["actions"]

    approved = client.patch(
        f"/improvement-requests/{request['id']}",
        json={"decision": "approved", "note": "Use this for revision two."},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert client.get(
        "/improvement-requests",
        params={"project_id": "project-1", "status": "approved"},
    ).json()[0]["id"] == request["id"]

    materialized = client.post(
        f"/improvement-requests/{request['id']}/materialize-revision",
    )

    assert materialized.status_code == 200
    revision = materialized.json()
    assert revision["format"] == "lorasuite.dataset-revision.v1"
    assert revision["parent_snapshot_id"] == source.id
    assert revision["revision_version"] == 2
    assert client.get(
        "/dataset-revisions",
        params={"project_id": "project-1"},
    ).json()[0]["id"] == revision["id"]
    assert client.post(
        f"/improvement-requests/{request['id']}/materialize-revision",
    ).json()["id"] == revision["id"]
