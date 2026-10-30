import json
import shutil
from contextlib import suppress
from math import isfinite
from pathlib import Path

from lorasuite_engine.ffmpeg import (
    extract_analysis_frames,
    extract_audio,
    extract_frame_at_timestamp,
    extract_frames,
    extract_video_clip,
    probe_video,
)
from lorasuite_engine.audio_cleaning import AudioCleaningService
from lorasuite_engine.curation_analysis import CurationAnalyzer
from lorasuite_engine.models import (
    AudioCleaningBatchOptions,
    DerivativeType,
    MediaItem,
    MediaType,
    ProcessingJob,
    ProcessingJobStatus,
    VideoBreakdownAnalysis,
    VideoBreakdownCommitRequest,
    VideoBreakdownOptions,
    VideoClipDecision,
    VideoFrameDecision,
    utc_now,
)
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService
from lorasuite_engine.video_analysis import analyze_video_frames


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
        with json_file_lock(self.jobs_path):
            jobs = self._read_jobs_unlocked()
            jobs[job.id] = job
            self._write_jobs_unlocked(jobs)
        return job

    def create_curation_analysis_job(
        self,
        *,
        source_media_item_ids: list[str],
    ) -> ProcessingJob:
        job = ProcessingJob(
            job_type="curation_analysis",
            source_media_item_ids=source_media_item_ids,
        )
        with json_file_lock(self.jobs_path):
            jobs = self._read_jobs_unlocked()
            jobs[job.id] = job
            self._write_jobs_unlocked(jobs)
        return job

    def create_audio_cleaning_job(
        self,
        *,
        source_media_item_ids: list[str],
        options: AudioCleaningBatchOptions,
    ) -> ProcessingJob:
        job = ProcessingJob(
            job_type="audio_cleaning",
            source_media_item_ids=source_media_item_ids,
            options=options.model_dump(mode="json"),
        )
        with json_file_lock(self.jobs_path):
            jobs = self._read_jobs_unlocked()
            jobs[job.id] = job
            self._write_jobs_unlocked(jobs)
        return job

    def process_job(self, job_id: str) -> ProcessingJob:
        with json_file_lock(self.jobs_path):
            jobs = self._read_jobs_unlocked()
            job = jobs[job_id]
            if job.status in TERMINAL_PROCESSING_STATUSES:
                return job

            job.status = ProcessingJobStatus.RUNNING
            job.started_at = utc_now()
            job.progress_message = {
                "curation_analysis": "Analyzing curation candidates",
                "audio_cleaning": "Preparing voice tracks",
            }.get(job.job_type, "Breaking down video media")
            job.derived_media_items = []
            job.video_analyses = []
            job.curation_analyses = []
            job.errors = []
            jobs[job.id] = job
            self._write_jobs(jobs)

        processing_state = {"manifest_appended": False}
        try:
            return self._process_running_job(jobs, job, processing_state)
        except Exception as exc:
            if job.job_type == "video_breakdown" and not processing_state["manifest_appended"]:
                self._delete_unmanifested_job_derivatives(job.id)
            job.status = ProcessingJobStatus.FAILED
            job.errors.append(
                {
                    "code": "processing_failed",
                    "message": str(exc) or exc.__class__.__name__,
                }
            )
            job.progress_message = {
                "curation_analysis": "Curation analysis failed",
                "audio_cleaning": "Voice preparation failed",
            }.get(job.job_type, "Video breakdown failed")
            job.completed_at = utc_now()
            self._save_job(job)
            return job

    def _process_running_job(
        self,
        jobs: dict[str, ProcessingJob],
        job: ProcessingJob,
        processing_state: dict[str, bool],
    ) -> ProcessingJob:
        if job.job_type == "curation_analysis":
            return self._process_curation_analysis_job(job)
        if job.job_type == "audio_cleaning":
            return self._process_audio_cleaning_job(job)
        if job.job_type != "video_breakdown":
            job.status = ProcessingJobStatus.FAILED
            job.errors.append(
                {
                    "code": "unsupported_processing_job",
                    "message": f"unsupported processing job type: {job.job_type}",
                }
            )
            job.completed_at = utc_now()
            self._save_job(job)
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
            self._save_job(job)
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
            breakdown_items, breakdown_errors, analysis = self._breakdown_video(
                job.id,
                vault,
                source_item,
                options,
                manifest_raw_paths,
            )
            derived_items.extend(breakdown_items)
            job.errors.extend(breakdown_errors)
            if analysis is not None:
                job.video_analyses.append(analysis)
                job.progress_message = (
                    f"Selected {sum(frame.decision == VideoFrameDecision.KEEPER for frame in analysis.frames)} "
                    f"keepers from {len(analysis.frames)} analyzed frames"
                )
                self._save_job(job)

        if derived_items:
            derived_items, items_to_append = self._resolve_manifest_derivatives(
                vault,
                derived_items,
            )
            try:
                if items_to_append:
                    appended = vault.append_media_items(items_to_append)
                    resolutions = {
                        candidate.id: resolved
                        for candidate, resolved in zip(items_to_append, appended, strict=True)
                    }
                    derived_items = [
                        resolutions.get(item.id, item) for item in derived_items
                    ]
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
        self._save_job(job)
        return job

    def _process_audio_cleaning_job(self, job: ProcessingJob) -> ProcessingJob:
        vault = VaultService(self.vault_root)
        cleaning = AudioCleaningService(self.vault_root)
        options = AudioCleaningBatchOptions.model_validate(job.options)
        total = len(job.source_media_item_ids)
        if total == 0:
            job.status = ProcessingJobStatus.FAILED
            job.progress_message = "No voice tracks were supplied"
            job.errors.append(
                {"code": "no_source_media", "message": "at least one audio item is required"}
            )
            job.completed_at = utc_now()
            self._save_job(job)
            return job

        if options.force_voice_isolation and not cleaning.separation_status().ready:
            job.status = ProcessingJobStatus.FAILED
            job.progress_message = "Voice isolation is unavailable"
            job.errors.append(
                {
                    "code": "voice_isolation_unavailable",
                    "message": cleaning.separation_status().message,
                }
            )
            job.completed_at = utc_now()
            self._save_job(job)
            return job

        for index, media_item_id in enumerate(job.source_media_item_ids, start=1):
            item = vault.get_media_item(media_item_id)
            if item is None:
                job.errors.append(
                    {
                        "code": "missing_source_media",
                        "message": f"source media item not found: {media_item_id}",
                    }
                )
                continue
            if item.media_type != MediaType.AUDIO:
                job.errors.append(
                    {
                        "code": "unsupported_media_type",
                        "message": f"source media item is not audio: {media_item_id}",
                    }
                )
                continue
            try:
                recipe = cleaning.get_recipe(media_item_id)
                if options.force_voice_isolation:
                    recipe = recipe.model_copy(update={"isolate_voice": True})
                result = cleaning.render(recipe)
                if result.rendered_media_item is not None:
                    job.derived_media_items.append(result.rendered_media_item)
            except Exception as error:
                job.errors.append(
                    {
                        "code": "audio_cleaning_failed",
                        "message": f"{media_item_id}: {str(error) or error.__class__.__name__}",
                    }
                )
            job.progress_message = f"Prepared {index} of {total} voice tracks"
            self._save_job(job)

        job.status = (
            ProcessingJobStatus.COMPLETE
            if job.derived_media_items
            else ProcessingJobStatus.FAILED
        )
        prepared = len(job.derived_media_items)
        failed = len(job.errors)
        job.progress_message = (
            f"Voice preparation complete: {prepared} prepared"
            + (f", {failed} failed" if failed else "")
            if job.status == ProcessingJobStatus.COMPLETE
            else "Voice preparation completed with errors"
        )
        job.completed_at = utc_now()
        self._save_job(job)
        return job

    def _process_curation_analysis_job(self, job: ProcessingJob) -> ProcessingJob:
        vault = VaultService(self.vault_root)
        analyzer = CurationAnalyzer(self.vault_root)
        total = len(job.source_media_item_ids)
        if total == 0:
            job.status = ProcessingJobStatus.FAILED
            job.progress_message = "No curation candidates were supplied"
            job.errors.append(
                {"code": "no_source_media", "message": "at least one media item is required"}
            )
            job.completed_at = utc_now()
            self._save_job(job)
            return job

        for index, media_item_id in enumerate(job.source_media_item_ids, start=1):
            item = vault.get_media_item(media_item_id)
            if item is None:
                job.errors.append(
                    {
                        "code": "missing_source_media",
                        "message": f"source media item not found: {media_item_id}",
                    }
                )
                continue
            try:
                job.curation_analyses.append(analyzer.analyze(item))
            except Exception as error:
                job.errors.append(
                    {
                        "code": "curation_analysis_failed",
                        "message": f"{media_item_id}: {str(error) or error.__class__.__name__}",
                    }
                )
            job.progress_message = f"Analyzed {index} of {total} candidates"
            if index == total or index % 10 == 0:
                self._save_job(job)

        job.status = (
            ProcessingJobStatus.COMPLETE
            if job.curation_analyses
            else ProcessingJobStatus.FAILED
        )
        job.progress_message = (
            f"Curation analysis complete: {len(job.curation_analyses)} analyzed"
            if job.status == ProcessingJobStatus.COMPLETE
            else "Curation analysis completed with errors"
        )
        job.completed_at = utc_now()
        self._save_job(job)
        return job

    def list_jobs(self) -> list[ProcessingJob]:
        return sorted(
            self._read_jobs().values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def get_job(self, job_id: str) -> ProcessingJob | None:
        return self._read_jobs().get(job_id)

    def update_video_keepers(
        self,
        job_id: str,
        frame_ids: list[str],
    ) -> ProcessingJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        selected_ids = set(frame_ids)
        frames_by_id = {
            frame.id: (analysis, frame)
            for analysis in job.video_analyses
            for frame in analysis.frames
        }
        unknown_ids = selected_ids.difference(frames_by_id)
        if unknown_ids:
            raise ValueError(f"unknown analysis frame: {sorted(unknown_ids)[0]}")
        if not selected_ids:
            raise ValueError("at least one keeper frame is required")

        vault = VaultService(self.vault_root)
        generated_items = self._apply_video_keeper_selection(job, selected_ids, vault)
        if generated_items:
            resolved_items = vault.append_media_items(generated_items)
            job.derived_media_items.extend(resolved_items)
        job.progress_message = f"Saved {len(selected_ids)} reviewed keeper frames"
        self._save_job(job)
        return job

    def commit_video_breakdown(
        self,
        job_id: str,
        request: VideoBreakdownCommitRequest,
    ) -> ProcessingJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.job_type != "video_breakdown" or not job.video_analyses:
            raise ValueError("processing job has no video breakdown analysis")

        selected_frame_ids = set(request.frame_ids)
        frames_by_id = {
            frame.id: frame
            for analysis in job.video_analyses
            for frame in analysis.frames
        }
        unknown_frame_ids = selected_frame_ids.difference(frames_by_id)
        if unknown_frame_ids:
            raise ValueError(f"unknown analysis frame: {sorted(unknown_frame_ids)[0]}")

        proposals_by_id = {
            proposal.id: (analysis, proposal)
            for analysis in job.video_analyses
            for proposal in analysis.clip_proposals
        }
        requested_clip_ids = {clip.clip_id for clip in request.clips}
        unknown_clip_ids = requested_clip_ids.difference(proposals_by_id)
        if unknown_clip_ids:
            raise ValueError(f"unknown video clip proposal: {sorted(unknown_clip_ids)[0]}")
        kept_clips = [clip for clip in request.clips if clip.decision == VideoClipDecision.KEEP]
        if not selected_frame_ids and not kept_clips:
            raise ValueError("select at least one keeper frame or video clip")

        vault = VaultService(self.vault_root)
        generated_items: list[MediaItem] = []
        generated_items.extend(
            self._apply_video_keeper_selection(job, selected_frame_ids, vault)
        )

        for clip_commit in request.clips:
            analysis, proposal = proposals_by_id[clip_commit.clip_id]
            if not isfinite(clip_commit.start_seconds) or not isfinite(clip_commit.end_seconds):
                raise ValueError("clip seconds must be finite")
            if clip_commit.start_seconds < 0 or clip_commit.end_seconds > analysis.duration_seconds:
                raise ValueError("clip range must stay inside the source video")
            if clip_commit.end_seconds - clip_commit.start_seconds < 0.5:
                raise ValueError("video clips must be at least 0.5 seconds long")

            unchanged_materialized_clip = (
                proposal.output_media_item_id is not None
                and proposal.start_seconds == clip_commit.start_seconds
                and proposal.end_seconds == clip_commit.end_seconds
            )
            proposal.start_seconds = clip_commit.start_seconds
            proposal.end_seconds = clip_commit.end_seconds
            proposal.decision = clip_commit.decision
            if clip_commit.decision != VideoClipDecision.KEEP or unchanged_materialized_clip:
                continue

            source_item = vault.get_media_item(analysis.source_media_item_id)
            if source_item is None:
                raise ValueError(f"source media item not found: {analysis.source_media_item_id}")
            clips_dir = (
                self.derivatives_dir
                / "video_breakdowns"
                / job.id
                / source_item.id
                / "clips"
            )
            clip_path = clips_dir / (
                f"{proposal.id}_{clip_commit.start_seconds:.3f}_"
                f"{clip_commit.end_seconds:.3f}.mp4"
            )
            extract_video_clip(
                source_item.raw_path,
                clip_path,
                clip_commit.start_seconds,
                clip_commit.end_seconds,
            )
            derivative = vault.build_derivative_media_item(
                source_item=source_item,
                derivative_path=clip_path,
                media_type=MediaType.VIDEO,
                derivative_type=DerivativeType.VIDEO_CLIP,
                metadata={
                    "time_range": {
                        "start_seconds": clip_commit.start_seconds,
                        "end_seconds": clip_commit.end_seconds,
                    },
                    "clip_proposal_id": proposal.id,
                    "stable_range_ids": proposal.stable_range_ids,
                    "selection_reasons": ["user approved clip", *proposal.reasons[:2]],
                    "scores": proposal.scores.model_dump(mode="json"),
                    "generator": {
                        "name": analysis.analyzer,
                        "settings": {"reviewed_video_clip": True},
                    },
                },
            )
            derivative.duration = clip_commit.end_seconds - clip_commit.start_seconds
            derivative.width = source_item.width
            derivative.height = source_item.height
            proposal.output_media_item_id = derivative.id
            generated_items.append(derivative)

        if generated_items:
            resolved_items = vault.append_media_items(generated_items)
            job.derived_media_items.extend(resolved_items)
            resolution_by_id = {
                candidate.id: resolved
                for candidate, resolved in zip(generated_items, resolved_items, strict=True)
            }
            for analysis in job.video_analyses:
                for frame in analysis.frames:
                    if frame.output_media_item_id in resolution_by_id:
                        frame.output_media_item_id = resolution_by_id[
                            frame.output_media_item_id
                        ].id
                for proposal in analysis.clip_proposals:
                    if proposal.output_media_item_id in resolution_by_id:
                        proposal.output_media_item_id = resolution_by_id[
                            proposal.output_media_item_id
                        ].id
        job.progress_message = (
            f"Committed {len(selected_frame_ids)} frames and {len(kept_clips)} video clips"
        )
        self._save_job(job)
        return job

    def _apply_video_keeper_selection(
        self,
        job: ProcessingJob,
        selected_ids: set[str],
        vault: VaultService,
    ) -> list[MediaItem]:
        frames_by_id = {
            frame.id: (analysis, frame)
            for analysis in job.video_analyses
            for frame in analysis.frames
        }
        generated_items: list[MediaItem] = []
        for frame_id in selected_ids:
            analysis, frame = frames_by_id[frame_id]
            if frame.output_media_item_id is None:
                source_item = vault.get_media_item(analysis.source_media_item_id)
                if source_item is None:
                    raise ValueError(
                        f"source media item not found: {analysis.source_media_item_id}"
                    )
                frames_dir = (
                    self.derivatives_dir
                    / "video_breakdowns"
                    / job.id
                    / source_item.id
                    / "frames"
                )
                frame_path = frames_dir / f"manual_{frame.id}_{frame.timestamp_seconds:.3f}.png"
                extract_frame_at_timestamp(
                    source_item.raw_path,
                    frame_path,
                    frame.timestamp_seconds,
                )
                derivative = vault.build_derivative_media_item(
                    source_item=source_item,
                    derivative_path=frame_path,
                    media_type=MediaType.IMAGE,
                    derivative_type=DerivativeType.VIDEO_FRAME,
                    metadata={
                        "time_range": {
                            "start_seconds": frame.timestamp_seconds,
                            "end_seconds": frame.timestamp_seconds,
                        },
                        "analysis_frame_id": frame.id,
                        "stable_range_id": frame.stable_range_id,
                        "selection_reasons": ["user selected"],
                        "scores": frame.scores.model_dump(mode="json"),
                        "generator": {
                            "name": analysis.analyzer,
                            "settings": {"manual_keeper": True},
                        },
                    },
                )
                frame.output_media_item_id = derivative.id
                generated_items.append(derivative)
            frame.decision = VideoFrameDecision.KEEPER
            if "user selected" not in frame.reasons:
                frame.reasons = ["user selected", *frame.reasons[:2]]

        for frame_id, (_analysis, frame) in frames_by_id.items():
            if frame_id not in selected_ids and frame.decision == VideoFrameDecision.KEEPER:
                frame.decision = VideoFrameDecision.REJECTED
                frame.reasons = ["removed by user"]
        return generated_items

    def _save_job(self, job: ProcessingJob) -> None:
        with json_file_lock(self.jobs_path):
            jobs = self._read_jobs_unlocked()
            jobs[job.id] = job
            self._write_jobs(jobs)

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
    ) -> tuple[list[MediaItem], list[dict[str, str]], VideoBreakdownAnalysis | None]:
        derived_items: list[MediaItem] = []
        errors: list[dict[str, str]] = []
        analysis: VideoBreakdownAnalysis | None = None

        try:
            metadata = probe_video(source_item.raw_path)
        except RuntimeError as exc:
            return (
                [],
                [
                    {
                        "code": "video_probe_failed",
                        "message": str(exc),
                    }
                ],
                None,
            )

        requested_frame_duration = options.max_frame_count / options.frames_per_second
        end_seconds = min(metadata.duration_seconds, requested_frame_duration)

        if options.generate_frames and options.intelligent_selection:
            intelligent_items, intelligent_errors, analysis = self._generate_intelligent_frames(
                job_id=job_id,
                vault=vault,
                source_item=source_item,
                options=options,
                duration_seconds=metadata.duration_seconds,
            )
            derived_items.extend(intelligent_items)
            errors.extend(intelligent_errors)
        elif options.generate_frames:
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

        return derived_items, errors, analysis

    def _generate_intelligent_frames(
        self,
        *,
        job_id: str,
        vault: VaultService,
        source_item: MediaItem,
        options: VideoBreakdownOptions,
        duration_seconds: float,
    ) -> tuple[list[MediaItem], list[dict[str, str]], VideoBreakdownAnalysis | None]:
        analysis_dir = (
            self.derivatives_dir
            / "video_breakdowns"
            / job_id
            / source_item.id
            / "analysis"
        )
        frames_dir = (
            self.derivatives_dir
            / "video_breakdowns"
            / job_id
            / source_item.id
            / "frames"
        )
        analysis_dir.mkdir(parents=True, exist_ok=True)
        effective_fps = min(
            float(options.frames_per_second),
            options.max_analysis_frame_count / max(duration_seconds, 0.001),
        )
        effective_fps = max(0.05, effective_fps)
        try:
            thumbnails = extract_analysis_frames(
                source_item.raw_path,
                analysis_dir,
                duration_seconds=duration_seconds,
                frames_per_second=effective_fps,
                max_width=options.analysis_width,
            )
        except (RuntimeError, ValueError) as exc:
            return (
                [],
                [{"code": "video_analysis_failed", "message": str(exc)}],
                None,
            )

        for excess_thumbnail in thumbnails[options.max_analysis_frame_count :]:
            excess_thumbnail.unlink(missing_ok=True)
        thumbnails = thumbnails[: options.max_analysis_frame_count]
        if not thumbnails:
            return (
                [],
                [
                    {
                        "code": "no_frames_analyzed",
                        "message": "intelligent analysis did not produce any frames",
                    }
                ],
                None,
            )

        try:
            analysis = analyze_video_frames(
                source_media_item_id=source_item.id,
                duration_seconds=duration_seconds,
                frame_paths=thumbnails,
                sample_fps=effective_fps,
                max_keeper_count=options.max_frame_count,
            )
        except Exception as exc:
            return (
                [],
                [{"code": "video_analysis_failed", "message": str(exc)}],
                None,
            )

        derived_items: list[MediaItem] = []
        errors: list[dict[str, str]] = []
        keepers = [
            frame
            for frame in analysis.frames
            if frame.decision == VideoFrameDecision.KEEPER
        ]
        for index, frame in enumerate(keepers, start=1):
            frame_path = frames_dir / f"keeper_{index:04d}_{frame.timestamp_seconds:.3f}.png"
            try:
                extract_frame_at_timestamp(
                    source_item.raw_path,
                    frame_path,
                    frame.timestamp_seconds,
                )
                derivative = vault.build_derivative_media_item(
                    source_item=source_item,
                    derivative_path=frame_path,
                    media_type=MediaType.IMAGE,
                    derivative_type=DerivativeType.VIDEO_FRAME,
                    metadata={
                        "time_range": {
                            "start_seconds": frame.timestamp_seconds,
                            "end_seconds": frame.timestamp_seconds,
                        },
                        "analysis_frame_id": frame.id,
                        "stable_range_id": frame.stable_range_id,
                        "selection_reasons": frame.reasons,
                        "scores": frame.scores.model_dump(mode="json"),
                        "generator": {
                            "name": analysis.analyzer,
                            "settings": options.model_dump(mode="json"),
                        },
                    },
                )
            except (RuntimeError, ValueError, OSError) as exc:
                errors.append(
                    {
                        "code": "keeper_extraction_failed",
                        "message": f"{frame.timestamp_seconds:.3f}s: {exc}",
                    }
                )
                frame.decision = VideoFrameDecision.REJECTED
                frame.reasons = ["full-resolution extraction failed"]
                continue
            frame.output_media_item_id = derivative.id
            derived_items.append(derivative)

        if not derived_items:
            errors.append(
                {
                    "code": "no_keeper_frames",
                    "message": "analysis did not produce any full-resolution keeper frames",
                }
            )
        return derived_items, errors, analysis

    def _read_jobs(self) -> dict[str, ProcessingJob]:
        with json_file_lock(self.jobs_path):
            return self._read_jobs_unlocked()

    def _read_jobs_unlocked(self) -> dict[str, ProcessingJob]:
        if not self.jobs_path.exists():
            return {}
        payload = json.loads(self.jobs_path.read_text(encoding="utf-8"))
        return {
            job_id: ProcessingJob.model_validate(job_payload)
            for job_id, job_payload in payload.items()
        }

    def _write_jobs(self, jobs: dict[str, ProcessingJob]) -> None:
        with json_file_lock(self.jobs_path):
            self._write_jobs_unlocked(jobs)

    def _write_jobs_unlocked(self, jobs: dict[str, ProcessingJob]) -> None:
        atomic_write_json(
            self.jobs_path,
            {
                job_id: job.model_dump(mode="json")
                for job_id, job in jobs.items()
            },
        )
