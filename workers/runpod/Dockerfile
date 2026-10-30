# check=skip=InvalidBaseImagePlatform
# RunPod 1.0.2 / CUDA 12.8.1 / Torch 2.8 / Ubuntu 24.04, pinned to linux/amd64.
FROM runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ffmpeg git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir runpod==1.8.1 uv "huggingface_hub[hf_xet]==1.23.0"

WORKDIR /worker
COPY handler.py /worker/handler.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "/worker/handler.py"]
