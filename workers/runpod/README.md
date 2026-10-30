# LoraSuite RunPod Worker

This image executes the versioned `lorasuite-runpod-v1` Serverless contract. It validates every supplied path under `/runpod-volume`, invokes the bundle's generated `train_serverless.sh` for long-running work, and returns SHA-256 artifact descriptors.

The worker uses RunPod's published `1.0.2-cu1281-torch280-ubuntu2404` PyTorch base, pinned to its `linux/amd64` image digest so OCI attestations and mutable tags cannot change the runtime. Build and CI always target `linux/amd64`, which is the architecture used by RunPod GPU workers.

Build and publish the image, then enter its immutable registry tag in LoraSuite's **RunPod Infrastructure** control. LoraSuite can create or adopt the network volume, private Serverless template, and GPU endpoint:

```bash
docker build -t YOUR_REGISTRY/lorasuite-runpod-worker:1 workers/runpod
docker push YOUR_REGISTRY/lorasuite-runpod-worker:1
```

The repository workflow `.github/workflows/runpod-worker.yml` publishes `linux/amd64` images to GHCR whenever the worker changes. It emits a content-addressed `worker-<digest>` tag for infrastructure profiles and a convenience `main` tag. For a manual publication from macOS, authenticate Docker to the registry and run:

```bash
scripts/publish_runpod_worker.sh ghcr.io/YOUR_ACCOUNT/lorasuite-runpod-worker
```

The script prints the exact content-addressed image tag to enter in LoraSuite.

The image must be visible to RunPod. Private registries require registry authentication configured in RunPod before provisioning. The RunPod API key and optional `HF_TOKEN` are passed only during provisioning and are not persisted by LoraSuite. Uploading datasets and model files uses a separate RunPod S3 API key.

The endpoint image must have access to the GPU and to model weights referenced by the selected profile. The Train workspace's **Install Models** action can populate the shared network volume asynchronously and resume interrupted Hugging Face downloads. Fish Speech S2-Pro is installed under `/runpod-volume/models/fish-speech-s2`. ID-LoRA installs the pinned LTX-2.3 checkpoint, upscaler, distilled LoRA, Gemma text model, and CelebVHQ adapter under `/runpod-volume/models/id-lora-ltx23`. The user must accept any gated model licenses before installation, and the endpoint template must contain a valid `HF_TOKEN` when a gated repository requires one. Manual installation remains valid because endpoint preflight verifies the actual paths. API, Hugging Face, and S3 credentials are supplied to LoraSuite at runtime and are not part of this image or the bootstrap manifest.

The worker accepts four contract actions:

- `preflight` inspects the worker contract, mounted bundle, required commands, named environment variables, model files, and available NVIDIA GPU memory without returning credential values or starting training;
- `bootstrap_models` accepts only the Fish Speech S2-Pro and ID-LoRA LTX-2.3 profile IDs, downloads their version-pinned assets into the shared network volume, emits RunPod progress updates, and writes a credential-free completion manifest;
- `train_lora` requires at least one checkpoint artifact and returns its associated preview samples;
- `run_id_lora` requires `inference_contract.json` and at least one generated MP4 sample, and does not register those samples as model checkpoints.

The LoraSuite UI uses RunPod's synchronous `/runsync` operation for `preflight` and persists the resulting report locally. Model installation and training use asynchronous `/run` jobs. Bootstrap state is persisted in `runpod_model_bootstrap_runs.json`, while credentials remain session-only. Training remains blocked until a ready preflight report matches the exact endpoint, profile, and bundle fingerprint.
