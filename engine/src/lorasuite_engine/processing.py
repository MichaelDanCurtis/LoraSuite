import json
import shutil
from contextlib import suppress
from pathlib import Path

from lorasuite_engine.ffmpeg import extract_audio, extract_frames, probe_video
from lorasuite_engine.models import (
    DerivativeType,
    MediaItem,
    MediaType,
    ProcessingJob,
    ProcessingJobStatus,
    VideoBreakdownOptions,
    utc_now,
)
from lorasuite_engine.vault import VaultService


TERMINAL_PROCESSING_STATUSES = frozenset(
    {
        ProcessingJobStatus.COMPLETE,
        ProcessingJobStatus.FAILED,
        ProcessingJobStatus.CANCELED,
    }
)


class ProcessingService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def jobs_path(self) -> Path:
        return self.vault_root / "processing_jobs.json"

    @property
    def derivatives_dir(self) -> Path:
        return self.vault_root / "derivatives"

    def create_video_breakdown_job(
        self,
        *,
        source_media_item_ids: list[str],
        options: VideoBreakdownOptions,
    ) -> ProcessingJob:
        job = ProcessingJob(
            job_type="video_breakdown",
            source_media_item_ids=source_media_item_ids,
            options=options.model_dump(mode="json"),
        )
        jobs = self._read_jobs()
        jobs[job.id] = job
        self._write_jobs(jobs)
        return job

    def process_job(self, job_id: str) -> ProcessingJob:
        jobs = self._read_jobs()
        job = jobs[job_id]
        if job.status in TERMINAL_PROCESSING_STATUSES:
            return job

        job.status = ProcessingJobStatus.RUNNING
        job.started_at = utc_now()
        job.progress_message = "Breaking down video media"
        job.derived_media_items = []
        job.errors = []
        jobs[job.id] = job
        self._write_jobs(jobs)

        processing_state = {"manifest_appended": False}
        try:
            return self._process_running_job(jobs, job, processing_state)
        except Exception as exc:
            if not processing_state["manifest_appended"]:
                self._delete_unmanifested_job_derivatives(job.id)
            job.status = ProcessingJobStatus.FAILED
            job.errors.append(
                {
                    "code": "processing_failed",
                    "message": str(exc) or exc.__class__.__name__,
                }
            )
            job.progress_message = "Video breakdown completed with errors"
            job.completed_at = utc_now()
            jobs[job.id] = job
            self._write_jobs(jobs)
            return job

    def _process_running_job(
        self,
        jobs: dict[str, ProcessingJob],
        job: ProcessingJob,
        processing_state: dict[str, bool],
    ) -> ProcessingJob:
        if job.job_type != "video_breakdown":
            job.status = ProcessingJobStatus.FAILED
            job.errors.append(
                {
                    "code": "unsupported_processing_job",
                    "message": f"unsupported processing job type: {job.job_type}",
                }
            )
            job.completed_at = utc_now()
            jobs[job.id] = job
            self._write_jobs(jobs)
            return job

        vault = VaultService(self.vault_root)
        options = VideoBreakdownOptions.model_validate(job.options)
        derived_items: list[MediaItem] = []
        manifest_raw_paths = self._manifest_raw_paths(vault)

        if not job.source_media_item_ids:
            job.errors.append(
                {
                    "code": "no_source_media",
                    "message": "at least one source media item is required",
                }
            )

        if not options.generate_frames and not options.extract_audio:
            job.errors.append(
                {
                    "code": "no_derivatives_requested",
                    "message": "at least one derivative output must be requested",
                }
            )

        if job.errors:
            job.status = ProcessingJobStatus.FAILED
            job.progress_message = "Video breakdown completed with errors"
            job.completed_at = utc_now()
            jobs[job.id] = job
            self._write_jobs(jobs)
            return job

        for media_item_id in job.source_media_item_ids:
            source_item = vault.get_media_item(media_item_id)
            if source_item is None:
                job.errors.append(
                    {
                        "code": "missing_source_media",
                        "message": f"source media item not found: {media_item_id}",
                    }
                )
                continue
            if source_item.media_type != MediaType.VIDEO:
                job.errors.append(
                    {
                        "code": "unsupported_media_type",
                        "message": f"source media item is not video: {media_item_id}",
                    }
                )
                continue
            breakdown_items, breakdown_errors = self._breakdown_video(
                job.id,
                vault,
                source_item,
                options,
                manifest_raw_paths,
            )
            derived_items.extend(breakdown_items)
            job.errors.extend(breakdown_errors)

        if derived_items:
            derived_items, items_to_append = self._resolve_manifest_derivatives(
                vault,
                derived_items,
            )
            try:
                if items_to_append:
                    vault.append_media_items(items_to_append)
                processing_state["manifest_appended"] = True
            except Exception:
                self._delete_derived_files(items_to_append)
                raise
        job.derived_media_items = derived_items
        job.status = (
            ProcessingJobStatus.COMPLETE
            if derived_items and not job.errors
            else ProcessingJobStatus.FAILED
        )
        job.progress_message = (
            "Video breakdown complete"
            if job.status == ProcessingJobStatus.COMPLETE
            else "Video breakdown completed with errors"
        )
        job.completed_at = utc_now()
        jobs[job.id] = job
        self._write_jobs(jobs)
        return job

    def list_jobs(self) -> list[ProcessingJob]:
        return sorted(
            self._read_jobs().values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def get_job(self, job_id: str) -> ProcessingJob | None:
        return self._read_jobs().get(job_id)

    def _delete_derived_files(self, derived_items: list[MediaItem]) -> None:
        for item in derived_items:
            with suppress(OSError):
                item.raw_path.unlink(missing_ok=True)

    def _resolve_manifest_derivatives(
        self,
        vault: VaultService,
        candidate_items: list[MediaItem],
    ) -> tuple[list[MediaItem], list[MediaItem]]:
        existing_by_raw_path = {
            Path(item.raw_path): item
            for item in vault.list_media_items()
        }
        resolved_items: list[MediaItem] = []
        items_to_append: list[MediaItem] = []
        for candidate_item in candidate_items:
            raw_path = Path(candidate_item.raw_path)
            existing_item = existing_by_raw_path.get(raw_path)
            if existing_item is not None:
                resolved_items.append(existing_item)
                continue

            resolved_items.append(candidate_item)
            items_to_append.append(candidate_item)
            existing_by_raw_path[raw_path] = candidate_item

        return resolved_items, items_to_append

    def _manifest_raw_paths(self, vault: VaultService) -> set[Path]:
        return {Path(item.raw_path) for item in vault.list_media_items()}

    def _materialize_frame_outputs(
        self,
        frame_paths: list[Path],
        frames_dir: Path,
        protected_raw_paths: set[Path],
    ) -> list[Path]:
        frames_dir.mkdir(parents=True, exist_ok=True)
        materialized_frames: list[Path] = []
        for frame_path in frame_paths:
            final_frame_path = frames_dir / frame_path.name
            if final_frame_path in protected_raw_paths:
                if frame_path != final_frame_path:
                    with suppress(OSError):
                        frame_path.unlink(missing_ok=True)
                materialized_frames.append(final_frame_path)
                continue

            if frame_path != final_frame_path:
                frame_path.replace(final_frame_path)
            materialized_frames.append(final_frame_path)

        return materialized_frames

    def _delete_unmanifested_job_derivatives(self, job_id: str) -> None:
        job_derivatives_dir = self.derivatives_dir / "video_breakdowns" / job_id
        if not job_derivatives_dir.exists():
            return

        try:
            manifest_raw_paths = self._manifest_raw_paths(VaultService(self.vault_root))
        except Exception:
            return

        for path in sorted(job_derivatives_dir.rglob("*"), reverse=True):
            if path.is_file() and path not in manifest_raw_paths:
                with suppress(OSError):
                    path.unlink()
            elif path.is_dir():
                with suppress(OSError):
                    path.rmdir()

    def _breakdown_video(
        self,
        job_id: str,
        vault: VaultService,
        source_item: MediaItem,
        options: VideoBreakdownOptions,
        protected_raw_paths: set[Path],
    ) -> tuple[list[MediaItem], list[dict[str, str]]]:
        derived_items: list[MediaItem] = []
        errors: list[dict[str, str]] = []

        try:
            metadata = probe_video(source_item.raw_path)
        except RuntimeError as exc:
            return [], [
                {
                    "code": "video_probe_failed",
                    "message": str(exc),
                }
            ]

        requested_frame_duration = options.max_frame_count / options.frames_per_second
        end_seconds = min(metadata.duration_seconds, requested_frame_duration)

        if options.generate_frames:
            frames_dir = (
                self.derivatives_dir
                / "video_breakdowns"
                / job_id
                / source_item.id
                / "frames"
            )
            staging_frames_dir = frames_dir / ".staging"
            shutil.rmtree(staging_frames_dir, ignore_errors=True)
            frames: list[Path] | None = None
            try:
                extracted_frames = extract_frames(
                    video_path=source_item.raw_path,
                    output_dir=staging_frames_dir,
                    start_seconds=0.0,
                    end_seconds=end_seconds,
                    frames_per_second=options.frames_per_second,
                )
                frames = self._materialize_frame_outputs(
                    extracted_frames,
                    frames_dir,
                    protected_raw_paths,
                )
            except (RuntimeError, ValueError) as exc:
                errors.append(
                    {
                        "code": "frame_extraction_failed",
                        "message": str(exc),
                    }
                )
            finally:
                shutil.rmtree(staging_frames_dir, ignore_errors=True)
            if frames is not None:
                manifested_frames = frames[: options.max_frame_count]
                for discarded_frame in frames[options.max_frame_count :]:
                    if discarded_frame not in protected_raw_paths:
                        discarded_frame.unlink(missing_ok=True)

                if not manifested_frames:
                    errors.append(
                        {
                            "code": "no_frames_extracted",
                            "message": "frame extraction did not produce any frames",
                        }
                    )

                for index, frame_path in enumerate(manifested_frames):
                    derived_items.append(
                        vault.build_derivative_media_item(
                            source_item=source_item,
                            derivative_path=frame_path,
                            media_type=MediaType.IMAGE,
                            derivative_type=DerivativeType.VIDEO_FRAME,
                            metadata={
                                "time_range": {
                                    "start_seconds": index / options.frames_per_second,
                                    "end_seconds": index / options.frames_per_second,
                                },
                                "generator": {
                                    "name": "ffmpeg",
                                    "settings": options.model_dump(mode="json"),
                                },
                            },
                        )
                    )

        if options.extract_audio:
            audio_dir = (
                self.derivatives_dir
                / "video_breakdowns"
                / job_id
                / source_item.id
                / "audio"
            )
            audio_path = audio_dir / "audio.wav"
            staging_audio_dir = audio_dir / ".staging"
            staging_audio_path = staging_audio_dir / "audio.wav"
            shutil.rmtree(staging_audio_dir, ignore_errors=True)
            try:
                extract_audio(
                    video_path=source_item.raw_path,
                    output_path=staging_audio_path,
                )
                if audio_path in protected_raw_paths:
                    with suppress(OSError):
                        staging_audio_path.unlink(missing_ok=True)
                else:
                    audio_dir.mkdir(parents=True, exist_ok=True)
                    staging_audio_path.replace(audio_path)
            except RuntimeError as exc:
                errors.append(
                    {
                        "code": "audio_extraction_failed",
                        "message": str(exc),
                    }
                )
            else:
                derived_items.append(
                    vault.build_derivative_media_item(
                        source_item=source_item,
                        derivative_path=audio_path,
                        media_type=MediaType.AUDIO,
                        derivative_type=DerivativeType.AUDIO_CLIP,
                        metadata={
                            "time_range": {
                                "start_seconds": 0.0,
                                "end_seconds": metadata.duration_seconds,
                            },
                            "generator": {
                                "name": "ffmpeg",
                                "settings": {"extract_audio": True},
                            },
                        },
                    )
                )
            finally:
                shutil.rmtree(staging_audio_dir, ignore_errors=True)

        return derived_items, errors

    def _read_jobs(self) -> dict[str, ProcessingJob]:
        if not self.jobs_path.exists():
            return {}
        payload = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        return {
            job_id: ProcessingJob.model_validate(job_payload)
            for job_id, job_payload in payload.items()
        }

    def _write_jobs(self, jobs: dict[str, ProcessingJob]) -> None:
        self.vault_root.mkdir(parents=True, exist_ok=True)
        self.jobs_path.write_text(
            json.dumps(
                {
                    job_id: job.model_dump(mode="json")
                    for job_id, job in jobs.items()
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
