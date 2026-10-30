import json
import shutil
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from lorasuite_engine.ffmpeg import extract_frame_at_timestamp
from lorasuite_engine.media_identity import canonical_identity_metadata
from lorasuite_engine.models import (
    IngressCandidate,
    IngressCandidateStatus,
    IngressJob,
    IngressJobStatus,
    IngressScanResult,
    MediaType,
    SourceKind,
    utc_now,
)
from lorasuite_engine.raw_images import is_raw_image, materialize_raw_image
from lorasuite_engine.storage import atomic_write_json, json_file_lock
from lorasuite_engine.vault import VaultService, detect_media_type, image_dimensions

MAX_REMOTE_DOWNLOAD_BYTES = 1024 * 1024 * 1024
REMOTE_DOWNLOAD_SUFFIXES_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
REMOTE_DOWNLOAD_SUFFIXES_BY_MEDIA_TYPE = {
    MediaType.IMAGE: ".jpg",
    MediaType.VIDEO: ".mp4",
    MediaType.AUDIO: ".m4a",
}
REMOTE_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
REMOTE_IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png"})
REMOTE_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def curation_metadata_for_candidate(candidate: IngressCandidate) -> dict[str, Any]:
    identity_metadata = canonical_identity_metadata(
        candidate.source_kind,
        candidate.metadata_json,
        candidate.source_locator,
        candidate.media_type,
    )
    bundle_key = identity_metadata["source_bundle_key"]
    lane = candidate.media_type.value if candidate.media_type is not None else "unknown"
    return {
        **candidate.metadata_json,
        **identity_metadata,
        "source_bundle_key": bundle_key,
        "source_kind": candidate.source_kind.value,
        "source_locator": candidate.source_locator,
        "display_name": candidate.display_name,
        "ingress_candidate_id": candidate.id,
        "curation_lane": lane,
        "ingress_record": {
            "candidate_id": candidate.id,
            "bundle_key": bundle_key,
            "lane": lane,
            "source_locator": candidate.source_locator,
        },
    }


class IngressService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def candidates_path(self) -> Path:
        return self.vault_root / "ingress_candidates.json"

    @property
    def jobs_path(self) -> Path:
        return self.vault_root / "ingress_jobs.json"

    @property
    def previews_dir(self) -> Path:
        return self.vault_root / "previews"

    def scan_local_roots(
        self, roots: list[Path], *, recursive: bool = True
    ) -> IngressScanResult:
        result = IngressScanResult()

        for root in roots:
            root_path = Path(root)
            if not root_path.exists():
                result.errors.append(
                    {
                        "path": str(root_path),
                        "code": "missing_path",
                        "message": "path does not exist",
                    }
                )
                continue

            for path in self._expand_root(root_path, recursive=recursive):
                result.candidates.append(self._candidate_for_path(path))

        self.store_candidates(result.candidates)
        return result

    def store_candidates(self, candidates: list[IngressCandidate]) -> None:
        stored_candidates = self._read_candidates()
        for candidate in candidates:
            stored_candidates[candidate.id] = candidate
        self._write_candidates(stored_candidates)

    def create_job(
        self,
        source_kind: SourceKind,
        candidate_ids: list[str],
        options: dict[str, Any] | None = None,
        reviewed_candidate_ids: list[str] | None = None,
    ) -> IngressJob:
        reviewed_ids = reviewed_candidate_ids or candidate_ids
        job = IngressJob(
            source_kind=source_kind,
            candidate_ids=candidate_ids,
            reviewed_candidate_ids=reviewed_ids,
            options=options or {},
            candidate_count=len(reviewed_ids),
            selected_count=len(candidate_ids),
        )
        jobs = self._read_jobs()
        jobs[job.id] = job
        self._write_jobs(jobs)
        return job

    def process_job(self, job_id: str) -> IngressJob:
        jobs = self._read_jobs()
        job = jobs[job_id]
        job.status = IngressJobStatus.RUNNING
        job.started_at = utc_now()
        job.progress_message = "Importing selected media"
        jobs[job.id] = job
        self._write_jobs(jobs)

        candidates = self._read_candidates()
        reviewed_candidate_ids = job.reviewed_candidate_ids or job.candidate_ids
        selected_candidate_ids = set(job.candidate_ids)
        review_deferred_candidates = [
            self._review_deferred_for_candidate(candidates.get(candidate_id), candidate_id)
            for candidate_id in reviewed_candidate_ids
            if candidate_id not in selected_candidate_ids
        ]
        selected_candidates = [
            candidates[candidate_id]
            for candidate_id in job.candidate_ids
            if candidate_id in candidates
        ]
        direct_import_paths = [
            import_path
            for candidate in selected_candidates
            if candidate.status == IngressCandidateStatus.READY
            for import_path in [self._import_path_for_candidate(candidate)]
            if import_path is not None
        ]
        (
            downloaded_import_paths,
            download_errors,
            handled_download_candidate_ids,
        ) = self._download_remote_candidates(selected_candidates)
        ready_import_paths = direct_import_paths + downloaded_import_paths
        deferred_downloads = [
            deferred_download
            for candidate in selected_candidates
            if candidate.status == IngressCandidateStatus.READY
            and self._import_path_for_candidate(candidate) is None
            and candidate.id not in handled_download_candidate_ids
            for deferred_download in [self._deferred_download_for_candidate(candidate)]
            if deferred_download is not None
        ]
        rejected_candidates = [
            candidate
            for candidate in selected_candidates
            if candidate.status != IngressCandidateStatus.READY
            or (
                self._import_path_for_candidate(candidate) is None
                and candidate.id not in handled_download_candidate_ids
                and self._deferred_download_for_candidate(candidate) is None
            )
        ]

        destination_vault = VaultService(self._destination_root_for_job(job))
        import_result = destination_vault.import_local_paths(ready_import_paths)
        annotated_media_items = []
        for index, media_item in enumerate(import_result.media_items):
            original_path = media_item.metadata_json.get("original_path")
            fallback_path = ready_import_paths[index] if index < len(ready_import_paths) else None
            candidate = self._candidate_for_imported_path(
                Path(original_path) if isinstance(original_path, str) else fallback_path,
                selected_candidates,
            )
            if candidate is None:
                annotated_media_items.append(media_item)
                continue
            try:
                annotated_media_items.append(
                    destination_vault.annotate_media_item(
                        media_item.id,
                        metadata=self._curation_metadata(candidate),
                        duration=candidate.duration,
                        width=candidate.width,
                        height=candidate.height,
                    )
                )
            except KeyError:
                annotated_media_items.append(media_item)
        missing_ids = [
            candidate_id for candidate_id in job.candidate_ids if candidate_id not in candidates
        ]

        job.imported_media_items = annotated_media_items
        job.imported_count = len(annotated_media_items)
        job.deferred_candidates = review_deferred_candidates + deferred_downloads
        job.deferred_count = len(job.deferred_candidates)
        job.failed_count = (
            len(import_result.errors)
            + len(download_errors)
            + len(rejected_candidates)
            + len(missing_ids)
        )
        job.skipped_count = max(
            0,
            len(job.candidate_ids)
            - job.imported_count
            - job.deferred_count
            - job.failed_count,
        )
        job.errors = [
            error.model_dump(mode="json") for error in import_result.errors
        ] + download_errors + [
            {
                "path": candidate.source_locator,
                "code": candidate.status.value,
                "message": candidate.error_message or "candidate is not ready",
            }
            for candidate in rejected_candidates
        ] + [
            {
                "path": candidate_id,
                "code": "missing_candidate",
                "message": "candidate was not found in the ingress store",
            }
            for candidate_id in missing_ids
        ]
        job.status = (
            IngressJobStatus.COMPLETE
            if job.failed_count == 0
            else IngressJobStatus.FAILED
        )
        if job.status == IngressJobStatus.COMPLETE:
            if review_deferred_candidates and deferred_downloads:
                job.progress_message = "Ingress complete; candidates and original downloads deferred"
            elif deferred_downloads:
                job.progress_message = "Ingress complete; original downloads deferred"
            elif review_deferred_candidates:
                job.progress_message = "Ingress complete; candidates deferred"
            else:
                job.progress_message = "Ingress complete"
        else:
            job.progress_message = "Ingress completed with errors"
        job.completed_at = utc_now()
        jobs[job.id] = job
        self._write_jobs(jobs)
        return job

    def list_jobs(self) -> list[IngressJob]:
        return sorted(
            self._read_jobs().values(),
            key=lambda job: job.created_at,
            reverse=True,
        )

    def list_candidates(
        self, source_kind: SourceKind | None = None
    ) -> list[IngressCandidate]:
        candidates = list(self._read_candidates().values())
        if source_kind is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.source_kind == source_kind
            ]
        return sorted(candidates, key=lambda candidate: candidate.display_name.lower())

    def get_job(self, job_id: str) -> IngressJob | None:
        return self._read_jobs().get(job_id)

    def prepare_candidate_video_preview(self, candidate_id: str) -> Path:
        candidate = self._read_candidates().get(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if candidate.media_type != MediaType.VIDEO:
            raise ValueError("candidate is not a video")

        if candidate.source_kind == SourceKind.TIKTOK:
            return self._download_tiktok_candidate(candidate)
        if candidate.source_kind != SourceKind.X_TWITTER:
            raise ValueError("local video preview proxy supports X and TikTok candidates only")

        download_url = self._download_url_for_candidate(candidate)
        if download_url is None:
            raise ValueError("candidate does not have a video download URL")
        parsed = urlparse(download_url)
        if parsed.scheme != "https" or parsed.hostname != "video.twimg.com":
            raise ValueError("X preview URL is not hosted by video.twimg.com")
        return self._download_remote_candidate(candidate, download_url)

    def prepare_candidate_thumbnail(self, candidate_id: str) -> Path:
        candidates = self._read_candidates()
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)

        existing_path = candidate.thumbnail_path or candidate.poster_asset_path
        if existing_path is not None and existing_path.exists():
            return existing_path

        parent_id = candidate.metadata_json.get("source_video_candidate_id")
        if candidate.media_type == MediaType.VIDEO:
            video_candidate = candidate
        elif (
            candidate.media_type == MediaType.IMAGE
            and candidate.metadata_json.get("asset_role") == "video_poster"
            and isinstance(parent_id, str)
        ):
            video_candidate = candidates.get(parent_id)
        else:
            video_candidate = None

        if video_candidate is None or video_candidate.media_type != MediaType.VIDEO:
            raise ValueError("candidate does not have a source video for thumbnail generation")
        if video_candidate.source_kind != SourceKind.X_TWITTER:
            raise ValueError("generated social thumbnails currently support X videos only")

        video_path = self.prepare_candidate_video_preview(video_candidate.id)
        thumbnail_dir = self.vault_root / "previews" / "x_twitter"
        thumbnail_path = thumbnail_dir / f"{video_candidate.id}_poster.png"
        if not thumbnail_path.exists():
            extract_frame_at_timestamp(video_path, thumbnail_path, 0.1)

        video_candidate.thumbnail_path = thumbnail_path
        video_candidate.poster_asset_path = thumbnail_path
        candidates[video_candidate.id] = video_candidate
        found_image_candidate = False
        for related in candidates.values():
            if related.metadata_json.get("source_video_candidate_id") != video_candidate.id:
                continue
            related.thumbnail_path = thumbnail_path
            if related.media_type == MediaType.IMAGE:
                found_image_candidate = True
                related.source_locator = str(thumbnail_path)
                related.metadata_json["local_import_path"] = str(thumbnail_path)
                related.metadata_json["materialize_from_video"] = False
            candidates[related.id] = related
        if not found_image_candidate:
            poster_candidate = IngressCandidate(
                id=f"{video_candidate.id}_poster",
                source_kind=video_candidate.source_kind,
                source_locator=str(thumbnail_path),
                display_name=f"{video_candidate.display_name} poster",
                media_type=MediaType.IMAGE,
                width=video_candidate.width,
                height=video_candidate.height,
                thumbnail_path=thumbnail_path,
                status=IngressCandidateStatus.READY,
                selected=True,
                metadata_json={
                    **video_candidate.metadata_json,
                    "source_video_candidate_id": video_candidate.id,
                    "local_import_path": str(thumbnail_path),
                    "asset_role": "video_poster",
                    "materialize_from_video": False,
                },
            )
            candidates[poster_candidate.id] = poster_candidate
        self._write_candidates(candidates)
        return thumbnail_path

    def _destination_root_for_job(self, job: IngressJob) -> Path:
        destination_root = job.options.get("destination_root")
        if isinstance(destination_root, str) and destination_root.strip():
            return Path(destination_root).expanduser()
        return self.vault_root

    def _import_path_for_candidate(self, candidate: IngressCandidate) -> Path | None:
        if candidate.source_kind == SourceKind.LOCAL:
            return Path(candidate.source_locator)

        local_import_path = candidate.metadata_json.get("local_import_path")
        if isinstance(local_import_path, str) and local_import_path:
            return Path(local_import_path)
        return None

    def _download_remote_candidates(
        self, candidates: list[IngressCandidate]
    ) -> tuple[list[Path], list[dict[str, str]], set[str]]:
        downloaded_paths: list[Path] = []
        errors: list[dict[str, str]] = []
        handled_candidate_ids: set[str] = set()

        for candidate in candidates:
            if candidate.status != IngressCandidateStatus.READY:
                continue
            if self._import_path_for_candidate(candidate) is not None:
                continue

            try:
                if candidate.metadata_json.get("asset_role") == "video_poster":
                    handled_candidate_ids.add(candidate.id)
                    downloaded_paths.append(self.prepare_candidate_thumbnail(candidate.id))
                    continue
                if candidate.source_kind == SourceKind.TIKTOK:
                    handled_candidate_ids.add(candidate.id)
                    downloaded_paths.append(self._download_tiktok_candidate(candidate))
                    continue

                download_url = self._download_url_for_candidate(candidate)
                if download_url is None:
                    continue
                handled_candidate_ids.add(candidate.id)
                downloaded_paths.append(self._download_remote_candidate(candidate, download_url))
            except (HTTPError, OSError, RuntimeError, URLError, ValueError) as exc:
                errors.append(
                    {
                        "path": candidate.source_locator,
                        "code": "download_failed",
                        "message": f"could not download original media: {exc}",
                    }
                )

        return downloaded_paths, errors, handled_candidate_ids

    def _download_tiktok_candidate(self, candidate: IngressCandidate) -> Path:
        target_dir = self.vault_root / "downloads" / SourceKind.TIKTOK.value
        target_dir.mkdir(parents=True, exist_ok=True)
        if candidate.media_type == MediaType.VIDEO:
            existing = next(
                (
                    path
                    for path in target_dir.glob(f"{candidate.id}.*")
                    if path.is_file() and path.suffix.lower() in REMOTE_VIDEO_SUFFIXES
                ),
                None,
            )
            if existing is not None:
                return existing
        source_path = self._download_tiktok_source(candidate, target_dir)
        if candidate.media_type == MediaType.AUDIO:
            audio_path = target_dir / f"{candidate.id}.m4a"
            if audio_path.exists():
                return audio_path
            return self._extract_audio_from_video(source_path, audio_path)
        if candidate.media_type != MediaType.VIDEO:
            raise ValueError("TikTok source download is only available for video or audio candidates")

        target_path = target_dir / f"{candidate.id}{source_path.suffix.lower()}"
        if not target_path.exists():
            shutil.copy2(source_path, target_path)
        return target_path

    def _download_tiktok_source(
        self,
        candidate: IngressCandidate,
        target_dir: Path,
    ) -> Path:
        source_url = candidate.metadata_json.get("source_url") or candidate.source_locator
        if not isinstance(source_url, str) or not source_url:
            raise ValueError("TikTok candidate does not include a source URL")
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "tiktok.com",
            "www.tiktok.com",
            "m.tiktok.com",
            "vm.tiktok.com",
            "vt.tiktok.com",
        }:
            raise ValueError("TikTok source URL is not supported")
        browser = str(candidate.metadata_json.get("browser_source") or "chrome").lower()
        if browser not in {
            "brave",
            "chrome",
            "chromium",
            "edge",
            "firefox",
            "opera",
            "safari",
            "vivaldi",
        }:
            raise ValueError("TikTok browser cookie source is not supported")

        raw_media_id = str(candidate.metadata_json.get("platform_media_id") or candidate.id)
        media_id = "".join(character for character in raw_media_id if character.isalnum() or character in {"-", "_"})
        if not media_id:
            raise ValueError("TikTok candidate media ID is invalid")
        source_stem = f"source_{media_id}"
        existing = next(
            (
                path
                for path in target_dir.glob(f"{source_stem}.*")
                if path.is_file() and path.suffix.lower() in REMOTE_VIDEO_SUFFIXES
            ),
            None,
        )
        if existing is not None:
            return existing

        output_template = target_dir / f"{source_stem}.%(ext)s"
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--cookies-from-browser",
            browser,
            "--no-playlist",
            "--no-warnings",
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
            "--output",
            str(output_template),
            "--print",
            "after_move:filepath",
            source_url,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=900,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f"yt-dlp could not download TikTok media: {error}") from error
        if completed.returncode != 0:
            detail_lines = [
                line.strip()
                for line in (completed.stderr or completed.stdout).splitlines()
                if line.strip()
            ]
            detail = detail_lines[-1][:500] if detail_lines else "unknown extractor error"
            raise ValueError(f"TikTok download failed: {detail}")

        printed_paths = [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]
        downloaded = next(
            (
                path
                for path in reversed(printed_paths)
                if path.exists()
                and path.is_file()
                and path.suffix.lower() in REMOTE_VIDEO_SUFFIXES
                and path.parent.resolve() == target_dir.resolve()
            ),
            None,
        )
        if downloaded is None:
            downloaded = next(
                (
                    path
                    for path in target_dir.glob(f"{source_stem}.*")
                    if path.is_file() and path.suffix.lower() in REMOTE_VIDEO_SUFFIXES
                ),
                None,
            )
        if downloaded is None:
            raise ValueError("yt-dlp completed without a supported TikTok video file")
        return downloaded

    def _download_url_for_candidate(self, candidate: IngressCandidate) -> str | None:
        if candidate.source_kind == SourceKind.LOCAL:
            return None
        download_url = candidate.metadata_json.get("download_url")
        if isinstance(download_url, str) and download_url:
            return download_url
        return None

    def _candidate_for_imported_path(
        self,
        path: Path | None,
        candidates: list[IngressCandidate],
    ) -> IngressCandidate | None:
        if path is None:
            return None
        for candidate in candidates:
            import_path = self._import_path_for_candidate(candidate)
            if import_path is not None and import_path == path:
                return candidate
            if path.name == candidate.id or path.name.startswith(f"{candidate.id}."):
                return candidate
        return None

    def _curation_metadata(self, candidate: IngressCandidate) -> dict[str, Any]:
        return curation_metadata_for_candidate(candidate)

    def _download_remote_candidate(
        self,
        candidate: IngressCandidate,
        download_url: str,
    ) -> Path:
        parsed = urlparse(download_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("download URL must be http or https")

        target_dir = self.vault_root / "downloads" / candidate.source_kind.value
        target_dir.mkdir(parents=True, exist_ok=True)
        if candidate.media_type == MediaType.AUDIO:
            return self._download_remote_audio_candidate(candidate, download_url, target_dir)

        suffix = self._remote_download_suffix(
            download_url,
            media_type=candidate.media_type,
        )
        target_path = target_dir / f"{candidate.id}{suffix}"
        if target_path.exists():
            return target_path

        self._download_remote_file(
            candidate,
            download_url,
            target_path,
            media_type=candidate.media_type,
        )
        return target_path

    def _download_remote_audio_candidate(
        self,
        candidate: IngressCandidate,
        download_url: str,
        target_dir: Path,
    ) -> Path:
        audio_path = target_dir / f"{candidate.id}.m4a"
        if audio_path.exists():
            return audio_path

        source_suffix = self._remote_video_source_suffix(download_url)
        source_path = target_dir / f"{candidate.id}.source{source_suffix}"
        if not source_path.exists():
            self._download_remote_file(
                candidate,
                download_url,
                source_path,
                media_type=MediaType.VIDEO,
            )
        return self._extract_audio_from_video(source_path, audio_path)

    def _download_remote_file(
        self,
        candidate: IngressCandidate,
        download_url: str,
        target_path: Path,
        *,
        media_type: MediaType | None,
    ) -> Path:
        suffix = target_path.suffix.lower()

        temporary_path = target_path.with_name(
            f".{target_path.name}.{uuid4().hex}.tmp"
        )
        request = Request(
            download_url,
            headers={
                "User-Agent": WEB_USER_AGENT,
                "Accept": self._remote_download_accept_header(media_type),
                "Referer": candidate.source_locator,
            },
        )
        try:
            with urlopen(request, timeout=120, context=self._ssl_context()) as response:
                content_type = response.headers.get_content_type().lower()
                self._validate_remote_download_suffix(
                    suffix,
                    content_type=content_type,
                    media_type=media_type,
                )
                content_length = response.headers.get("Content-Length")
                if (
                    content_length is not None
                    and int(content_length) > MAX_REMOTE_DOWNLOAD_BYTES
                ):
                    raise ValueError("remote media is larger than the download limit")

                bytes_written = 0
                with temporary_path.open("wb") as file:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        bytes_written += len(chunk)
                        if bytes_written > MAX_REMOTE_DOWNLOAD_BYTES:
                            raise ValueError(
                                "remote media is larger than the download limit"
                            )
                        file.write(chunk)

                if bytes_written == 0:
                    raise ValueError("remote media response was empty")
                temporary_path.replace(target_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        return target_path

    def _extract_audio_from_video(self, video_path: Path, audio_path: Path) -> Path:
        temporary_path = audio_path.with_name(f".{audio_path.stem}.{uuid4().hex}.m4a")
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "aac",
            "-b:a",
            "192k",
            str(temporary_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=180,
            )
        except subprocess.SubprocessError as error:
            if temporary_path.exists():
                temporary_path.unlink()
            raise ValueError(f"could not extract audio with ffmpeg: {error}") from error
        if completed.returncode != 0:
            if temporary_path.exists():
                temporary_path.unlink()
            message = (completed.stderr or completed.stdout).strip()
            raise ValueError(f"could not extract audio with ffmpeg: {message}")
        temporary_path.replace(audio_path)
        return audio_path

    def _remote_download_suffix(
        self,
        download_url: str,
        *,
        media_type: MediaType | None,
    ) -> str:
        suffix = Path(urlparse(download_url).path).suffix.lower()
        if suffix in REMOTE_IMAGE_SUFFIXES | REMOTE_VIDEO_SUFFIXES:
            return suffix
        if media_type in REMOTE_DOWNLOAD_SUFFIXES_BY_MEDIA_TYPE:
            return REMOTE_DOWNLOAD_SUFFIXES_BY_MEDIA_TYPE[media_type]
        return ".bin"

    def _remote_video_source_suffix(self, download_url: str) -> str:
        suffix = Path(urlparse(download_url).path).suffix.lower()
        if suffix in REMOTE_VIDEO_SUFFIXES:
            return suffix
        return ".mp4"

    def _validate_remote_download_suffix(
        self,
        suffix: str,
        *,
        content_type: str,
        media_type: MediaType | None,
    ) -> None:
        expected_suffix = REMOTE_DOWNLOAD_SUFFIXES_BY_CONTENT_TYPE.get(content_type)
        if expected_suffix is not None and suffix == expected_suffix:
            return
        if media_type == MediaType.IMAGE and (
            content_type in REMOTE_IMAGE_CONTENT_TYPES or suffix in REMOTE_IMAGE_SUFFIXES
        ):
            return
        if media_type == MediaType.VIDEO and suffix in REMOTE_VIDEO_SUFFIXES:
            return
        raise ValueError(f"unsupported remote media content type: {content_type}")

    def _remote_download_accept_header(self, media_type: MediaType | None) -> str:
        if media_type == MediaType.IMAGE:
            return "image/jpeg,image/png,image/*,*/*"
        if media_type == MediaType.VIDEO:
            return "video/mp4,video/*,*/*"
        return "*/*"

    def _ssl_context(self) -> ssl.SSLContext:
        try:
            import certifi

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()

    def _deferred_download_for_candidate(
        self, candidate: IngressCandidate
    ) -> dict[str, Any] | None:
        if candidate.source_kind == SourceKind.LOCAL:
            return None

        download_url = candidate.metadata_json.get("download_url")
        source_url = candidate.metadata_json.get("source_url")
        source_locator = candidate.source_locator
        if not download_url and not source_url and not source_locator:
            return None

        return {
            "candidate_id": candidate.id,
            "display_name": candidate.display_name,
            "media_type": candidate.media_type.value if candidate.media_type else None,
            "source_kind": candidate.source_kind.value,
            "source_locator": source_locator,
            "download_url": download_url if isinstance(download_url, str) else None,
            "source_url": source_url if isinstance(source_url, str) and source_url else None,
            "reason": "original download requires session helper transfer",
        }

    def _review_deferred_for_candidate(
        self,
        candidate: IngressCandidate | None,
        candidate_id: str,
    ) -> dict[str, Any]:
        if candidate is None:
            return {
                "candidate_id": candidate_id,
                "reason": "not selected for this ingress batch",
            }

        return {
            "candidate_id": candidate.id,
            "display_name": candidate.display_name,
            "media_type": candidate.media_type.value if candidate.media_type else None,
            "source_kind": candidate.source_kind.value,
            "source_locator": candidate.source_locator,
            "reason": "not selected for this ingress batch",
        }

    def _expand_root(self, root: Path, *, recursive: bool) -> list[Path]:
        if root.is_file():
            return [root]
        if not root.is_dir():
            return []

        iterator = root.rglob("*") if recursive else root.iterdir()
        return sorted(path for path in iterator if path.is_file())

    def _candidate_for_path(self, path: Path) -> IngressCandidate:
        media_type = detect_media_type(path)
        if media_type is None:
            return IngressCandidate(
                source_kind=SourceKind.LOCAL,
                source_locator=str(path),
                display_name=path.name,
                size_bytes=self._safe_size(path),
                status=IngressCandidateStatus.UNSUPPORTED,
                error_message="suffix is not supported",
                selected=False,
            )

        width: int | None = None
        height: int | None = None
        thumbnail_path: Path | None = None
        status = IngressCandidateStatus.READY
        error_message: str | None = None

        if media_type == MediaType.IMAGE:
            try:
                width, height = image_dimensions(path)
                thumbnail_path = self._create_image_thumbnail(path)
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                status = IngressCandidateStatus.ERROR
                error_message = f"image could not be decoded: {exc}"

        return IngressCandidate(
            source_kind=SourceKind.LOCAL,
            source_locator=str(path),
            display_name=path.name,
            media_type=media_type,
            size_bytes=self._safe_size(path),
            width=width,
            height=height,
            thumbnail_path=thumbnail_path,
            status=status,
            error_message=error_message,
            selected=status == IngressCandidateStatus.READY,
            metadata_json={"suffix": path.suffix.lower()},
        )

    def _create_image_thumbnail(self, path: Path) -> Path:
        self.previews_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = self.previews_dir / f"{path.stem}-{path.stat().st_size}.jpg"
        if thumbnail_path.exists():
            return thumbnail_path

        preview_source = path
        temporary_raw_preview: Path | None = None
        if is_raw_image(path):
            temporary_raw_preview = self.previews_dir / f".raw-preview-{uuid4().hex}.jpg"
            materialize_raw_image(path, temporary_raw_preview)
            preview_source = temporary_raw_preview
        try:
            with Image.open(preview_source) as image:
                image.thumbnail((320, 320))
                image.convert("RGB").save(thumbnail_path, "JPEG", quality=85)
        finally:
            if temporary_raw_preview is not None:
                temporary_raw_preview.unlink(missing_ok=True)
        return thumbnail_path

    def _safe_size(self, path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

    def _read_candidates(self) -> dict[str, IngressCandidate]:
        data = self._read_json(self.candidates_path, default={"candidates": []})
        return {
            item["id"]: IngressCandidate.model_validate(item)
            for item in data.get("candidates", [])
        }

    def _write_candidates(self, candidates: dict[str, IngressCandidate]) -> None:
        self._write_json(
            self.candidates_path,
            {
                "version": 1,
                "candidates": [
                    candidate.model_dump(mode="json")
                    for candidate in candidates.values()
                ]
            },
        )

    def _read_jobs(self) -> dict[str, IngressJob]:
        data = self._read_json(self.jobs_path, default={"jobs": []})
        return {item["id"]: IngressJob.model_validate(item) for item in data.get("jobs", [])}

    def _write_jobs(self, jobs: dict[str, IngressJob]) -> None:
        self._write_json(
            self.jobs_path,
            {
                "version": 1,
                "jobs": [job.model_dump(mode="json") for job in jobs.values()],
            },
        )

    def _read_json(self, path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
        with json_file_lock(path):
            if not path.exists():
                return default
            return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        with json_file_lock(path):
            atomic_write_json(path, payload)
