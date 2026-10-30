"""Add explicit local candidates to a NEW review proposal; no vault mutation or training."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from prepare_h3_pilot import image_hash, render_review


def extend(source, destination, additions):
    if destination.exists():
        raise ValueError("Use a new destination; existing proposals are preserved")
    payload = source.read_bytes()
    manifest = json.loads(payload)
    heldout = manifest["heldout"]
    heldout_groups = {row["group"] for row in heldout}
    existing = manifest["train"] + heldout + manifest.get("parked", []) + manifest.get("reserve", [])
    seen = {row["sha256"] for row in existing}
    appended = []
    for addition in additions:
        path = Path(addition["path"]).resolve(strict=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        dhash = image_hash(path)
        if digest in seen:
            raise ValueError(f"Duplicate file: {path.name}")
        if addition["group"] in heldout_groups or any((dhash ^ int(row["dhash"], 16)).bit_count() <= 6 for row in heldout):
            raise ValueError(f"Held-out overlap needs review: {path.name}")
        if not addition["caption"].strip():
            raise ValueError("Caption is required")
        seen.add(digest)
        appended.append({"media_id": "local_candidate_" + digest[:24], "item_id": None,
            "source_filename": path.name, "path": str(path), "sha256": digest,
            "dhash": f"{dhash:016x}", "group": addition["group"],
            "group_basis": "conservative visual session grouping; provenance not independently verified",
            "rank": None, "caption": manifest["trigger"] + ", " + addition["caption"],
            "coverage": addition["coverage"], "review_status": "needs_caption_and_final_split_review",
            "selection_basis": "user requested inclusion as a pilot candidate",
            "vault_imported": False})
    manifest["train"].extend(appended)
    manifest["parent_proposal_sha256"] = hashlib.sha256(payload).hexdigest()
    manifest["status"] = "proposal_not_authorized_for_training"
    manifest["paid_launch_authorized"] = False
    manifest["previous_revision_warnings"] = manifest["warnings"]
    manifest["warnings"] = [
        f"Face + body pilot: {len(manifest['train'])} training candidates, {len(heldout)} unchanged held-out candidates. Six user-supplied local photos were added; original files and prior proposals are untouched." if len(appended) == 6 else f"Added {len(appended)} local candidates; original files and held-out split unchanged.",
        "New local candidates are not yet imported into the app vault. Their content hashes, proposed captions and session groups are recorded here; no upload or training has started.",
        "The waterfall photos (0609, 0613, 0614) stay together in training. The red-swimsuit and waterfall photos are conservatively grouped as one possible trip/session; none is used for held-out evaluation.",
        "These photos add useful body and pose coverage. Missing neutral head-to-toe views do not disqualify them or block an exploratory pilot; claims about unseen angles remain unverified.",
        "Held-out body evaluation remains limited. Rate only visible proportions; do not count an unobservable view as a pass. Additional independent standing side/rear views would strengthen evaluation.",
        "Review draft captions, screenshot UI in IMG_0611 and cross-post/session overlap before finalizing. Do not center-crop away head or legs; preserve aspect ratio. Session grouping and perceptual checks do not prove independence.",
        "Photo-only training tests appearance, not learned motion or voice. One previously parked likely repost remains parked."
    ]
    manifest["coverage_counts"] = {split: dict(Counter(row["coverage"]["primary_use"] for row in manifest[split])) for split in ("train", "heldout")}
    destination.mkdir(parents=True)
    (destination / "proposal.json").write_text(json.dumps(manifest, indent=2) + "\n")
    render_review(manifest, destination)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--additions", type=Path, required=True)
    args = parser.parse_args()
    result = extend(args.source, args.destination, json.loads(args.additions.read_text()))
    print(json.dumps({"train": len(result["train"]), "heldout": len(result["heldout"]), "coverage": result["coverage_counts"], "review": str(args.destination / "review.html")}))
