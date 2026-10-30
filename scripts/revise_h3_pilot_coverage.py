"""Apply reviewed coverage notes to a new pilot proposal; never change its source."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from prepare_h3_pilot import render_review


def revise(source, destination, plan):
    if destination.exists():
        raise ValueError("Use a new destination; preserve previous evidence")
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != plan["source_sha256"]:
        raise ValueError("Coverage notes belong to a different frozen proposal")
    manifest = json.loads(payload)
    rows = manifest["train"] + manifest["heldout"]
    ranks = [str(row["rank"]) for row in rows]
    if len(set(ranks)) != len(ranks) or set(ranks) != set(plan["annotations"]):
        raise ValueError("Every candidate needs one unambiguous coverage annotation")
    manifest["parked"] = []
    for row in rows:
        row["coverage"] = plan["annotations"][str(row["rank"])]
        row["review_status"] = "needs_human_review"
    for row in manifest["train"]:
        if str(row["rank"]) in plan["park_ranks"]:
            manifest["parked"].append(row)
    if set(plan["park_ranks"]) != {str(row["rank"]) for row in manifest["parked"]}:
        raise ValueError("Only training candidates can be parked; held-out split is frozen")
    manifest["train"] = [row for row in manifest["train"] if row not in manifest["parked"]]
    manifest["parent_proposal_sha256"] = plan["source_sha256"]
    manifest["objective"] = "face_identity_and_visible_body_proportions"
    manifest["status"] = "proposal_not_authorized_for_training"
    manifest["paid_launch_authorized"] = False
    manifest["coverage_counts"] = {split: dict(Counter(row["coverage"]["primary_use"] for row in manifest[split])) for split in ("train", "heldout")}
    manifest["warnings"] = plan["warnings"] + [
        "Previous proposal: " + warning if warning.startswith("Diversity shortfall:") else warning
        for warning in manifest["warnings"]
    ]
    # Preserve source captions verbatim; review notes call out inaccurate framing.
    destination.mkdir(parents=True)
    (destination / "proposal.json").write_text(json.dumps(manifest, indent=2) + "\n")
    render_review(manifest, destination)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--coverage-plan", type=Path, required=True)
    args = parser.parse_args()
    result = revise(args.source, args.destination, json.loads(args.coverage_plan.read_text()))
    print(json.dumps({"coverage": result["coverage_counts"], "parked": len(result["parked"]), "review": str(args.destination / "review.html")}))
