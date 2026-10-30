# LoraSuite for ComfyUI

This maintained node pack consumes the versioned
`lorasuite.comfy-handoff.v1` manifest installed beside each registered LoRA.

It provides:

- artifact metadata and trigger-token discovery;
- model-and-CLIP and model-only LoRA loaders;
- a human evaluation report node that returns a decision to LoraSuite.

LoraSuite installs this directory into `ComfyUI/custom_nodes/LoraSuite`.
Restart ComfyUI after installation or upgrade.
