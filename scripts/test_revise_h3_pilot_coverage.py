import hashlib
import json

from PIL import Image
import pytest

from revise_h3_pilot_coverage import revise


def test_coverage_revision_preserves_source_split_and_requires_review(tmp_path):
    image = tmp_path / "photo.png"
    Image.new("RGB", (30, 60)).save(image)
    rows = [{"rank": n, "media_id": str(n), "caption": "original caption", "path": str(image)} for n in range(1, 4)]
    source = tmp_path / "original.json"
    source.write_text(json.dumps({"train": rows[:2], "heldout": rows[2:], "warnings": [], "paid_launch_authorized": True}))
    before = source.read_bytes()
    plan = {"source_sha256": hashlib.sha256(before).hexdigest(), "park_ranks": ["2"], "warnings": ["Coverage incomplete"], "annotations": {str(n): {"primary_use": "face detail", "limitations": "Body not visible <test>"} for n in range(1, 4)}}
    out = tmp_path / "revision"
    result = revise(source, out, plan)
    assert source.read_bytes() == before
    assert [r["media_id"] for r in result["train"]] == ["1"]
    assert [r["media_id"] for r in result["heldout"]] == ["3"]
    assert [r["media_id"] for r in result["parked"]] == ["2"]
    assert not result["paid_launch_authorized"]
    assert result["heldout"][0]["caption"] == "original caption"
    assert all(r["review_status"] == "needs_human_review" for split in ("train", "heldout", "parked") for r in result[split])
    assert "Body not visible &lt;test&gt;" in (out / "review.html").read_text()
    with pytest.raises(ValueError, match="new destination"):
        revise(source, out, plan)
    with pytest.raises(ValueError, match="different frozen"):
        revise(source, tmp_path / "wrong", {**plan, "source_sha256": "wrong"})
    with pytest.raises(ValueError, match="Every candidate"):
        revise(source, tmp_path / "missing", {**plan, "annotations": {}})
    with pytest.raises(ValueError, match="held-out split"):
        revise(source, tmp_path / "heldout", {**plan, "park_ranks": ["3"]})
