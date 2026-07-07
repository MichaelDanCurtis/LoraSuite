import json
from pathlib import Path
from typing import Any

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

        stored_candidates = self._read_candidates()
        for candidate in result.candidates:
            stored_candidates[candidate.id] = candidate
        self._write_candidates(stored_candidates)
        return result

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
        ready_local_paths = [
            Path(candidate.source_locator)
            for candidate in selected_candidates
            if candidate.source_kind == SourceKind.LOCAL
            and candidate.status == IngressCandidateStatus.READY
        ]
        rejected_candidates = [
            candidate
            for candidate in selected_candidates
            if candidate.source_kind != SourceKind.LOCAL
            or candidate.status != IngressCandidateStatus.READY
        ]

        import_result = VaultService(self.vault_root).import_local_paths(ready_local_paths)
        missing_ids = [
            candidate_id for candidate_id in job.candidate_ids if candidate_id not in candidates
        ]

        job.imported_media_items = import_result.media_items
        job.imported_count = len(import_result.media_items)
        job.failed_count = (
            len(import_result.errors) + len(rejected_candidates) + len(missing_ids)
        )
        job.skipped_count = max(
            0,
            len(job.candidate_ids) - job.imported_count - job.failed_count,
        )
        job.errors = [
            error.model_dump(mode="json") for error in import_result.errors
        ] + [
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
        job.progress_message = (
            "Ingress complete"
            if job.status == IngressJobStatus.COMPLETE
            else "Ingress completed with errors"
        )
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

    def get_job(self, job_id: str) -> IngressJob | None:
        return self._read_jobs().get(job_id)

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
