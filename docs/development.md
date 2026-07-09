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

By default, the engine uses `~/.lorasuite/vault`. Override that during development with:

```bash
LORASUITE_VAULT_ROOT=/absolute/path/to/vault npm run dev:engine
```

## Desktop App

Run the desktop development app and engine together:

```bash
npm run dev:all
```

The Vite dev server runs on `http://127.0.0.1:5173`, and Tauri opens the desktop shell.

## Tests

Run frontend tests:

```bash
npm run test
```

Run engine tests:

```bash
npm run engine:test
```

Run production frontend build:

```bash
npm run build
```

Check the Tauri/Rust shell:

```bash
cargo check --manifest-path src-tauri/Cargo.toml
```

## First Slice Workflow

1. Open **Data Ingress**.
2. Scan local files or folders.
3. Review candidates in **Tile**, **List**, or **Gallery** mode.
4. Confirm selected candidates to import them into the vault.
5. Watch the ingress job table for completion.
6. Open **Curate**.
7. Send selected image candidates to **Identify**.
8. Select imported videos for breakdown to generate frame and voice derivatives.
9. Open **Train**.
10. Paste frame paths and choose an output folder.
11. Create the RunComfy AI Toolkit image export.

## Local Ingress Review

The **Data Ingress** tab uses scan -> review -> confirm.

1. Open **Data Ingress**.
2. Click **Choose Files** or **Choose Folder** in the Tauri app.
3. In browser-only development, paste absolute paths into **Manual path fallback** and click **Scan Manual Paths**.
4. Review candidates in **Tile**, **List**, or **Gallery** mode.
5. Select the candidates to import.
6. Click **Confirm Ingest**.
7. Watch the ingress job table for status.
8. Completed imports are added to the app's media list for **Curate / Search**.

The first scan does not copy raw media into the vault. It creates reviewable candidates and lightweight previews. Confirming selected candidates creates an ingress job that copies selected ready local candidates and downloads selected social originals when a direct media URL is available.

## Video Breakdown Processing

The first processing slice is trainer-neutral. It creates derivatives from imported vault videos and writes those derivatives back as normal `MediaItem` records.

1. Import or confirm-ingest a video so it appears in **Curate**.
2. Select the video's **Breakdown** checkbox.
3. Click **Break Down Selected Videos**.
4. The frontend creates a `/processing/jobs` video breakdown job.
5. The engine extracts frame images and a WAV voice clip through FFmpeg.
6. Generated derivatives are appended to the vault manifest and returned to **Curate**.

The processing service stores job state in `processing_jobs.json` under the vault root. Video derivatives are written under `derivatives/video_breakdowns/<job_id>/<source_media_item_id>/`, then appended to the vault manifest with derivative metadata such as `asset_role`, `derivative_type`, `source_media_item_id`, `time_range`, and generator settings.

Retries are manifest-aware. If a stale running job is processed again, existing manifest-backed derivative paths are reused instead of duplicated or overwritten. Failed attempts clean up only unmanifested outputs; if manifest state cannot be read, cleanup leaves files in place rather than risking data loss.

The API surface is:

```http
POST /processing/jobs
GET /processing/jobs
GET /processing/jobs/{job_id}
```

Example request:

```json
{
  "job_type": "video_breakdown",
  "source_media_item_ids": ["media_video_1"],
  "options": {
    "generate_frames": true,
    "extract_audio": true,
    "frames_per_second": 1,
    "max_frame_count": 6
  }
}
```

The current UI uses this processing path for frame extraction and audio extraction. It does not yet caption frames, detect faces, score frame quality, or create trainer-specific packages directly. Those steps belong to the later Identify and Train slices.

## Instagram Browser Scan

The normal Instagram v0 path uses browser cookies from a local browser session:

1. Start the engine with `npm run dev:engine`.
2. Log into Instagram in Chrome, Brave, Chromium, Edge, Firefox, or Safari.
3. Open **Data Ingress** -> **Instagram Source** in LoraSuite.
4. Paste an Instagram post URL, reel URL, or profile reels tab URL such as `https://www.instagram.com/example/reels/` into **Instagram URL**.
5. Choose the matching **Browser cookies** source.
6. Click **Scan Instagram URL**.
7. Review the candidates in **Tile**, **List**, or **Gallery** mode.
8. Confirm only the candidates that should enter the vault.

For individual post and reel URLs, the engine uses `yt-dlp` with the selected browser's local cookies to read Instagram metadata. For profile reels tabs, the engine resolves the profile through Instagram's web API and then reads the reels/clips feed with the same browser session. Scans download only thumbnail/poster bytes for review and preserve direct media URLs for confirm-time transfer. They do not persist browser cookies, authorization headers, CSRF tokens, or session fields.

The unpacked Session Helper extension remains available as a fallback:

1. Load `helpers/lorasuite-session-helper` as an unpacked Chrome/Chromium extension.
2. Open an Instagram post or reel in that browser.
3. Click the extension and choose **Scan Current Instagram Page**.
4. Open **Data Ingress** -> **Instagram Source** in LoraSuite.
5. Click **Load Helper Candidates**.

The helper reads page metadata and poster image URLs from the active tab. It sends a sanitized manifest to `http://127.0.0.1:8765/ingress/instagram/helper-scan`, and uses `credentials: "omit"` when fetching poster image bytes for the low-bandwidth preview. It does not send cookies, authorization headers, CSRF tokens, or browser session fields.

The debug fallback still accepts a browser-extension Session Helper payload. In development, paste fixture JSON into **Instagram Source** -> **Instagram helper payload**.

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

The engine rejects token-like fields such as `cookie`, `authorization`, `csrf`, `session`, and `token`. The helper path creates a video preview candidate and a selectable poster image candidate. If a selected video candidate has a direct `download_url`, the ingress job streams it into `vault/downloads/<source>/` and imports it into the raw vault.

If a helper video candidate is selected before a direct original URL exists, the ingress job completes with that item counted as **Deferred** instead of failed. Poster-image candidates with cached local previews still import immediately.

## Legacy Direct Import API

The engine still exposes `/vault/import/local` for direct tests and compatibility, but the product UI should use the ingress scan/job flow.

## Train and Export Workflow

1. Use **Curate** to select image candidates and generated video frames.
2. Use **Identify** to assemble target identity candidates.
3. Open **Train**.
4. Paste frame paths and choose an output folder.
5. Create the RunComfy AI Toolkit image export.

## Export Safety

RunComfy image export accepts explicit frame paths only. It writes `images/000001.<ext>`, matching `images/000001.txt`, `manifest.json`, and `export_report.md`.

The exporter refuses WebP, unreadable images, empty frame lists, duplicate frame paths, and unrelated non-empty output folders. It can safely replace a previous LoraSuite RunComfy export folder.
