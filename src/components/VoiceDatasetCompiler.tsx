import { Activity, Archive, AudioLines, Check, FolderOpen, RefreshCw, Save, Scissors, ShieldAlert, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import { projectOptionLabel } from "../lib/projects";
import type {
  CharacterProject,
  MediaItem,
  VoiceDatasetCompilation,
  VoiceDatasetSegment,
  VoiceExportTarget,
  VoiceIdentityProfile,
  VoiceSegmentStatus,
} from "../lib/types";
import { RunPodBundleConsole } from "./RunPodBundleConsole";
import { VoiceArtifactEvaluator } from "./VoiceArtifactEvaluator";

type VoiceDatasetEngine = Pick<
  EngineClient,
  | "assetUrl"
  | "listVaultMedia"
  | "listCharacterProjects"
  | "getCurationHandoff"
  | "getVoiceIdentityProfile"
  | "setVoiceIdentityAnchors"
  | "getVoiceDataset"
  | "compileVoiceDataset"
  | "updateVoiceDatasetSegment"
  | "bulkUpdateVoiceDatasetSegments"
  | "rescoreVoiceDataset"
  | "analyzeVoiceDatasetQuality"
  | "exportVoiceDataset"
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
  | "listModelArtifacts"
  | "listVoiceArtifactEvaluations"
  | "getVoiceArtifactEvaluation"
  | "getRecommendedVoiceArtifactEvaluation"
  | "createVoiceArtifactEvaluation"
  | "selectVoiceArtifactEvaluation"
>;

type SegmentFilter = "all" | VoiceSegmentStatus;

export function VoiceDatasetCompiler({ engine, activeProjectId = "", guided = false, onProjectChange }: { engine: VoiceDatasetEngine; activeProjectId?: string; guided?: boolean; onProjectChange?(projectId: string): void }) {
  const [projects, setProjects] = useState<CharacterProject[]>([]);
  const [project, setProject] = useState<CharacterProject | null>(null);
  const [voiceProfile, setVoiceProfile] = useState<VoiceIdentityProfile | null>(null);
  const [compilation, setCompilation] = useState<VoiceDatasetCompilation | null>(null);
  const [sourceItems, setSourceItems] = useState<MediaItem[]>([]);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [transcriptDraft, setTranscriptDraft] = useState("");
  const [filter, setFilter] = useState<SegmentFilter>("all");
  const [stagedDecisions, setStagedDecisions] = useState<Record<string, VoiceSegmentStatus>>({});
  const [anchorsOpen, setAnchorsOpen] = useState(false);
  const [outputDir, setOutputDir] = useState("");
  const [exportTarget, setExportTarget] = useState<VoiceExportTarget>("voice_cloning");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Loading voice dataset workspace...");
  const [artifactRevision, setArtifactRevision] = useState(0);

  useEffect(() => {
    let ignore = false;
    async function load() {
      setBusy(true);
      try {
        const [projects, mediaItems] = await Promise.all([
          engine.listCharacterProjects(),
          engine.listVaultMedia(),
        ]);
        const currentProject = projects.find((candidate) => candidate.id === activeProjectId) ?? projects[0] ?? null;
        if (!currentProject) throw new Error("Create a character project in Identify first");
        const handoff = await engine.getCurationHandoff(currentProject.id);
        let [profile, dataset] = await Promise.all([
          engine.getVoiceIdentityProfile(currentProject.id),
          engine.getVoiceDataset(currentProject.id),
        ]);
        let rescoredForAnchors = false;
        if (Object.keys(dataset.segments).length > 0 && isNewer(profile.updated_at, dataset.updated_at)) {
          dataset = await engine.rescoreVoiceDataset(currentProject.id);
          profile = await engine.getVoiceIdentityProfile(currentProject.id);
          rescoredForAnchors = true;
        }
        const acceptedIds = new Set(
          handoff.items
            .filter((item) => item.lane === "audio" && item.review_status === "accepted")
            .map((item) => item.media_item_id),
        );
        const sources = preferredVoiceSources(mediaItems, acceptedIds);
        if (!ignore) {
          setProject(currentProject);
          setProjects(projects);
          if (currentProject.id !== activeProjectId) onProjectChange?.(currentProject.id);
          setVoiceProfile(profile);
          setCompilation(dataset);
          setSourceItems(sources);
          const qualityCount = Object.values(dataset.segments).filter((segment) => segment.quality).length;
          setStatus(
            qualityCount < Object.keys(dataset.segments).length
              ? `${Object.keys(dataset.segments).length - qualityCount} segments need the audio quality gate.`
              : rescoredForAnchors
              ? `Anchor set changed; rescored ${Object.keys(dataset.segments).length} voice segments.`
              : sources.length
              ? `${sources.length} approved audio source${sources.length === 1 ? "" : "s"} ready to compile.`
              : "Approve speaker-verified audio in Identify before compiling.",
          );
        }
      } catch (error) {
        if (!ignore) setStatus(`Voice dataset error: ${errorMessage(error)}`);
      } finally {
        if (!ignore) setBusy(false);
      }
    }
    void load();
    return () => {
      ignore = true;
    };
  }, [engine, activeProjectId]);

  const segments = useMemo(
    () => Object.values(compilation?.segments ?? {}).sort((left, right) => left.created_at.localeCompare(right.created_at)),
    [compilation],
  );
  const visibleSegments = filter === "all" ? segments : segments.filter((segment) => segment.status === filter);
  const selectedSegment = segments.find((segment) => segment.id === selectedSegmentId) ?? visibleSegments[0] ?? null;
  const approvedCount = segments.filter((segment) => segment.status === "approved").length;
  const reviewCount = segments.filter((segment) => segment.status === "needs_review").length;
  const rejectedCount = segments.filter((segment) => segment.status === "rejected").length;
  const stagedCount = Object.keys(stagedDecisions).length;
  const anchorIds = voiceProfile?.anchor_media_item_ids ?? [];
  const qualityCount = segments.filter((segment) => segment.quality).length;
  const qualityReady = segments.length > 0 && qualityCount === segments.length;
  const compliance = compilation?.balance?.recipe_compliance;

  useEffect(() => {
    if (selectedSegment && selectedSegment.id !== selectedSegmentId) {
      setSelectedSegmentId(selectedSegment.id);
    }
    setTranscriptDraft(selectedSegment?.transcript ?? "");
  }, [selectedSegment?.id]);

  async function compileSegments() {
    if (!project || busy) return;
    setBusy(true);
    setStatus("Transcribing verified tracks and creating timestamped audio samples...");
    try {
      const updated = await engine.compileVoiceDataset(project.id, sourceItems.map((item) => item.id));
      setCompilation(updated);
      const count = Object.keys(updated.segments).length;
      setStatus(`Created ${count} timestamped audio sample${count === 1 ? "" : "s"}.`);
    } catch (error) {
      setStatus(`Voice compilation error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateSegment(update: { status?: VoiceSegmentStatus; transcript?: string }) {
    if (!project || !selectedSegment || busy) return;
    setBusy(true);
    try {
      const updated = await engine.updateVoiceDatasetSegment(project.id, selectedSegment.id, update);
      setCompilation(updated);
      setStatus(update.transcript !== undefined ? "Transcript saved." : `Segment marked ${update.status?.replace("_", " ")}.`);
    } catch (error) {
      setStatus(`Voice segment error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function runQualityGate() {
    if (!project || busy || segments.length === 0) return;
    setBusy(true);
    setStatus(`Measuring signal quality and speaker overlap across ${segments.length} segments...`);
    try {
      const updated = await engine.analyzeVoiceDatasetQuality(project.id);
      setCompilation(updated);
      const keep = Object.values(updated.segments).filter((segment) => segment.recommendation === "keep").length;
      setStagedDecisions({});
      setStatus(`Quality gate complete; ${keep} segment${keep === 1 ? "" : "s"} pass${keep === 1 ? "es" : ""} both identity and signal checks.`);
    } catch (error) {
      setStatus(`Audio quality error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function stageRecommendations() {
    const decisions = Object.fromEntries(
      segments.map((segment) => [segment.id, recommendationStatus(segment)]),
    );
    setStagedDecisions(decisions);
    const approvals = Object.values(decisions).filter((status) => status === "approved").length;
    const rejections = Object.values(decisions).filter((status) => status === "rejected").length;
    setStatus(`Staged AI recommendations: ${approvals} approve, ${rejections} reject, ${segments.length - approvals - rejections} review. Inspect or override before applying.`);
  }

  function stageDecision(segmentId: string, status: VoiceSegmentStatus) {
    setStagedDecisions((current) => ({ ...current, [segmentId]: status }));
    setStatus(`Staged segment as ${status.replace("_", " ")}. Apply staged decisions when review is complete.`);
  }

  async function applyStagedDecisions() {
    if (!project || busy || stagedCount === 0) return;
    setBusy(true);
    setStatus(`Applying ${stagedCount} staged voice decisions...`);
    try {
      const updated = await engine.bulkUpdateVoiceDatasetSegments(project.id, stagedDecisions);
      setCompilation(updated);
      setStagedDecisions({});
      setStatus(`Applied ${stagedCount} reviewed voice decisions.`);
    } catch (error) {
      setStatus(`Voice decision error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function toggleAnchor(segment: VoiceDatasetSegment) {
    if (!project || busy) return;
    const isAnchor = anchorIds.includes(segment.media_item_id);
    if (!isAnchor && segment.status !== "approved") {
      setStatus("Approve the segment before promoting it to a trusted anchor.");
      return;
    }
    await persistAnchorChange(segment.media_item_id, !isAnchor);
  }

  async function persistAnchorChange(mediaItemId: string, shouldTrust: boolean) {
    if (!project || busy) return;
    if (!shouldTrust && anchorIds.length === 1) {
      setStatus("Keep at least one trusted voice anchor.");
      return;
    }
    const nextAnchors = shouldTrust
      ? [...anchorIds, mediaItemId]
      : anchorIds.filter((anchorId) => anchorId !== mediaItemId);
    setBusy(true);
    setStatus(shouldTrust ? "Adding voice anchor and rescoring..." : "Removing voice anchor and rescoring...");
    try {
      await engine.setVoiceIdentityAnchors(project.id, nextAnchors);
      const updated = await engine.rescoreVoiceDataset(project.id);
      const profile = await engine.getVoiceIdentityProfile(project.id);
      setCompilation(updated);
      setVoiceProfile(profile);
      setStatus(`${profile.anchor_media_item_ids.length} trusted anchors; all segments rescored.`);
    } catch (error) {
      setStatus(`Voice anchor error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function exportDataset() {
    if (!project || busy) return;
    const destination = stripShellQuotes(outputDir);
    if (!destination) {
      setStatus("Choose an output folder for the voice dataset.");
      return;
    }
    setBusy(true);
    setStatus("Exporting approved WAV and transcript pairs...");
    try {
      const result = await engine.exportVoiceDataset(project.id, destination, exportTarget);
      setCompilation(result.compilation);
      setOutputDir(destination);
      setStatus(`${exportTargetLabel(exportTarget)} export complete: ${result.package.output_path}`);
    } catch (error) {
      setStatus(`Voice export error: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workspace-section voice-dataset-workspace">
      <header className="voice-dataset-header">
        <div><AudioLines size={20} aria-hidden="true" /><span><h2>Voice Sample Compiler</h2><p>{project?.name ?? "Character Dataset"}</p></span></div>
        <label className="voice-project-select">Project<select aria-label="Voice character project" value={project?.id ?? ""} onChange={(event) => onProjectChange?.(event.target.value)} disabled={busy}>{projects.map((candidate) => <option key={candidate.id} value={candidate.id}>{projectOptionLabel(candidate)}</option>)}</select></label>
        <dl aria-label="Voice dataset summary">
          <Metric label="Sources" value={sourceItems.length} />
          <Metric label="Samples" value={segments.length} />
          <Metric label="Review" value={reviewCount} />
          <Metric label="Approved" value={approvedCount} />
          <Metric label="Rejected" value={rejectedCount} />
        </dl>
        <div className="voice-header-actions">
          <button type="button" onClick={() => void runQualityGate()} disabled={busy || segments.length === 0}><Activity size={14} /> Quality Gate</button>
          <button className="primary-action" type="button" onClick={() => void compileSegments()} disabled={busy || sourceItems.length === 0 || !(voiceProfile?.anchor_media_item_ids.length)}>
            {busy ? <RefreshCw className="spin" size={14} /> : <Scissors size={14} />} Create Audio Samples
          </button>
        </div>
      </header>

      <div className="voice-source-strip">
        <button className="voice-anchor-summary" type="button" aria-expanded={anchorsOpen} onClick={() => setAnchorsOpen((open) => !open)}><ShieldCheck size={14} /> {anchorIds.length} trusted voice anchors</button>
        <span>{sourceItems.length} accepted sources</span>
        <select aria-label="Voice export target" value={exportTarget} onChange={(event) => setExportTarget(event.target.value as VoiceExportTarget)}>
          <option value="voice_cloning">Voice Cloning</option>
          <option value="av_lora">AV-LoRA Reference</option>
          <option value="both">Both Targets</option>
        </select>
        <label><FolderOpen size={14} /><input aria-label="Voice output folder" value={outputDir} onChange={(event) => setOutputDir(event.target.value)} placeholder="/path/to/voice-dataset" /></label>
        <button type="button" onClick={() => void exportDataset()} disabled={busy || approvedCount === 0 || !!compliance?.blocker_count}><Archive size={14} /> Export Approved</button>
      </div>

      {compliance ? (
        <details className={`video-recipe-compliance voice-recipe-compliance ${compliance.status}`} open={compliance.status !== "ready"}>
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
      ) : null}

      {anchorsOpen ? (
        <div className="voice-anchor-manager" aria-label="Trusted voice anchors">
          {anchorIds.map((mediaItemId, index) => {
            const segment = segments.find((candidate) => candidate.media_item_id === mediaItemId);
            return <span key={mediaItemId}><ShieldCheck size={13} /><strong>{segment ? `${formatTime(segment.start_seconds)}–${formatTime(segment.end_seconds)}` : `Source anchor ${index + 1}`}</strong><button type="button" title="Remove voice anchor" onClick={() => void persistAnchorChange(mediaItemId, false)} disabled={busy || anchorIds.length === 1}><Trash2 size={12} /></button></span>;
          })}
        </div>
      ) : null}

      {segments.length === 0 ? (
        <p className="empty-state">Create audio samples from the accepted, speaker-verified tracks.</p>
      ) : (
        <div className="voice-dataset-layout">
          <aside className="voice-segment-queue" aria-label="Audio sample queue">
            <div className="voice-queue-toolbar">
              <div className="segmented-control" role="group" aria-label="Audio sample filter">
                {(["all", "needs_review", "approved", "rejected"] as SegmentFilter[]).map((option) => (
                  <button type="button" key={option} aria-pressed={filter === option} onClick={() => setFilter(option)}>{segmentFilterLabel(option)}</button>
                ))}
              </div>
              <button type="button" title="Stage AI recommendations" onClick={stageRecommendations} disabled={busy || !qualityReady}><Sparkles size={13} /> Stage AI</button>
              <button className="apply-staged" type="button" onClick={() => void applyStagedDecisions()} disabled={busy || stagedCount === 0}><Check size={13} /> Apply {stagedCount || ""}</button>
              <button type="button" title="Clear staged decisions" onClick={() => setStagedDecisions({})} disabled={busy || stagedCount === 0}><X size={13} /></button>
            </div>
            <div>
              {visibleSegments.map((segment) => (
                <button className={selectedSegment?.id === segment.id ? "active" : ""} type="button" key={segment.id} onClick={() => setSelectedSegmentId(segment.id)}>
                  <span><strong>{formatTime(segment.start_seconds)}–{formatTime(segment.end_seconds)}</strong><small>{formatPercent(segment.speaker_similarity)} voice · {formatDuration(segment)}</small></span>
                  <i className={`${stagedDecisions[segment.id] ?? segment.status}${stagedDecisions[segment.id] ? " staged" : ""}`}>{decisionGlyph(stagedDecisions[segment.id] ?? segment.status)}</i>
                </button>
              ))}
            </div>
          </aside>

          <section className="voice-segment-review" aria-label="Voice segment review">
            {selectedSegment ? (
              <>
                <header><div><strong>{formatTime(selectedSegment.start_seconds)}–{formatTime(selectedSegment.end_seconds)}</strong><span className={`voice-recommendation ${selectedSegment.recommendation}`}>{selectedSegment.recommendation}</span></div><small>{selectedSegment.language?.toUpperCase() ?? "--"} · {formatPercent(selectedSegment.transcript_confidence)} transcript</small></header>
                <audio src={engine.assetUrl(selectedSegment.audio_path)} controls preload="metadata" />
                <dl className="voice-segment-evidence">
                  <Metric label="Speaker" value={formatPercent(selectedSegment.speaker_similarity)} />
                  <Metric label="Quality" value={formatPercent(selectedSegment.quality?.quality_score)} />
                  <Metric label="SNR" value={formatDb(selectedSegment.quality?.snr_db)} />
                  <Metric label="Active" value={formatPercent(selectedSegment.quality?.active_audio_ratio)} />
                  <Metric label="Clipping" value={formatPercent(selectedSegment.quality?.clipping_ratio)} />
                  <Metric label="Echo Risk" value={formatPercent(selectedSegment.quality?.reverb_risk)} />
                </dl>
                <div className="voice-quality-summary">
                  <span className={`voice-recommendation ${selectedSegment.identity_recommendation}`}>identity {selectedSegment.identity_recommendation}</span>
                  <span className={`voice-recommendation ${selectedSegment.quality?.recommendation ?? "review"}`}>signal {selectedSegment.quality?.recommendation ?? "pending"}</span>
                  <span>{selectedSegment.quality?.source_classification.replaceAll("_", " ") ?? "quality pending"}</span>
                  <span>{selectedSegment.quality?.speaker_count == null ? "speaker overlap unknown" : `${selectedSegment.quality.speaker_count} speaker${selectedSegment.quality.speaker_count === 1 ? "" : "s"}`}</span>
                </div>
                <label className="voice-transcript-editor">Transcript<textarea aria-label="Voice segment transcript" value={transcriptDraft} onChange={(event) => setTranscriptDraft(event.target.value)} /></label>
                <div className="voice-segment-actions">
                  <button type="button" onClick={() => void updateSegment({ transcript: transcriptDraft })} disabled={busy || transcriptDraft.trim() === selectedSegment.transcript}><Save size={14} /> Save Transcript</button>
                  <button className={anchorIds.includes(selectedSegment.media_item_id) ? "voice-anchor-action active" : "voice-anchor-action"} type="button" onClick={() => void toggleAnchor(selectedSegment)} disabled={busy || (!anchorIds.includes(selectedSegment.media_item_id) && selectedSegment.status !== "approved")} title={anchorIds.includes(selectedSegment.media_item_id) ? "Remove trusted anchor" : "Promote approved segment to trusted anchor"}><ShieldCheck size={14} /> {anchorIds.includes(selectedSegment.media_item_id) ? "Trusted" : "Trust Voice"}</button>
                  <span />
                  <button className={(stagedDecisions[selectedSegment.id] ?? selectedSegment.status) === "approved" ? "active accept" : "accept"} type="button" title="Stage approval" onClick={() => stageDecision(selectedSegment.id, "approved")} disabled={busy}><Check size={15} /></button>
                  <button className={(stagedDecisions[selectedSegment.id] ?? selectedSegment.status) === "needs_review" ? "active review" : "review"} type="button" title="Stage for review" onClick={() => stageDecision(selectedSegment.id, "needs_review")} disabled={busy}><RefreshCw size={14} /></button>
                  <button className={(stagedDecisions[selectedSegment.id] ?? selectedSegment.status) === "rejected" ? "active reject" : "reject"} type="button" title="Stage rejection" onClick={() => stageDecision(selectedSegment.id, "rejected")} disabled={busy}><X size={15} /></button>
                </div>
                <div className="voice-segment-reasons"><p>{selectedSegment.reasons[0]}</p>{selectedSegment.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}</div>
              </>
            ) : null}
          </section>
        </div>
      )}
      {project && compilation?.export_path ? <RunPodBundleConsole engine={engine} sourceExportPath={compilation.export_path} modality="voice" triggerToken={project.intent.trigger_token} fingerprint={`voice-${project.id}`} trainingTargetProfileId={compilation.export_target !== "av_lora" ? "runpod_fish_speech_s2_voice_lora" : undefined} onArtifactsRegistered={() => setArtifactRevision((value) => value + 1)} /> : null}
      {!guided && project ? <VoiceArtifactEvaluator engine={engine} projectId={project.id} refreshToken={artifactRevision} /> : null}
      <p aria-live="polite" className="status-line">{status}</p>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function formatDuration(segment: VoiceDatasetSegment) { return `${(segment.end_seconds - segment.start_seconds).toFixed(1)}s`; }
function formatTime(value: number) { const minutes = Math.floor(value / 60); return `${minutes}:${Math.floor(value % 60).toString().padStart(2, "0")}`; }
function formatPercent(value?: number | null) { return value == null ? "--" : `${Math.round(value * 100)}%`; }
function formatDb(value?: number | null) { return value == null ? "--" : `${value.toFixed(1)} dB`; }
function segmentFilterLabel(value: SegmentFilter) { return value === "all" ? "All" : value === "needs_review" ? "?" : value === "approved" ? "Yes" : "No"; }
function decisionGlyph(value: VoiceSegmentStatus) { return value === "approved" ? "Y" : value === "rejected" ? "N" : "?"; }
function recommendationStatus(segment: VoiceDatasetSegment): VoiceSegmentStatus { return segment.recommendation === "keep" ? "approved" : segment.recommendation === "reject" ? "rejected" : "needs_review"; }
function exportTargetLabel(value: VoiceExportTarget) { return value === "voice_cloning" ? "Voice cloning" : value === "av_lora" ? "AV-LoRA reference" : "Combined voice and AV-LoRA"; }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : String(error); }
function stripShellQuotes(value: string) { const trimmed = value.trim(); return trimmed.length >= 2 && trimmed[0] === trimmed.at(-1) && ["'", '"'].includes(trimmed[0]) ? trimmed.slice(1, -1).trim() : trimmed; }
function isNewer(candidate: string, reference: string) { return Date.parse(candidate) > Date.parse(reference); }

function preferredVoiceSources(items: MediaItem[], acceptedIds: Set<string>): MediaItem[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  return [...acceptedIds].map((sourceId) => {
    const clean = items.find((item) => item.media_type === "audio" && item.metadata_json?.derivative_type === "audio_clean" && item.metadata_json?.source_media_item_id === sourceId);
    return clean ?? byId.get(sourceId);
  }).filter((item): item is MediaItem => item !== undefined && item.media_type === "audio");
}
