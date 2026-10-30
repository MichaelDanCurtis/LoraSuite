from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lorasuite_engine.identity_models import IdentityModelPaths
from lorasuite_engine.models import (
    CropKind,
    CropRecipe,
    IdentityFace,
    NormalizedPoint,
    NormalizedRect,
)


@dataclass
class FaceEmbedding:
    face: IdentityFace
    embedding: np.ndarray


class SFaceIdentityEngine:
    backend = "opencv-sface-2021dec"
    same_identity_threshold = 0.363

    def __init__(self, model_paths: IdentityModelPaths):
        import cv2

        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(
            str(model_paths.yunet),
            "",
            (320, 320),
            0.75,
            0.3,
            5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(model_paths.sface), "")

    def analyze(self, path: Path) -> list[FaceEmbedding]:
        image = self.cv2.imread(str(path))
        if image is None:
            raise ValueError(f"could not read image for identity analysis: {path}")
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _result, detected = self.detector.detect(image)
        if detected is None:
            return []
        detected = sorted(
            detected,
            key=lambda row: float(row[2] * row[3]),
            reverse=True,
        )
        faces: list[FaceEmbedding] = []
        for index, row in enumerate(detected):
            aligned = self.recognizer.alignCrop(image, row)
            feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
            norm = float(np.linalg.norm(feature))
            if norm <= 0:
                continue
            feature /= norm
            x, y, box_width, box_height = (float(value) for value in row[:4])
            landmarks = [
                NormalizedPoint(
                    x=_clamp(float(row[offset]) / width),
                    y=_clamp(float(row[offset + 1]) / height),
                )
                for offset in range(4, 14, 2)
            ]
            faces.append(
                FaceEmbedding(
                    face=IdentityFace(
                        index=index,
                        confidence=float(row[14]),
                        bounding_box=NormalizedRect(
                            x=_clamp(x / width),
                            y=_clamp(y / height),
                            width=max(0.0001, min(1.0 - _clamp(x / width), box_width / width)),
                            height=max(0.0001, min(1.0 - _clamp(y / height), box_height / height)),
                        ),
                        landmarks=landmarks,
                    ),
                    embedding=feature,
                )
            )
        return faces


def anchor_similarity(embedding: np.ndarray, anchors: list[np.ndarray]) -> float | None:
    if not anchors:
        return None
    scores = sorted((float(np.dot(embedding, anchor)) for anchor in anchors))
    if len(scores) >= 3:
        middle = len(scores) // 2
        return scores[middle] if len(scores) % 2 else (scores[middle - 1] + scores[middle]) / 2
    return sum(scores) / len(scores)


def crop_proposals(
    *,
    media_item_id: str,
    selected_face: IdentityFace | None,
    image_width: int | None = None,
    image_height: int | None = None,
) -> list[CropRecipe]:
    if selected_face is None:
        return [
            CropRecipe(
                media_item_id=media_item_id,
                kind=CropKind.FULL_BODY,
                rect=NormalizedRect(x=0.0, y=0.0, width=1.0, height=1.0),
                aspect_ratio="original",
            )
        ]

    box = selected_face.bounding_box
    pixel_aspect_scale = (
        image_height / image_width
        if image_width is not None
        and image_width > 0
        and image_height is not None
        and image_height > 0
        else 1.0
    )
    center_x = box.x + box.width / 2
    center_y = box.y + box.height / 2
    face_rect = _aspect_crop(
        center_x=center_x,
        center_y=center_y + box.height * 0.04,
        minimum_width=box.width * 1.7,
        minimum_height=box.height * 1.85,
        aspect_ratio=1.0 * pixel_aspect_scale,
    )
    upper_rect = _aspect_crop(
        center_x=center_x,
        center_y=center_y + box.height * 1.05,
        minimum_width=box.width * 3.1,
        minimum_height=box.height * 4.4,
        aspect_ratio=(4 / 5) * pixel_aspect_scale,
    )
    full_rect = _aspect_crop(
        center_x=center_x,
        center_y=max(0.5, center_y + box.height * 2.3),
        minimum_width=box.width * 4.4,
        minimum_height=max(box.height * 7.2, 0.78),
        aspect_ratio=(2 / 3) * pixel_aspect_scale,
    )
    return [
        CropRecipe(
            media_item_id=media_item_id,
            kind=CropKind.FACE,
            rect=face_rect,
            aspect_ratio="1:1",
            face_index=selected_face.index,
        ),
        CropRecipe(
            media_item_id=media_item_id,
            kind=CropKind.UPPER_BODY,
            rect=upper_rect,
            aspect_ratio="4:5",
            face_index=selected_face.index,
        ),
        CropRecipe(
            media_item_id=media_item_id,
            kind=CropKind.FULL_BODY,
            rect=full_rect,
            aspect_ratio="2:3",
            face_index=selected_face.index,
        ),
    ]


def _aspect_crop(
    *,
    center_x: float,
    center_y: float,
    minimum_width: float,
    minimum_height: float,
    aspect_ratio: float,
) -> NormalizedRect:
    width = max(minimum_width, minimum_height * aspect_ratio)
    height = width / aspect_ratio
    if height < minimum_height:
        height = minimum_height
        width = height * aspect_ratio
    scale = min(1.0 / max(width, 0.0001), 1.0 / max(height, 0.0001), 1.0)
    width *= scale
    height *= scale
    x = min(max(center_x - width / 2, 0.0), 1.0 - width)
    y = min(max(center_y - height / 2, 0.0), 1.0 - height)
    return NormalizedRect(x=x, y=y, width=width, height=height)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
