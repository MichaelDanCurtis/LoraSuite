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
6. Open **Video Review** and select segment intent flags.
7. Extract frames through the engine tests or direct API.
8. Open **Exports**.
9. Paste frame paths and choose an output folder.
10. Create the RunComfy AI Toolkit image export.

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

The first scan does not copy raw media into the vault. It creates reviewable candidates and lightweight previews. Confirming selected candidates creates an ingress job that copies only selected ready candidates.

## Legacy Direct Import API

The engine still exposes `/vault/import/local` for direct tests and compatibility, but the product UI should use the ingress scan/job flow.

## Video and Export Workflow

1. Open **Video Review** and select segment intent flags.
2. Extract frames through the engine tests or direct API.
3. Open **Exports**.
4. Paste frame paths and choose an output folder.
5. Create the RunComfy AI Toolkit image export.

## Export Safety

RunComfy image export accepts explicit frame paths only. It writes `images/000001.<ext>`, matching `images/000001.txt`, `manifest.json`, and `export_report.md`.

The exporter refuses WebP, unreadable images, empty frame lists, duplicate frame paths, and unrelated non-empty output folders. It can safely replace a previous LoraSuite RunComfy export folder.
