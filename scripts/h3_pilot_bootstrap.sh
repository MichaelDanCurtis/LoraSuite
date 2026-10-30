#!/bin/bash
set -euo pipefail
cd /workspace/pilot
export HF_HOME=/workspace/hf-cache
export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
# Reuse the existing CUDA torch supplied by the qualified RunPod template.
python -m pip install --disable-pip-version-check 'transformers==5.16.1' 'accelerate==1.14.0' 'peft==0.20.0' 'huggingface_hub==1.30.0' 'safetensors==0.8.0' 'einops==0.8.2' psutil 'imageio[ffmpeg]' modelscope ftfy pandas
git clone --no-checkout https://github.com/modelscope/DiffSynth-Studio.git /workspace/trainer
git -C /workspace/trainer checkout --detach 183007ec38a55151673b99232567928611e53a8c
python -m pip install --no-deps -e /workspace/trainer
hf download MiniMaxAI/MiniMax-H3 --revision 42ed227ee7df40d41602854ae760620d6eb651fe --include 'Ref2VA/transformer/*' --include 'Ref2VA/text_encoder/*' --include 'Ref2VA/audio_vae/*' --include 'Ref2VA/video_vae/source/*' --include 'Ref2VA/video_vae/config.json' --local-dir /workspace/weights
hf cache verify MiniMaxAI/MiniMax-H3 --revision 42ed227ee7df40d41602854ae760620d6eb651fe --local-dir /workspace/weights
python h3_cloud_pilot.py worker --runtime /workspace/trainer --run /workspace/pilot/package --weights /workspace/weights/Ref2VA --stage cache --deadline "$PILOT_TRAIN_EPOCH"
python h3_cloud_pilot.py worker --runtime /workspace/trainer --run /workspace/pilot/package --weights /workspace/weights/Ref2VA --stage train --deadline "$PILOT_TRAIN_EPOCH"
