import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  ArtifactComparison,
  DatasetRevisionRecord,
  ImprovementRequest,
  ModelArtifactRecord,
} from "../lib/types";
import { ArtifactImprovementPanel } from "./ArtifactImprovementPanel";

describe("ArtifactImprovementPanel", () => {
  it("compares revisions, approves a plan, and creates a separate editable draft", async () => {
    const user = userEvent.setup();
    const reference = artifact("reference", "reference.safetensors", "reference-sha");
    const candidate = artifact("candidate", "candidate.safetensors", "candidate-sha");
    const comparison = comparisonFixture(reference, candidate);
    const draft = requestFixture(comparison, "draft");
    const approved = { ...draft, status: "approved" as const, decision_note: "Build revision two." };
    const revision = revisionFixture(approved);
    const onOpenRevision = vi.fn();
    const engine = {
      listModelArtifacts: vi.fn().mockResolvedValue([candidate, reference]),
      listArtifactComparisons: vi.fn().mockResolvedValue([]),
      createArtifactComparison: vi.fn().mockResolvedValue(comparison),
      listImprovementRequests: vi.fn().mockResolvedValue([]),
      createImprovementRequest: vi.fn().mockResolvedValue(draft),
      decideImprovementRequest: vi.fn().mockResolvedValue(approved),
      listDatasetRevisions: vi.fn().mockResolvedValue([]),
      materializeDatasetRevision: vi.fn().mockResolvedValue(revision),
    };

    render(<ArtifactImprovementPanel engine={engine} projectId="project-1" mode="image" onOpenRevision={onOpenRevision} />);

    expect(await screen.findByRole("option", { name: /candidate\.safetensors/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Compare" }));

    await waitFor(() => expect(engine.createArtifactComparison).toHaveBeenCalledWith({
      project_id: "project-1",
      benchmark_kind: "image",
      candidate_artifact_id: "candidate",
      reference_artifact_id: "reference",
    }));
    expect(await screen.findByText("Exact baseline")).toBeInTheDocument();
    expect(screen.getByText("+10%")).toBeInTheDocument();
    expect(screen.getByText("-10%")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Stage Improvement Plan" }));

    expect(await screen.findByText("Raise visual quality")).toBeInTheDocument();
    expect(screen.getByText("No automatic mutations")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Improvement decision note"), "Build revision two.");
    await user.click(screen.getByRole("button", { name: "Approve Plan" }));

    await waitFor(() => expect(engine.decideImprovementRequest).toHaveBeenCalledWith(
      draft.id,
      "approved",
      "Build revision two.",
    ));
    expect(await screen.findByText(/frozen dataset and settings remain unchanged/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create Revision Draft" }));

    await waitFor(() => expect(engine.materializeDatasetRevision).toHaveBeenCalledWith(draft.id));
    expect(await screen.findByText("Revision v2")).toBeInTheDocument();
    expect(screen.getByText(/copied unchanged for manual editing/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open Image Draft" }));
    expect(onOpenRevision).toHaveBeenCalledWith("image");
  });
});

function artifact(id: string, name: string, sha: string): ModelArtifactRecord {
  return {
    id,
    project_id: "project-1",
    training_run_id: `training-${id}`,
    snapshot_id: `snapshot-${id}`,
    dataset_fingerprint: `fingerprint-${id}`,
    checkpoint_name: name,
    checkpoint_path: `/tmp/${name}`,
    checkpoint_sha256: sha,
    checkpoint_size_bytes: 1024,
    sample_paths: [],
    trigger_token: "person_token",
    modality: "image",
    model_family: "flux1",
    evaluation: {
      status: "ready",
      checkpoint_valid: true,
      provenance_valid: true,
      config_present: true,
      sample_count: 0,
      tensor_count: 1,
      parameter_count: 1,
      warnings: [],
      evaluated_at: "2026-07-16T00:00:00Z",
    },
    acceptance: {
      status: "certified",
      screening_ready: true,
      release_ready: true,
      passed_count: 6,
      failed_count: 0,
      blocked_count: 0,
      warnings: [],
    },
    selected_for_release: id === "reference",
    installed_paths: [],
    workflow_paths: [],
    handoff_paths: [],
    comfy_installations: [],
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
  };
}

function comparisonFixture(reference: ModelArtifactRecord, candidate: ModelArtifactRecord): ArtifactComparison {
  const evidence = (item: ModelArtifactRecord) => ({
    artifact_id: item.id,
    checkpoint_name: item.checkpoint_name,
    checkpoint_sha256: item.checkpoint_sha256,
    dataset_snapshot_id: item.snapshot_id,
    dataset_fingerprint: item.dataset_fingerprint,
    training_run_id: item.training_run_id,
    model_family: item.model_family,
    modality: item.modality,
    benchmark_run_id: `benchmark-${item.id}`,
    benchmark_status: "complete",
    case_ids: ["neutral_closeup"],
    comfy_report_ids: [],
  });
  return {
    format: "lorasuite.artifact-comparison.v1",
    contract_version: 1,
    id: "comparison-1",
    project_id: "project-1",
    benchmark_kind: "image",
    comparison_kind: "artifact_vs_artifact",
    reference: evidence(reference),
    candidate: evidence(candidate),
    comparability: "exact_baseline",
    comparability_notes: ["Both artifacts share identical baseline files, prompts, and seeds."],
    cases: [],
    aggregate_metrics: [
      { metric: "identity_similarity", direction: "higher", delta: 0.1, verdict: "improved" },
      { metric: "visual_quality", direction: "higher", delta: -0.1, verdict: "regressed" },
    ],
    improved_count: 1,
    regressed_count: 1,
    unchanged_count: 0,
    candidate_comfy: { report_count: 0, pass_count: 0, review_count: 0, fail_count: 0, average_metrics: {} },
    created_at: "2026-07-16T00:00:00Z",
  };
}

function requestFixture(comparison: ArtifactComparison, status: "draft" | "approved" | "rejected"): ImprovementRequest {
  return {
    format: "lorasuite.improvement-request.v1",
    contract_version: 1,
    id: "request-1",
    comparison_id: comparison.id,
    project_id: comparison.project_id,
    benchmark_kind: comparison.benchmark_kind,
    candidate_artifact_id: comparison.candidate.artifact_id,
    candidate_checkpoint_sha256: comparison.candidate.checkpoint_sha256,
    reference_artifact_id: comparison.reference?.artifact_id,
    reference_checkpoint_sha256: comparison.reference?.checkpoint_sha256,
    status,
    summary: "One metric regressed.",
    actions: [{
      id: "action-1",
      category: "curation",
      priority: "high",
      title: "Raise visual quality",
      recommendation: "Review low-quality training items before compiling a new revision.",
      evidence: ["neutral_closeup:visual_quality"],
      automatic: false,
    }],
    decision_note: "",
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
  };
}

function revisionFixture(request: ImprovementRequest): DatasetRevisionRecord {
  return {
    format: "lorasuite.dataset-revision.v1",
    contract_version: 1,
    id: "revision-1",
    improvement_request_id: request.id,
    comparison_id: request.comparison_id,
    project_id: request.project_id,
    modality: "image",
    source_artifact_id: request.candidate_artifact_id,
    source_checkpoint_sha256: request.candidate_checkpoint_sha256,
    parent_snapshot_id: "snapshot-candidate",
    parent_snapshot_fingerprint: "fingerprint-candidate",
    revision_snapshot_id: "snapshot-revision-2",
    revision_version: 2,
    action_ids: request.actions.map((action) => action.id),
    status: "draft",
    created_at: "2026-07-16T00:00:00Z",
  };
}
