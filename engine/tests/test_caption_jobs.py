from pathlib import Path

from PIL import Image

from lorasuite_engine.caption_jobs import CaptionGenerationService
from lorasuite_engine.dataset_compiler import DatasetCompilerService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.models import (
    DatasetItemStatus,
    DatasetReviewStatus,
    DatasetView,
    ProcessingJobStatus,
    VisionCaptionEvidence,
    VisionProviderAuthMode,
    VisionProviderDialect,
)
from lorasuite_engine.processing import ProcessingService
from lorasuite_engine.vault import VaultService
from lorasuite_engine.vision_caption import VisionProviderConfig


class FakeVisionProvider:
    contexts = []
    paths = []

    def __init__(self, _config):
        pass

    def caption(self, image_path, _intent, analysis_context=None):
        self.contexts.append(analysis_context)
        self.paths.append(image_path)
        return VisionCaptionEvidence(
            expression="smiling",
            pose="standing with one hand raised",
            clothing="red sleeveless dress",
            environment="indoors beside large windows",
            camera="eye-level full-body view",
            other_people="none",
            watermark="none",
            content="general",
            confidence=0.93,
        )


class FailingVisionProvider:
    calls = 0

    def __init__(self, _config):
        pass

    def caption(self, _image_path, _intent, analysis_context=None):
        del analysis_context
        type(self).calls += 1
        raise ValueError("provider request failed")


def make_snapshot(tmp_path, image_count=1):
    vault_root = tmp_path / "vault"
    image_paths = []
    for index in range(image_count):
        image_path = tmp_path / f"person-{index}.png"
        Image.new("RGB", (320, 480), color=(120, 40 + index, 60)).save(image_path)
        image_paths.append(image_path)
    media_items = VaultService(vault_root).import_local_paths(image_paths).media_items
    projects = CharacterProjectService(vault_root)
    project = projects.create_project()
    project.intent.trigger_token = "example_person"
    project = projects.update_project(project.id, intent=project.intent)
    project = projects.add_candidates(project.id, [item.id for item in media_items])
    for media_item in media_items:
        project = projects.update_observation(
            project.id,
            media_item.id,
            review_status=DatasetReviewStatus.ACCEPTED,
            view=DatasetView.FULL_BODY,
        )
    snapshot = DatasetCompilerService(vault_root).compile_project(project.id)
    return vault_root, snapshot


def test_caption_job_updates_snapshot_without_persisting_api_key(tmp_path):
    vault_root, snapshot = make_snapshot(tmp_path)
    item = next(iter(snapshot.items.values()))
    FakeVisionProvider.contexts = []
    FakeVisionProvider.paths = []
    processing = ProcessingService(vault_root)
    analysis_job = processing.create_curation_analysis_job(
        source_media_item_ids=[item.source_media_item_id]
    )
    processing.process_job(analysis_job.id)
    config = VisionProviderConfig(
        provider_id="test",
        provider_label="Test Vision",
        dialect=VisionProviderDialect.RESPONSES,
        base_url="https://vision.example/v1",
        model="vision-test",
        api_key="super-secret-key",
    )
    service = CaptionGenerationService(
        vault_root,
        provider_factory=FakeVisionProvider,
    )
    DatasetCompilerService(vault_root).bulk_update_status(
        snapshot.id,
        status=DatasetItemStatus.APPROVED,
        item_ids=[item.id],
    )

    job = service.create_job(
        snapshot_id=snapshot.id,
        item_ids=[item.id],
        config=config,
    )
    completed = service.process_job(job.id, config)

    assert completed.status == ProcessingJobStatus.COMPLETE
    assert completed.completed_count == 1
    assert completed.failed_count == 0
    assert "super-secret-key" not in service.jobs_path.read_text(encoding="utf-8")
    updated = DatasetCompilerService(vault_root).get_snapshot(snapshot.id)
    assert updated is not None
    record = updated.items[item.id]
    assert record.caption == (
        "example_person, person, full-body photo, smiling, "
        "standing with one hand raised, red sleeveless dress, "
        "indoors beside large windows, eye-level full-body view"
    )
    assert record.unresolved_attributes == []
    assert record.caption_source.value == "vision"
    assert record.caption_provider == "Test Vision"
    assert record.caption_model == "vision-test"
    assert record.caption_confidence == 0.93
    assert record.status.value == "needs_review"
    assert FakeVisionProvider.contexts[0] is not None
    assert FakeVisionProvider.contexts[0].media_item_id == item.source_media_item_id


def test_caption_job_resumes_after_last_persisted_item(tmp_path):
    vault_root, snapshot = make_snapshot(tmp_path, image_count=2)
    item_ids = list(snapshot.items)
    config = VisionProviderConfig(
        provider_id="grok_oauth",
        provider_label="Grok OAuth",
        dialect=VisionProviderDialect.GROK_CLI,
        base_url="grok://local-oauth",
        model="grok-4.5",
        auth_mode=VisionProviderAuthMode.GROK_OAUTH,
    )
    service = CaptionGenerationService(vault_root, provider_factory=FakeVisionProvider)
    job = service.create_job(snapshot_id=snapshot.id, item_ids=item_ids, config=config)

    jobs = service._read_jobs()
    interrupted = jobs[job.id]
    interrupted.status = ProcessingJobStatus.RUNNING
    interrupted.completed_count = 1
    interrupted.progress_message = "Generated 1 of 2 captions"
    service._write_jobs(jobs)

    FakeVisionProvider.contexts = []
    FakeVisionProvider.paths = []
    recovered = service.recover_interrupted_jobs()
    assert len(recovered) == 1
    assert recovered[0][0].next_item_index == 1

    completed = service.process_job(job.id, recovered[0][1])

    assert completed.status == ProcessingJobStatus.COMPLETE
    assert completed.completed_count == 2
    assert completed.failed_count == 0
    assert completed.next_item_index == 2
    assert len(FakeVisionProvider.paths) == 1


def test_caption_job_stops_after_repeated_provider_failures(tmp_path):
    vault_root, snapshot = make_snapshot(tmp_path, image_count=5)
    config = VisionProviderConfig(
        provider_id="test",
        provider_label="Test Vision",
        dialect=VisionProviderDialect.RESPONSES,
        base_url="https://vision.example/v1",
        model="vision-test",
        api_key="test-key",
    )
    FailingVisionProvider.calls = 0
    service = CaptionGenerationService(
        vault_root,
        provider_factory=FailingVisionProvider,
    )
    job = service.create_job(
        snapshot_id=snapshot.id,
        item_ids=list(snapshot.items),
        config=config,
    )

    failed = service.process_job(job.id, config)

    assert failed.status == ProcessingJobStatus.FAILED
    assert failed.failed_count == 3
    assert failed.next_item_index == 3
    assert "Stopped after 3 repeated failures" in failed.progress_message
    assert FailingVisionProvider.calls == 3


def test_caption_job_can_be_canceled_before_processing(tmp_path):
    vault_root, snapshot = make_snapshot(tmp_path)
    config = VisionProviderConfig(
        provider_id="test",
        provider_label="Test Vision",
        dialect=VisionProviderDialect.RESPONSES,
        base_url="https://vision.example/v1",
        model="vision-test",
        api_key="test-key",
    )
    FakeVisionProvider.paths = []
    service = CaptionGenerationService(
        vault_root,
        provider_factory=FakeVisionProvider,
    )
    job = service.create_job(
        snapshot_id=snapshot.id,
        item_ids=list(snapshot.items),
        config=config,
    )

    canceled = service.cancel_job(job.id)
    processed = service.process_job(job.id, config)

    assert canceled.status == ProcessingJobStatus.CANCELED
    assert processed.status == ProcessingJobStatus.CANCELED
    assert "stopped by the user" in processed.progress_message
    assert FakeVisionProvider.paths == []
