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
2. Paste absolute paths to local images or videos.
3. Import them into the vault.
4. Open **Video Review** and select segment intent flags.
5. Extract frames through the engine tests or direct API.
6. Open **Exports**.
7. Paste frame paths and choose an output folder.
8. Create the RunComfy AI Toolkit image export.

## Export Safety

RunComfy image export accepts explicit frame paths only. It writes `images/000001.<ext>`, matching `images/000001.txt`, `manifest.json`, and `export_report.md`.

The exporter refuses WebP, unreadable images, empty frame lists, duplicate frame paths, and unrelated non-empty output folders. It can safely replace a previous LoraSuite RunComfy export folder.
