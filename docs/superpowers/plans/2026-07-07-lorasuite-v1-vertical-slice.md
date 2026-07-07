# LoraSuite V1 Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working LoraSuite desktop slice: local media import, tabbed workspace shell, video segment intent selection, FFmpeg frame extraction, RunComfy AI Toolkit image dataset export, manifest writing, and focused tests.

**Architecture:** Use a Tauri 2 desktop shell with a React/Vite TypeScript frontend and a Python FastAPI engine process running on localhost during development. The engine owns vault state, segment validation, media processing, and export creation; the UI owns the tabbed workflow and calls the engine through typed HTTP helpers. This plan intentionally proves local media first; Instagram/X/Twitter/TikTok acquisition and full PhotoMapAI embedding/indexing get their own follow-up plans after this loop works.

**Tech Stack:** Tauri 2, React, TypeScript, Vite, Vitest, Testing Library, Python 3.11+, FastAPI, Pydantic v2, pytest, Pillow, FFmpeg.

---

## Source References

- Approved design spec: `docs/superpowers/specs/2026-07-06-lorasuite-v1-design.md`
- Tauri project creation: https://v2.tauri.app/start/create-project/
- Tauri Vite configuration: https://v2.tauri.app/start/frontend/vite/
- Tauri sidecar/external binary model: https://v2.tauri.app/develop/sidecar/

## Scope

This plan implements the first vertical slice from the approved design:

- Tauri + React/Vite frontend scaffold.
- Python FastAPI engine scaffold.
- Top-level tabs: **Data Ingress**, **Curate / Search**, **Video Review**, **Exports**.
- Local image/video import into a vault.
- Segment creation with free start/end and image/video/voice toggles.
- Intent-aware guidance text for the segment form.
- FFmpeg frame extraction for image-intent segments.
- RunComfy AI Toolkit image export with images, matching `.txt` captions, `manifest.json`, and an export report.
- Unit/integration/UI tests for the above.

Not included in this plan:

- Instagram/X/Twitter/TikTok download connectors.
- Browser cookie profile management.
- Production bundling of the Python engine into a signed app package.
- Full PhotoMapAI embedding generation, UMAP, clustering, and albums.
- In-app model training.

## File Structure

Create or modify these files during execution:

```text
.
├── .gitignore
├── docs/
│   ├── development.md
│   └── superpowers/
│       ├── plans/2026-07-07-lorasuite-v1-vertical-slice.md
│       └── specs/2026-07-06-lorasuite-v1-design.md
├── engine/
│   ├── pyproject.toml
│   ├── src/lorasuite_engine/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── exports.py
│   │   ├── ffmpeg.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── segments.py
│   │   └── vault.py
│   └── tests/
│       ├── conftest.py
│       ├── test_api.py
│       ├── test_exports.py
│       ├── test_ffmpeg.py
│       ├── test_segments.py
│       └── test_vault.py
├── index.html
├── package.json
├── package-lock.json
├── src/
│   ├── App.test.tsx
│   ├── App.tsx
│   ├── components/
│   │   ├── CurateSearchTab.tsx
│   │   ├── DataIngressTab.tsx
│   │   ├── ExportsTab.tsx
│   │   └── VideoReviewTab.tsx
│   ├── lib/
│   │   ├── api.test.ts
│   │   ├── api.ts
│   │   └── types.ts
│   ├── main.tsx
│   ├── setupTests.ts
│   └── styles.css
├── src-tauri/
│   ├── Cargo.toml
│   ├── build.rs
│   ├── capabilities/default.json
│   ├── src/main.rs
│   └── tauri.conf.json
├── tsconfig.json
├── tsconfig.node.json
└── vite.config.ts
```

Boundary decisions:

- `engine/src/lorasuite_engine/models.py` contains durable Pydantic models and enums only.
- `engine/src/lorasuite_engine/segments.py` contains segment validation and intent guidance only.
- `engine/src/lorasuite_engine/vault.py` owns local import, file hashing, vault folders, and vault JSON persistence.
- `engine/src/lorasuite_engine/ffmpeg.py` owns FFmpeg command construction and execution.
- `engine/src/lorasuite_engine/exports.py` owns RunComfy-compatible image export creation.
- `engine/src/lorasuite_engine/api.py` creates the FastAPI app and maps HTTP DTOs to engine services.
- `src/lib/types.ts` mirrors the API contract used by the frontend.
- `src/lib/api.ts` is the only frontend file that performs HTTP calls.
- `src/App.tsx` owns tab state and layout only.
- Tab components own workflow-specific UI and receive API functions as props where useful for testing.

## Task 1: Scaffold the Tauri, React, and Python Project Base

**Files:**
- Create: `package.json`
- Create: `index.html`
- Create: `src/main.tsx`
- Create: `src/App.tsx`
- Create: `src/styles.css`
- Create: `src/setupTests.ts`
- Create: `vite.config.ts`
- Create: `tsconfig.json`
- Create: `tsconfig.node.json`
- Create: `src-tauri/`
- Create: `engine/pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Create the React/Vite scaffold**

Run:

```bash
npm create vite@latest . -- --template react-ts
```

Expected:

```text
Scaffolding project in /Volumes/Main External/Development/LoraSuite...
Done.
```

If Vite refuses to scaffold into a non-empty directory, create the generated files manually from the file contents specified in this plan and continue.

- [ ] **Step 2: Install frontend and Tauri dependencies**

Run:

```bash
npm install
npm install @tauri-apps/api @tauri-apps/plugin-dialog @tauri-apps/plugin-shell
npm install -D @tauri-apps/cli vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event concurrently
```

Expected:

```text
added
found 0 vulnerabilities
```

If npm reports dependency audit warnings, capture the warnings in the task notes and continue unless install exits non-zero.

- [ ] **Step 3: Initialize Tauri**

Run:

```bash
npx tauri init
```

Use these prompt answers:

```text
What is your app name? LoraSuite
What should the window title be? LoraSuite
Where are your web assets located? ../dist
What is the url of your dev server? http://localhost:5173
What is your frontend dev command? npm run dev
What is your frontend build command? npm run build
```

Expected:

```text
This will create a src-tauri directory in your project
```

- [ ] **Step 4: Replace `package.json` scripts with the vertical-slice commands**

Ensure `package.json` contains these scripts:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "dev:engine": "engine/.venv/bin/python -m uvicorn lorasuite_engine.main:app --app-dir engine/src --host 127.0.0.1 --port 8765 --reload",
    "dev:all": "concurrently -k -n engine,tauri \"npm run dev:engine\" \"npm run tauri dev\"",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "tauri": "tauri",
    "engine:test": "python -m pytest engine/tests -q"
  }
}
```

Keep the dependency sections generated by npm.

- [ ] **Step 5: Configure Vitest in `vite.config.ts`**

Use this exact shape:

```ts
/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**", "**/engine/.venv/**"],
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["src/setupTests.ts"],
  },
});
```

- [ ] **Step 6: Create the Python package metadata**

Create `engine/pyproject.toml`:

```toml
[project]
name = "lorasuite-engine"
version = "0.1.0"
description = "Local media engine for LoraSuite"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "pillow>=10.0",
  "pydantic>=2.8",
  "uvicorn[standard]>=0.30",
]

[project.optional-dependencies]
dev = [
  "httpx>=0.27",
  "pytest>=8.2",
]

[build-system]
requires = ["setuptools>=70"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 7: Install Python development dependencies**

Run:

```bash
python3 -m venv engine/.venv
engine/.venv/bin/python -m pip install --upgrade pip
engine/.venv/bin/python -m pip install -e "engine[dev]"
```

Expected:

```text
Successfully installed lorasuite-engine
```

- [ ] **Step 8: Expand `.gitignore`**

Ensure `.gitignore` contains:

```gitignore
.superpowers/
node_modules/
dist/
.vite/
*.log

engine/.venv/
engine/.pytest_cache/
engine/**/__pycache__/
*.pyc

src-tauri/target/
.DS_Store
.lorasuite/
```

- [ ] **Step 9: Verify scaffold commands**

Run:

```bash
npm run build
engine/.venv/bin/python -m pytest engine/tests -q
```

Expected:

```text
vite build completes successfully
no tests ran
```

The Python command exits with code 5 when no tests exist. Record that as expected for this task only.

- [ ] **Step 10: Commit scaffold**

Run:

```bash
git add .gitignore package.json package-lock.json index.html src src-tauri tsconfig.json tsconfig.node.json vite.config.ts engine/pyproject.toml
git commit -m "chore: scaffold LoraSuite app"
```

## Task 2: Add Engine Health API and Test Harness

**Files:**
- Create: `engine/src/lorasuite_engine/__init__.py`
- Create: `engine/src/lorasuite_engine/api.py`
- Create: `engine/src/lorasuite_engine/main.py`
- Create: `engine/tests/conftest.py`
- Create: `engine/tests/test_api.py`

- [ ] **Step 1: Write the failing health API test**

Create `engine/tests/conftest.py`:

```python
from fastapi.testclient import TestClient
import pytest

from lorasuite_engine.api import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(vault_root=tmp_path / "vault")
    with TestClient(app) as test_client:
        yield test_client
```

Create `engine/tests/test_api.py`:

```python
from lorasuite_engine.api import create_app


def test_health_endpoint_reports_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lorasuite-engine"}


def test_create_app_uses_env_vault_root(monkeypatch, tmp_path):
    vault_root = tmp_path / "env-vault"
    monkeypatch.setenv("LORASUITE_VAULT_ROOT", str(vault_root))

    app = create_app()

    assert app.state.vault_root == vault_root
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'lorasuite_engine'
```

- [ ] **Step 3: Implement the health API**

Create `engine/src/lorasuite_engine/__init__.py`:

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create `engine/src/lorasuite_engine/api.py`:

```python
import os
from pathlib import Path

from fastapi import FastAPI


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.state.vault_root = vault_root or default_vault_root()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    return app
```

Create `engine/src/lorasuite_engine/main.py`:

```python
from lorasuite_engine.api import create_app

app = create_app()
```

- [ ] **Step 4: Run the health API test to verify it passes**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit health API**

Run:

```bash
git add engine/src/lorasuite_engine engine/tests
git commit -m "feat: add engine health api"
```

## Task 3: Add Domain Models and Segment Validation

**Files:**
- Create: `engine/src/lorasuite_engine/models.py`
- Create: `engine/src/lorasuite_engine/segments.py`
- Create: `engine/tests/test_segments.py`

- [ ] **Step 1: Write failing segment/model tests**

Create `engine/tests/test_segments.py`:

```python
import pytest

from lorasuite_engine.models import SegmentCreate
from lorasuite_engine.segments import guidance_for_segment, validate_segment_range


def test_segment_requires_positive_end_after_start():
    with pytest.raises(ValueError, match="end_seconds must be greater than start_seconds"):
        validate_segment_range(start_seconds=8.0, end_seconds=8.0)


def test_segment_supports_any_intent_combination():
    segment = SegmentCreate(
        media_item_id="media-1",
        start_seconds=2.5,
        end_seconds=14.0,
        label="good face range",
        notes="clean lighting",
        use_for_image=True,
        use_for_video=False,
        use_for_voice=True,
    )

    assert segment.use_for_image is True
    assert segment.use_for_video is False
    assert segment.use_for_voice is True


def test_guidance_mentions_enabled_intents():
    segment = SegmentCreate(
        media_item_id="media-1",
        start_seconds=0.0,
        end_seconds=12.0,
        use_for_image=True,
        use_for_video=True,
        use_for_voice=False,
    )

    guidance = guidance_for_segment(segment)

    assert "Extract sparse keyframes" in guidance
    assert "Keep the clip coherent" in guidance
    assert "Voice export is off" in guidance
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_segments.py -q
```

Expected:

```text
ModuleNotFoundError
```

- [ ] **Step 3: Implement models and segment validation**

Create `engine/src/lorasuite_engine/models.py`:

```python
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceKind(StrEnum):
    LOCAL = "local"
    INSTAGRAM = "instagram"
    X_TWITTER = "x_twitter"
    TIKTOK = "tiktok"


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class MediaStatus(StrEnum):
    NEW = "new"
    REVIEWED = "reviewed"
    IGNORED = "ignored"
    EXPORTED = "exported"


class AssetType(StrEnum):
    FRAME = "frame"
    CLIP = "clip"
    AUDIO = "audio"
    CAPTION = "caption"
    TRANSCRIPT = "transcript"
    MASK = "mask"


class ExportType(StrEnum):
    RUNCOMFY_IMAGE = "runcomfy_image"
    AI_TOOLKIT_VIDEO = "ai_toolkit_video"
    VOICE_HANDOFF = "voice_handoff"


class MediaSource(BaseModel):
    id: str = Field(default_factory=lambda: new_id("source"))
    kind: SourceKind
    source_url: str | None = None
    account_handle: str | None = None
    cookie_profile_id: str | None = None
    imported_at: datetime = Field(default_factory=utc_now)
    download_tool: str | None = None
    tool_version: str | None = None


class MediaItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("media"))
    source_id: str
    raw_path: Path
    media_type: MediaType
    sha256: str
    perceptual_hash: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    status: MediaStatus = MediaStatus.NEW


class SegmentCreate(BaseModel):
    media_item_id: str
    start_seconds: float
    end_seconds: float
    label: str = ""
    notes: str = ""
    quality_flags: list[str] = Field(default_factory=list)
    use_for_image: bool = False
    use_for_video: bool = False
    use_for_voice: bool = False

    @field_validator("end_seconds")
    @classmethod
    def end_must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("end_seconds must be positive")
        return value


class Segment(SegmentCreate):
    id: str = Field(default_factory=lambda: new_id("segment"))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DerivedAsset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asset"))
    media_item_id: str
    segment_id: str | None = None
    asset_type: AssetType
    path: Path
    sha256: str
    generation_settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ExportPackage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("export"))
    export_type: ExportType
    output_path: Path
    created_at: datetime = Field(default_factory=utc_now)
    preset_json: dict[str, Any] = Field(default_factory=dict)
    manifest_path: Path | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    status: str = "created"
```

Create `engine/src/lorasuite_engine/segments.py`:

```python
from lorasuite_engine.models import Segment, SegmentCreate


def validate_segment_range(start_seconds: float, end_seconds: float) -> None:
    if start_seconds < 0:
        raise ValueError("start_seconds must be zero or greater")
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds must be greater than start_seconds")


def create_segment(payload: SegmentCreate) -> Segment:
    validate_segment_range(payload.start_seconds, payload.end_seconds)
    return Segment(**payload.model_dump())


def guidance_for_segment(segment: SegmentCreate) -> list[str]:
    guidance: list[str] = []
    duration = segment.end_seconds - segment.start_seconds

    if segment.use_for_image:
        guidance.append("Extract sparse keyframes from stable visual ranges and dedupe near-identical frames.")
    else:
        guidance.append("Image export is off for this segment.")

    if segment.use_for_video:
        guidance.append(f"Keep the clip coherent; selected duration is {duration:.1f} seconds.")
    else:
        guidance.append("Video export is off for this segment.")

    if segment.use_for_voice:
        guidance.append("Prefer clean speech with one speaker and low background noise.")
    else:
        guidance.append("Voice export is off for this segment.")

    return guidance
```

- [ ] **Step 4: Run segment tests**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_segments.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit models and segment logic**

Run:

```bash
git add engine/src/lorasuite_engine/models.py engine/src/lorasuite_engine/segments.py engine/tests/test_segments.py
git commit -m "feat: add media segment model"
```

## Task 4: Add Local Vault Import

**Files:**
- Create: `engine/src/lorasuite_engine/vault.py`
- Create: `engine/tests/test_vault.py`
- Modify: `engine/src/lorasuite_engine/api.py`
- Modify: `engine/tests/test_api.py`

- [ ] **Step 1: Write failing vault import tests**

Create `engine/tests/test_vault.py`:

```python
from pathlib import Path

from PIL import Image

from lorasuite_engine.models import MediaType
from lorasuite_engine.vault import VaultService


def create_image(path: Path) -> None:
    image = Image.new("RGB", (32, 32), color=(120, 80, 40))
    image.save(path)


def test_import_local_image_copies_file_and_records_metadata(tmp_path):
    source = tmp_path / "input.png"
    create_image(source)
    service = VaultService(tmp_path / "vault")

    items = service.import_local_paths([source])

    assert len(items) == 1
    assert items[0].media_type == MediaType.IMAGE
    assert items[0].raw_path.exists()
    assert items[0].raw_path.parent.name == "raw"
    assert service.state_path.exists()


def test_import_rejects_unsupported_suffix(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("not media", encoding="utf-8")
    service = VaultService(tmp_path / "vault")

    items = service.import_local_paths([source])

    assert items == []
```

- [ ] **Step 2: Run vault tests to verify they fail**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_vault.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'lorasuite_engine.vault'
```

- [ ] **Step 3: Implement vault service**

Create `engine/src/lorasuite_engine/vault.py`:

```python
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

from lorasuite_engine.models import MediaItem, MediaSource, MediaType, SourceKind


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


class VaultService:
    def __init__(self, root: Path):
        self.root = root
        self.raw_dir = root / "raw"
        self.state_path = root / "vault.json"

    def import_local_paths(self, paths: list[Path]) -> list[MediaItem]:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        source = MediaSource(kind=SourceKind.LOCAL, download_tool="local-import")
        items: list[MediaItem] = []

        for path in paths:
            media_type = detect_media_type(path)
            if media_type is None:
                continue

            digest = sha256_file(path)
            target = self.raw_dir / f"{digest}{path.suffix.lower()}"
            if not target.exists():
                shutil.copy2(path, target)

            width, height = image_dimensions(target) if media_type == MediaType.IMAGE else (None, None)
            items.append(
                MediaItem(
                    source_id=source.id,
                    raw_path=target,
                    media_type=media_type,
                    sha256=digest,
                    width=width,
                    height=height,
                    metadata_json={"original_path": str(path)},
                )
            )

        self._write_state(source, items)
        return items

    def _write_state(self, source: MediaSource, items: list[MediaItem]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "sources": [source.model_dump(mode="json")],
            "media_items": [item.model_dump(mode="json") for item in items],
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def detect_media_type(path: Path) -> MediaType | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return MediaType.IMAGE
    if suffix in VIDEO_SUFFIXES:
        return MediaType.VIDEO
    return None


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    with Image.open(path) as image:
        return image.width, image.height
```

- [ ] **Step 4: Add local import endpoint test**

Append to `engine/tests/test_api.py`:

```python
from pathlib import Path

from PIL import Image


def test_import_local_endpoint_returns_media_items(client, tmp_path):
    image_path = tmp_path / "portrait.png"
    Image.new("RGB", (24, 24), color=(10, 20, 30)).save(image_path)

    response = client.post("/vault/import/local", json={"paths": [str(image_path)]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["media_items"]) == 1
    assert body["media_items"][0]["media_type"] == "image"
```

- [ ] **Step 5: Implement local import endpoint**

Update `engine/src/lorasuite_engine/api.py`:

```python
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from lorasuite_engine.vault import VaultService


class LocalImportRequest(BaseModel):
    paths: list[str]


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.state.vault_root = vault_root or default_vault_root()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    @app.post("/vault/import/local")
    def import_local(request: LocalImportRequest) -> dict[str, object]:
        service = VaultService(app.state.vault_root)
        items = service.import_local_paths([Path(path) for path in request.paths])
        return {"media_items": [item.model_dump(mode="json") for item in items]}

    return app
```

- [ ] **Step 6: Run vault and API tests**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_vault.py engine/tests/test_api.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 7: Commit vault import**

Run:

```bash
git add engine/src/lorasuite_engine/api.py engine/src/lorasuite_engine/vault.py engine/tests/test_api.py engine/tests/test_vault.py
git commit -m "feat: import local media into vault"
```

## Task 5: Add FFmpeg Frame Extraction

**Files:**
- Create: `engine/src/lorasuite_engine/ffmpeg.py`
- Create: `engine/tests/test_ffmpeg.py`

- [ ] **Step 1: Write failing FFmpeg tests**

Create `engine/tests/test_ffmpeg.py`:

```python
import shutil
import subprocess

import pytest

from lorasuite_engine.ffmpeg import extract_frames


ffmpeg_missing = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@ffmpeg_missing
def test_extract_frames_from_segment(tmp_path):
    video_path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=64x64:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )

    output_dir = tmp_path / "frames"
    frames = extract_frames(
        video_path=video_path,
        output_dir=output_dir,
        start_seconds=0.0,
        end_seconds=1.0,
        frames_per_second=2,
    )

    assert len(frames) >= 1
    assert all(frame.suffix == ".png" for frame in frames)
    assert all(frame.exists() for frame in frames)
```

- [ ] **Step 2: Run FFmpeg test to verify it fails**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ffmpeg.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'lorasuite_engine.ffmpeg'
```

- [ ] **Step 3: Implement frame extraction**

Create `engine/src/lorasuite_engine/ffmpeg.py`:

```python
import subprocess
from pathlib import Path


def extract_frames(
    video_path: Path,
    output_dir: Path,
    start_seconds: float,
    end_seconds: float,
    frames_per_second: int = 1,
) -> list[Path]:
    if start_seconds < 0:
        raise ValueError("start_seconds must be zero or greater")
    if end_seconds <= start_seconds:
        raise ValueError("end_seconds must be greater than start_seconds")
    if frames_per_second <= 0:
        raise ValueError("frames_per_second must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "frame_%05d.png"
    duration = end_seconds - start_seconds
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(video_path),
        "-vf",
        f"fps={frames_per_second}",
        str(output_pattern),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {completed.stderr[-1000:]}")

    return sorted(output_dir.glob("frame_*.png"))
```

- [ ] **Step 4: Run FFmpeg test**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ffmpeg.py -q
```

Expected when FFmpeg is installed:

```text
1 passed
```

Expected when FFmpeg is absent:

```text
1 skipped
```

- [ ] **Step 5: Commit FFmpeg extraction**

Run:

```bash
git add engine/src/lorasuite_engine/ffmpeg.py engine/tests/test_ffmpeg.py
git commit -m "feat: extract frames with ffmpeg"
```

## Task 6: Add RunComfy AI Toolkit Image Export

**Files:**
- Create: `engine/src/lorasuite_engine/exports.py`
- Create: `engine/tests/test_exports.py`
- Modify: `engine/src/lorasuite_engine/api.py`
- Modify: `engine/tests/test_api.py`

- [ ] **Step 1: Write failing export tests**

Create `engine/tests/test_exports.py`:

```python
import json
from pathlib import Path

from PIL import Image

from lorasuite_engine.exports import create_runcomfy_image_export


def create_frame(path: Path) -> None:
    Image.new("RGB", (32, 32), color=(200, 100, 50)).save(path)


def test_runcomfy_export_writes_images_captions_manifest_and_report(tmp_path):
    frame = tmp_path / "frame.png"
    create_frame(frame)
    output_dir = tmp_path / "export"

    package = create_runcomfy_image_export(
        frames=[frame],
        output_dir=output_dir,
        caption_template="subject trigger_token, clean portrait",
        source_segment_ids=["segment-1"],
    )

    exported_image = output_dir / "images" / "000001.png"
    exported_caption = output_dir / "images" / "000001.txt"
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "export_report.md"

    assert package.status == "complete"
    assert exported_image.exists()
    assert exported_caption.read_text(encoding="utf-8") == "subject trigger_token, clean portrait\n"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["export_type"] == "runcomfy_image"
    assert "RunComfy AI Toolkit Image Export" in report_path.read_text(encoding="utf-8")


def test_runcomfy_export_rejects_webp(tmp_path):
    webp = tmp_path / "frame.webp"
    webp.write_bytes(b"fake")

    try:
        create_runcomfy_image_export(
            frames=[webp],
            output_dir=tmp_path / "export",
            caption_template="caption",
            source_segment_ids=[],
        )
    except ValueError as error:
        assert "WebP is not supported" in str(error)
    else:
        raise AssertionError("expected webp export rejection")
```

- [ ] **Step 2: Run export tests to verify they fail**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_exports.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'lorasuite_engine.exports'
```

- [ ] **Step 3: Implement RunComfy export**

Create `engine/src/lorasuite_engine/exports.py`:

```python
import json
import shutil
from pathlib import Path

from lorasuite_engine.models import ExportPackage, ExportType
from lorasuite_engine.vault import sha256_file


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def create_runcomfy_image_export(
    frames: list[Path],
    output_dir: Path,
    caption_template: str,
    source_segment_ids: list[str],
) -> ExportPackage:
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    exported_files: list[dict[str, str]] = []
    for index, frame in enumerate(frames, start=1):
        suffix = frame.suffix.lower()
        if suffix == ".webp":
            raise ValueError("WebP is not supported for RunComfy AI Toolkit image export")
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image suffix for RunComfy export: {suffix}")

        basename = f"{index:06d}"
        image_target = images_dir / f"{basename}{suffix}"
        caption_target = images_dir / f"{basename}.txt"
        shutil.copy2(frame, image_target)
        caption_target.write_text(caption_template.rstrip() + "\n", encoding="utf-8")
        exported_files.append(
            {
                "image": str(image_target),
                "caption": str(caption_target),
                "sha256": sha256_file(image_target),
            }
        )

    package = ExportPackage(
        export_type=ExportType.RUNCOMFY_IMAGE,
        output_path=output_dir,
        source_segment_ids=source_segment_ids,
        status="complete",
    )
    manifest_path = output_dir / "manifest.json"
    package.manifest_path = manifest_path
    manifest = {
        "export_id": package.id,
        "export_type": package.export_type,
        "status": package.status,
        "source_segment_ids": source_segment_ids,
        "files": exported_files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "export_report.md").write_text(
        "# RunComfy AI Toolkit Image Export\n\n"
        f"- Images: {len(exported_files)}\n"
        "- Captions: one .txt file per image with matching basename\n",
        encoding="utf-8",
    )
    return package
```

- [ ] **Step 4: Add API endpoint test**

Append to `engine/tests/test_api.py`:

```python
def test_runcomfy_export_endpoint(client, tmp_path):
    frame = tmp_path / "frame.png"
    Image.new("RGB", (24, 24), color=(40, 50, 60)).save(frame)
    output_dir = tmp_path / "export"

    response = client.post(
        "/exports/runcomfy-image",
        json={
            "frames": [str(frame)],
            "output_dir": str(output_dir),
            "caption_template": "person trigger_token",
            "source_segment_ids": ["segment-1"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert (output_dir / "images" / "000001.png").exists()
```

- [ ] **Step 5: Add export endpoint**

Extend `engine/src/lorasuite_engine/api.py`:

```python
import os
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from lorasuite_engine.exports import create_runcomfy_image_export
from lorasuite_engine.vault import VaultService


class LocalImportRequest(BaseModel):
    paths: list[str]


class RunComfyImageExportRequest(BaseModel):
    frames: list[str]
    output_dir: str
    caption_template: str
    source_segment_ids: list[str]


def default_vault_root() -> Path:
    configured_root = os.environ.get("LORASUITE_VAULT_ROOT")
    if configured_root:
        return Path(configured_root)

    return Path.home() / ".lorasuite" / "vault"


def create_app(vault_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="LoraSuite Engine")
    app.state.vault_root = vault_root or default_vault_root()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lorasuite-engine"}

    @app.post("/vault/import/local")
    def import_local(request: LocalImportRequest) -> dict[str, object]:
        service = VaultService(app.state.vault_root)
        items = service.import_local_paths([Path(path) for path in request.paths])
        return {"media_items": [item.model_dump(mode="json") for item in items]}

    @app.post("/exports/runcomfy-image")
    def export_runcomfy_image(request: RunComfyImageExportRequest) -> dict[str, object]:
        package = create_runcomfy_image_export(
            frames=[Path(frame) for frame in request.frames],
            output_dir=Path(request.output_dir),
            caption_template=request.caption_template,
            source_segment_ids=request.source_segment_ids,
        )
        return package.model_dump(mode="json")

    return app
```

- [ ] **Step 6: Run export and API tests**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_exports.py engine/tests/test_api.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 7: Commit export support**

Run:

```bash
git add engine/src/lorasuite_engine/api.py engine/src/lorasuite_engine/exports.py engine/tests/test_api.py engine/tests/test_exports.py
git commit -m "feat: export runcomfy image dataset"
```

## Task 7: Add Frontend Types, API Client, and Tab Shell

**Files:**
- Create: `src/lib/types.ts`
- Create: `src/lib/api.ts`
- Create: `src/lib/api.test.ts`
- Create: `src/App.test.tsx`
- Modify: `src/App.tsx`
- Modify: `src/main.tsx`
- Modify: `src/setupTests.ts`
- Modify: `src/styles.css`

- [ ] **Step 1: Write failing API and tab tests**

Create `src/setupTests.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `src/lib/api.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { createEngineClient } from "./api";

describe("createEngineClient", () => {
  it("posts local import paths to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ media_items: [{ id: "media_1", media_type: "image" }] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    const result = await client.importLocal(["/tmp/a.png"]);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/vault/import/local", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: ["/tmp/a.png"] }),
    });
    expect(result.media_items[0].id).toBe("media_1");
  });
});
```

Create `src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("shows the four workspace tabs", () => {
    render(<App />);

    expect(screen.getByRole("tab", { name: "Data Ingress" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Curate / Search" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Video Review" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Exports" })).toBeInTheDocument();
  });

  it("switches workspace tabs", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("tab", { name: "Curate / Search" }));

    expect(screen.getByRole("heading", { name: "Curate / Search" })).toBeInTheDocument();
    expect(screen.getByText("PhotoMapAI-derived curation workspace")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run frontend tests to verify they fail**

Run:

```bash
npm run test -- src/lib/api.test.ts src/App.test.tsx
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Implement frontend types and API client**

Create `src/lib/types.ts`:

```ts
export type MediaType = "image" | "video" | "audio";

export interface MediaItem {
  id: string;
  source_id?: string;
  raw_path?: string;
  media_type: MediaType;
  sha256?: string;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  status?: string;
}

export interface LocalImportResponse {
  media_items: MediaItem[];
}

export interface RunComfyExportRequest {
  frames: string[];
  output_dir: string;
  caption_template: string;
  source_segment_ids: string[];
}

export interface ExportPackage {
  id: string;
  export_type: string;
  output_path: string;
  manifest_path?: string | null;
  source_segment_ids: string[];
  status: string;
}
```

Create `src/lib/api.ts`:

```ts
import type { ExportPackage, LocalImportResponse, RunComfyExportRequest } from "./types";

type FetchLike = typeof fetch;

export interface EngineClient {
  importLocal(paths: string[]): Promise<LocalImportResponse>;
  exportRunComfyImage(request: RunComfyExportRequest): Promise<ExportPackage>;
}

export function createEngineClient(
  baseUrl = import.meta.env.VITE_LORASUITE_ENGINE_URL || "http://127.0.0.1:8765",
  fetcher: FetchLike = fetch,
): EngineClient {
  async function postJson<TResponse>(path: string, body: unknown): Promise<TResponse> {
    const response = await fetcher(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(`Engine request failed: ${response.status}`);
    }
    return response.json() as Promise<TResponse>;
  }

  return {
    importLocal(paths: string[]) {
      return postJson<LocalImportResponse>("/vault/import/local", { paths });
    },
    exportRunComfyImage(request: RunComfyExportRequest) {
      return postJson<ExportPackage>("/exports/runcomfy-image", request);
    },
  };
}
```

- [ ] **Step 4: Implement tab shell**

Create or replace `src/App.tsx`:

```tsx
import { useMemo, useState } from "react";
import { CurateSearchTab } from "./components/CurateSearchTab";
import { DataIngressTab } from "./components/DataIngressTab";
import { ExportsTab } from "./components/ExportsTab";
import { VideoReviewTab } from "./components/VideoReviewTab";
import { createEngineClient } from "./lib/api";
import type { MediaItem } from "./lib/types";
import "./styles.css";

type TabId = "ingress" | "curate" | "video" | "exports";

const tabs: Array<{ id: TabId; label: string }> = [
  { id: "ingress", label: "Data Ingress" },
  { id: "curate", label: "Curate / Search" },
  { id: "video", label: "Video Review" },
  { id: "exports", label: "Exports" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("ingress");
  const [mediaItems, setMediaItems] = useState<MediaItem[]>([]);
  const engine = useMemo(() => createEngineClient(), []);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <h1>LoraSuite</h1>
          <p>Local media to training-ready LoRA dataset handoffs.</p>
        </div>
      </header>

      <nav className="workspace-tabs" role="tablist" aria-label="LoraSuite workspace">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? "tab active" : "tab"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <section className="workspace-panel" role="tabpanel">
        {activeTab === "ingress" && (
          <DataIngressTab engine={engine} mediaItems={mediaItems} onMediaItemsImported={setMediaItems} />
        )}
        {activeTab === "curate" && <CurateSearchTab mediaItems={mediaItems} />}
        {activeTab === "video" && <VideoReviewTab mediaItems={mediaItems} />}
        {activeTab === "exports" && <ExportsTab engine={engine} />}
      </section>
    </main>
  );
}
```

Create simple tab components for this task:

```tsx
// src/components/DataIngressTab.tsx
import type { EngineClient } from "../lib/api";
import type { MediaItem } from "../lib/types";

interface Props {
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
}

export function DataIngressTab({ mediaItems }: Props) {
  return (
    <section>
      <h2>Data Ingress</h2>
      <p>Import local images and videos before social acquisition connectors are added.</p>
      <p>{mediaItems.length} media items imported.</p>
    </section>
  );
}
```

```tsx
// src/components/CurateSearchTab.tsx
import type { MediaItem } from "../lib/types";

interface Props {
  mediaItems: MediaItem[];
}

export function CurateSearchTab({ mediaItems }: Props) {
  return (
    <section>
      <h2>Curate / Search</h2>
      <p>PhotoMapAI-derived curation workspace</p>
      <p>{mediaItems.length} items available for curation.</p>
    </section>
  );
}
```

```tsx
// src/components/VideoReviewTab.tsx
import type { MediaItem } from "../lib/types";

interface Props {
  mediaItems: MediaItem[];
}

export function VideoReviewTab({ mediaItems }: Props) {
  const videoCount = mediaItems.filter((item) => item.media_type === "video").length;
  return (
    <section>
      <h2>Video Review</h2>
      <p>{videoCount} videos ready for segment review.</p>
    </section>
  );
}
```

```tsx
// src/components/ExportsTab.tsx
import type { EngineClient } from "../lib/api";

interface Props {
  engine: EngineClient;
}

export function ExportsTab(_props: Props) {
  return (
    <section>
      <h2>Exports</h2>
      <p>Create RunComfy AI Toolkit image dataset folders.</p>
    </section>
  );
}
```

- [ ] **Step 5: Add shell styling**

Replace `src/styles.css` with:

```css
:root {
  color: #172026;
  background: #f6f7f4;
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

body {
  margin: 0;
}

button,
input,
textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto auto 1fr;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 28px 16px;
  border-bottom: 1px solid #d7ddd6;
  background: #ffffff;
}

.app-header h1 {
  margin: 0 0 4px;
  font-size: 28px;
  font-weight: 700;
}

.app-header p {
  margin: 0;
  color: #58666e;
}

.workspace-tabs {
  display: flex;
  gap: 6px;
  padding: 10px 16px 0;
  border-bottom: 1px solid #d7ddd6;
  background: #eef2ee;
}

.tab {
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-bottom: 0;
  background: transparent;
  color: #35424a;
  cursor: pointer;
}

.tab.active {
  background: #ffffff;
  border-color: #d7ddd6;
  color: #11181c;
  font-weight: 650;
}

.workspace-panel {
  padding: 24px 28px;
}
```

- [ ] **Step 6: Run frontend tests**

Run:

```bash
npm run test -- src/lib/api.test.ts src/App.test.tsx
```

Expected:

```text
2 files passed
```

- [ ] **Step 7: Commit tab shell**

Run:

```bash
git add src package.json package-lock.json vite.config.ts
git commit -m "feat: add tabbed workspace shell"
```

## Task 8: Add Data Ingress and Segment Review UI

**Files:**
- Modify: `src/components/DataIngressTab.tsx`
- Modify: `src/components/VideoReviewTab.tsx`
- Modify: `src/App.test.tsx`

- [ ] **Step 1: Add failing UI tests for import and segment guidance**

Append to `src/App.test.tsx`:

```tsx
it("shows segment intent guidance in video review", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(screen.getByRole("tab", { name: "Video Review" }));
  await user.click(screen.getByLabelText("Use for image training"));
  await user.click(screen.getByLabelText("Use for voice training / cloning"));

  expect(screen.getByText("Extract sparse keyframes from stable visual ranges.")).toBeInTheDocument();
  expect(screen.getByText("Prefer clean speech with one speaker and low noise.")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm run test -- src/App.test.tsx
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Implement Data Ingress path input**

Replace `src/components/DataIngressTab.tsx` with:

```tsx
import { useState } from "react";
import type { EngineClient } from "../lib/api";
import type { MediaItem } from "../lib/types";

interface Props {
  engine: EngineClient;
  mediaItems: MediaItem[];
  onMediaItemsImported(items: MediaItem[]): void;
}

export function DataIngressTab({ engine, mediaItems, onMediaItemsImported }: Props) {
  const [pathsText, setPathsText] = useState("");
  const [status, setStatus] = useState("Idle");

  async function importPaths() {
    const paths = pathsText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (paths.length === 0) {
      setStatus("Enter at least one local file path.");
      return;
    }
    setStatus("Importing");
    const response = await engine.importLocal(paths);
    onMediaItemsImported(response.media_items);
    setStatus(`Imported ${response.media_items.length} media item(s).`);
  }

  return (
    <section className="workflow-panel">
      <h2>Data Ingress</h2>
      <label htmlFor="local-paths">Local image/video paths</label>
      <textarea
        id="local-paths"
        value={pathsText}
        onChange={(event) => setPathsText(event.target.value)}
        rows={6}
        placeholder="/absolute/path/to/file.png"
      />
      <button onClick={importPaths}>Import Local Media</button>
      <p aria-live="polite">{status}</p>
      <p>{mediaItems.length} media items imported.</p>
    </section>
  );
}
```

- [ ] **Step 4: Implement segment review controls and guidance**

Replace `src/components/VideoReviewTab.tsx` with:

```tsx
import { useMemo, useState } from "react";
import type { MediaItem } from "../lib/types";

interface Props {
  mediaItems: MediaItem[];
}

export function VideoReviewTab({ mediaItems }: Props) {
  const [startSeconds, setStartSeconds] = useState("0");
  const [endSeconds, setEndSeconds] = useState("10");
  const [useForImage, setUseForImage] = useState(false);
  const [useForVideo, setUseForVideo] = useState(false);
  const [useForVoice, setUseForVoice] = useState(false);
  const videoCount = mediaItems.filter((item) => item.media_type === "video").length;

  const guidance = useMemo(() => {
    const lines: string[] = [];
    if (useForImage) lines.push("Extract sparse keyframes from stable visual ranges.");
    if (useForVideo) lines.push("Keep the clip coherent; there is no hard duration limit.");
    if (useForVoice) lines.push("Prefer clean speech with one speaker and low noise.");
    if (lines.length === 0) lines.push("Select at least one training intent for this segment.");
    return lines;
  }, [useForImage, useForVideo, useForVoice]);

  return (
    <section className="workflow-panel">
      <h2>Video Review</h2>
      <p>{videoCount} videos ready for segment review.</p>

      <div className="field-grid">
        <label>
          Start seconds
          <input value={startSeconds} onChange={(event) => setStartSeconds(event.target.value)} inputMode="decimal" />
        </label>
        <label>
          End seconds
          <input value={endSeconds} onChange={(event) => setEndSeconds(event.target.value)} inputMode="decimal" />
        </label>
      </div>

      <fieldset>
        <legend>Training intent</legend>
        <label>
          <input type="checkbox" checked={useForImage} onChange={(event) => setUseForImage(event.target.checked)} />
          Use for image training
        </label>
        <label>
          <input type="checkbox" checked={useForVideo} onChange={(event) => setUseForVideo(event.target.checked)} />
          Use for video training
        </label>
        <label>
          <input type="checkbox" checked={useForVoice} onChange={(event) => setUseForVoice(event.target.checked)} />
          Use for voice training / cloning
        </label>
      </fieldset>

      <div>
        <h3>Guidance</h3>
        {guidance.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Add form styling**

Append to `src/styles.css`:

```css
.workflow-panel {
  max-width: 980px;
}

.workflow-panel h2 {
  margin-top: 0;
}

.workflow-panel label,
.workflow-panel legend {
  color: #27343b;
  font-weight: 650;
}

.workflow-panel textarea,
.workflow-panel input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 9px 10px;
  border: 1px solid #bbc7c0;
  background: #ffffff;
  color: #172026;
}

.workflow-panel button {
  margin-top: 12px;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid #225c63;
  background: #276a72;
  color: #ffffff;
  cursor: pointer;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(140px, 220px));
  gap: 14px;
  margin: 18px 0;
}

fieldset {
  display: grid;
  gap: 10px;
  max-width: 420px;
  margin: 18px 0;
  padding: 14px;
  border: 1px solid #d7ddd6;
}

fieldset label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

fieldset input {
  width: auto;
  margin: 0;
}
```

- [ ] **Step 6: Run UI tests**

Run:

```bash
npm run test -- src/App.test.tsx
```

Expected:

```text
1 file passed
```

- [ ] **Step 7: Commit ingress and video UI**

Run:

```bash
git add src/components/DataIngressTab.tsx src/components/VideoReviewTab.tsx src/App.test.tsx src/styles.css
git commit -m "feat: add local ingress and segment review ui"
```

## Task 9: Add Export UI and Engine Request

**Files:**
- Modify: `src/components/ExportsTab.tsx`
- Modify: `src/App.test.tsx`

- [ ] **Step 1: Write failing export UI test**

Append to `src/App.test.tsx`:

```tsx
it("shows RunComfy export controls", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(screen.getByRole("tab", { name: "Exports" }));

  expect(screen.getByLabelText("Frame paths")).toBeInTheDocument();
  expect(screen.getByLabelText("Output folder")).toBeInTheDocument();
  expect(screen.getByLabelText("Caption template")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create RunComfy Image Export" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm run test -- src/App.test.tsx
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Implement export controls**

Replace `src/components/ExportsTab.tsx` with:

```tsx
import { useState } from "react";
import type { EngineClient } from "../lib/api";

interface Props {
  engine: EngineClient;
}

export function ExportsTab({ engine }: Props) {
  const [framesText, setFramesText] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [captionTemplate, setCaptionTemplate] = useState("trigger_token, clean portrait");
  const [status, setStatus] = useState("Idle");

  async function createExport() {
    const frames = framesText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (frames.length === 0 || outputDir.trim() === "") {
      setStatus("Frame paths and output folder are required.");
      return;
    }
    setStatus("Exporting");
    const result = await engine.exportRunComfyImage({
      frames,
      output_dir: outputDir.trim(),
      caption_template: captionTemplate,
      source_segment_ids: [],
    });
    setStatus(`Export ${result.status}: ${result.output_path}`);
  }

  return (
    <section className="workflow-panel">
      <h2>Exports</h2>
      <label htmlFor="frame-paths">Frame paths</label>
      <textarea id="frame-paths" value={framesText} onChange={(event) => setFramesText(event.target.value)} rows={6} />

      <label htmlFor="output-folder">Output folder</label>
      <input id="output-folder" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} />

      <label htmlFor="caption-template">Caption template</label>
      <input
        id="caption-template"
        value={captionTemplate}
        onChange={(event) => setCaptionTemplate(event.target.value)}
      />

      <button onClick={createExport}>Create RunComfy Image Export</button>
      <p aria-live="polite">{status}</p>
    </section>
  );
}
```

- [ ] **Step 4: Run export UI test**

Run:

```bash
npm run test -- src/App.test.tsx
```

Expected:

```text
1 file passed
```

- [ ] **Step 5: Commit export UI**

Run:

```bash
git add src/components/ExportsTab.tsx src/App.test.tsx
git commit -m "feat: add runcomfy export ui"
```

## Task 10: Add Development Documentation and Full Verification

**Files:**
- Create: `docs/development.md`
- Modify: `package.json`
- Modify: `src-tauri/tauri.conf.json`

- [ ] **Step 1: Confirm Tauri configuration**

Ensure `src-tauri/tauri.conf.json` contains this build section:

```json
{
  "build": {
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build",
    "devUrl": "http://localhost:5173",
    "frontendDist": "../dist"
  }
}
```

Keep generated Tauri product and bundle fields intact.

- [ ] **Step 2: Write development documentation**

Create `docs/development.md`:

````markdown
# LoraSuite Development

## Local Engine

Create the Python environment once:

```bash
python3 -m venv engine/.venv
engine/.venv/bin/python -m pip install --upgrade pip
engine/.venv/bin/python -m pip install -e "engine[dev]"
```

Run the engine:

```bash
npm run dev:engine
```

The engine listens on `http://127.0.0.1:8765`.

## Desktop App

Run the desktop development app and engine together:

```bash
npm run dev:all
```

## Tests

Run frontend tests:

```bash
npm run test
```

Run engine tests:

```bash
engine/.venv/bin/python -m pytest engine/tests -q
```

Run production frontend build:

```bash
npm run build
```

## First Slice Workflow

1. Open **Data Ingress**.
2. Paste absolute paths to local images or videos.
3. Import them into the vault.
4. Open **Video Review** and select segment intent flags.
5. Extract frames through the engine tests or direct API.
6. Open **Exports**.
7. Paste frame paths and choose an output folder.
8. Create the RunComfy AI Toolkit image export.
````

- [ ] **Step 3: Run full verification**

Run:

```bash
npm run test
engine/.venv/bin/python -m pytest engine/tests -q
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected:

```text
frontend tests pass
engine tests pass
vite build completes
cargo check completes
```

FFmpeg-specific tests may show `skipped` when FFmpeg is not installed. That is acceptable only for `engine/tests/test_ffmpeg.py`.

- [ ] **Step 4: Commit docs and verification config**

Run:

```bash
git add docs/development.md package.json package-lock.json src-tauri/tauri.conf.json
git commit -m "docs: add development workflow"
```

## Task 11: Manual Smoke Test the Vertical Slice

**Files:**
- No planned file edits.

- [ ] **Step 1: Start engine and desktop app**

Run:

```bash
npm run dev:all
```

Expected:

```text
engine | Uvicorn running on http://127.0.0.1:8765
tauri  | App started
```

- [ ] **Step 2: Create a local image fixture**

Run:

```bash
engine/.venv/bin/python - <<'PY'
from pathlib import Path
from PIL import Image

fixture_dir = Path(".lorasuite/manual-fixtures")
fixture_dir.mkdir(parents=True, exist_ok=True)
Image.new("RGB", (128, 128), color=(100, 140, 180)).save(fixture_dir / "portrait.png")
print((fixture_dir / "portrait.png").resolve())
PY
```

Expected:

```text
/Volumes/Main External/Development/LoraSuite/.lorasuite/manual-fixtures/portrait.png
```

- [ ] **Step 3: Exercise the UI**

Use the Tauri window:

```text
Data Ingress: paste the printed image path and click Import Local Media.
Curate / Search: confirm the imported item count updates.
Video Review: toggle image and voice intent and confirm guidance text appears.
Exports: paste the imported raw image path or fixture path, choose .lorasuite/manual-export, and click Create RunComfy Image Export.
```

Expected files:

```text
.lorasuite/manual-export/images/000001.png
.lorasuite/manual-export/images/000001.txt
.lorasuite/manual-export/manifest.json
.lorasuite/manual-export/export_report.md
```

- [ ] **Step 4: Stop dev processes**

Press `Ctrl-C` in the terminal running `npm run dev:all`.

- [ ] **Step 5: Record final state**

Run:

```bash
git status --short --branch
```

Expected:

```text
## main
```

If manual smoke output under `.lorasuite/` exists, it remains ignored by git.

## Post-Plan Acceptance Criteria

The implementation is complete when:

- `npm run test` passes.
- `engine/.venv/bin/python -m pytest engine/tests -q` passes, with FFmpeg tests passing or explicitly skipped because FFmpeg is absent.
- `npm run build` passes.
- `cargo check --manifest-path src-tauri/Cargo.toml` passes.
- `npm run dev:all` starts the engine and desktop shell.
- Manual smoke test creates a RunComfy-compatible folder with `images/000001.png`, `images/000001.txt`, `manifest.json`, and `export_report.md`.
- `git status --short --branch` shows a clean `main` branch after committed implementation work.
