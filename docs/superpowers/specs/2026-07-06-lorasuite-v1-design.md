# LoraSuite V1 Design

## Purpose

LoraSuite is a local-first desktop tool for turning personal and collected media into training-ready dataset handoffs for character LoRAs and related media models.

The app focuses on three steps:

1. Acquire media from a narrow set of sources: Instagram, X/Twitter, TikTok, and local folders.
2. Break down, search, sort, segment, caption, and curate that media.
3. Export clean handoff folders for external training tools, especially RunComfy AI Toolkit.

LoraSuite does not run LoRA training in V1. It prepares reproducible dataset folders, captions, clips, audio, and manifests for another app to consume.

## Product Scope

### In Scope

- Local import of images and videos.
- Acquisition from Instagram, X/Twitter, and TikTok using `yt-dlp`, `gallery-dl`, browser-cookie/cookie-file auth, and FFmpeg.
- A media vault that preserves raw files and provenance.
- Video review with free start/end segment selection.
- Segment-level training-intent toggles:
  - Use for image training.
  - Use for video training.
  - Use for voice training / cloning.
- Intent-aware duration guidance, quality warnings, and export defaults.
- PhotoMapAI-derived embedding, search, UMAP, and dataset curator capabilities embedded into LoraSuite.
- RunComfy AI Toolkit image dataset export:
  - `jpg`, `jpeg`, or `png` images.
  - Matching `.txt` captions with the same basename.
  - Optional AI Toolkit trigger placeholder handling.
  - Optional generated AI Toolkit config snippet.
- Video clip handoff export for AI Toolkit-compatible video workflows.
- Generic voice handoff export:
  - `.wav` audio segments.
  - transcript text.
  - speaker label metadata.
  - provenance manifest.
- `manifest.json` for audit, rebuild, and reproducibility.

### Out of Scope

- In-app model training.
- Broad universal downloader support beyond Instagram, X/Twitter, TikTok, and local folders.
- Copying Social Saver code; it is a product reference only.
- Embedding TagGUI Video code unless the project explicitly accepts GPL-3.0 obligations.
- Preserving PhotoMapAI's current interface as the primary LoraSuite interface.

## Key External References

- PhotoMapAI: MIT-licensed local image search, embeddings, UMAP, albums, and LoRA-oriented curation.
- Social Saver: reference for desktop acquisition UX, dependency management, `yt-dlp`, `gallery-dl`, FFmpeg, and browser-cookie workflows. Its public repo is not a safe code foundation because the visible license is proprietary/personal-use and the app source is incomplete.
- TagGUI Video: reference for video review, tagging, captioning, crop/include/exclude marks, exports, and video workflow language. Its GPL-3.0 license makes it a workflow reference unless LoraSuite chooses GPL-compatible reuse.
- RunComfy AI Toolkit / ostris ai-toolkit: primary V1 export target.

## Architecture

LoraSuite uses a Tauri desktop shell with a web UI and a Python sidecar engine.

### Tauri Desktop Shell

The Tauri Rust layer owns:

- application windows and native shell behavior;
- filesystem permissions and folder pickers;
- sidecar process lifecycle;
- secure command/event bridging between the UI and Python sidecar;
- app settings that should live at the shell layer.

### Frontend

The frontend is TypeScript + React + Vite.

It owns:

- the persistent workspace tab shell;
- acquisition setup screens;
- source account and cookie-profile controls;
- media vault browsing;
- video review and segment selection UI;
- image/video/voice training-intent toggles;
- curation UI over PhotoMapAI-derived results;
- export presets and export status;
- job progress, warnings, and recoverable error states.

### Workspace Tabs

V1 should use a tabbed workspace so PhotoMapAI can live as a substantial app surface without becoming the whole product.

Initial tabs:

- **Data Ingress**: local imports, Instagram/X/Twitter/TikTok source setup, cookie profiles, acquisition jobs, and import provenance.
- **Curate / Search**: the embedded PhotoMapAI-derived workspace for browsing, semantic search, albums, UMAP/clusters, representative selection, and dataset curation.
- **Video Review**: video player, free start/end segment selection, image/video/voice intent toggles, and segment quality guidance.
- **Exports**: RunComfy AI Toolkit image dataset exports, video clip handoffs, voice handoffs, manifests, and export reports.

The first implementation can keep these as top-level app tabs. Later versions can add deeper navigation inside each tab, but V1 should avoid burying ingress or curation behind modal workflows.

### Python Sidecar Engine

The Python sidecar owns:

- a local FastAPI or equivalent worker API;
- long-running job orchestration;
- media vault database;
- provenance and manifest persistence;
- acquisition connector execution;
- FFmpeg frame, clip, and audio extraction;
- embedded PhotoMapAI core integration;
- export package creation.

The sidecar should expose a narrow API to the UI rather than leaking tool-specific command lines into the frontend.

### Embedded PhotoMapAI Core

PhotoMapAI should be vendored or forked directly into LoraSuite and gradually carved into a `photomapai_core`-style module.

The retained core capabilities are:

- album/index model adapted to LoraSuite's vault;
- CLIP/SigLIP embedding generation and persistence;
- text/image semantic search;
- UMAP and clustering;
- diversity and representative selection for LoRA candidate curation.

The current PhotoMapAI UI should not be the whole LoraSuite shell. A compatible PhotoMapAI-derived workspace can sit inside the **Curate / Search** tab while its backend and curation ideas are carved into reusable LoraSuite components.

## Data Model

### Media Source

Represents where media came from.

Fields:

- `id`
- `kind`: `instagram`, `x_twitter`, `tiktok`, or `local`
- `source_url`
- `account_handle`
- `cookie_profile_id`
- `imported_at`
- `download_tool`
- `tool_version`

### Media Item

Represents one raw acquired or imported media file.

Fields:

- `id`
- `source_id`
- `raw_path`
- `media_type`: `image`, `video`, or `audio`
- `sha256`
- `perceptual_hash`
- `duration`
- `width`
- `height`
- `created_at`
- `metadata_json`
- `status`: `new`, `reviewed`, `ignored`, or `exported`

### Segment

Represents a user-selected span of a video.

Fields:

- `id`
- `media_item_id`
- `start_seconds`
- `end_seconds`
- `label`
- `notes`
- `quality_flags`
- `use_for_image`
- `use_for_video`
- `use_for_voice`
- `created_at`
- `updated_at`

The segment range is freeform. The app gives intent-aware guidance instead of imposing a fixed duration.

### Derived Asset

Represents generated frames, clips, audio, captions, masks, or transcripts.

Fields:

- `id`
- `media_item_id`
- `segment_id`
- `asset_type`: `frame`, `clip`, `audio`, `caption`, `transcript`, or `mask`
- `path`
- `sha256`
- `generation_settings`
- `created_at`

### Export Package

Represents an output folder or zip.

Fields:

- `id`
- `export_type`: `runcomfy_image`, `ai_toolkit_video`, or `voice_handoff`
- `output_path`
- `created_at`
- `preset_json`
- `manifest_path`
- `source_segment_ids`
- `status`

## Segment Triage Workflow

1. User opens a video in the review player.
2. User chooses whether to use or skip the video.
3. If used, user selects a free start/end segment range.
4. User enables any combination of:
   - image training;
   - video training;
   - voice training / cloning.
5. LoraSuite shows intent-aware duration and quality guidance:
   - Image: stable visual range, extract sparse keyframes, dedupe near-identical frames.
   - Video: short coherent clips are preferred, but there is no hard duration limit.
   - Voice: clean speech spans with one speaker and low noise are preferred.
6. Export jobs derive outputs based on selected intents.
7. Manifest records source, time range, selected intents, hashes, outputs, and warnings.

## Export Formats

### RunComfy AI Toolkit Image Dataset

Primary V1 export.

Folder contents:

- image files in `jpg`, `jpeg`, or `png`;
- one matching `.txt` caption per image;
- optional AI Toolkit config snippet;
- LoraSuite `manifest.json`;
- human-readable export report.

Rules:

- WebP is avoided because AI Toolkit documentation calls out current issues.
- Captions use the same basename as the image.
- Captions can contain a trigger placeholder when the user selects trigger-word handoff.
- `manifest.json` is for LoraSuite audit and rebuild, not required by AI Toolkit.

### AI Toolkit Video-Ready Clip Dataset

Secondary V1 export.

Folder contents:

- selected clip files from user-approved segments;
- matching caption or prompt files where applicable;
- clip-level manifest entries with frame count, FPS, duration, source URL/path, and hashes.

This export is shaped for AI Toolkit-compatible video model workflows, but image dataset export remains the first validation target.

### Voice Handoff Dataset

Basic V1 handoff.

Folder contents:

- normalized `.wav` files;
- transcript sidecars;
- speaker labels;
- consent/provenance metadata;
- LoraSuite manifest.

The voice target remains a generic handoff until a specific downstream voice training app is selected.

## Acquisition

### Connectors

- `gallery-dl`: Instagram and X/Twitter images/galleries where appropriate.
- `yt-dlp`: TikTok, X/Twitter video, and supported video downloads.
- FFmpeg: media inspection, normalization, clips, frames, and audio.
- Local folders: direct import of existing images and videos.

### Cookie Handling

V1 supports browser-cookie and cookie-file workflows because Instagram, X/Twitter, and TikTok frequently require authenticated access.

The app should:

- let the user define named cookie profiles;
- record the cookie profile used in provenance without storing secrets in manifests;
- show clear failure states when authentication expires;
- avoid silently broadening acquisition beyond the intended source/account.

## Error Handling

Acquisition errors should preserve the attempted URL, tool, tool version, exit code, and stderr summary.

Media processing errors should preserve:

- source media item;
- attempted operation;
- FFmpeg command template or settings;
- stderr summary;
- recoverability flag.

Export errors should fail the package atomically where possible. Partial exports should be marked incomplete and include a recovery report.

## Testing Strategy

### Unit Tests

- manifest serialization;
- segment range validation;
- intent toggle logic;
- export filename generation;
- caption pairing rules;
- provenance redaction rules.

### Integration Tests

- local media import into vault;
- FFmpeg frame extraction from a small fixture video;
- FFmpeg audio extraction from a small fixture video;
- RunComfy AI Toolkit image export folder validation;
- PhotoMapAI embedding/index wrapper on fixture images.

### UI Tests

- workspace tab navigation;
- media import flow;
- video segment selection;
- intent toggle behavior;
- export preset creation;
- export completion and error states.

## First Vertical Slice

The first implementation slice should prove the product loop without social connectors:

1. Scaffold Tauri + React/Vite frontend and Python sidecar.
2. Add the workspace tab shell with **Data Ingress**, **Curate / Search**, **Video Review**, and **Exports** tabs.
3. Import local images/videos into the vault from **Data Ingress**.
4. Review one local video in **Video Review**.
5. Select a segment with free start/end.
6. Toggle image/video/voice intents.
7. Extract image frames for image intent.
8. Export a RunComfy AI Toolkit image dataset folder from **Exports**.
9. Write `manifest.json`.
10. Add basic tests for vault, segment, tab navigation, FFmpeg frame extraction, and export folder validation.

After that slice works, add Instagram/X/TikTok acquisition connectors.

## Design Diagrams

- Tauri + Python + PhotoMapAI architecture: https://prixmaviz.ailuxis.com/w/9d9a9d4c-84c2-49e7-b284-a519acad81ec
- Segment triage with intent-aware durations: https://prixmaviz.ailuxis.com/w/b5fc1406-ab71-4935-acd4-b156c2f1648e
- RunComfy AI Toolkit export flow: https://prixmaviz.ailuxis.com/w/6b88982e-80be-4945-a68e-46422f587fc4

## Approval Checkpoint

This design locks the major V1 product and architecture decisions:

- Tauri desktop app.
- TypeScript + React/Vite UI.
- Python sidecar engine.
- Tabbed workspace shell with separate **Data Ingress**, **Curate / Search**, **Video Review**, and **Exports** tabs.
- Embedded PhotoMapAI-derived workspace in the **Curate / Search** tab.
- Acquisition from Instagram, X/Twitter, TikTok, and local folders.
- Segment-level image/video/voice training intents.
- Intent-aware duration guidance.
- RunComfy AI Toolkit image dataset export as the first concrete handoff.
- No in-app training.
