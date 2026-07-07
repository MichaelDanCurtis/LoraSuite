from pathlib import Path

from lorasuite_engine.models import (
    AssetType,
    IngressCandidate,
    IngressCandidateStatus,
    IngressJob,
    IngressJobStatus,
    MediaType,
    SourceKind,
)


def test_ingress_candidate_serializes_preview_fields():
    candidate = IngressCandidate(
        source_kind=SourceKind.LOCAL,
        source_locator="/tmp/source/image.png",
        display_name="image.png",
        media_type=MediaType.IMAGE,
        size_bytes=123,
        width=64,
        height=48,
        thumbnail_path=Path("/tmp/vault/previews/thumb.jpg"),
        status=IngressCandidateStatus.READY,
        selected=True,
    )

    payload = candidate.model_dump(mode="json")

    assert payload["source_kind"] == "local"
    assert payload["source_locator"] == "/tmp/source/image.png"
    assert payload["thumbnail_path"] == "/tmp/vault/previews/thumb.jpg"
    assert payload["status"] == "ready"
    assert payload["selected"] is True


def test_ingress_job_tracks_counts_and_imported_items():
    job = IngressJob(
        source_kind=SourceKind.LOCAL,
        candidate_ids=["candidate_1", "candidate_2"],
        selected_count=2,
        status=IngressJobStatus.RUNNING,
        progress_message="Importing selected media",
    )

    assert job.status == IngressJobStatus.RUNNING
    assert job.candidate_count == 2
    assert job.selected_count == 2
    assert job.imported_count == 0


def test_asset_type_includes_thumbnail_and_poster():
    assert AssetType.THUMBNAIL == "thumbnail"
    assert AssetType.POSTER == "poster"
