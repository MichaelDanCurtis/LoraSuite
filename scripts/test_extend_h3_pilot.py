import hashlib
import json

from PIL import Image
import pytest

import extend_h3_pilot as pilot


def test_local_candidates_preserve_heldout_and_source(tmp_path, monkeypatch):
    photo = tmp_path / "new.jpeg"
    Image.new("RGB", (40, 80), "red").save(photo)
    monkeypatch.setattr(pilot, "image_hash", lambda path: 2**64 - 1)
    row = {"media_id": "held", "group": "held-session", "rank": 1, "sha256": "old", "dhash": "0", "path": str(photo), "caption": "old caption", "coverage": {"primary_use": "face detail", "limitations": "none"}}
    original = {"train": [], "heldout": [row], "warnings": ["old warning"], "trigger": "subject", "paid_launch_authorized": True}
    source = tmp_path / "source.json"
    source.write_text(json.dumps(original))
    before = source.read_bytes()
    additions = [{"path": str(photo), "group": "new-session", "caption": "standing", "coverage": {"primary_use": "longer-body framing", "limitations": "posed"}}]
    out = tmp_path / "r5"
    result = pilot.extend(source, out, additions)
    assert result["heldout"] == original["heldout"]
    assert source.read_bytes() == before
    assert result["parent_proposal_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["train"][0]["item_id"] is None
    assert result["train"][0]["vault_imported"] is False
    assert result["train"][0]["caption"] == "subject, standing"
    assert not result["paid_launch_authorized"]
    assert "new.jpeg" in (out / "review.html").read_text()
    with pytest.raises(ValueError, match="new destination"):
        pilot.extend(source, out, additions)
    with pytest.raises(ValueError, match="Duplicate"):
        pilot.extend(source, tmp_path / "duplicate", additions * 2)
    with pytest.raises(ValueError, match="Held-out"):
        pilot.extend(source, tmp_path / "session", [{**additions[0], "group": "held-session"}])
    monkeypatch.setattr(pilot, "image_hash", lambda path: 1)
    with pytest.raises(ValueError, match="Held-out"):
        pilot.extend(source, tmp_path / "perceptual", additions)
