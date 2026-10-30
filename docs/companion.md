# LoraSuite Companion

The companion connects supported Civitai/model pages to your local workflow. Install the extracted release folder using Chrome's **Load unpacked** control. Keep the folder in place; reload the extension after replacing it with a newer version.

## Direct LoRA Manager connection

Start LoRA Manager separately, normally through ComfyUI at `http://127.0.0.1:8188`. Configure that endpoint in the companion. **Add to LM** delegates the download to the manager; a queued response is not proof of a completed installation. Inspect the resulting manager entry and job status.

## Pairing with LoraSuite

Open **Model Library** in LoraSuite, generate a pairing code and enter it in the companion's LoraSuite connection controls. Pairing grants access to the limited reference/import bridge, not arbitrary local filesystem operations. Choose the project/output for captured references. Local trained-artifact import remains an explicit action in LoraSuite.

## Data

The extension stores connection preferences and pairing state through Chrome extension storage. It reads supported page metadata and previews when you invoke its controls. Review the requested host permissions before installation. It does not host LoRA Manager, install ComfyUI, transfer browser cookies into LoraSuite, or make arbitrary model activations automatic.

## Limitations

This is an unpacked extension preview, not a Chrome Web Store release. Upstream sites and LoRA Manager API versions can change. Test a small import first and verify metadata, images and the final downloaded artifact. Report reproducible issues without keys, pairing tokens or private media.
