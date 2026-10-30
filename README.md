# LoraSuite

Prepare a reviewed dataset, build a LoRA training package, and carry the result into your existing generation tools.

LoraSuite combines a React workspace, a local Python engine, a Tauri desktop shell, and an optional Chrome companion. Guided mode walks through Create → Sources → Prepare → Verify → Build & Train → Evaluate & Release. Advanced controls use the same projects and recipe catalog.

**Status: public preview.** The primary development platform is Apple Silicon macOS. Windows and Linux build workflows are included, but clean-machine desktop installation has not been qualified on those platforms. A model appearing in the catalog does not mean its training provider has passed an end-to-end qualification.

## What it does

- Import local images, video, and audio; review social-source imports before adding them.
- Browse saved project media, assess quality and variety, select identity references, and review crops and captions.
- Compile image, video, voice, and audiovisual packages using compatible model recipes.
- Hand off supported training jobs to RunComfy or RunPod, track work, and review resulting artifacts.
- Connect to an **external** LoRA Manager and preserve model metadata and preview images.
- Capture Civitai references and initiate LoRA Manager operations through the browser companion.

LoraSuite does **not** install, host, or start LoRA Manager or ComfyUI. Open those applications separately. The retired experimental H3 scene editor is not included. H3 reference generation and Living Identity zero-shot workflows are distinct from training a new per-person LoRA.

## Run from source

Prerequisites: Node.js 22.12+ (or a compatible newer LTS), Python 3.11+, and FFmpeg on `PATH`. Desktop development also needs Rust and the [Tauri platform prerequisites](https://v2.tauri.app/start/prerequisites/).

```bash
git clone https://github.com/MichaelDanCurtis/LoraSuite.git
cd LoraSuite
npm ci
python3 -m venv engine/.venv
engine/.venv/bin/python -m pip install --upgrade 'pip>=26.2' 'setuptools>=84.1.0'
engine/.venv/bin/python -m pip install -e 'engine[dev]'
```

On Windows, use `python` to create the environment and `engine/.venv/Scripts/python.exe` to install dependencies.

Start the engine and web workspace in separate terminals:

```bash
npm run dev:engine
npm run dev
```

Open the local URL printed by Vite. The engine defaults to `http://127.0.0.1:8765`. To configure another loopback port, copy `.env.example` to `.env.local` and set the engine URL there. Do not expose the engine to the network.

For the desktop development app:

```bash
npm run dev:all
```

## Start a project

1. Choose an output and model recipe. Experimental recipes are labeled.
2. Add source media you have permission to use. An existing project's saved media stays visible in Sources.
3. Prepare and review the collection, then verify the intended identity or speaker.
4. Build a draft, review captions and recipe checks, and export the package.
5. Configure an external provider if you want to train; provider usage may incur charges.
6. Evaluate the artifact before treating it as release-ready.

Open the **Advanced options** sections for detailed import, preparation, identity and dataset controls. **Ask AI** currently offers local, rule-based workflow guidance; it is not a general-purpose model chat.

## Browser companion

Download the companion ZIP from [Releases](https://github.com/MichaelDanCurtis/LoraSuite/releases), extract it, and load its folder through Chrome's **Extensions → Developer mode → Load unpacked**. It is not currently distributed through the Chrome Web Store.

Open your separate LoRA Manager, normally on port 8188, before using **Add to LM**. LoraSuite pairing enables the narrower project-reference bridge. See [companion setup and data handling](docs/companion.md).

## Validation and packaging

```bash
npm test
npm run test:companion
npm run engine:test
cargo test --manifest-path src-tauri/Cargo.toml
npm run build
npm run build:desktop
```

Build and installation details: [development](docs/development.md), [desktop release](docs/desktop-release.md), [preview limitations](docs/release-notes.md).

## Data and security

The default vault is `~/.lorasuite/vault`; use `LORASUITE_VAULT_ROOT` for a different location. Local media and review state are not part of this repository. Back up the vault before upgrading preview builds.

Desktop provider credentials use the OS credential store. Browser credentials remain in the current browser session. External services receive data when you invoke their features; model downloads, provider accounts, GPU capacity and third-party licenses are separate requirements. See [security and privacy](SECURITY.md).

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md). LoraSuite is licensed under [Apache License 2.0](LICENSE). Dependencies, external applications, models and datasets retain their own licenses; the LoraSuite license grants no rights to those assets. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
