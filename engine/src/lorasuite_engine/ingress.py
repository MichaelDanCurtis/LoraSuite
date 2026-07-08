import json
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

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
from lorasuite_engine.vault import VaultService, detect_media_type, image_dimensions

MAX_REMOTE_DOWNLOAD_BYTES = 1024 * 1024 * 1024
REMOTE_DOWNLOAD_SUFFIXES_BY_CONTENT_TYPE = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
REMOTE_DOWNLOAD_SUFFIXES_BY_MEDIA_TYPE = {
    MediaType.VIDEO: ".mp4",
    MediaType.AUDIO: ".m4a",
}
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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

    def create_job(self, source_kind: SourceKind, candidate_ids: list[str]) -> IngressJob:
        job = IngressJob(
            source_kind=source_kind,
            candidate_ids=candidate_ids,
            candidate_count=len(candidate_ids),
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

        import_result = VaultService(self.vault_root).import_local_paths(ready_import_paths)
        missing_ids = [
            candidate_id for candidate_id in job.candidate_ids if candidate_id not in candidates
        ]

        job.imported_media_items = import_result.media_items
        job.imported_count = len(import_result.media_items)
        job.deferred_candidates = deferred_downloads
        job.deferred_count = len(deferred_downloads)
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
            job.progress_message = (
                "Ingress complete; original downloads deferred"
                if job.deferred_count
                else "Ingress complete"
            )
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

            download_url = self._download_url_for_candidate(candidate)
            if download_url is None:
                continue

            handled_candidate_ids.add(candidate.id)
            try:
                downloaded_paths.append(
                    self._download_remote_candidate(candidate, download_url)
                )
            except (HTTPError, OSError, URLError, ValueError) as exc:
                errors.append(
                    {
                        "path": candidate.source_locator,
                        "code": "download_failed",
                        "message": f"could not download original media: {exc}",
                    }
                )

        return downloaded_paths, errors, handled_candidate_ids

    def _download_url_for_candidate(self, candidate: IngressCandidate) -> str | None:
        if candidate.source_kind == SourceKind.LOCAL:
            return None
        download_url = candidate.metadata_json.get("download_url")
        if isinstance(download_url, str) and download_url:
            return download_url
        return None

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
        suffix = self._remote_download_suffix(
            download_url,
            media_type=candidate.media_type,
        )
        target_path = target_dir / f"{candidate.id}{suffix}"
        if target_path.exists():
            return target_path

        temporary_path = target_path.with_name(
            f".{target_path.name}.{uuid4().hex}.tmp"
        )
        request = Request(
            download_url,
            headers={
                "User-Agent": WEB_USER_AGENT,
                "Accept": "video/mp4,video/*,*/*",
                "Referer": candidate.source_locator,
            },
        )
        try:
            with urlopen(request, timeout=120, context=self._ssl_context()) as response:
                content_type = response.headers.get_content_type().lower()
                self._validate_remote_download_suffix(
                    suffix,
                    content_type=content_type,
                    media_type=candidate.media_type,
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

    def _remote_download_suffix(
        self,
        download_url: str,
        *,
        media_type: MediaType | None,
    ) -> str:
        suffix = Path(urlparse(download_url).path).suffix.lower()
        if suffix in {".mp4", ".mov", ".m4v", ".webm"}:
            return suffix
        if media_type in REMOTE_DOWNLOAD_SUFFIXES_BY_MEDIA_TYPE:
            return REMOTE_DOWNLOAD_SUFFIXES_BY_MEDIA_TYPE[media_type]
        return ".bin"

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
        if media_type == MediaType.VIDEO and suffix in {".mp4", ".mov", ".m4v", ".webm"}:
            return
        raise ValueError(f"unsupported remote media content type: {content_type}")

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
                error_message = f"image could not be read by Pillow: {exc}"

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

        with Image.open(path) as image:
            image.thumbnail((320, 320))
            image.convert("RGB").save(thumbnail_path, "JPEG", quality=85)
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
            {"jobs": [job.model_dump(mode="json") for job in jobs.values()]},
        )

    def _read_json(self, path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
