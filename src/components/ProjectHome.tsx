import { ArrowRight, Check, CircleAlert, Cloud, Cpu, House, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AppDialog } from "./AppDialog";

import type { EngineClient } from "../lib/api";
import { projectOptionLabel } from "../lib/projects";
import type {
  CharacterProject,
  RequestedOutput,
  TrainingTargetProfile,
  TrainingWorkflowLane,
  TrainingWorkflowStatus,
} from "../lib/types";

type ProjectHomeEngine = Pick<EngineClient, "listCharacterProjects" | "getTrainingWorkflow" | "listTrainingTargets">;

const outputLabels: Record<RequestedOutput, string> = {
  image: "Image",
  video: "Video",
  voice: "Voice",
  id_lora: "Living Identity",
};

export function ProjectHome({
  engine,
  activeProjectId,
  onProjectChange,
  onContinue,
}: {
  engine: ProjectHomeEngine;
  activeProjectId: string;
  onProjectChange(projectId: string): void;
  onContinue(lane: TrainingWorkflowLane): void;
}) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [workflow, setWorkflow] = useState<TrainingWorkflowStatus | null>(null);
  const [targets, setTargets] = useState<TrainingTargetProfile[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    let disposed = false;
    setStatus("Loading project status...");
    setWorkflow(null);
    Promise.all([
      engine.listCharacterProjects(),
      engine.listTrainingTargets(),
      activeProjectId ? engine.getTrainingWorkflow(activeProjectId) : Promise.resolve(null),
    ]).then(([projectPayload, targetPayload, workflowPayload]) => {
      if (disposed) return;
      const availableProjects = Array.isArray(projectPayload) ? projectPayload : [];
      setProjects(availableProjects);
      setTargets(Array.isArray(targetPayload) ? targetPayload : []);
      setWorkflow(workflowPayload);
      setStatus("");
    }).catch((error) => {
      if (!disposed) setStatus(`Project status unavailable: ${errorMessage(error)}`);
    });
    return () => { disposed = true; };
  }, [activeProjectId, engine, open]);

  const project = projects.find((candidate) => candidate.id === activeProjectId) ?? null;
  const targetById = useMemo(() => new Map(targets.map((target) => [target.profile_id, target])), [targets]);
  const requestedOutputs = project?.intent.requested_outputs?.length ? project.intent.requested_outputs : (["image"] as RequestedOutput[]);
  const currentWorkflow = workflow?.project_id === activeProjectId ? workflow : null;
  const recommendedLane = currentWorkflow?.lanes.find((lane) => lane.id === currentWorkflow.recommended_lane) ?? null;

  return (
    <div className="project-home-control">
      <button type="button" title="Open Project Home" aria-label="Project Home" onClick={() => setOpen(true)}>
        <House size={16} aria-hidden="true" />
        <span>Project</span>
      </button>
      {open ? (
        <AppDialog className="project-home-panel" label="Project Home" onClose={() => setOpen(false)}>
            <header>
              <div><House size={19} /><span><strong>Project Home</strong><small>Brief, readiness, and the next useful action</small></span></div>
              <button type="button" title="Close Project Home" onClick={() => setOpen(false)}><X size={17} /></button>
            </header>

            {projects.length ? (
              <label className="project-home-picker">
                <span>Active project</span>
                <select value={activeProjectId} onChange={(event) => onProjectChange(event.target.value)}>
                  {projects.map((candidate) => <option value={candidate.id} key={candidate.id}>{projectOptionLabel(candidate)}</option>)}
                </select>
              </label>
            ) : !status ? <p className="empty-state">Create a project to begin.</p> : null}

            {project ? (
              <>
                <section className="project-home-brief">
                  <div><small>Subject</small><strong>{project.intent.subject_name || project.name}</strong></div>
                  <div><small>Accepted sources</small><strong>{project.health.accepted_count}</strong></div>
                  <div><small>Identity anchors</small><strong>{project.health.anchor_count}</strong></div>
                  <div><small>Last updated</small><strong>{new Date(project.updated_at).toLocaleDateString()}</strong></div>
                </section>

                <section className="project-home-contracts" aria-label="What you're making">
                  <h3>What you're making</h3>
                  {requestedOutputs.map((output) => {
                    const profileId = project.intent.training_target_profile_ids?.[output];
                    const target = profileId ? targetById.get(profileId) : undefined;
                    return <TargetContract key={output} output={output} target={target} />;
                  })}
                </section>

                <section className="project-home-lanes" aria-label="Project readiness">
                  <h3>Readiness</h3>
                  {currentWorkflow?.lanes.filter((lane) => requestedOutputs.includes(lane.id as RequestedOutput) || lane.id === "evaluate").map((lane) => (
                    <article className={lane.state} key={lane.id}>
                      <span className="project-home-lane-state">{lane.state === "complete" ? <Check size={14} /> : lane.state === "blocked" ? <CircleAlert size={14} /> : <span />}</span>
                      <div><strong>{lane.label}</strong><small>{lane.summary}</small>{lane.blockers[0] ? <em>{lane.blockers[0]}</em> : null}</div>
                      <button type="button" onClick={() => { onContinue(lane); setOpen(false); }}>{lane.action_label}<ArrowRight size={13} /></button>
                    </article>
                  ))}
                </section>

                {recommendedLane ? (
                  <footer>
                    <span><small>Recommended next</small><strong>{workflow?.recommendation}</strong></span>
                    <button className="primary-action" type="button" onClick={() => { onContinue(recommendedLane); setOpen(false); }}>
                      Continue <ArrowRight size={14} />
                    </button>
                  </footer>
                ) : null}
              </>
            ) : null}
            {status ? <p className="status-line" role="status">{status}</p> : null}
        </AppDialog>
      ) : null}
    </div>
  );
}

function TargetContract({ output, target }: { output: RequestedOutput; target?: TrainingTargetProfile }) {
  const inference = target?.recipe?.workflow_kind === "inference";
  const recipe = target?.recipe;
  const requirements = [
    recipe?.dataset.allowed_image_extensions?.length ? "images" : "",
    recipe?.dataset.allowed_video_extensions?.length ? "video" : "",
    recipe?.dataset.allowed_audio_extensions?.length ? "audio" : "",
  ].filter(Boolean);
  const baseline = target?.duration_baselines?.[0];
  return (
    <article>
      <div>
        <strong>{outputLabels[output]}</strong>
        <small>{target?.label ?? "Target not selected"}</small>
      </div>
      <span className={inference ? "reference" : "training"}>{inference ? <Cpu size={12} /> : <Cloud size={12} />}{inference ? "Reference-only" : "Training"}</span>
      <dl>
        <div><dt>Media</dt><dd>{requirements.join(" + ") || "project review"}</dd></div>
        <div><dt>Run</dt><dd>{target?.provider === "comfyui" ? "Local ComfyUI" : target?.provider ?? "Choose provider"}</dd></div>
        <div><dt>Time</dt><dd>{inference ? "Per generation" : baseline ? `${baseline.low_hours}–${baseline.high_hours}h ${baseline.gpu_family.toUpperCase()}` : "Estimated before submission"}</dd></div>
        <div><dt>Output</dt><dd>{target?.output_format.replaceAll("_", " ") ?? "Not selected"}</dd></div>
      </dl>
      {target?.warnings[0] ? <p>{target.warnings[0]}</p> : null}
    </article>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
