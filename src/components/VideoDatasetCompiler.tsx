import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { Archive, AudioLines, Check, Film, FolderOpen, Image, RefreshCw, Save, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import { TrainingTargetSelect } from "./TrainingTargetSelect";
import { targetsForOutput } from "../lib/trainingCatalog";
import { projectOptionLabel } from "../lib/projects";
import type { CharacterProject, CurationHandoffItem, MediaItem, TrainingTargetProfile, VideoDatasetItemStatus, VideoDatasetSnapshot } from "../lib/types";
import { RunComfyTrainingConsole } from "./RunComfyTrainingConsole";
import { RunPodBundleConsole } from "./RunPodBundleConsole";

type VideoDatasetEngine = Pick<
  EngineClient,
  | "assetUrl"
  | "listCharacterProjects"
  | "listVideoDatasetCandidates"
  | "listVideoDatasetSnapshots"
  | "listVaultMedia"
  | "getCurationHandoff"
  | "compileVideoDataset"
  | "updateVideoDatasetItem"
  | "bulkUpdateVideoDataset"
  | "freezeVideoDataset"
  | "exportVideoDataset"
  | "listTrainingTargets"
  | "listTrainingRuns"
  | "getTrainingRun"
  | "createTrainingRun"
  | "refreshTrainingRun"
  | "resumeTrainingRun"
  | "cancelTrainingRun"
  | "listModelArtifacts"
  | "registerTrainingArtifacts"
  | "listComfyInstallations"
  | "installModelArtifact"
  | "createRunPodBundle"
  | "listRunPodBundles"
  | "listRunPodInfrastructureProfiles"
  | "provisionRunPodInfrastructure"
  | "listRunPodModelBootstrapRuns"
  | "getRunPodModelBootstrapRun"
  | "createRunPodModelBootstrapRun"
  | "refreshRunPodModelBootstrapRun"
  | "cancelRunPodModelBootstrapRun"
  | "listRunPodBundleUploadJobs"
  | "getRunPodBundleUploadJob"
  | "createRunPodBundleUploadJob"
  | "resumeRunPodBundleUploadJob"
  | "listRunPodPreflightReports"
  | "createRunPodPreflightReport"
  | "listRunPodTrainingRuns"
  | "getRunPodTrainingRun"
  | "createRunPodTrainingRun"
  | "refreshRunPodTrainingRun"
  | "cancelRunPodTrainingRun"
  | "downloadRunPodTrainingArtifacts"
  | "registerRunPodTrainingArtifacts"
> & Partial<Pick<EngineClient, "updateCharacterProject">>;

export function VideoDatasetCompiler({ engine, activeProjectId = "", onProjectChange }: { engine: VideoDatasetEngine; activeProjectId?: string; guided?: boolean; onProjectChange?(projectId: string): void }) {
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [candidates, setCandidates] = useState<MediaItem[]>([]);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());
  const [snapshot, setSnapshot] = useState<VideoDatasetSnapshot | null>(null);
  const [trainingTargets, setTrainingTargets] = useState<TrainingTargetProfile[]>([]);
  const [targetProfileId, setTargetProfileId] = useState("runcomfy_wan22_14b_t2v_character");
  const [vaultMedia, setVaultMedia] = useState<MediaItem[]>([]);
  const [handoffItems, setHandoffItems] = useState<CurationHandoffItem[]>([]);
  const [referenceImageIds, setReferenceImageIds] = useState<Set<string>>(new Set());
  const [referenceAudioIds, setReferenceAudioIds] = useState<Set<string>>(new Set());
  const [outputDir, setOutputDir] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading accepted video clips...");

  useEffect(() => {
    let disposed = false;
    engine.listCharacterProjects().then(async (projectPayload) => {
      if (disposed) return;
      const availableProjects = Array.isArray(projectPayload) ? projectPayload : [];
      const initialProjectId = availableProjects.find((project) => project.id === activeProjectId)?.id ?? availableProjects[0]?.id ?? "";
      const [candidatePayload, snapshotPayload, targetPayload] = await Promise.all([
        engine.listVideoDatasetCandidates(initialProjectId || undefined),
        engine.listVideoDatasetSnapshots(),
        engine.listTrainingTargets(),
      ]);
      if (disposed) return;
      const availableCandidates = Array.isArray(candidatePayload) ? candidatePayload : [];
      setProjects(availableProjects);
      setProjectId(initialProjectId);
      if (initialProjectId && initialProjectId !== activeProjectId) onProjectChange?.(initialProjectId);
      setCandidates(availableCandidates);
      setSelectedCandidateIds(new Set(availableCandidates.map((item) => item.id)));
      const initialSnapshot = (Array.isArray(snapshotPayload) ? snapshotPayload : []).find((item) => item.project_id === initialProjectId) ?? null;
      const initialProject = availableProjects.find((project) => project.id === initialProjectId);
      setSnapshot(initialSnapshot);
      setTargetProfileId(
        initialProject?.intent.training_target_profile_ids?.video
        ?? initialSnapshot?.target_profile_id
        ?? "runcomfy_wan22_14b_t2v_character",
      );
      setTrainingTargets(Array.isArray(targetPayload) ? targetPayload : []);
      setStatus(availableCandidates.length ? `${availableCandidates.length} accepted clip${availableCandidates.length === 1 ? "" : "s"} ready.` : "Approve video sources and commit clips before compiling.");
    }).catch((error) => setStatus(`Video dataset error: ${errorMessage(error)}`));
    return () => { disposed = true; };
  }, [engine, activeProjectId]);

  useEffect(() => {
    if (!projectId) return;
    let disposed = false;
    setSnapshot(null);
    Promise.all([
      engine.listVideoDatasetCandidates(projectId),
      engine.listVideoDatasetSnapshots(projectId),
      engine.listVaultMedia(),
      engine.getCurationHandoff(projectId),
    ])
      .then(([candidatePayload, payload, mediaPayload, handoff]) => {
        if (disposed) return;
        const nextCandidates = Array.isArray(candidatePayload) ? candidatePayload : [];
        const nextSnapshot = (Array.isArray(payload) ? payload : [])[0] ?? null;
        const projectTarget = projects.find((project) => project.id === projectId)?.intent.training_target_profile_ids?.video;
        setCandidates(nextCandidates);
        setSelectedCandidateIds(new Set(nextCandidates.map((item) => item.id)));
        setSnapshot(nextSnapshot);
        setVaultMedia(Array.isArray(mediaPayload) ? mediaPayload : []);
        setHandoffItems(Array.isArray(handoff?.items) ? handoff.items : []);
        setReferenceImageIds(new Set(nextSnapshot?.reference_image_media_item_ids ?? []));
        setReferenceAudioIds(new Set(nextSnapshot?.reference_audio_media_item_ids ?? []));
        setTargetProfileId(projectTarget ?? nextSnapshot?.target_profile_id ?? "runcomfy_wan22_14b_t2v_character");
      })
      .catch((error) => { if (!disposed) setStatus(`Video dataset error: ${errorMessage(error)}`); });
    return () => { disposed = true; };
  }, [engine, projectId, projects]);

  async function selectTarget(value: string) {
    const currentProject = projects.find((item) => item.id === projectId);
    if (!currentProject || !engine.updateCharacterProject) { setTargetProfileId(value); return; }
    setBusy(true);
    try {
      const updated = await engine.updateCharacterProject(projectId, { intent: {
        ...currentProject.intent,
        training_target_profile_ids: { ...currentProject.intent.training_target_profile_ids, video: value },
      } });
      setProjects((current) => current.map((item) => item.id === updated.id ? updated : item));
      setTargetProfileId(value);
      setStatus("Video recipe saved to this project.");
    } catch (error) { setStatus(`Could not save video recipe: ${errorMessage(error)}`); }
    finally { setBusy(false); }
  }

  const mediaById = useMemo(() => new Map(candidates.map((item) => [item.id, item])), [candidates]);
  const records = useMemo(() => Object.values(snapshot?.items ?? {}).sort((left, right) => left.id.localeCompare(right.id)), [snapshot]);
  const mutable = snapshot?.status === "draft";
  const balance = snapshot?.balance;
  const compliance = balance?.recipe_compliance;
  const targetProfile = trainingTargets.find((target) => target.profile_id === targetProfileId);
  const videoTargets = targetsForOutput(trainingTargets, "video");
  const workflowKind = targetProfile?.recipe?.workflow_kind ?? "training";
  const isH3Target = targetProfileId === "comfyui_minimax_h3_ref2va";
  const referencesChanged = isH3Target && snapshot !== null && (
    !sameIds(referenceImageIds, snapshot.reference_image_media_item_ids ?? [])
    || !sameIds(referenceAudioIds, snapshot.reference_audio_media_item_ids ?? [])
  );
  const draftChanged = referencesChanged || (snapshot !== null && snapshot.target_profile_id !== targetProfileId);
  const selectedProject = projects.find((project) => project.id === projectId);
  const acceptedImageIds = useMemo(() => new Set(
    Object.values(selectedProject?.observations ?? {})
      .filter((observation) => observation.review_status === "accepted")
      .map((observation) => observation.media_item_id),
  ), [selectedProject]);
  const acceptedAudioById = useMemo(() => new Map(
    handoffItems
      .filter((item) => item.lane === "audio" && item.review_status === "accepted" && item.speaker_confirmation)
      .map((item) => [item.media_item_id, item]),
  ), [handoffItems]);
  const imageReferences = useMemo(() => vaultMedia.filter((item) => item.media_type === "image" && acceptedImageIds.has(item.id)), [acceptedImageIds, vaultMedia]);
  const audioReferences = useMemo(() => vaultMedia.filter((item) => item.media_type === "audio" && acceptedAudioById.has(item.id)), [acceptedAudioById, vaultMedia]);

  async function compile() {
    if (!projectId || (!selectedCandidateIds.size && !(isH3Target && (referenceImageIds.size || referenceAudioIds.size))) || busy) return;
    setBusy(true);
    setStatus("Compiling accepted clips and temporal evidence...");
    try {
      const result = await engine.compileVideoDataset(
        projectId,
        [...selectedCandidateIds],
        targetProfileId,
        isH3Target ? [...referenceImageIds] : undefined,
        isH3Target ? [...referenceAudioIds] : undefined,
      );
      setSnapshot(result);
      setStatus(`Video dataset v${result.version} compiled with ${result.balance.total_count} clips.`);
    } catch (error) {
      setStatus(`Video compile error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateItem(itemId: string, update: { caption?: string; status?: VideoDatasetItemStatus }) {
    if (!snapshot || !mutable || busy) return;
    setBusy(true);
    try {
      const result = await engine.updateVideoDatasetItem(snapshot.id, itemId, update);
      setSnapshot(result);
      setStatus("Video decision saved.");
    } catch (error) {
      setStatus(`Video decision error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function approveAll() {
    if (!snapshot || !mutable || busy) return;
    setBusy(true);
    try {
      const result = await engine.bulkUpdateVideoDataset(snapshot.id, "approved");
      setSnapshot(result);
      setStatus("All remaining video clips staged as approved.");
    } catch (error) {
      setStatus(`Video approval error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function freeze() {
    if (!snapshot || !mutable || busy || draftChanged) return;
    setBusy(true);
    try {
      const result = await engine.freezeVideoDataset(snapshot.id);
      setSnapshot(result);
      setStatus(`Video dataset frozen: ${result.fingerprint?.slice(0, 12)}.`);
    } catch (error) {
      setStatus(`Video freeze error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function chooseOutput() {
    if (!isTauri()) return;
    try {
      const selected = await open({ directory: true, multiple: false, title: "Choose video dataset destination" });
      if (typeof selected === "string") setOutputDir(selected);
    } catch (error) {
      setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function exportDataset() {
    if (!snapshot || snapshot.status === "draft" || !outputDir.trim() || busy || draftChanged) return;
    setBusy(true);
    setStatus("Normalizing and packaging video clips...");
    try {
      const result = await engine.exportVideoDataset(snapshot.id, outputDir.trim());
      setSnapshot(result.snapshot);
      setStatus(`Video export complete: ${result.package.output_path}`);
    } catch (error) {
      setStatus(`Video export error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function toggleCandidate(itemId: string) {
    setSelectedCandidateIds((existing) => {
      const next = new Set(existing);
      if (next.has(itemId)) next.delete(itemId); else next.add(itemId);
      return next;
    });
  }

  function toggleReference(itemId: string, kind: "image" | "audio") {
    const setter = kind === "image" ? setReferenceImageIds : setReferenceAudioIds;
    const limit = kind === "image" ? 9 : 3;
    setter((existing) => {
      const next = new Set(existing);
      if (next.has(itemId)) next.delete(itemId);
      else if (next.size < limit) next.add(itemId);
      return next;
    });
  }

  return (
    <section className="workspace-section video-dataset-workspace">
      <header className="video-dataset-commandbar">
        <div><Film size={19} /><span><strong>Video Dataset Compiler</strong><small>Temporal clips · source-safe splits</small></span></div>
        <label>Project<select value={projectId} onChange={(event) => { setProjectId(event.target.value); onProjectChange?.(event.target.value); }} disabled={busy}>{projects.length ? projects.map((project) => <option key={project.id} value={project.id}>{projectOptionLabel(project)}</option>) : <option value="">No Identity projects</option>}</select></label>
        <label>Target<TrainingTargetSelect targets={videoTargets} output="video" label="Video target" value={targetProfileId} onChange={(value) => void selectTarget(value)} disabled={busy} /></label>
        <span className={`snapshot-state ${snapshot?.status ?? "empty"}`}>{snapshot?.status ?? "not compiled"}</span>
        <button type="button" onClick={compile} disabled={!projectId || (!selectedCandidateIds.size && !(isH3Target && (referenceImageIds.size || referenceAudioIds.size))) || busy}><RefreshCw size={14} /> {mutable ? "Recompile" : "Build Draft"}</button>
        <button type="button" onClick={approveAll} disabled={!mutable || !balance?.review_count || busy}><Check size={14} /> Approve All</button>
        <button className="primary-action" type="button" onClick={freeze} disabled={!mutable || !!balance?.review_count || !balance?.approved_count || !!compliance?.blocker_count || busy || draftChanged}><Archive size={14} /> Freeze</button>
      </header>
      {draftChanged ? <p role="status">Your target or references changed. Recompile to save them before freezing or exporting.</p> : null}
      <dl className="video-dataset-metrics">
        <Metric label="Candidates" value={candidates.length} />
        <Metric label="Clips" value={balance?.total_count ?? 0} />
        <Metric label="Approved" value={balance?.approved_count ?? 0} />
        <Metric label="Review" value={balance?.review_count ?? 0} />
        <Metric label="Sources" value={balance?.source_count ?? 0} />
        <Metric label="Duration" value={`${(balance?.total_duration_seconds ?? 0).toFixed(1)}s`} />
        <Metric label="Train" value={balance?.train_count ?? 0} />
        <Metric label="Validation" value={balance?.validation_count ?? 0} />
      </dl>
      {isH3Target ? (
        <section className="h3-reference-picker" aria-label="MiniMax H3 reviewed references">
          <header>
            <div><strong>MiniMax H3 standalone references</strong><small>Choose only the subject evidence you want copied into the H3 package. Nothing is selected automatically.</small></div>
            <span>{referenceImageIds.size}/9 images · {referenceAudioIds.size}/3 audio</span>
          </header>
          <div className="h3-reference-group">
            <div className="h3-reference-heading"><Image size={15} /><span><strong>Identity-approved images</strong><small>Optional still references already approved in Verify</small></span></div>
            <div className="h3-image-references">
              {imageReferences.map((item) => (
                <label className={referenceImageIds.has(item.id) ? "selected" : ""} key={item.id}>
                  <input aria-label={`Include image reference ${item.id}`} type="checkbox" checked={referenceImageIds.has(item.id)} disabled={busy || (!!snapshot && !mutable) || (!referenceImageIds.has(item.id) && referenceImageIds.size >= 9)} onChange={() => toggleReference(item.id, "image")} />
                  <img src={item.raw_path ? engine.assetUrl(item.raw_path) : undefined} alt="Reviewed identity reference" />
                </label>
              ))}
              {!imageReferences.length ? <p>No identity-approved stills are available for this project.</p> : null}
            </div>
          </div>
          <div className="h3-reference-group">
            <div className="h3-reference-heading"><AudioLines size={15} /><span><strong>Speaker-confirmed audio</strong><small>Optional voice references with an anchor, model match, or human override</small></span></div>
            <div className="h3-audio-references">
              {audioReferences.map((item) => {
                const confirmation = acceptedAudioById.get(item.id)?.speaker_confirmation;
                return (
                  <label className={referenceAudioIds.has(item.id) ? "selected" : ""} key={item.id}>
                    <input aria-label={`Include audio reference ${item.id}`} type="checkbox" checked={referenceAudioIds.has(item.id)} disabled={busy || (!!snapshot && !mutable) || (!referenceAudioIds.has(item.id) && referenceAudioIds.size >= 3)} onChange={() => toggleReference(item.id, "audio")} />
                    <audio controls preload="metadata" src={item.raw_path ? engine.assetUrl(item.raw_path) : undefined} />
                    <span>{confirmation?.replaceAll("_", " ")}</span>
                  </label>
                );
              })}
              {!audioReferences.length ? <p>No accepted, speaker-confirmed audio is available for this project.</p> : null}
            </div>
          </div>
        </section>
      ) : null}
      {compliance ? (
        <details className={`video-recipe-compliance ${compliance.status}`} open={compliance.status !== "ready"}>
          <summary>
            <span>
              {compliance.status === "ready" ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
              <strong>{compliance.recipe_label}</strong>
              <small>Recipe v{compliance.recipe_version} · {Math.round(compliance.score * 100)}% preflight</small>
            </span>
            <span className="video-recipe-state">{compliance.status}</span>
          </summary>
          <div className="video-recipe-checks">
            {compliance.checks.map((check) => (
              <article className={check.passed ? "passed" : check.severity} key={check.check_id} title={check.detail}>
                <span>{check.passed ? <Check size={12} /> : <X size={12} />}</span>
                <div><strong>{check.label}</strong><small>{check.passed ? `${check.current ?? "ready"}` : check.detail}</small></div>
              </article>
            ))}
          </div>
        </details>
      ) : balance?.warnings.length ? <div className="video-dataset-warnings"><ShieldAlert size={15} />{balance.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div> : null}
      {!snapshot ? (
        <section className="video-candidate-picker">
          {candidates.map((candidate) => <label key={candidate.id}><input type="checkbox" checked={selectedCandidateIds.has(candidate.id)} onChange={() => toggleCandidate(candidate.id)} /><video src={engine.assetUrl(candidate.raw_path ?? "")} muted preload="metadata" /><span>{candidate.duration?.toFixed(1) ?? "--"}s</span></label>)}
          {!candidates.length ? <p>No accepted video candidates.</p> : null}
        </section>
      ) : (
        <section className="video-dataset-grid">
          {records.map((record) => {
            const media = mediaById.get(record.media_item_id);
            return <VideoRecord key={record.id} record={record} media={media} assetUrl={engine.assetUrl} mutable={mutable} busy={busy} onUpdate={updateItem} />;
          })}
        </section>
      )}
      <section className="video-dataset-export">
        <div><strong>{workflowKind === "inference" ? "MiniMax H3 References" : "AI Toolkit Video"}</strong><small>{snapshot?.fingerprint ? `Fingerprint ${snapshot.fingerprint.slice(0, 12)}` : "Freeze reviewed clips before export"}</small></div>
        <input aria-label="Video output folder" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} placeholder="/path/to/video-dataset" />
        {isTauri() ? <button type="button" onClick={chooseOutput} disabled={busy} title="Choose output folder"><FolderOpen size={14} /></button> : null}
        <button className="primary-action" type="button" onClick={exportDataset} disabled={!snapshot || snapshot.status === "draft" || !outputDir.trim() || busy || draftChanged}>Export</button>
      </section>
      {snapshot?.status === "exported" && workflowKind === "inference" ? (
        <section className="video-dataset-warnings minimax-h3-handoff">
          <ShieldCheck size={15} />
          <span>
            H3 reference package ready. Open ComfyUI 0.30.0 or later, choose the <strong>MiniMax H3 R2V</strong> template,
            then load the package references in manifest order. This is zero-shot generation, not LoRA training.
          </span>
          <a href="https://docs.comfy.org/tutorials/video/minimax/minimax-h3" target="_blank" rel="noreferrer">Open H3 workflow guide</a>
        </section>
      ) : null}
      {snapshot?.status === "exported" && workflowKind === "training" ? (
        <>
          <RunComfyTrainingConsole
            engine={engine}
            snapshot={snapshot}
            targetProfile={targetProfile}
          />
          {snapshot.export_path ? <RunPodBundleConsole engine={engine} sourceExportPath={snapshot.export_path} modality="video" triggerToken={snapshot.trigger_token} fingerprint={snapshot.fingerprint ?? snapshot.id} trainingTargetProfileId={snapshot.target_profile_id} /> : null}
        </>
      ) : null}
      <p className="status-line" aria-live="polite">{status}</p>
    </section>
  );
}

function VideoRecord({ record, media, assetUrl, mutable, busy, onUpdate }: {
  record: VideoDatasetSnapshot["items"][string];
  media?: MediaItem;
  assetUrl(path: string): string;
  mutable: boolean;
  busy: boolean;
  onUpdate(itemId: string, update: { caption?: string; status?: VideoDatasetItemStatus }): void;
}) {
  const [caption, setCaption] = useState(record.caption);
  useEffect(() => setCaption(record.caption), [record.caption]);
  return (
    <article className={`video-dataset-card ${record.status}`}>
      <video src={media?.raw_path ? assetUrl(media.raw_path) : undefined} controls preload="metadata" />
      <div className="video-record-facts"><span>{record.duration_seconds.toFixed(1)}s</span><span>{record.width}×{record.height}</span><span>ID {Math.round(record.identity_score * 100)}%</span><span>{record.split}</span></div>
      <textarea aria-label={`Video caption ${record.id}`} value={caption} onChange={(event) => setCaption(event.target.value)} disabled={!mutable || busy} />
      <div className="video-record-actions">
        <button type="button" title="Save caption" onClick={() => onUpdate(record.id, { caption })} disabled={!mutable || busy || caption.trim() === record.caption}><Save size={13} /></button>
        <button type="button" title="Approve clip" className={record.status === "approved" ? "active approve" : "approve"} onClick={() => onUpdate(record.id, { status: "approved" })} disabled={!mutable || busy}><Check size={14} /></button>
        <button type="button" title="Exclude clip" className={record.status === "excluded" ? "active exclude" : "exclude"} onClick={() => onUpdate(record.id, { status: "excluded" })} disabled={!mutable || busy}><X size={14} /></button>
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function sameIds(selected: Set<string>, saved: string[]): boolean {
  const ordered = [...selected];
  return ordered.length === saved.length && saved.every((id, index) => ordered[index] === id);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
