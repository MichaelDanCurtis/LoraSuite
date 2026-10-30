import { Film, ImageIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { EvaluationHarness, type EvaluationEngine } from "./EvaluationHarness";
import { ImageEvaluationHarness, type ImageEvaluationEngine } from "./ImageEvaluationHarness";
import { ReleaseCandidatePanel } from "./ReleaseCandidatePanel";
import { ArtifactImprovementPanel } from "./ArtifactImprovementPanel";

type EvaluationWorkspaceEngine = EvaluationEngine & ImageEvaluationEngine & Pick<import("../lib/api").EngineClient, "listModelReleaseCandidates" | "selectModelRelease"> & Partial<Pick<import("../lib/api").EngineClient, "listArtifactComparisons" | "createArtifactComparison" | "listImprovementRequests" | "createImprovementRequest" | "decideImprovementRequest" | "listDatasetRevisions" | "materializeDatasetRevision">>;

export function EvaluationWorkspace({ engine, activeProjectId = "", initialMode = "image", onProjectChange, onOpenRevision }: { engine: EvaluationWorkspaceEngine; activeProjectId?: string; initialMode?: "image" | "audio_visual"; onProjectChange?(projectId: string): void; onOpenRevision?(modality: "image" | "video"): void }) {
  const [mode, setMode] = useState<"image" | "audio_visual">(initialMode);
  useEffect(() => setMode(initialMode), [initialMode]);
  return <div className="evaluation-workspace-shell">
    <div className="evaluation-mode-tabs" role="tablist" aria-label="LoRA evaluation modes">
      <button type="button" role="tab" aria-selected={mode === "image"} onClick={() => setMode("image")}><ImageIcon size={14} /> Image LoRA</button>
      <button type="button" role="tab" aria-selected={mode === "audio_visual"} onClick={() => setMode("audio_visual")}><Film size={14} /> Audio-Visual</button>
    </div>
    <ReleaseCandidatePanel engine={engine} projectId={activeProjectId} mode={mode} />
    <ArtifactImprovementPanel engine={engine} projectId={activeProjectId} mode={mode} onOpenRevision={onOpenRevision} />
    {mode === "image"
      ? <ImageEvaluationHarness engine={engine} activeProjectId={activeProjectId} onProjectChange={onProjectChange} />
      : <EvaluationHarness engine={engine} activeProjectId={activeProjectId} onProjectChange={onProjectChange} />}
  </div>;
}
