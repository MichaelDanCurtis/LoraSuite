# LoraSuite Ingress Review and Jobs Design

## Purpose

This spec defines the next LoraSuite slice after the initial local import/export loop:

1. Replace path-paste local import with a native file/folder picker and review surface.
2. Add a reusable candidate review model with tile, list, and gallery views.
3. Run confirmed ingestion as asynchronous jobs.
4. Establish the connector model for Instagram and X/Twitter using a browser-extension Session Helper.
5. Treat social video poster images as first-class assets for both thumbnails and optional image-training candidates.

The goal is to avoid downloading or copying media the user will not use while giving enough preview context to make selection fast.

## Product Decisions

### Local Ingress Uses Scan Then Confirm

The local flow is not "click Import and immediately copy everything." It is:

1. User clicks **Add Local Media**.
2. Tauri opens a native picker for files or folders.
3. The engine scans selected files/folders into lightweight ingress candidates.
4. The UI shows every supported candidate in tile, list, and gallery views.
5. User selects the candidates they want.
6. User clicks **Confirm Ingest**.
7. The engine creates an asynchronous ingress job.
8. Completed imported media appears in **Curate / Search**.

The first action is a scan/review action. The second action is the actual vault import.

### Ingress Jobs Are Reusable

Local, Instagram, X/Twitter, and later TikTok should all submit work through the same job table concept.

Jobs have visible states:

- `queued`
- `running`
- `complete`
- `failed`
- `canceled`

Jobs track:

- source kind;
- candidate count;
- selected count;
- imported count;
- skipped count;
- failed count;
- progress message;
- started and completed timestamps;
- recoverable errors.

The frontend can poll jobs in V1. A later version can move to server-sent events or a Tauri event stream.

### Browser-Session Social Connector

Instagram and X/Twitter should use a browser-extension/local-helper connector rather than direct cookie-file scraping as the primary product path.

The Session Helper runs inside the user's authenticated browser context and talks to LoraSuite over a localhost channel.

The helper is allowed to use the current browser session to discover media. It must not hand raw cookies or bearer tokens to the normal LoraSuite UI, export manifests, or project files.

The helper returns:

- stable source media identifiers;
- source URLs;
- author/account metadata when available;
- media type;
- dimensions and duration when available;
- preview thumbnail URLs or preview bytes;
- video poster image URLs or preview bytes;
- candidate download descriptors for originals or chosen variants.

LoraSuite persists provenance and selected asset data, not raw browser secrets.

### Preview First, Original Later

All connectors should minimize bandwidth by default:

1. Fetch metadata and small previews first.
2. Populate the review grid from thumbnails/posters.
3. Download full original media only for confirmed candidates.
4. Prefer lower-resolution preview variants for review where platform data exposes them.
5. Keep a clear byte estimate when the connector can provide one.

This applies to local sources too, but the bandwidth concern is different: local scans generate or cache lightweight thumbnails without copying full media into the vault until confirmation.

## Local Ingress UI

### Header Actions

The **Data Ingress** tab should lead with source-specific actions:

- **Add Local Media**
- **Add Instagram Source** (disabled stub until the Session Helper exists)
- **Add X Source** (disabled stub until the Session Helper exists)

The local action opens a Tauri file/folder picker. The UI should not require pasted paths for normal use.

### Candidate Review Toolbar

After scan, the review toolbar includes:

- view mode segmented control: `Tile`, `List`, `Gallery`;
- media filter: `All`, `Images`, `Videos`;
- selection controls: `Select All`, `Deselect All`, `Invert`;
- candidate counts: total, selected, unsupported/skipped;
- **Confirm Ingest** button.

### Tile View

Tile view is the default.

Each tile shows:

- thumbnail or file-type fallback artwork;
- checkbox;
- media type;
- filename;
- dimensions or duration if known;
- status badge for ready, duplicate, unsupported, or scan error.

Tile view is optimized for quick selection across many images.

### List View

List view is for dense inspection and troubleshooting.

Columns:

- selected;
- filename;
- source path;
- media type;
- size;
- dimensions or duration;
- scan status;
- notes/error.

The first implementation can provide a static table without column sorting, but the structure should leave room for sorting.

### Gallery View

Gallery view is for visual review.

It shows one large candidate at a time with:

- previous/next controls;
- selected checkbox;
- filename and path;
- metadata;
- thumbnail/poster image;
- status details.

The first implementation can use image thumbnails and fallback artwork for videos. Video playback can come after the review/job loop is stable.

## Candidate Model

An ingress candidate is a previewable item that may or may not be imported.

Fields:

- `id`
- `source_kind`: `local`, `instagram`, `x_twitter`, or `tiktok`
- `source_locator`: local path or source URL/id
- `display_name`
- `media_type`: `image`, `video`, or `audio`
- `size_bytes`
- `width`
- `height`
- `duration`
- `thumbnail_path`
- `poster_asset_path`
- `status`: `ready`, `duplicate`, `unsupported`, or `error`
- `error_message`
- `selected`
- `metadata_json`

For local images, `thumbnail_path` can be generated from the local original during scan. For local videos, the first version can use fallback artwork or extract a cheap poster frame if FFmpeg is available.

For Instagram and X/Twitter videos, `poster_asset_path` is important. Platform-provided poster images are often clear enough to be useful for:

- UI thumbnail display;
- optional image LoRA training candidate;
- provenance-linked still image export.

## Asset Model Extension

The existing `DerivedAsset` concept should be extended or mirrored to represent source-provided preview assets.

Recommended asset types:

- `thumbnail`
- `poster`
- `frame`
- `clip`
- `audio`
- `caption`
- `transcript`
- `mask`

A `poster` is a source-provided still image for a video. It differs from an extracted `frame` because it comes from the platform's media metadata, not FFmpeg analysis.

Posters can be imported as image-training candidates only when the user selects them or when a connector option explicitly enables "include video posters as image candidates."

## Engine API Shape

### Candidate Scanning

`POST /ingress/local/scan`

Request:

- `roots`: list of local file or folder paths.
- `recursive`: boolean, default true.

Response:

- `scan_id`
- `candidates`
- `errors`

The scan should not copy media into the vault.

### Job Creation

`POST /ingress/jobs`

Request:

- `source_kind`
- `candidate_ids`
- `options`

Response:

- `job`

The engine starts processing in the background and returns immediately.

### Job Listing

`GET /ingress/jobs`

Response:

- list of recent jobs.

### Job Detail

`GET /ingress/jobs/{job_id}`

Response:

- job summary;
- errors;
- imported media item IDs when complete.

For V1, candidates can live in a small JSON store under the vault root. A later version can move this into SQLite when the vault/index model expands.

## Browser Extension Session Helper

### Responsibilities

The helper should:

- run in the authenticated browser context;
- discover Instagram and X/Twitter media candidates;
- return thumbnails, poster images, and metadata;
- offer descriptors for downloading selected originals;
- redact auth material from every payload sent to LoraSuite unless the user explicitly enters a credential into a secure connector flow.

### LoraSuite Responsibilities

LoraSuite should:

- show helper connection status;
- request media inventory for specific accounts, posts, or current page context;
- cache thumbnails/posters in the vault preview area;
- store provenance fields;
- submit confirmed candidates to the common ingress job queue.

### Security Rules

- Raw browser cookies, bearer tokens, CSRF tokens, and session headers are never written to export manifests.
- Raw auth material is not logged.
- Helper payloads should be shaped as candidate descriptors, not arbitrary browser request dumps.
- If a token-like value must be held temporarily, it stays in memory or OS keychain/app-private storage, not the repo or vault manifests.
- Provenance records may include account handle, source URL, platform media ID, helper version, and retrieval timestamp.

## Instagram Behavior

Instagram video candidates should include the platform poster/thumbnail image when available.

The poster should be stored as:

- the UI thumbnail for the video candidate;
- a source-provided `poster` asset;
- an optional image-training candidate if the user selects it.

The original video is downloaded only after user confirmation.

## X/Twitter Behavior

X/Twitter video and animated media candidates should include preview images when available.

The preview image should be stored as:

- the UI thumbnail for the video candidate;
- a source-provided `poster` asset;
- an optional image-training candidate if the user selects it.

When media variants are available, the connector should show or use a bandwidth-aware default: thumbnail/poster for review, original or highest useful variant only after confirmation.

## Error Handling

Local scan errors should be candidate-level when possible:

- unsupported suffix;
- unreadable image;
- missing path;
- permission denied;
- FFmpeg poster extraction unavailable.

Social connector errors should preserve:

- platform;
- attempted source URL or account;
- helper version;
- failure category;
- user-facing remediation;
- whether retry is useful.

Expired browser sessions should surface as a connector health problem, not as a generic import failure.

## Testing Strategy

### Engine Tests

- local folder scan returns candidates without copying raw files;
- unsupported local files appear as skipped/error candidates;
- confirming selected candidates creates an ingress job;
- job processing imports only selected candidates;
- job results preserve errors and imported item references;
- poster assets can be represented independently from raw videos.

### UI Tests

- **Add Local Media** path scan populates candidates;
- tile/list/gallery mode switching keeps selection state;
- select all/deselect all/invert works;
- confirm ingest creates a job and shows it in the job table;
- completed jobs make imported items available to downstream tabs.

### Connector Tests

The browser extension helper can start with contract tests using fixture payloads:

- Instagram video fixture includes a poster asset;
- X/Twitter video fixture includes a preview/poster asset;
- helper payloads reject or redact raw cookie/token-like fields before persistence.

## Implementation Order

1. Add engine candidate and ingress job models.
2. Add local scan API with recursive folder support.
3. Add in-memory or JSON-backed job queue that processes local confirmed candidates.
4. Replace the current path-paste Data Ingress UI with native picker plus candidate review.
5. Add tile/list/gallery views and selection controls.
6. Add the job table.
7. Route completed imports into **Curate / Search**.
8. Define the browser-extension Session Helper contract.
9. Build Instagram inventory against the helper contract.
10. Add X/Twitter inventory against the same helper contract.

## Approval Checkpoint

This spec locks the following decisions:

- Local ingress becomes scan/review/confirm, not immediate import.
- Tile, list, and gallery views are all first-class candidate review modes.
- Ingestion runs as asynchronous jobs visible in the UI.
- Instagram and X/Twitter use a browser-extension Session Helper as the preferred authenticated connector path.
- Social connectors fetch thumbnails/posters first and download originals only after confirmation.
- Instagram and X/Twitter video poster/preview images are stored as first-class poster assets and can be selected for image training.
