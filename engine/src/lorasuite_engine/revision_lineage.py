from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RevisionLineage(BaseModel):
    parent_snapshot_id: str | None = None
    parent_dataset_fingerprint: str | None = None
    improvement_request_id: str | None = None
    parent_artifact_id: str | None = None
    parent_checkpoint_sha256: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> "RevisionLineage":
        return cls(
            parent_snapshot_id=_string_value(
                getattr(snapshot, "parent_snapshot_id", None)
            ),
            parent_dataset_fingerprint=_string_value(
                getattr(snapshot, "parent_fingerprint", None)
            ),
            improvement_request_id=_string_value(
                getattr(snapshot, "improvement_request_id", None)
            ),
            parent_artifact_id=_string_value(
                getattr(snapshot, "source_artifact_id", None)
            ),
            parent_checkpoint_sha256=_string_value(
                getattr(snapshot, "source_checkpoint_sha256", None)
            ),
        )

    @classmethod
    def from_source_manifest(
        cls,
        manifest: dict[str, Any],
    ) -> "RevisionLineage":
        direct = manifest.get("revision_lineage")
        if isinstance(direct, dict):
            return cls.model_validate(direct)
        model_card = manifest.get("model_card")
        provenance = (
            model_card.get("provenance")
            if isinstance(model_card, dict)
            else None
        )
        if not isinstance(provenance, dict):
            return cls()
        return cls(
            parent_snapshot_id=_string_value(
                provenance.get("parent_dataset_snapshot_id")
            ),
            parent_dataset_fingerprint=_string_value(
                provenance.get("parent_dataset_fingerprint")
            ),
            improvement_request_id=_string_value(
                provenance.get("improvement_request_id")
            ),
            parent_artifact_id=_string_value(
                provenance.get("source_artifact_id")
            ),
            parent_checkpoint_sha256=_string_value(
                provenance.get("source_checkpoint_sha256")
            ),
        )

    def manifest_payload(self) -> dict[str, str]:
        return self.model_dump(mode="json", exclude_none=True)


def _string_value(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
