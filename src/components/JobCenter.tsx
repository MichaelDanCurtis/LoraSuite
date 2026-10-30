import { Activity, Ban, Check, CircleAlert, RefreshCw, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppDialog } from "./AppDialog";

import type { EngineClient } from "../lib/api";
import type {
  CaptionGenerationJob,
  IngressJob,
  ProcessingJob,
  RunPodBundleUploadJob,
  SocialAcquisitionJob,
  TrainingRun,
} from "../lib/types";

type JobCenterEngine = Pick<EngineClient,
  | "listIngressJobs"
  | "listProcessingJobs"
  | "listCaptionJobs"
  | "listTrainingRuns"
  | "listRunPodBundleUploadJobs"
  | "listSocialAcquisitionJobs"
  | "cancelSocialAcquisitionJob"
  | "resumeSocialAcquisitionJob"
  | "cancelCaptionJob"
  | "refreshTrainingRun"
  | "resumeTrainingRun"
  | "cancelTrainingRun"
  | "resumeRunPodBundleUploadJob"
>;

type JobKind = "Retrieval" | "Import" | "Prepare" | "Caption" | "Training" | "Upload";
type JobRecord = {
  id: string;
  kind: JobKind;
  status: string;
  message: string;
  progress?: string;
  createdAt: string;
  raw: SocialAcquisitionJob | IngressJob | ProcessingJob | CaptionGenerationJob | TrainingRun | RunPodBundleUploadJob;
};

const activeStatuses = new Set(["queued", "running", "cooldown", "uploading", "dataset_ready", "in_queue", "downloading"]);
const failedStatuses = new Set(["failed", "canceled", "stopped", "interrupted"]);

export function JobCenter({ engine }: { engine: JobCenterEngine }) {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [status, setStatus] = useState("");
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setStatus("Refreshing jobs...");
    const requests = await Promise.allSettled([
      engine.listSocialAcquisitionJobs?.() ?? Promise.resolve([]),
      engine.listIngressJobs(),
      engine.listProcessingJobs(),
      engine.listCaptionJobs(),
      engine.listTrainingRuns(),
      engine.listRunPodBundleUploadJobs(),
    ]);
    const values = requests.map((request) => request.status === "fulfilled" && Array.isArray(request.value) ? request.value : []);
    setJobs(normalizeJobs(
      values[0] as SocialAcquisitionJob[],
      values[1] as IngressJob[],
      values[2] as ProcessingJob[],
      values[3] as CaptionGenerationJob[],
      values[4] as TrainingRun[],
      values[5] as RunPodBundleUploadJob[],
    ));
    const failures = requests.filter((request) => request.status === "rejected").length;
    setStatus(failures ? `${failures} job source${failures === 1 ? " is" : "s are"} temporarily unavailable.` : "");
  }, [engine]);

  useEffect(() => {
    if (!open) return undefined;
    void load(true);
    const timer = window.setInterval(() => void load(true), 10_000);
    return () => window.clearInterval(timer);
  }, [load, open]);

  const activeCount = useMemo(() => jobs.filter((job) => activeStatuses.has(job.status)).length, [jobs]);

  async function act(job: JobRecord, action: "cancel" | "retry" | "refresh") {
    setBusyId(job.id);
    setStatus("");
    try {
      if (job.kind === "Retrieval") {
        if (action === "cancel") await engine.cancelSocialAcquisitionJob?.(job.id);
        else await engine.resumeSocialAcquisitionJob?.(job.id);
      } else if (job.kind === "Caption") {
        await engine.cancelCaptionJob(job.id);
      } else if (job.kind === "Training") {
        if (action === "cancel") await engine.cancelTrainingRun(job.id);
        else if (action === "retry") await engine.resumeTrainingRun(job.id);
        else await engine.refreshTrainingRun(job.id);
      } else if (job.kind === "Upload" && action === "retry") {
        await engine.resumeRunPodBundleUploadJob(job.id);
      }
      await load(true);
    } catch (error) {
      setStatus(`Job action failed: ${errorMessage(error)}`);
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="job-center-control">
      <button type="button" title="Open Job Center" aria-label="Job Center" onClick={() => setOpen(true)}>
        <Activity size={16} aria-hidden="true" /><span>Jobs</span>{activeCount ? <i>{activeCount}</i> : null}
      </button>
      {open ? (
        <AppDialog className="job-center-panel" label="Job Center" onClose={() => setOpen(false)}>
            <header>
              <div><Activity size={19} /><span><strong>Job Center</strong><small>Persistent retrieval, preparation, captioning, and provider work</small></span></div>
              <button type="button" title="Refresh jobs" onClick={() => void load()}><RefreshCw size={16} /></button>
              <button type="button" title="Close Job Center" onClick={() => setOpen(false)}><X size={17} /></button>
            </header>
            <div className="job-center-summary"><span><strong>{activeCount}</strong> active</span><span><strong>{jobs.filter((job) => failedStatuses.has(job.status)).length}</strong> need attention</span><span><strong>{jobs.filter((job) => job.status === "complete" || job.status === "completed").length}</strong> complete</span></div>
            <div className="job-center-list">
              {jobs.slice(0, 40).map((job) => (
                <article className={job.status} key={`${job.kind}:${job.id}`}>
                  <span className="job-center-state">{job.status === "complete" || job.status === "completed" ? <Check size={14} /> : failedStatuses.has(job.status) ? <CircleAlert size={14} /> : <Activity size={14} />}</span>
                  <div><small>{job.kind}</small><strong>{job.message}</strong><span>{job.progress ?? job.status.replaceAll("_", " ")}</span><time>{formatTime(job.createdAt)}</time></div>
                  <div className="job-center-actions">
                    {canRefresh(job) ? <button type="button" title="Refresh job" disabled={busyId === job.id} onClick={() => void act(job, "refresh")}><RefreshCw size={13} /></button> : null}
                    {canRetry(job) ? <button type="button" disabled={busyId === job.id} onClick={() => void act(job, "retry")}><RotateCcw size={13} /> Retry</button> : null}
                    {canCancel(job) ? <button type="button" disabled={busyId === job.id} onClick={() => void act(job, "cancel")}><Ban size={13} /> Cancel</button> : null}
                  </div>
                </article>
              ))}
              {!jobs.length ? <p className="empty-state">No persistent jobs yet.</p> : null}
            </div>
            {status ? <p className="status-line" role="status">{status}</p> : null}
        </AppDialog>
      ) : null}
    </div>
  );
}

function normalizeJobs(social: SocialAcquisitionJob[], ingress: IngressJob[], processing: ProcessingJob[], captions: CaptionGenerationJob[], training: TrainingRun[], uploads: RunPodBundleUploadJob[]): JobRecord[] {
  return [
    ...social.map((job): JobRecord => ({ id: job.id, kind: "Retrieval", status: job.status, message: `${job.request.provider} · ${job.progress_message}`, createdAt: job.created_at, raw: job })),
    ...ingress.map((job): JobRecord => ({ id: job.id, kind: "Import", status: job.status, message: job.progress_message || `${job.source_kind} import`, progress: `${job.imported_count}/${job.selected_count} imported`, createdAt: job.created_at, raw: job })),
    ...processing.map((job): JobRecord => ({ id: job.id, kind: "Prepare", status: job.status, message: job.progress_message || job.job_type.replaceAll("_", " "), progress: `${job.derived_media_items.length} outputs`, createdAt: job.created_at, raw: job })),
    ...captions.map((job): JobRecord => ({ id: job.id, kind: "Caption", status: job.status, message: job.progress_message || `${job.provider_label} captions`, progress: `${job.completed_count}/${job.total_count} · ${job.failed_count} failed`, createdAt: job.created_at, raw: job })),
    ...training.map((job): JobRecord => ({ id: job.id, kind: "Training", status: job.status, message: job.progress_message || `${job.provider} training`, progress: `${Math.round(job.progress_percent)}% · ${job.artifacts.length} artifacts`, createdAt: job.created_at, raw: job })),
    ...uploads.map((job): JobRecord => ({ id: job.id, kind: "Upload", status: job.status, message: job.current_file || "RunPod bundle upload", progress: `${job.files_uploaded}/${job.files_total} files`, createdAt: job.created_at, raw: job })),
  ].sort((left, right) => Number(activeStatuses.has(right.status)) - Number(activeStatuses.has(left.status)) || Date.parse(right.createdAt) - Date.parse(left.createdAt));
}

function canCancel(job: JobRecord): boolean {
  return activeStatuses.has(job.status) && ["Retrieval", "Caption", "Training"].includes(job.kind);
}

function canRetry(job: JobRecord): boolean {
  return failedStatuses.has(job.status) && ["Retrieval", "Training", "Upload"].includes(job.kind);
}

function canRefresh(job: JobRecord): boolean {
  return job.kind === "Training" && activeStatuses.has(job.status);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
