import importlib.util
import json
from pathlib import Path
from PIL import Image
import pytest

spec = importlib.util.spec_from_file_location("pilot", Path(__file__).with_name("prepare_h3_pilot.py"))
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def test_post_provenance_includes_all_derivatives():
    parent = {"id": "video", "metadata_json": {"canonical_source_id": "post:one"}}
    frame = {"id": "frame", "source_id": "ingestion-batch", "metadata_json": {"source_media_item_id": "video"}}
    assert pilot.group_for(frame, {"video": parent}) == "post:one"
    assert pilot.group_for({"id": "local", "metadata_json": {}}, {}) == "local"
    with pytest.raises(ValueError, match="Cyclic"):
        pilot.group_for({"id": "cycle", "metadata_json": {"source_media_item_id": "cycle"}}, {"cycle": {"id": "cycle"}})


def test_frozen_proposal_excludes_rejected_duplicates_and_keeps_splits_disjoint(tmp_path, monkeypatch):
    vault, out = tmp_path / "vault", tmp_path / "pilot"
    vault.mkdir(); media, items = [], {}
    for n in range(8):
        path = vault / f"{n}.png"; Image.new("RGB", (20, 20), (n * 20, 10, 20)).save(path)
        media.append({"id": str(n), "raw_path": str(path), "metadata_json": {"canonical_source_id": f"post:{max(0, n - 1)}"}})
        items[str(n)] = {"id": str(n), "status": "approved" if n < 7 else "excluded", "training_media_item_id": str(n), "caption": "test", "strongest_set_rank": n + 1}
    (vault / "vault.json").write_text(json.dumps({"media_items": media}))
    (vault / "dataset_snapshots.json").write_text(json.dumps({"snapshots": [{"id": "s", "project_id": "p", "intent": {"trigger_token": "person"}, "items": items}]}))
    before = (vault / "dataset_snapshots.json").read_bytes()
    monkeypatch.setattr(pilot, "image_hash", lambda path: 255 << (int(path.stem) * 8))
    result = pilot.prepare(vault, out, "s", train_count=4, heldout_count=2)
    assert len(result["train"]) == 4 and len(result["heldout"]) == 2
    assert not {r["group"] for r in result["train"]} & {r["group"] for r in result["heldout"]}
    assert "7" not in {r["media_id"] for r in result["train"] + result["heldout"]}
    assert (vault / "dataset_snapshots.json").read_bytes() == before
    assert not result["paid_launch_authorized"]
    assert (out / "review.html").exists()
    with pytest.raises(ValueError, match="existing pilot"):
        pilot.prepare(vault, out, "s")
    revised = pilot.prepare(vault, tmp_path / "revised", "s", train_count=3, heldout_ids=["3", "4"], exclude_ids=["0"])
    assert {r["media_id"] for r in revised["heldout"]} == {"3", "4"}
    assert not {"0", "1"} & {r["media_id"] for r in revised["train"] + revised["heldout"]}
    with pytest.raises(ValueError, match="approved"):
        pilot.prepare(vault, tmp_path / "bad", "s", heldout_ids=["7"])
