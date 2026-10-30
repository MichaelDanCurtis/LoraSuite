from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from lorasuite_engine.comfyui_handoff import ComfyEvaluationReportService
from lorasuite_engine.improvement_loop import ImprovementLoopService
from lorasuite_engine.model_registry import ModelArtifactRecord, ModelRegistryService
from lorasuite_engine.models import utc_now
from lorasuite_engine.provider_readiness import (
    ProviderReadinessItem,
    ProviderReadinessService,
)


QualificationCheckStatus = Literal["passed", "pending", "failed"]
QualificationLaneStatus = Literal["qualified", "in_progress", "blocked"]
QualificationPartner = Literal["runcomfy", "runpod", "comfyui"]


class PartnerQualificationCheck(BaseModel):
    id: str
    label: str
    status: QualificationCheckStatus
    detail: str
    action: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class PartnerQualificationLane(BaseModel):
    partner: QualificationPartner
    lane: Literal["image", "video", "voice", "id_lora"]
    profile_id: str
    status: QualificationLaneStatus
    passed_count: int
    total_count: int
    checks: list[PartnerQualificationCheck]


class PartnerQualificationReport(BaseModel):
    format: Literal["lorasuite.partner-qualification.v1"] = (
        "lorasuite.partner-qualification.v1"
    )
    project_id: str
    status: QualificationLaneStatus
    passed_count: int
    total_count: int
    lanes: list[PartnerQualificationLane]
    next_actions: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class PartnerQualificationService:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)

    def report(self, project_id: str) -> PartnerQualificationReport:
        readiness = ProviderReadinessService(self.vault_root).status(project_id)
        artifacts = [
            artifact
            for artifact in ModelRegistryService(self.vault_root).list_artifacts()
            if artifact.project_id == project_id
        ]
        evaluations = ComfyEvaluationReportService(self.vault_root).list_reports(
            project_id=project_id
        )
        revisions = ImprovementLoopService(self.vault_root).list_revisions(
            project_id=project_id
        )

        lanes = [_provider_lane(item) for item in readiness.items]
        for lane in ("image", "video"):
            lane_artifacts = [artifact for artifact in artifacts if artifact.modality == lane]
            artifact = lane_artifacts[0] if lane_artifacts else None
            lanes.append(
                _comfyui_lane(
                    lane,
                    artifact,
                    evaluations=evaluations,
                    revision_source_ids={revision.source_artifact_id for revision in revisions},
                )
            )

        checks = [check for lane in lanes for check in lane.checks]
        next_actions = list(
            dict.fromkeys(
                check.action
                for check in checks
                if check.status != "passed" and check.action
            )
        )
        return PartnerQualificationReport(
            project_id=project_id,
            status=_combined_status(lanes),
            passed_count=sum(check.status == "passed" for check in checks),
            total_count=len(checks),
            lanes=lanes,
            next_actions=next_actions,
        )


def _provider_lane(item: ProviderReadinessItem) -> PartnerQualificationLane:
    checks = [
        _check(
            "dataset_export",
            "Immutable dataset export",
            bool(item.source_export_path),
            "A frozen provider package is available." if item.source_export_path else "No frozen provider package is available.",
            item.action_label,
            item.snapshot_id,
        ),
        _check(
            "provider_smoke",
            "Local provider contract smoke",
            item.smoke_ready,
            "The exact package passed its local provider contract." if item.smoke_ready else "The exact package has not passed its local provider contract.",
            "Run the provider contract smoke test.",
            item.smoke_run_id,
            failed=bool(item.smoke_run_id and not item.smoke_ready),
        ),
    ]
    if item.provider == "runpod":
        checks.extend(
            [
                _check(
                    "provider_bundle",
                    "RunPod bundle",
                    bool(item.bundle_id),
                    "A versioned RunPod bundle exists." if item.bundle_id else "No RunPod bundle exists for this package.",
                    "Create and verify the RunPod bundle.",
                    item.bundle_id,
                ),
                _check(
                    "endpoint_preflight",
                    "RunPod endpoint preflight",
                    bool(item.endpoint_id)
                    and item.state
                    in {"endpoint_ready", "running", "outputs_ready", "complete"},
                    "The selected endpoint passed preflight." if item.endpoint_id and item.state in {"endpoint_ready", "running", "outputs_ready", "complete"} else "No successful endpoint preflight is recorded.",
                    "Upload the bundle and run endpoint preflight.",
                    item.endpoint_id,
                    failed=bool(item.endpoint_id and item.state == "blocked"),
                ),
            ]
        )
    checks.extend(
        [
            _check(
                "provider_execution",
                "Real provider execution",
                bool(item.run_id) and item.state in {"outputs_ready", "complete"},
                "The provider completed the requested workload." if item.run_id and item.state in {"outputs_ready", "complete"} else "A successful real-provider workload is not recorded.",
                item.action_label,
                item.run_id,
                failed=bool(item.run_id and item.state == "blocked"),
            ),
            _check(
                "artifact_registration",
                "Verified artifact registration",
                item.state == "complete",
                "The returned artifact is registered with provider lineage." if item.state == "complete" else "No returned artifact has completed checksum verification and registration.",
                "Retrieve, verify, and register the returned artifact.",
                item.run_id if item.state == "complete" else None,
            ),
            _check(
                "release_decision",
                "Release candidate decision",
                item.release_selected,
                "A release-ready artifact is selected." if item.release_selected else "No release-ready artifact is selected for this lane.",
                "Evaluate the artifact and select a release candidate.",
                item.release_artifact_id,
            ),
        ]
    )
    return _lane(item.provider, item.lane, item.profile_id, checks)


def _comfyui_lane(
    lane: Literal["image", "video"],
    artifact: ModelArtifactRecord | None,
    *,
    evaluations: list,
    revision_source_ids: set[str],
) -> PartnerQualificationLane:
    artifact_id = artifact.id if artifact else None
    artifact_reports = [
        report for report in evaluations if artifact and report.artifact_id == artifact.id
    ]
    installations = artifact.comfy_installations if artifact else []
    runnable_count = sum(item.runnable_workflow_count for item in installations)
    integrity_ready = bool(
        artifact
        and artifact.evaluation.checkpoint_valid
        and artifact.evaluation.provenance_valid
    )
    checks = [
        _check(
            "registered_artifact",
            "Registered returned artifact",
            artifact is not None,
            "A returned artifact is registered." if artifact else "No returned artifact is registered for this modality.",
            "Complete provider training and register its artifact.",
            artifact_id,
        ),
        _check(
            "artifact_integrity",
            "Checkpoint and lineage integrity",
            integrity_ready,
            "Checkpoint and provenance checks passed." if integrity_ready else "Checkpoint and provenance checks have not passed.",
            "Verify the checkpoint and dataset lineage.",
            artifact_id if integrity_ready else None,
            failed=bool(artifact and artifact.evaluation.status == "failed"),
        ),
        _check(
            "comfyui_installation",
            "ComfyUI installation",
            bool(installations),
            "The artifact and handoff are installed in ComfyUI." if installations else "No ComfyUI installation is recorded.",
            "Install the artifact and LoraSuite handoff in ComfyUI.",
            artifact_id if installations else None,
        ),
        _check(
            "runnable_workflow",
            "Runnable evaluation workflow",
            runnable_count > 0,
            "At least one compatible workflow is runnable." if runnable_count > 0 else "No compatible evaluation workflow is confirmed runnable.",
            "Resolve base-model bindings and verify the generated workflow.",
            artifact_id if runnable_count > 0 else None,
        ),
        _check(
            "evaluation_report",
            "Returned ComfyUI evaluation",
            bool(artifact_reports),
            "ComfyUI returned evaluation evidence for the exact checkpoint." if artifact_reports else "No ComfyUI evaluation report is recorded for the exact checkpoint.",
            "Run the fixed evaluation workflow and return its report.",
            artifact_reports[0].id if artifact_reports else None,
            failed=bool(artifact_reports and all(report.verdict == "fail" for report in artifact_reports)),
        ),
        _check(
            "release_acceptance",
            "Release acceptance",
            bool(artifact and artifact.selected_for_release and artifact.acceptance.release_ready),
            "The evaluated artifact is selected for release." if artifact and artifact.selected_for_release and artifact.acceptance.release_ready else "The artifact has not passed and received a release decision.",
            "Review evaluation evidence and select a release candidate.",
            artifact_id if artifact and artifact.selected_for_release else None,
        ),
        _check(
            "measured_revision",
            "Measured revision lineage",
            bool(artifact_id and artifact_id in revision_source_ids),
            "A measured dataset revision preserves this artifact as its parent." if artifact_id and artifact_id in revision_source_ids else "No measured revision has been materialized from this artifact.",
            "Create revision two from measured evaluation evidence.",
            artifact_id if artifact_id in revision_source_ids else None,
        ),
    ]
    return _lane("comfyui", lane, f"comfyui_{lane}_evaluation", checks)


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: str,
    action: str,
    evidence_id: str | None,
    *,
    failed: bool = False,
) -> PartnerQualificationCheck:
    return PartnerQualificationCheck(
        id=check_id,
        label=label,
        status="passed" if passed else "failed" if failed else "pending",
        detail=detail,
        action=None if passed else action,
        evidence_ids=[evidence_id] if evidence_id else [],
    )


def _lane(partner, lane, profile_id, checks) -> PartnerQualificationLane:
    status: QualificationLaneStatus
    if any(check.status == "failed" for check in checks):
        status = "blocked"
    elif all(check.status == "passed" for check in checks):
        status = "qualified"
    else:
        status = "in_progress"
    return PartnerQualificationLane(
        partner=partner,
        lane=lane,
        profile_id=profile_id,
        status=status,
        passed_count=sum(check.status == "passed" for check in checks),
        total_count=len(checks),
        checks=checks,
    )


def _combined_status(lanes: list[PartnerQualificationLane]) -> QualificationLaneStatus:
    if any(lane.status == "blocked" for lane in lanes):
        return "blocked"
    if lanes and all(lane.status == "qualified" for lane in lanes):
        return "qualified"
    return "in_progress"
