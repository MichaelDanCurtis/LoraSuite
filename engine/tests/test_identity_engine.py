import hashlib
import json

import numpy as np
import pytest

import lorasuite_engine.identity_models as identity_models_module
from lorasuite_engine.identity_engine import anchor_similarity, crop_proposals
from lorasuite_engine.identity_models import IdentityModelService
from lorasuite_engine.models import CropKind, IdentityFace, NormalizedRect


def test_anchor_similarity_uses_median_consensus_for_three_or_more_anchors():
    candidate = np.array([1.0, 0.0], dtype=np.float32)
    anchors = [
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.8, 0.6], dtype=np.float32),
        np.array([-1.0, 0.0], dtype=np.float32),
    ]

    assert anchor_similarity(candidate, anchors) == pytest.approx(0.8)


def test_face_crop_proposals_are_bounded_and_have_training_aspects():
    face = IdentityFace(
        index=2,
        confidence=0.99,
        bounding_box=NormalizedRect(x=0.74, y=0.04, width=0.24, height=0.28),
        selected=True,
    )

    recipes = crop_proposals(
        media_item_id="media_1",
        selected_face=face,
        image_width=720,
        image_height=1278,
    )

    assert [recipe.kind for recipe in recipes] == [
        CropKind.FACE,
        CropKind.UPPER_BODY,
        CropKind.FULL_BODY,
    ]
    assert [recipe.aspect_ratio for recipe in recipes] == ["1:1", "4:5", "2:3"]
    assert all(recipe.face_index == 2 for recipe in recipes)
    assert all(recipe.rect.x + recipe.rect.width <= 1 for recipe in recipes)
    assert all(recipe.rect.y + recipe.rect.height <= 1 for recipe in recipes)
    expected_pixel_aspects = [1.0, 4 / 5, 2 / 3]
    for recipe, expected_aspect in zip(recipes, expected_pixel_aspects, strict=True):
        pixel_aspect = (recipe.rect.width * 720) / (recipe.rect.height * 1278)
        assert pixel_aspect == pytest.approx(expected_aspect)


def test_identity_model_install_verifies_files_and_writes_license_manifest(
    monkeypatch, tmp_path
):
    sface_source = tmp_path / "sface.onnx"
    yunet_source = tmp_path / "yunet.onnx"
    sface_source.write_bytes(b"test-sface-model")
    yunet_source.write_bytes(b"test-yunet-model")
    monkeypatch.setattr(
        identity_models_module,
        "SFACE_SHA256",
        hashlib.sha256(sface_source.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        identity_models_module,
        "YUNET_SHA256",
        hashlib.sha256(yunet_source.read_bytes()).hexdigest(),
    )
    service = IdentityModelService(tmp_path / "vault")

    status = service.install_from_paths(sface=sface_source, yunet=yunet_source)

    assert status.installed is True
    assert status.ready is True
    assert service.paths.sface.read_bytes() == sface_source.read_bytes()
    assert service.paths.yunet.read_bytes() == yunet_source.read_bytes()
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "opencv-sface"
    assert manifest["license"] == "Apache-2.0 AND MIT"
    assert [model["license"] for model in manifest["models"]] == ["Apache-2.0", "MIT"]
