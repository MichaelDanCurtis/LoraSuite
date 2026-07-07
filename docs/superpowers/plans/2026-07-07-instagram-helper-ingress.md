# Instagram Helper Ingress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first Instagram ingress path by accepting browser-extension Session Helper payloads, turning Instagram video posters into reviewable candidates, and allowing selected cached poster-image candidates to flow through the existing ingress job table.

**Architecture:** The first version is fixture-backed and local-only: it does not scrape Instagram or persist browser tokens. A new engine service validates helper payloads, rejects token-like fields, caches local poster/thumbnail image files into the vault preview area, and emits `IngressCandidate` records. The existing Data Ingress UI gets an Instagram helper payload panel that feeds those candidates into the same tile/list/gallery review and job flow.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, Pillow, React 19, TypeScript, Vite, Vitest, pytest.

---

## File Structure

Engine:

- Create `engine/src/lorasuite_engine/social_helper.py`
  - Validate helper payloads.
  - Reject raw auth/cookie/token-like keys.
  - Convert Instagram helper media descriptors into ingress candidates.
  - Cache local poster paths into `vault/previews/social`.
- Modify `engine/src/lorasuite_engine/ingress.py`
  - Allow non-local candidates to import only when they provide a local cached `metadata_json.local_import_path`.
- Modify `engine/src/lorasuite_engine/api.py`
  - Add `POST /ingress/instagram/helper-scan`.
- Add `engine/tests/test_social_helper.py`
  - Cover auth redaction and poster candidate creation.
- Modify `engine/tests/test_ingress.py`
  - Cover job processing for a social poster candidate with a cached local import path.
- Modify `engine/tests/test_api.py`
  - Cover the new Instagram helper scan endpoint.

Frontend:

- Modify `src/lib/api.ts`
  - Add `scanInstagramHelperPayload`.
- Modify `src/lib/api.test.ts`
  - Cover the new client method.
- Modify `src/components/DataIngressTab.tsx`
  - Enable **Instagram Source**.
  - Add a helper payload textarea and **Scan Instagram Helper Payload** action.
  - Let confirm jobs use the selected candidates' source kind instead of always `local`.
- Modify `src/App.test.tsx`
  - Cover the Instagram helper payload controls.
- Modify `src/styles.css`
  - Add a compact `.helper-payload-panel` style for the fixture JSON panel.
- Modify `docs/development.md`
  - Document the fixture-backed Instagram helper payload format.

---

## Task 1: Add Social Helper Service

**Files:**
- Create: `engine/src/lorasuite_engine/social_helper.py`
- Create: `engine/tests/test_social_helper.py`

- [ ] **Step 1: Write failing tests**

Create `engine/tests/test_social_helper.py`:

```python
from pathlib import Path

import pytest
from PIL import Image

from lorasuite_engine.models import MediaType, SourceKind
from lorasuite_engine.social_helper import scan_instagram_helper_payload


def test_instagram_helper_rejects_token_like_payload_keys(tmp_path):
    payload = {
        "helper_version": "fixture",
        "headers": {"cookie": "sessionid=secret"},
        "media": [],
    }

    with pytest.raises(ValueError, match="token-like field"):
        scan_instagram_helper_payload(payload, tmp_path / "vault")


def test_instagram_helper_creates_video_and_poster_candidates(tmp_path):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (120, 160), color=(80, 40, 120)).save(poster)
    payload = {
        "helper_version": "fixture",
        "media": [
            {
                "id": "ig_video_1",
                "source_url": "https://www.instagram.com/reel/example/",
                "display_name": "example reel",
                "media_type": "video",
                "poster_path": str(poster),
                "width": 1080,
                "height": 1920,
                "duration": 9.5,
            }
        ],
    }

    result = scan_instagram_helper_payload(
        payload,
        tmp_path / "vault",
        include_video_posters_as_image_candidates=True,
    )

    assert len(result.candidates) == 2
    video = result.candidates[0]
    poster_candidate = result.candidates[1]
    assert video.source_kind == SourceKind.INSTAGRAM
    assert video.media_type == MediaType.VIDEO
    assert video.poster_asset_path is not None
    assert Path(video.poster_asset_path).exists()
    assert video.selected is False
    assert poster_candidate.media_type == MediaType.IMAGE
    assert poster_candidate.selected is True
    assert poster_candidate.metadata_json["local_import_path"] == str(video.poster_asset_path)
    assert poster_candidate.metadata_json["source_video_candidate_id"] == video.id
```

- [ ] **Step 2: Verify RED**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_social_helper.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'lorasuite_engine.social_helper'
```

- [ ] **Step 3: Implement service**

Create `engine/src/lorasuite_engine/social_helper.py`:

```python
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lorasuite_engine.models import (
    IngressCandidate,
    IngressCandidateStatus,
    IngressScanResult,
    MediaType,
    SourceKind,
)

TOKEN_LIKE_KEYS = frozenset(
    {"authorization", "cookie", "cookies", "csrf", "session", "token", "x-csrftoken"}
)


def scan_instagram_helper_payload(
    payload: dict[str, Any],
    vault_root: Path,
    *,
    include_video_posters_as_image_candidates: bool = True,
) -> IngressScanResult:
    reject_token_like_fields(payload)
    result = IngressScanResult()
    helper_version = str(payload.get("helper_version") or "unknown")
    for item in payload.get("media", []):
        candidate = _candidate_from_item(item, Path(vault_root), helper_version)
        result.candidates.append(candidate)
        if (
            include_video_posters_as_image_candidates
            and candidate.media_type == MediaType.VIDEO
            and candidate.poster_asset_path is not None
        ):
            result.candidates.append(_poster_candidate(candidate))
    return result


def reject_token_like_fields(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in TOKEN_LIKE_KEYS or any(part in normalized for part in TOKEN_LIKE_KEYS):
                raise ValueError(f"token-like field is not accepted: {path}.{key}")
            reject_token_like_fields(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_token_like_fields(child, path=f"{path}[{index}]")


def _candidate_from_item(
    item: Mapping[str, Any], vault_root: Path, helper_version: str
) -> IngressCandidate:
    media_id = str(item["id"])
    media_type = MediaType(str(item["media_type"]))
    poster_path = _cache_preview_asset(item, vault_root, media_id)
    source_url = str(item.get("source_url") or "")
    return IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator=source_url or media_id,
        display_name=str(item.get("display_name") or media_id),
        media_type=media_type,
        width=_optional_int(item.get("width")),
        height=_optional_int(item.get("height")),
        duration=_optional_float(item.get("duration")),
        thumbnail_path=poster_path,
        poster_asset_path=poster_path if media_type == MediaType.VIDEO else None,
        status=IngressCandidateStatus.READY,
        selected=media_type == MediaType.IMAGE,
        metadata_json={
            "platform_media_id": media_id,
            "source_url": source_url,
            "helper_version": helper_version,
            "download_url": item.get("download_url"),
            "poster_source_path": item.get("poster_path") or item.get("thumbnail_path"),
        },
    )


def _poster_candidate(video_candidate: IngressCandidate) -> IngressCandidate:
    poster_path = video_candidate.poster_asset_path
    return IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator=str(poster_path),
        display_name=f"{video_candidate.display_name} poster",
        media_type=MediaType.IMAGE,
        width=video_candidate.width,
        height=video_candidate.height,
        thumbnail_path=poster_path,
        status=IngressCandidateStatus.READY,
        selected=True,
        metadata_json={
            **video_candidate.metadata_json,
            "source_video_candidate_id": video_candidate.id,
            "local_import_path": str(poster_path),
            "asset_role": "video_poster",
        },
    )


def _cache_preview_asset(
    item: Mapping[str, Any], vault_root: Path, media_id: str
) -> Path | None:
    raw_path = item.get("poster_path") or item.get("thumbnail_path")
    if not raw_path:
        return None
    source_path = Path(str(raw_path))
    if not source_path.exists() or not source_path.is_file():
        return None
    previews_dir = vault_root / "previews" / "social"
    previews_dir.mkdir(parents=True, exist_ok=True)
    target = previews_dir / f"{media_id}{source_path.suffix.lower()}"
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return target


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_social_helper.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/social_helper.py engine/tests/test_social_helper.py
git commit -m "feat: add instagram helper scan service"
```

---

## Task 2: Let Jobs Import Cached Social Poster Candidates

**Files:**
- Modify: `engine/src/lorasuite_engine/ingress.py`
- Modify: `engine/tests/test_ingress.py`

- [ ] **Step 1: Write failing job test**

Append to `engine/tests/test_ingress.py`:

```python
from lorasuite_engine.models import IngressCandidate


def test_ingress_job_imports_cached_social_poster_candidate(tmp_path):
    poster = tmp_path / "poster.jpg"
    Image.new("RGB", (32, 48), color=(120, 60, 20)).save(poster)
    service = IngressService(tmp_path / "vault")
    candidate = IngressCandidate(
        source_kind=SourceKind.INSTAGRAM,
        source_locator="https://www.instagram.com/reel/example/#poster",
        display_name="example reel poster",
        media_type=MediaType.IMAGE,
        thumbnail_path=poster,
        selected=True,
        metadata_json={"local_import_path": str(poster), "asset_role": "video_poster"},
    )
    service._write_candidates({candidate.id: candidate})

    job = service.create_job(SourceKind.INSTAGRAM, [candidate.id])
    completed = service.process_job(job.id)

    assert completed.status == IngressJobStatus.COMPLETE
    assert completed.imported_count == 1
    assert completed.imported_media_items[0].metadata_json["original_path"] == str(poster)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ingress.py::test_ingress_job_imports_cached_social_poster_candidate -q
```

Expected:

```text
assert <IngressJobStatus.FAILED: 'failed'> == <IngressJobStatus.COMPLETE: 'complete'>
```

- [ ] **Step 3: Update job import path selection**

Modify `engine/src/lorasuite_engine/ingress.py` in `process_job`:

```python
        ready_import_paths = [
            import_path
            for candidate in selected_candidates
            if candidate.status == IngressCandidateStatus.READY
            for import_path in [self._import_path_for_candidate(candidate)]
            if import_path is not None
        ]
        rejected_candidates = [
            candidate
            for candidate in selected_candidates
            if candidate.status != IngressCandidateStatus.READY
            or self._import_path_for_candidate(candidate) is None
        ]

        import_result = VaultService(self.vault_root).import_local_paths(ready_import_paths)
```

Add method:

```python
    def _import_path_for_candidate(self, candidate: IngressCandidate) -> Path | None:
        if candidate.source_kind == SourceKind.LOCAL:
            return Path(candidate.source_locator)
        local_import_path = candidate.metadata_json.get("local_import_path")
        if isinstance(local_import_path, str) and local_import_path:
            return Path(local_import_path)
        return None
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_ingress.py -q
```

Expected:

```text
all ingress tests pass
```

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/ingress.py engine/tests/test_ingress.py
git commit -m "feat: import cached social poster candidates"
```

---

## Task 3: Add Instagram Helper API Endpoint

**Files:**
- Modify: `engine/src/lorasuite_engine/api.py`
- Modify: `engine/tests/test_api.py`

- [ ] **Step 1: Write failing API test**

Append to `engine/tests/test_api.py`:

```python
def test_instagram_helper_scan_endpoint_returns_poster_candidates(client, tmp_path):
    poster = tmp_path / "api-poster.jpg"
    Image.new("RGB", (44, 66), color=(80, 20, 140)).save(poster)

    response = client.post(
        "/ingress/instagram/helper-scan",
        json={
            "payload": {
                "helper_version": "fixture",
                "media": [
                    {
                        "id": "ig_api_video",
                        "source_url": "https://www.instagram.com/reel/api/",
                        "display_name": "api reel",
                        "media_type": "video",
                        "poster_path": str(poster),
                    }
                ],
            },
            "include_video_posters_as_image_candidates": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 2
    assert body["candidates"][0]["source_kind"] == "instagram"
    assert body["candidates"][1]["media_type"] == "image"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py::test_instagram_helper_scan_endpoint_returns_poster_candidates -q
```

Expected:

```text
assert 404 == 200
```

- [ ] **Step 3: Implement endpoint**

Modify `engine/src/lorasuite_engine/api.py`:

```python
from typing import Any
from lorasuite_engine.social_helper import scan_instagram_helper_payload
```

Add model:

```python
class InstagramHelperScanRequest(BaseModel):
    payload: dict[str, Any]
    include_video_posters_as_image_candidates: bool = True
```

Add endpoint inside `create_app`:

```python
    @app.post("/ingress/instagram/helper-scan")
    def scan_instagram_helper(request: InstagramHelperScanRequest) -> dict[str, object]:
        try:
            result = scan_instagram_helper_payload(
                request.payload,
                app.state.vault_root,
                include_video_posters_as_image_candidates=request.include_video_posters_as_image_candidates,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return result.model_dump(mode="json")
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py engine/tests/test_social_helper.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/api.py engine/tests/test_api.py
git commit -m "feat: add instagram helper scan api"
```

---

## Task 4: Add Frontend Client and UI

**Files:**
- Modify: `src/lib/api.ts`
- Modify: `src/lib/api.test.ts`
- Modify: `src/components/DataIngressTab.tsx`
- Modify: `src/App.test.tsx`

- [ ] **Step 1: Write failing client and UI tests**

Append to `src/lib/api.test.ts`:

```typescript
  it("posts instagram helper payloads to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_ig", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const payload = { helper_version: "fixture", media: [] };

    await client.scanInstagramHelperPayload(payload, true);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/instagram/helper-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        payload,
        include_video_posters_as_image_candidates: true,
      }),
    });
  });
```

Append to `src/App.test.tsx`:

```typescript
it("shows instagram helper payload controls", async () => {
  const user = userEvent.setup();
  render(<App />);

  await user.click(screen.getByRole("button", { name: "Instagram Source" }));

  expect(screen.getByLabelText("Instagram helper payload")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Scan Instagram Helper Payload" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify RED**

Run:

```bash
npm run test -- src/lib/api.test.ts src/App.test.tsx
```

Expected:

```text
client.scanInstagramHelperPayload is not a function
```

- [ ] **Step 3: Add client method**

Modify `src/lib/api.ts`:

```typescript
  scanInstagramHelperPayload(
    payload: Record<string, unknown>,
    includeVideoPostersAsImageCandidates?: boolean,
  ): Promise<IngressScanResult>;
```

Add return method:

```typescript
    scanInstagramHelperPayload(
      payload: Record<string, unknown>,
      includeVideoPostersAsImageCandidates = true,
    ) {
      return postJson<IngressScanResult>("/ingress/instagram/helper-scan", {
        payload,
        include_video_posters_as_image_candidates: includeVideoPostersAsImageCandidates,
      });
    },
```

- [ ] **Step 4: Add UI panel**

Modify `src/components/DataIngressTab.tsx`:

- add state:

```typescript
  const [showInstagramHelper, setShowInstagramHelper] = useState(false);
  const [instagramPayloadText, setInstagramPayloadText] = useState(
    '{\n  "helper_version": "fixture",\n  "media": []\n}',
  );
```

- make **Instagram Source** enabled:

```tsx
        <button type="button" onClick={() => setShowInstagramHelper((visible) => !visible)}>
          Instagram Source
        </button>
```

- add function:

```typescript
  async function scanInstagramHelperPayload() {
    try {
      const payload = JSON.parse(instagramPayloadText) as Record<string, unknown>;
      setStatus("Scanning Instagram helper payload.");
      const result = await engine.scanInstagramHelperPayload(payload, true);
      setCandidates(result.candidates);
      setSelectedIds(
        new Set(
          result.candidates
            .filter((candidate) => candidate.status === "ready" && candidate.selected)
            .map((candidate) => candidate.id),
        ),
      );
      setGalleryIndex(0);
      setStatus(`Scanned ${result.candidates.length} Instagram candidate(s).`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Instagram helper scan failed.");
    }
  }
```

- add panel after actions:

```tsx
      {showInstagramHelper && (
        <div className="form-stack helper-payload-panel">
          <label htmlFor="instagram-helper-payload">Instagram helper payload</label>
          <textarea
            id="instagram-helper-payload"
            value={instagramPayloadText}
            onChange={(event) => setInstagramPayloadText(event.target.value)}
            rows={8}
          />
          <button type="button" onClick={scanInstagramHelperPayload}>
            Scan Instagram Helper Payload
          </button>
        </div>
      )}
```

- add style in `src/styles.css`:

```css
.helper-payload-panel {
  max-width: 760px;
}
```

- change `confirmIngest` to use selected source kind:

```typescript
    const selectedCandidates = candidates.filter(
      (candidate) => candidate.status === "ready" && selectedIds.has(candidate.id),
    );
    const sourceKinds = new Set(selectedCandidates.map((candidate) => candidate.source_kind));
    if (sourceKinds.size !== 1) {
      setStatus("Confirm one source type at a time.");
      return;
    }
    const sourceKind = selectedCandidates[0].source_kind;
```

Then send:

```typescript
        source_kind: sourceKind,
        candidate_ids: candidateIds,
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
npm run test -- src/lib/api.test.ts src/App.test.tsx
npm run build
```

Expected:

```text
src/lib/api.test.ts and src/App.test.tsx pass
build passes
```

- [ ] **Step 6: Commit**

```bash
git add src/lib/api.ts src/lib/api.test.ts src/components/DataIngressTab.tsx src/App.test.tsx src/styles.css
git commit -m "feat: add instagram helper ingress ui"
```

---

## Task 5: Docs, Smoke, and Full Verification

**Files:**
- Modify: `docs/development.md`

- [ ] **Step 1: Document fixture helper payload**

Add to `docs/development.md`:

```markdown
## Instagram Helper Fixture

The first Instagram ingress path accepts a browser-extension Session Helper payload. In development, paste fixture JSON into **Instagram Source** -> **Instagram helper payload**.

Example:

```json
{
  "helper_version": "fixture",
  "media": [
    {
      "id": "ig_video_1",
      "source_url": "https://www.instagram.com/reel/example/",
      "display_name": "example reel",
      "media_type": "video",
      "poster_path": "/absolute/path/to/poster.jpg",
      "width": 1080,
      "height": 1920,
      "duration": 9.5
    }
  ]
}
```

The engine rejects token-like fields such as `cookie`, `authorization`, `csrf`, `session`, and `token`. The fixture path creates a video preview candidate and a selectable poster image candidate. Full Instagram original downloading remains behind the future browser-extension helper.
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

- [ ] **Step 3: Run API smoke**

Run:

```bash
PYTHONPATH=engine/src engine/.venv/bin/python - <<'PY'
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from lorasuite_engine.api import create_app

root = Path('.lorasuite/instagram-helper-smoke').resolve()
poster = root / 'poster.jpg'
poster.parent.mkdir(parents=True, exist_ok=True)
Image.new('RGB', (64, 96), color=(120, 40, 90)).save(poster)
client = TestClient(create_app(root / 'vault'))
scan = client.post('/ingress/instagram/helper-scan', json={
    'payload': {
        'helper_version': 'fixture',
        'media': [{
            'id': 'ig_smoke_video',
            'source_url': 'https://www.instagram.com/reel/smoke/',
            'display_name': 'smoke reel',
            'media_type': 'video',
            'poster_path': str(poster),
            'width': 64,
            'height': 96,
            'duration': 3.0,
        }],
    },
}).json()
poster_candidate = [c for c in scan['candidates'] if c['media_type'] == 'image'][0]
job = client.post('/ingress/jobs', json={
    'source_kind': 'instagram',
    'candidate_ids': [poster_candidate['id']],
}).json()
detail = client.get(f"/ingress/jobs/{job['id']}").json()
print({'candidates': len(scan['candidates']), 'job_status': detail['status'], 'imported': detail['imported_count']})
PY
```

Expected:

```text
{'candidates': 2, 'job_status': 'complete', 'imported': 1}
```

- [ ] **Step 4: Commit docs**

```bash
git add docs/development.md
git commit -m "docs: describe instagram helper fixture"
```

---

## Success Criteria

- Instagram helper payloads never persist raw auth/cookie/token-like fields.
- Fixture-backed Instagram videos produce a video candidate and a selectable poster image candidate.
- Cached poster image candidates can be confirmed through the existing ingress job table.
- The UI exposes an Instagram helper payload panel without pretending the real extension is complete.
- Full original Instagram downloading remains out of scope for this slice.
