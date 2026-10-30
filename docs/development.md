# Development

Follow README.md for installation. The frontend uses React/TypeScript with Vite, the desktop shell uses Tauri/Rust, and `engine/src/lorasuite_engine` provides the local FastAPI service. `extensions/lorasuite-companion` is the optional Chrome extension; `workers/runpod` holds the cloud-worker contract.

## Configuration

`VITE_LORASUITE_ENGINE_URL` chooses a loopback engine URL for both development launchers and desktop builds. The default is `http://127.0.0.1:8765`. `.env.local` is machine-specific and ignored. `LORASUITE_VAULT_ROOT` selects the data vault; use a temporary directory for isolated testing. `LORASUITE_ENGINE_PYTHON` can override the Python executable.

The packaged app reuses an existing genuine LoraSuite engine or starts its own sidecar. It shuts down only its owned engine. It never starts or stops LoRA Manager or ComfyUI.

## Checks

```bash
npm ci
npm test
npm run test:companion
npm run engine:test
cargo test --manifest-path src-tauri/Cargo.toml
npm run build
```

Frontend tests block unmocked network access. Engine tests use temporary vaults and mock external provider calls. Passing these tests does not qualify paid training or model identity quality.

## Release artifacts

After committing a reviewed source tree, run `python3 scripts/package_public_release.py` to produce the source archive, companion ZIP and checksums in ignored `release-artifacts/`. The source archive uses the committed tree, not arbitrary files in the working directory. The companion ZIP contains runtime assets and license files only.

See desktop-release.md for native packaging. Internal experiment archives, local release evidence, personal datasets and abandoned source snapshots are not part of the public distribution.
