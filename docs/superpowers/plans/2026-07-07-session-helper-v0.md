# Session Helper v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a browser-extension-style Session Helper v0 that scans the active Instagram page with the user's browser session, sends only sanitized media manifests to LoraSuite, and lets the Data Ingress UI load those candidates for review.

**Architecture:** The helper is a local unpacked browser extension under `helpers/lorasuite-session-helper`. It reads page metadata and poster URLs from the active Instagram tab, converts poster thumbnails to low-bandwidth data URLs when possible, and posts a token-free payload to the existing engine scan endpoint. The engine decodes helper poster data into cached vault previews, persists candidates, and the UI can load stored Instagram candidates without pasted JSON.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, Pillow, React 19, TypeScript, Vite, Vitest, Chrome/Chromium Manifest V3.

---

## File Structure

- Modify `engine/src/lorasuite_engine/social_helper.py`
  - Decode `poster_data_url` / `thumbnail_data_url` image payloads into vault preview files.
  - Preserve source URLs but never persist raw data URLs.
- Modify `engine/tests/test_social_helper.py`
  - Cover data URL poster ingestion and token-like payload rejection.
- Modify `engine/src/lorasuite_engine/ingress.py`
  - Add `list_candidates(source_kind=None)` for UI reload after external helper scans.
- Modify `engine/src/lorasuite_engine/api.py`
  - Add `GET /ingress/candidates`.
- Modify `engine/tests/test_api.py`
  - Cover source-filtered candidate listing after Instagram helper scan.
- Modify `src/lib/api.ts`, `src/lib/api.test.ts`
  - Add `listIngressCandidates`.
- Modify `src/components/DataIngressTab.tsx`, `src/App.test.tsx`, `src/styles.css`
  - Add **Load Helper Candidates** beside the Instagram helper controls.
  - Keep JSON fixture textarea as development fallback.
- Create `helpers/lorasuite-session-helper/manifest.json`
  - Manifest V3 extension shell.
- Create `helpers/lorasuite-session-helper/popup.html`
  - Minimal helper UI for scanning current Instagram tab and sending to engine.
- Create `helpers/lorasuite-session-helper/popup.js`
  - Uses `chrome.scripting.executeScript`, converts poster URLs to data URLs, posts to engine.
- Create `helpers/lorasuite-session-helper/src/instagram-page.js`
  - Pure manifest builder from a collected page snapshot.
- Create `helpers/lorasuite-session-helper/src/payload-safety.js`
  - Token-like key guard for helper payloads before network send.
- Create `helpers/lorasuite-session-helper/src/instagram-page.test.js`
  - Vitest coverage for page metadata -> sanitized helper payload.
- Create `helpers/lorasuite-session-helper/README.md`
  - Local install/use instructions.
- Modify `docs/development.md`
  - Document the extension workflow and debug fallback.

---

## Task 1: Engine Poster Data URLs

**Files:**
- Modify: `engine/tests/test_social_helper.py`
- Modify: `engine/src/lorasuite_engine/social_helper.py`

- [ ] **Step 1: Write failing test**

Add a test that sends a small JPEG `poster_data_url`, verifies two candidates are created, verifies the cached preview exists, and verifies the raw data URL is not stored in `metadata_json`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_social_helper.py::test_instagram_helper_caches_poster_data_url_without_persisting_data -q
```

Expected: fail because data URLs are not decoded.

- [ ] **Step 3: Implement minimal data URL decoding**

Add a helper that accepts only `data:image/jpeg;base64,...`, `data:image/jpg;base64,...`, and `data:image/png;base64,...`, writes the decoded bytes to `vault/previews/social/<media_id>.<ext>`, and returns that path.

- [ ] **Step 4: Run focused tests**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_social_helper.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/social_helper.py engine/tests/test_social_helper.py
git commit -m "feat: accept helper poster data urls"
```

## Task 2: Stored Candidate Listing

**Files:**
- Modify: `engine/tests/test_api.py`
- Modify: `engine/src/lorasuite_engine/ingress.py`
- Modify: `engine/src/lorasuite_engine/api.py`

- [ ] **Step 1: Write failing API test**

Add a test that scans an Instagram helper payload, calls `GET /ingress/candidates?source_kind=instagram`, and verifies it returns the stored Instagram candidates.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py::test_ingress_candidates_endpoint_filters_instagram_candidates -q
```

Expected: 404.

- [ ] **Step 3: Implement listing**

Add `IngressService.list_candidates(source_kind: SourceKind | None = None)` and `GET /ingress/candidates`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
engine/.venv/bin/python -m pytest engine/tests/test_api.py engine/tests/test_ingress.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add engine/src/lorasuite_engine/api.py engine/src/lorasuite_engine/ingress.py engine/tests/test_api.py
git commit -m "feat: list stored ingress candidates"
```

## Task 3: Frontend Load Helper Candidates

**Files:**
- Modify: `src/lib/api.test.ts`
- Modify: `src/lib/api.ts`
- Modify: `src/App.test.tsx`
- Modify: `src/components/DataIngressTab.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Write failing frontend tests**

Add API client coverage for `GET /ingress/candidates?source_kind=instagram` and UI coverage for the **Load Helper Candidates** button.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
npm run test -- src/lib/api.test.ts src/App.test.tsx
```

Expected: fail because the client method and button do not exist.

- [ ] **Step 3: Implement UI**

Add `listIngressCandidates(sourceKind?: SourceKind)` to the client. Add a **Load Helper Candidates** button in the Instagram helper panel that loads stored Instagram candidates into the existing tile/list/gallery review state.

- [ ] **Step 4: Run focused tests and build**

Run:

```bash
npm run test -- src/lib/api.test.ts src/App.test.tsx
npm run build
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/lib/api.ts src/lib/api.test.ts src/App.test.tsx src/components/DataIngressTab.tsx src/styles.css
git commit -m "feat: load instagram helper candidates"
```

## Task 4: Browser Session Helper Package

**Files:**
- Create: `helpers/lorasuite-session-helper/manifest.json`
- Create: `helpers/lorasuite-session-helper/popup.html`
- Create: `helpers/lorasuite-session-helper/popup.js`
- Create: `helpers/lorasuite-session-helper/src/instagram-page.js`
- Create: `helpers/lorasuite-session-helper/src/payload-safety.js`
- Create: `helpers/lorasuite-session-helper/src/instagram-page.test.js`
- Create: `helpers/lorasuite-session-helper/README.md`

- [ ] **Step 1: Write failing helper test**

Add a Vitest test that builds a helper payload from an Instagram reel-like snapshot with `og:video`, `og:image`, `og:title`, and canonical URL.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
npm run test -- helpers/lorasuite-session-helper/src/instagram-page.test.js
```

Expected: fail because helper modules do not exist.

- [ ] **Step 3: Implement helper modules and extension shell**

Create the Manifest V3 extension. The popup scans the active tab, builds a sanitized helper payload, fetches poster URLs as data URLs where possible, rejects token-like keys before sending, and posts to `http://127.0.0.1:8765/ingress/instagram/helper-scan`.

- [ ] **Step 4: Run helper tests**

Run:

```bash
npm run test -- helpers/lorasuite-session-helper/src/instagram-page.test.js
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add helpers/lorasuite-session-helper
git commit -m "feat: add instagram session helper extension"
```

## Task 5: Docs and Verification

**Files:**
- Modify: `docs/development.md`

- [ ] **Step 1: Document the workflow**

Add instructions for loading the unpacked helper extension, scanning an Instagram page, then using **Load Helper Candidates** in LoraSuite.

- [ ] **Step 2: Run final verification**

Run:

```bash
npm run test
npm run engine:test
npm run build
cargo check --manifest-path src-tauri/Cargo.toml
```

Expected: all pass.

- [ ] **Step 3: Smoke the helper payload path**

Run a Python smoke that posts a `poster_data_url` helper payload, lists stored Instagram candidates, creates an Instagram job for the poster candidate, and verifies `status=complete` and `imported_count=1`.

- [ ] **Step 4: Commit**

```bash
git add docs/development.md
git commit -m "docs: describe session helper workflow"
```

---

## Self-Review

- Spec coverage: The plan covers browser-session acquisition, no token transport, low-bandwidth poster thumbnails, UI review before confirm, and fixture fallback.
- Placeholder scan: No implementation step relies on unspecified behavior.
- Type consistency: Engine/source kind names match existing `SourceKind.INSTAGRAM`; frontend uses existing `SourceKind` type.
