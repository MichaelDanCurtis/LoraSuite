# Ingress Review Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the next LoraSuite ingress slice: scan local files/folders into reviewable candidates, let the user select candidates in tile/list/gallery views, and run confirmed ingestion through visible asynchronous jobs.

**Architecture:** Add a small Python ingress service that persists scan candidates and ingress jobs under the vault root, then expose it through FastAPI endpoints. The React UI replaces path-paste import with candidate review controls, while retaining a manual path fallback for browser-only development where Tauri's native dialog is unavailable.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, Pillow, React 19, TypeScript, Vite, Tauri dialog plugin, Vitest, Testing Library, pytest.

---

## File Structure

Engine:

- Modify `engine/src/lorasuite_engine/models.py`
  - Add `AssetType.THUMBNAIL` and `AssetType.POSTER`.
  - Add `IngressCandidateStatus`, `IngressJobStatus`, `IngressCandidate`, `IngressScanResult`, and `IngressJob`.
- Create `engine/src/lorasuite_engine/ingress.py`
  - Own local scan, candidate persistence, job persistence, local job processing, and thumbnail creation.
- Modify `engine/src/lorasuite_engine/api.py`
  - Add local scan endpoint, job creation endpoint, job list endpoint, and job detail endpoint.
- Add `engine/tests/test_ingress.py`
  - Cover local scans, unsupported candidates, jobs importing only selected candidates, and poster/thumbnail model support.
- Modify `engine/tests/test_api.py`
  - Cover new HTTP endpoints.

Frontend:

- Modify `src/lib/types.ts`
  - Add ingress candidate/job request and response types.
- Modify `src/lib/api.ts`
  - Add `scanLocalIngress`, `createIngressJob`, `listIngressJobs`, and `getIngressJob`.
- Modify `src/lib/api.test.ts`
  - Cover the new HTTP client methods.
- Modify `src/components/DataIngressTab.tsx`
  - Replace path-paste-first UI with source buttons, candidate review, view modes, selection controls, and jobs table.
- Modify `src/App.tsx`
  - Append imported media items when completed jobs return them.
- Modify `src/App.test.tsx`
  - Cover the user-visible local ingress flow and view switching.
- Modify `src/styles.css`
  - Add dense, work-focused layouts for candidate grid/list/gallery and jobs table.
- Modify `docs/development.md`
  - Document the new local ingress flow and browser fallback.

---

## Task 1: Add Ingress Models

**Files:**
- Modify: `engine/src/lorasuite_engine/models.py`
- Test: `engine/tests/test_ingress.py`

- [ ] **Step 1: Write the failing model tests**

Create `engine/tests/test_ingress.py` with:

```python
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
```

- [ ] **Step 2: Run the model tests and verify RED**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ingress.py -q
```

Expected:

```text
ImportError: cannot import name 'IngressCandidate'
```

- [ ] **Step 3: Add the models**

Modify `engine/src/lorasuite_engine/models.py`:

```python
class AssetType(StrEnum):
    THUMBNAIL = "thumbnail"
    POSTER = "poster"
    FRAME = "frame"
    CLIP = "clip"
    AUDIO = "audio"
    CAPTION = "caption"
    TRANSCRIPT = "transcript"
    MASK = "mask"
```

Add after `MediaStatus`:

```python
class IngressCandidateStatus(StrEnum):
    READY = "ready"
    DUPLICATE = "duplicate"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class IngressJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELED = "canceled"
```

Add after `MediaItem`:

```python
class IngressCandidate(BaseModel):
    id: str = Field(default_factory=lambda: new_id("candidate"))
    source_kind: SourceKind
    source_locator: str
    display_name: str
    media_type: MediaType | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    thumbnail_path: Path | None = None
    poster_asset_path: Path | None = None
    status: IngressCandidateStatus = IngressCandidateStatus.READY
    error_message: str | None = None
    selected: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class IngressScanResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scan"))
    candidates: list[IngressCandidate] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class IngressJob(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ingress_job"))
    source_kind: SourceKind
    candidate_ids: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    selected_count: int = 0
    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    status: IngressJobStatus = IngressJobStatus.QUEUED
    progress_message: str = "Queued"
    errors: list[dict[str, str]] = Field(default_factory=list)
    imported_media_items: list[MediaItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def count_candidates(self) -> Self:
        if self.candidate_count == 0 and self.candidate_ids:
            self.candidate_count = len(self.candidate_ids)
        return self
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ingress.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/models.py engine/tests/test_ingress.py
git commit -m "feat: add ingress models"
```

---

## Task 2: Add Local Scan and Job Service

**Files:**
- Create: `engine/src/lorasuite_engine/ingress.py`
- Modify: `engine/tests/test_ingress.py`

- [ ] **Step 1: Add failing service tests**

Append to `engine/tests/test_ingress.py`:

```python
from PIL import Image

from lorasuite_engine.ingress import IngressService


def test_scan_local_folder_returns_candidates_without_copying_raw_files(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    image_path = source_dir / "person.png"
    Image.new("RGB", (80, 60), color=(30, 60, 90)).save(image_path)
    vault_root = tmp_path / "vault"

    result = IngressService(vault_root).scan_local_roots([source_dir])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.display_name == "person.png"
    assert candidate.source_locator == str(image_path)
    assert candidate.media_type == MediaType.IMAGE
    assert candidate.width == 80
    assert candidate.height == 60
    assert candidate.thumbnail_path is not None
    assert Path(candidate.thumbnail_path).exists()
    assert not (vault_root / "raw").exists()


def test_scan_local_folder_marks_unsupported_files(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    unsupported = source_dir / "notes.txt"
    unsupported.write_text("not media", encoding="utf-8")

    result = IngressService(tmp_path / "vault").scan_local_roots([source_dir])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.status == IngressCandidateStatus.UNSUPPORTED
    assert candidate.error_message == "suffix is not supported"
    assert candidate.selected is False


def test_ingress_job_imports_only_selected_ready_candidates(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "first.png"
    second = source_dir / "second.png"
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(first)
    Image.new("RGB", (24, 24), color=(40, 50, 60)).save(second)
    service = IngressService(tmp_path / "vault")
    scan = service.scan_local_roots([source_dir])

    job = service.create_job(SourceKind.LOCAL, [scan.candidates[0].id])
    service.process_job(job.id)
    completed = service.get_job(job.id)

    assert completed is not None
    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.selected_count == 1
    assert completed.imported_count == 1
    assert completed.imported_media_items[0].metadata_json["original_path"] == str(first)
    raw_files = list((tmp_path / "vault" / "raw").iterdir())
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == first.read_bytes()
```

- [ ] **Step 2: Run the service tests and verify RED**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ingress.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'lorasuite_engine.ingress'
```

- [ ] **Step 3: Implement `IngressService`**

Create `engine/src/lorasuite_engine/ingress.py` with:

```python
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
from lorasuite_engine.vault import (
    SUPPORTED_IMAGE_SUFFIXES,
    SUPPORTED_VIDEO_SUFFIXES,
    VaultService,
    detect_media_type,
    image_dimensions,
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
                    {"path": str(root_path), "code": "missing_path", "message": "path does not exist"}
                )
                continue
            paths = self._expand_root(root_path, recursive=recursive)
            for path in paths:
                result.candidates.append(self._candidate_for_path(path))

        stored = self._read_candidates()
        for candidate in result.candidates:
            stored[candidate.id] = candidate
        self._write_candidates(stored)
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
        selected = [candidates[candidate_id] for candidate_id in job.candidate_ids if candidate_id in candidates]
        ready_local_paths = [
            Path(candidate.source_locator)
            for candidate in selected
            if candidate.source_kind == SourceKind.LOCAL
            and candidate.status == IngressCandidateStatus.READY
        ]
        rejected = [
            candidate
            for candidate in selected
            if candidate.source_kind != SourceKind.LOCAL
            or candidate.status != IngressCandidateStatus.READY
        ]
        result = VaultService(self.vault_root).import_local_paths(ready_local_paths)

        job.imported_media_items = result.media_items
        job.imported_count = len(result.media_items)
        job.failed_count = len(result.errors) + len(rejected)
        job.skipped_count = max(0, len(job.candidate_ids) - job.imported_count - job.failed_count)
        job.errors = [
            error.model_dump(mode="json") for error in result.errors
        ] + [
            {
                "path": candidate.source_locator,
                "code": candidate.status.value,
                "message": candidate.error_message or "candidate is not ready",
            }
            for candidate in rejected
        ]
        job.status = IngressJobStatus.COMPLETE if job.failed_count == 0 else IngressJobStatus.FAILED
        job.progress_message = "Ingress complete" if job.status == IngressJobStatus.COMPLETE else "Ingress completed with errors"
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
            {"candidates": [candidate.model_dump(mode="json") for candidate in candidates.values()]},
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
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ingress.py -q
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/ingress.py engine/tests/test_ingress.py
git commit -m "feat: add local ingress service"
```

---

## Task 3: Add Ingress API Endpoints

**Files:**
- Modify: `engine/src/lorasuite_engine/api.py`
- Modify: `engine/tests/test_api.py`

- [ ] **Step 1: Add failing API tests**

Append to `engine/tests/test_api.py`:

```python
def test_local_ingress_scan_endpoint_returns_candidates(client, tmp_path):
    image_path = tmp_path / "scan-image.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)

    response = client.post("/ingress/local/scan", json={"roots": [str(image_path)]})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["display_name"] == "scan-image.png"
    assert candidate["status"] == "ready"
    assert candidate["selected"] is True
    assert candidate["thumbnail_path"]


def test_ingress_job_endpoint_processes_selected_candidates(client, tmp_path):
    image_path = tmp_path / "job-image.png"
    Image.new("RGB", (31, 37), color=(80, 90, 100)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]

    response = client.post(
        "/ingress/jobs",
        json={"source_kind": "local", "candidate_ids": [candidate_id], "options": {}},
    )

    assert response.status_code == 200
    job = response.json()
    detail = client.get(f"/ingress/jobs/{job['id']}").json()
    assert detail["status"] == "complete"
    assert detail["imported_count"] == 1
    assert detail["imported_media_items"][0]["metadata_json"]["original_path"] == str(image_path)


def test_ingress_jobs_endpoint_lists_recent_jobs(client, tmp_path):
    image_path = tmp_path / "listed-image.png"
    Image.new("RGB", (12, 14), color=(10, 20, 30)).save(image_path)
    scan = client.post("/ingress/local/scan", json={"roots": [str(image_path)]}).json()
    candidate_id = scan["candidates"][0]["id"]
    client.post("/ingress/jobs", json={"source_kind": "local", "candidate_ids": [candidate_id]})

    response = client.get("/ingress/jobs")

    assert response.status_code == 200
    assert response.json()[0]["source_kind"] == "local"
```

- [ ] **Step 2: Run API tests and verify RED**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py -q
```

Expected:

```text
assert 404 == 200
```

- [ ] **Step 3: Implement API endpoints**

Modify `engine/src/lorasuite_engine/api.py`:

```python
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from lorasuite_engine.ingress import IngressService
from lorasuite_engine.models import SourceKind
```

Add request models:

```python
class LocalIngressScanRequest(BaseModel):
    roots: list[Path]
    recursive: bool = True


class IngressJobRequest(BaseModel):
    source_kind: SourceKind
    candidate_ids: list[str]
    options: dict[str, object] = Field(default_factory=dict)
```

Add helper inside `create_app`:

```python
    def ingress_service() -> IngressService:
        return IngressService(app.state.vault_root)
```

Add endpoints:

```python
    @app.post("/ingress/local/scan")
    def scan_local_ingress(request: LocalIngressScanRequest) -> dict[str, object]:
        return ingress_service().scan_local_roots(
            request.roots,
            recursive=request.recursive,
        ).model_dump(mode="json")

    @app.post("/ingress/jobs")
    def create_ingress_job(
        request: IngressJobRequest, background_tasks: BackgroundTasks
    ) -> dict[str, object]:
        job = ingress_service().create_job(request.source_kind, request.candidate_ids)
        background_tasks.add_task(ingress_service().process_job, job.id)
        return job.model_dump(mode="json")

    @app.get("/ingress/jobs")
    def list_ingress_jobs() -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in ingress_service().list_jobs()]

    @app.get("/ingress/jobs/{job_id}")
    def get_ingress_job(job_id: str) -> dict[str, object]:
        job = ingress_service().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Ingress job not found")
        return job.model_dump(mode="json")
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py engine/tests/test_ingress.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/api.py engine/tests/test_api.py
git commit -m "feat: add ingress api endpoints"
```

---

## Task 4: Add Frontend API Types and Client Methods

**Files:**
- Modify: `src/lib/types.ts`
- Modify: `src/lib/api.ts`
- Modify: `src/lib/api.test.ts`

- [ ] **Step 1: Add failing client tests**

Append to `src/lib/api.test.ts`:

```typescript
  it("posts local scan roots to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_1", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.scanLocalIngress(["/tmp/media"], true);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/local/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roots: ["/tmp/media"], recursive: true }),
    });
  });

  it("creates an ingress job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "job_1", source_kind: "local", candidate_ids: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.createIngressJob({ source_kind: "local", candidate_ids: ["candidate_1"] });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_kind: "local", candidate_ids: ["candidate_1"] }),
    });
  });
```

- [ ] **Step 2: Run client tests and verify RED**

Run:

```bash
npm run test -- src/lib/api.test.ts
```

Expected:

```text
Property 'scanLocalIngress' does not exist
```

- [ ] **Step 3: Add TypeScript types**

Modify `src/lib/types.ts`:

```typescript
export type SourceKind = "local" | "instagram" | "x_twitter" | "tiktok";
export type IngressCandidateStatus = "ready" | "duplicate" | "unsupported" | "error";
export type IngressJobStatus = "queued" | "running" | "complete" | "failed" | "canceled";

export interface IngressCandidate {
  id: string;
  source_kind: SourceKind;
  source_locator: string;
  display_name: string;
  media_type?: MediaType | null;
  size_bytes?: number | null;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
  thumbnail_path?: string | null;
  poster_asset_path?: string | null;
  status: IngressCandidateStatus;
  error_message?: string | null;
  selected: boolean;
  metadata_json?: Record<string, unknown>;
}

export interface IngressScanResult {
  id: string;
  candidates: IngressCandidate[];
  errors: Array<Record<string, string>>;
}

export interface CreateIngressJobRequest {
  source_kind: SourceKind;
  candidate_ids: string[];
  options?: Record<string, unknown>;
}

export interface IngressJob {
  id: string;
  source_kind: SourceKind;
  candidate_ids: string[];
  candidate_count: number;
  selected_count: number;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  status: IngressJobStatus;
  progress_message: string;
  errors: Array<Record<string, string>>;
  imported_media_items: MediaItem[];
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}
```

- [ ] **Step 4: Add client methods**

Modify `src/lib/api.ts`:

```typescript
import type {
  CreateIngressJobRequest,
  ExportPackage,
  IngressJob,
  IngressScanResult,
  LocalImportResponse,
  RunComfyExportRequest,
} from "./types";
```

Extend `EngineClient`:

```typescript
  scanLocalIngress(roots: string[], recursive?: boolean): Promise<IngressScanResult>;
  createIngressJob(request: CreateIngressJobRequest): Promise<IngressJob>;
  listIngressJobs(): Promise<IngressJob[]>;
  getIngressJob(jobId: string): Promise<IngressJob>;
```

Add a `getJson` helper:

```typescript
  async function getJson<TResponse>(path: string): Promise<TResponse> {
    const response = await fetcher(`${normalizedBaseUrl}${path}`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
      throw new Error(await readEngineError(response));
    }
    return (await response.json()) as TResponse;
  }
```

Add return methods:

```typescript
    scanLocalIngress(roots: string[], recursive = true) {
      return postJson<IngressScanResult>("/ingress/local/scan", { roots, recursive });
    },
    createIngressJob(request: CreateIngressJobRequest) {
      return postJson<IngressJob>("/ingress/jobs", request);
    },
    listIngressJobs() {
      return getJson<IngressJob[]>("/ingress/jobs");
    },
    getIngressJob(jobId: string) {
      return getJson<IngressJob>(`/ingress/jobs/${jobId}`);
    },
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
npm run test -- src/lib/api.test.ts
```

Expected:

```text
all api tests pass
```

- [ ] **Step 6: Commit**

```bash
git add src/lib/types.ts src/lib/api.ts src/lib/api.test.ts
git commit -m "feat: add ingress api client"
```

---

## Task 5: Replace Data Ingress UI

**Files:**
- Modify: `src/components/DataIngressTab.tsx`
- Modify: `src/App.tsx`
- Modify: `src/App.test.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Add failing UI tests**

Modify `src/App.test.tsx` by adding:

```typescript
it("shows local ingress candidate review controls", () => {
  render(<App />);

  expect(screen.getByRole("button", { name: "Choose Files" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Choose Folder" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Tile" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "List" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Gallery" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Confirm Ingest" })).toBeDisabled();
});

it("switches local ingress review modes", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(screen.getByRole("button", { name: "List" }));
  expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");

  await user.click(screen.getByRole("button", { name: "Gallery" }));
  expect(screen.getByRole("button", { name: "Gallery" })).toHaveAttribute("aria-pressed", "true");
});
```

- [ ] **Step 2: Run UI tests and verify RED**

Run:

```bash
npm run test -- src/App.test.tsx
```

Expected:

```text
Unable to find role="button" and name "Choose Files"
```

- [ ] **Step 3: Implement the UI**

Replace `src/components/DataIngressTab.tsx` with a component that:

- imports `open` from `@tauri-apps/plugin-dialog`;
- keeps `candidates`, `selectedIds`, `viewMode`, `filter`, `jobs`, and `status` state;
- exposes `Choose Files` and `Choose Folder` buttons;
- keeps a manual path textarea fallback for browser-only development;
- calls `engine.scanLocalIngress(paths, true)`;
- renders tile/list/gallery candidate views;
- calls `engine.createIngressJob({ source_kind: "local", candidate_ids })`;
- polls `engine.getIngressJob(job.id)` until `complete` or `failed`;
- passes completed imported items to `onMediaItemsImported`.

Use these local helpers inside the component:

```typescript
type ViewMode = "tile" | "list" | "gallery";
type MediaFilter = "all" | "image" | "video";

function mediaSummary(candidate: IngressCandidate): string {
  if (candidate.width && candidate.height) {
    return `${candidate.width}x${candidate.height}`;
  }
  if (candidate.duration) {
    return `${candidate.duration.toFixed(1)}s`;
  }
  return candidate.media_type ?? "unknown";
}

function fileUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  return `file://${path}`;
}
```

Modify `src/App.tsx` so `onMediaItemsImported` appends:

```typescript
function addMediaItems(items: MediaItem[]) {
  setMediaItems((existing) => [...existing, ...items]);
}
```

Pass `onMediaItemsImported={addMediaItems}`.

Style classes in `src/styles.css`:

```css
.ingress-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.review-toolbar { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }
.segmented-control { display: inline-flex; border: 1px solid #d7dde7; border-radius: 6px; overflow: hidden; }
.segmented-control button { border: 0; border-right: 1px solid #d7dde7; background: #fff; padding: 0.45rem 0.7rem; }
.segmented-control button[aria-pressed="true"] { background: #172033; color: #fff; }
.candidate-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 0.75rem; }
.candidate-tile { border: 1px solid #d7dde7; border-radius: 8px; overflow: hidden; background: #fff; }
.candidate-thumb { aspect-ratio: 1 / 1; display: grid; place-items: center; background: #eef2f7; color: #5a6577; }
.candidate-thumb img { width: 100%; height: 100%; object-fit: cover; }
.candidate-body { padding: 0.65rem; display: grid; gap: 0.35rem; }
.candidate-list { width: 100%; border-collapse: collapse; }
.candidate-list th, .candidate-list td { border-bottom: 1px solid #e5eaf1; padding: 0.5rem; text-align: left; }
.gallery-review { display: grid; grid-template-columns: minmax(220px, 420px) 1fr; gap: 1rem; }
.jobs-table { width: 100%; border-collapse: collapse; }
.jobs-table th, .jobs-table td { border-bottom: 1px solid #e5eaf1; padding: 0.5rem; text-align: left; }
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
npm run test -- src/App.test.tsx
```

Expected:

```text
all App tests pass
```

- [ ] **Step 5: Commit**

```bash
git add src/components/DataIngressTab.tsx src/App.tsx src/App.test.tsx src/styles.css
git commit -m "feat: add ingress candidate review ui"
```

---

## Task 6: Document and Verify the Full Slice

**Files:**
- Modify: `docs/development.md`

- [ ] **Step 1: Update development docs**

Add a "Local Ingress Review" section:

```markdown
## Local Ingress Review

The Data Ingress tab now uses scan -> review -> confirm.

1. Open **Data Ingress**.
2. Click **Choose Files** or **Choose Folder** in the Tauri app.
3. In browser-only development, paste absolute paths into **Manual path fallback** and click **Scan Manual Paths**.
4. Review candidates in **Tile**, **List**, or **Gallery** mode.
5. Select the candidates to import.
6. Click **Confirm Ingest**.
7. Watch the ingress job table for status.
8. Completed imports are added to the app's media list for **Curate / Search**.
```

- [ ] **Step 2: Run full verification**

Run:

```bash
npm run test
npm run engine:test
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected:

```text
Vitest passes
pytest passes
Vite build passes
cargo check passes
```

- [ ] **Step 3: Smoke test with MarySue folder**

Run a direct API smoke:

```bash
PYTHONPATH=engine/src engine/.venv/bin/python - <<'PY'
from pathlib import Path
from fastapi.testclient import TestClient
from lorasuite_engine.api import create_app

source = Path('/Volumes/Main External/InterestingFiles/MarySue stuff')
roots = [str(source)]
client = TestClient(create_app(Path('.lorasuite/ingress-plan-smoke-vault').resolve()))
scan = client.post('/ingress/local/scan', json={'roots': roots, 'recursive': True}).json()
ready = [candidate['id'] for candidate in scan['candidates'] if candidate['status'] == 'ready'][:3]
job = client.post('/ingress/jobs', json={'source_kind': 'local', 'candidate_ids': ready}).json()
detail = client.get(f"/ingress/jobs/{job['id']}").json()
print({'candidates': len(scan['candidates']), 'selected': len(ready), 'status': detail['status'], 'imported': detail['imported_count']})
PY
```

Expected:

```text
status is complete
imported is 3
```

- [ ] **Step 4: Commit docs**

```bash
git add docs/development.md
git commit -m "docs: describe ingress review workflow"
```

---

## Success Criteria

- Local file/folder scanning does not copy raw media into the vault.
- Candidate review shows all scanned supported/unsupported files.
- Tile/list/gallery modes render and preserve selection state.
- Confirmed ingestion creates a visible job.
- Jobs import only selected ready candidates.
- Completed job media items flow to downstream app state.
- Instagram/X browser-session helper decisions remain documented as connector contract, not half-built connector code.
