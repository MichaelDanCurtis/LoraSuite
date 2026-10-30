"""Link only hash-verified identical FL2VA components into the pinned Ref2VA tree.

Does not download weights, replace existing files, or modify FL2VA files.
"""
import argparse
import hashlib
import json
import os
import ssl
from pathlib import Path
from urllib.request import urlopen

import certifi

REVISION = "42ed227ee7df40d41602854ae760620d6eb651fe"
PREFIXES = ("text_encoder/", "tokenizer/", "audio_vae/", "video_vae/source/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    args = parser.parse_args()
    root = args.model_dir.resolve(strict=True)
    url = f"https://huggingface.co/api/models/MiniMaxAI/MiniMax-H3/revision/{REVISION}?blobs=true"
    with urlopen(url, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as response:
        files = {item["rfilename"]: item for item in json.load(response)["siblings"]}
    linked = 0
    for name, ref in files.items():
        if not name.startswith("Ref2VA/"):
            continue
        relative = name.removeprefix("Ref2VA/")
        if not (relative.startswith(PREFIXES) or relative == "video_vae/config.json"):
            continue
        source = root / "FL2VA" / relative
        target = root / name
        base = files[f"FL2VA/{relative}"]
        lfs = ref.get("lfs")
        expected = lfs["sha256"] if lfs else ref["blobId"]
        base_hash = base.get("lfs", {}).get("sha256", base.get("blobId"))
        if expected != base_hash or source.stat().st_size != ref["size"]:
            raise ValueError(f"Not an identical reusable component: {name}")
        digest = hashlib.sha256() if lfs else hashlib.sha1()
        if not lfs:
            digest.update(f"blob {ref['size']}\0".encode())
        with source.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"Local checksum mismatch: {source}")
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != source.resolve():
                raise ValueError(f"Refusing to replace existing component: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.path.relpath(source, target.parent))
        linked += 1
        print(f"Verified shared component: {name}", flush=True)
    print(f"Verified and linked {linked} components at revision {REVISION}", flush=True)


if __name__ == "__main__":
    main()
