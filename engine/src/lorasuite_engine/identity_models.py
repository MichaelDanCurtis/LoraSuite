from __future__ import annotations

import hashlib
import shutil
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

import certifi

from lorasuite_engine.models import IdentityRuntimeStatus
from lorasuite_engine.storage import atomic_write_json, json_file_lock


MODEL_VERSION = "opencv-sface-2021dec-yunet-2023mar"
SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"
YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
SFACE_URL = (
    "https://huggingface.co/opencv/face_recognition_sface/resolve/main/"
    f"{SFACE_FILENAME}?download=true"
)
YUNET_URL = (
    "https://huggingface.co/opencv/face_detection_yunet/resolve/main/"
    f"{YUNET_FILENAME}?download=true"
)
SFACE_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
DOWNLOAD_SIZE_BYTES = 39_000_000


@dataclass(frozen=True)
class IdentityModelPaths:
    sface: Path
    yunet: Path


class IdentityModelService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    @property
    def model_dir(self) -> Path:
        return self.vault_root / "models" / "identity" / MODEL_VERSION

    @property
    def manifest_path(self) -> Path:
        return self.model_dir / "manifest.json"

    @property
    def paths(self) -> IdentityModelPaths:
        return IdentityModelPaths(
            sface=self.model_dir / SFACE_FILENAME,
            yunet=self.model_dir / YUNET_FILENAME,
        )

    def status(self) -> IdentityRuntimeStatus:
        paths = self.paths
        installed = (
            paths.sface.is_file()
            and paths.yunet.is_file()
            and _sha256(paths.sface) == SFACE_SHA256
            and _sha256(paths.yunet) == YUNET_SHA256
        )
        runtime_ready = False
        runtime_message = "Identity models are not installed"
        if installed:
            try:
                import cv2

                runtime_ready = all(
                    hasattr(cv2, attribute)
                    for attribute in ("FaceDetectorYN", "FaceRecognizerSF")
                )
            except ImportError:
                runtime_message = "OpenCV identity runtime is not installed"
            else:
                runtime_message = (
                    "SFace identity runtime is ready"
                    if runtime_ready
                    else "OpenCV was built without face recognition support"
                )
        return IdentityRuntimeStatus(
            installed=installed,
            ready=installed and runtime_ready,
            download_size_bytes=DOWNLOAD_SIZE_BYTES,
            message=runtime_message,
        )

    def install(self) -> IdentityRuntimeStatus:
        with json_file_lock(self.manifest_path):
            self.model_dir.mkdir(parents=True, exist_ok=True)
            self._install_file(SFACE_URL, self.paths.sface, SFACE_SHA256)
            self._install_file(YUNET_URL, self.paths.yunet, YUNET_SHA256)
            atomic_write_json(
                self.manifest_path,
                {
                    "version": MODEL_VERSION,
                    "backend": "opencv-sface",
                    "license": "Apache-2.0 AND MIT",
                    "models": [
                        {
                            "name": SFACE_FILENAME,
                            "source": SFACE_URL,
                            "sha256": SFACE_SHA256,
                            "license": "Apache-2.0",
                        },
                        {
                            "name": YUNET_FILENAME,
                            "source": YUNET_URL,
                            "sha256": YUNET_SHA256,
                            "license": "MIT",
                        },
                    ],
                },
            )
        return self.status()

    def install_from_paths(self, *, sface: Path, yunet: Path) -> IdentityRuntimeStatus:
        with json_file_lock(self.manifest_path):
            self.model_dir.mkdir(parents=True, exist_ok=True)
            self._copy_verified(sface, self.paths.sface, SFACE_SHA256)
            self._copy_verified(yunet, self.paths.yunet, YUNET_SHA256)
            atomic_write_json(
                self.manifest_path,
                {
                    "version": MODEL_VERSION,
                    "backend": "opencv-sface",
                    "license": "Apache-2.0 AND MIT",
                    "models": [
                        {"name": SFACE_FILENAME, "license": "Apache-2.0"},
                        {"name": YUNET_FILENAME, "license": "MIT"},
                    ],
                },
            )
        return self.status()

    def _install_file(self, url: str, target: Path, expected_sha256: str) -> None:
        if target.is_file() and _sha256(target) == expected_sha256:
            return
        temporary = target.with_suffix(f"{target.suffix}.download")
        temporary.unlink(missing_ok=True)
        request = Request(url, headers={"User-Agent": "LoraSuite/0.1"})
        context = ssl.create_default_context(cafile=certifi.where())
        try:
            with urlopen(request, timeout=60, context=context) as response:
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
            if _sha256(temporary) != expected_sha256:
                raise ValueError(f"identity model checksum failed: {target.name}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def _copy_verified(self, source: Path, target: Path, expected_sha256: str) -> None:
        if _sha256(source) != expected_sha256:
            raise ValueError(f"identity model checksum failed: {source.name}")
        temporary = target.with_suffix(f"{target.suffix}.copy")
        temporary.unlink(missing_ok=True)
        try:
            shutil.copy2(source, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
