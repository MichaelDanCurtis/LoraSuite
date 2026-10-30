"""Read-only vault selection -> frozen, review-first H3 pilot proposal. No upload/training."""
import argparse
import base64
import hashlib
import html
import io
import json
from pathlib import Path
from PIL import Image, ImageOps


def group_for(item, media):
    """Use post/video provenance, not ingestion-batch source_id."""
    current, seen = item, set()
    while current["id"] not in seen:
        seen.add(current["id"])
        meta = current.get("metadata_json") or {}
        key = meta.get("canonical_source_id") or meta.get("source_bundle_key")
        if key:
            return str(key)
        parent = meta.get("source_media_item_id")
        if not parent or parent not in media:
            return current["id"]
        current = media[parent]
    raise ValueError("Cyclic media provenance")


def image_hash(path):
    with Image.open(path) as image:
        pixels = list(ImageOps.exif_transpose(image).convert("L").resize((9, 8)).getdata())
    return sum((pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
               for y in range(8) for x in range(8))


def prepare(vault, destination, snapshot_id, train_count=24, heldout_count=6, heldout_ids=None, exclude_ids=()):
    if destination.exists():
        raise ValueError("Use a new destination; existing pilot evidence is immutable")
    snapshots = json.loads((vault / "dataset_snapshots.json").read_text())["snapshots"]
    snapshot = next(s for s in snapshots if s["id"] == snapshot_id)
    media = {m["id"]: m for m in json.loads((vault / "vault.json").read_text())["media_items"]}
    items = sorted((i for i in snapshot["items"].values() if i["status"] == "approved"),
                   key=lambda i: (i.get("strongest_set_rank") or 100000, i["id"]))
    approved_ids = {i["training_media_item_id"] for i in items}
    if heldout_ids and (not set(heldout_ids) <= approved_ids or len(set(heldout_ids)) != len(heldout_ids)):
        raise ValueError("Explicit held-out IDs must be distinct approved images")
    excluded_groups = {group_for(media[mid], media) for mid in exclude_ids}
    if heldout_ids:
        heldout_count = len(heldout_ids)
    selected, groups, hashes, excluded = [], set(), [], []
    for item in items:
        m = media[item["training_media_item_id"]]
        path = Path(m["raw_path"])
        if not path.is_file() or not item.get("caption"):
            excluded.append({"id": m["id"], "reason": "missing file or caption"}); continue
        group = group_for(m, media)
        if group in excluded_groups:
            excluded.append({"id": m["id"], "reason": "post withheld during visual proposal review"}); continue
        if group in groups:
            excluded.append({"id": m["id"], "reason": "same post/video as a stronger candidate"}); continue
        try:
            dhash = image_hash(path)
        except (OSError, ValueError):
            excluded.append({"id": m["id"], "reason": "unreadable image"}); continue
        if any((dhash ^ previous).bit_count() <= 6 for previous in hashes):
            excluded.append({"id": m["id"], "reason": "conservative near-duplicate screen"}); continue
        groups.add(group); hashes.append(dhash)
        selected.append({"media_id": m["id"], "item_id": item["id"], "group": group,
                         "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "dhash": f"{dhash:016x}", "rank": item.get("strongest_set_rank"),
                         "caption": item["caption"], "review_status": "needs_human_review"})
    # Distribute held-out examples through rank order rather than relegating the
    # weakest images to evaluation. No frame from a selected group crosses splits.
    if heldout_ids:
        heldout = [r for r in selected if r["media_id"] in heldout_ids]
        if len(heldout) != len(heldout_ids):
            raise ValueError("A held-out candidate was excluded by provenance or duplicate checks; review the split")
        train = [r for r in selected if r["media_id"] not in heldout_ids][:train_count]
    else:
        target = min(len(selected), train_count + heldout_count)
        chosen = selected[:target]
        heldout_indices = {int((i + .5) * target / heldout_count) for i in range(heldout_count)} if target >= heldout_count * 2 else set()
        heldout = [r for i, r in enumerate(chosen) if i in heldout_indices]
        train = [r for i, r in enumerate(chosen) if i not in heldout_indices]
    chosen_ids = {r["media_id"] for r in train + heldout}
    reserve = [r for r in selected if r["media_id"] not in chosen_ids]
    warnings = ["Human review required: verify clear faces, captions, pose diversity and cross-post duplicates.",
                "Perceptual hashing and post grouping do not prove session-level independence.",
                "Photo-only pilot tests appearance, not learned motion or voice."]
    if len(train) < train_count or len(heldout) < heldout_count:
        warnings.append(f"Diversity shortfall: requested {train_count}+{heldout_count}, proposed {len(train)}+{len(heldout)}. Do not fill with neighboring frames.")
    manifest = {"version": 1, "status": "proposal_not_authorized_for_training", "project_id": snapshot["project_id"],
                "snapshot_id": snapshot_id, "trigger": snapshot["intent"]["trigger_token"],
                "train": train, "heldout": heldout, "reserve": reserve, "excluded": excluded,
                "explicit_heldout_ids": heldout_ids, "visual_review_excluded_ids": list(exclude_ids),
                "warnings": warnings, "paid_launch_authorized": False}
    destination.mkdir(parents=True)
    (destination / "proposal.json").write_text(json.dumps(manifest, indent=2) + "\n")
    render_review(manifest, destination)
    print(json.dumps({"train": len(train), "heldout": len(heldout), "reserve": len(reserve), "excluded": len(excluded), "review": str(destination / "review.html"), "warnings": warnings}))
    return manifest


def render_review(manifest, destination):
    """Render a frozen proposal, including optional reviewed coverage annotations."""
    cards = []
    for title, rows in (("Training candidates", manifest["train"]), ("Held-out evaluation candidates — never train on these", manifest["heldout"]), ("Parked — not selected for training", manifest.get("parked", []))):
        if not rows:
            continue
        cards.append(f"<h2>{html.escape(title)} ({len(rows)})</h2><div class='grid'>")
        for index, row in enumerate(rows, 1):
            # Embedded review thumbnails are local derivatives, never uploaded.
            with Image.open(row["path"]) as source:
                thumb = ImageOps.exif_transpose(source).convert("RGB"); thumb.thumbnail((320, 420))
                buffer = io.BytesIO(); thumb.save(buffer, format="JPEG", quality=80)
            uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
            coverage = row.get("coverage")
            annotation = (f"<p><strong>Primary use: {html.escape(coverage['primary_use'])}</strong></p><p>{html.escape(coverage['limitations'])}</p>" if coverage else "")
            label = row.get("source_filename") or f"rank {row['rank']}"
            cards.append(f"<article><h3>{index} · {html.escape(label)}</h3><img src='{uri}' alt='Candidate {index}'>{annotation}<p>{html.escape(row['caption'])}</p><small>{html.escape(row['media_id'])}</small></article>")
        cards.append("</div>")
    page = "<!doctype html><meta charset='utf-8'><title>Example Subject H3 pilot review</title><style>body{background:#141921;color:#eee;font:16px system-ui;padding:24px}h1,h2{max-width:100%}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}article{background:#242c37;padding:16px;border-radius:12px;overflow-wrap:anywhere}img{width:100%;height:420px;object-fit:contain}p{line-height:1.5}small{color:#aab}</style><h1>H3 pilot — selection proposal</h1><p>Not uploaded. Not approved for training. Review both splits and captions before launch.</p>" + "".join(f"<p>{html.escape(w)}</p>" for w in manifest["warnings"]) + "".join(cards)
    (destination / "review.html").write_text(page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--heldout-media", action="append")
    parser.add_argument("--exclude-media", action="append", default=[])
    args = parser.parse_args()
    prepare(args.vault, args.destination, args.snapshot, heldout_ids=args.heldout_media, exclude_ids=args.exclude_media)
