import { isTauri } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import {
  ArchiveRestore,
  CheckCircle2,
  FolderOpen,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { EngineClient } from "../lib/api";
import type { RecoveredDatasetExport } from "../lib/types";

type RecoveryEngine = Pick<
  EngineClient,
  | "listRecoveredDatasetExports"
  | "registerRecoveredDatasetExport"
  | "verifyRecoveredDatasetExport"
>;

interface RecoveredDatasetConsoleProps {
  engine: RecoveryEngine;
  activeRecordId?: string | null;
  onUseForTraining(record: RecoveredDatasetExport): void;
}

export function RecoveredDatasetConsole({
  engine,
  activeRecordId,
  onUseForTraining,
}: RecoveredDatasetConsoleProps) {
  const [records, setRecords] = useState<RecoveredDatasetExport[]>([]);
  const [exportPath, setExportPath] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [status, setStatus] = useState("Register an existing LoraSuite export without reconstructing its review history.");
  const picker = useMemo(() => recoveryDirectoryPicker(), []);
  const supported = Boolean(
    engine.listRecoveredDatasetExports
    && engine.registerRecoveredDatasetExport
    && engine.verifyRecoveredDatasetExport,
  );

  useEffect(() => {
    if (!engine.listRecoveredDatasetExports) return;
    let disposed = false;
    engine.listRecoveredDatasetExports()
      .then((payload) => {
        if (disposed) return;
        const available = Array.isArray(payload) ? payload : [];
        setRecords(available);
        if (available.length) setStatus(`${available.length} immutable export${available.length === 1 ? "" : "s"} available.`);
      })
      .catch((error) => {
        if (!disposed) setStatus(`Recovery catalog unavailable: ${errorMessage(error)}`);
      });
    return () => {
      disposed = true;
    };
  }, [engine]);

  async function chooseFolder() {
    if (!picker) return;
    try {
      const selected = await picker();
      if (selected) setExportPath(selected);
    } catch (error) {
      if (!isAbortError(error)) setStatus(`Folder picker error: ${errorMessage(error)}`);
    }
  }

  async function registerExport() {
    const path = normalizePath(exportPath);
    if (!engine.registerRecoveredDatasetExport || !path || busyId) return;
    setBusyId("register");
    setStatus("Inspecting manifest, pair integrity, checksums, and provenance...");
    try {
      const record = await engine.registerRecoveredDatasetExport(path);
      setRecords((current) => [record, ...current.filter((item) => item.id !== record.id)]);
      setExportPath(record.export_path);
      setStatus(
        record.ready
          ? `Verified ${record.verified_file_count} of ${record.file_count} training entries.`
          : "The export was cataloged but is not training-ready.",
      );
    } catch (error) {
      setStatus(`Recovery failed: ${errorMessage(error)}`);
    } finally {
      setBusyId(null);
    }
  }

  async function verifyExport(record: RecoveredDatasetExport) {
    if (!engine.verifyRecoveredDatasetExport || busyId) return;
    setBusyId(record.id);
    setStatus(`Rechecking ${record.export_path}...`);
    try {
      const updated = await engine.verifyRecoveredDatasetExport(record.id);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
      setStatus(
        updated.ready
          ? `Integrity verified: ${updated.verified_file_count} of ${updated.file_count} entries.`
          : "Verification found blocking export errors.",
      );
    } catch (error) {
      setStatus(`Verification failed: ${errorMessage(error)}`);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className={`recovered-dataset-drawer ${expanded ? "expanded" : ""}`} aria-label="Recovered dataset exports">
      <button
        className="recovered-dataset-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <ArchiveRestore size={16} aria-hidden="true" />
        <span>
          <strong>Recovered Exports</strong>
          <small>{records.length ? `${records.length} verified package${records.length === 1 ? "" : "s"}` : "Resume from an existing dataset package"}</small>
        </span>
        <i>{expanded ? "Close" : "Open"}</i>
      </button>
      {expanded ? (
        <div className="recovered-dataset-console">
          <div className="recovery-import-row">
            <label>
              Export folder
              <input
                value={exportPath}
                onChange={(event) => setExportPath(event.target.value)}
                onBlur={() => setExportPath(normalizePath(exportPath))}
                placeholder="/absolute/path/to/export"
                disabled={!supported || busyId !== null}
              />
            </label>
            {picker ? (
              <button type="button" onClick={chooseFolder} disabled={!supported || busyId !== null} title="Choose export folder">
                <FolderOpen size={15} />
              </button>
            ) : null}
            <button className="primary-action" type="button" onClick={registerExport} disabled={!supported || !exportPath.trim() || busyId !== null}>
              <ArchiveRestore size={15} /> Recover Export
            </button>
          </div>
          <p className="recovery-scope">
            Recovery is read-only. It preserves the manifest, fingerprint, captions, and training target; discarded media and original review decisions are not recreated.
          </p>
          {records.length ? (
            <div className="recovery-record-list">
              {records.map((record) => {
                const active = record.id === activeRecordId;
                const valid = record.ready && record.source_available;
                return (
                  <article key={record.id} className={`${record.integrity_status} ${active ? "active" : ""}`}>
                    <div className="recovery-record-state">
                      {valid ? <CheckCircle2 size={17} /> : <ShieldAlert size={17} />}
                      <span>
                        <strong>{record.model_card?.display_name || record.training_target.label}</strong>
                        <small>{record.modality.replace("_", " ")} · v{record.dataset_version} · {record.verified_file_count}/{record.file_count} verified</small>
                      </span>
                    </div>
                    <dl>
                      <div><dt>Trigger</dt><dd>{record.trigger_token || "unknown"}</dd></div>
                      <div><dt>Fingerprint</dt><dd>{record.fingerprint.slice(0, 12)}</dd></div>
                      <div><dt>Integrity</dt><dd>{record.integrity_status}</dd></div>
                    </dl>
                    <p title={record.export_path}>{record.export_path}</p>
                    {record.errors.length ? <small className="recovery-record-error">{record.errors.join(" ")}</small> : null}
                    {record.warnings.length ? <small className="recovery-record-warning">{record.warnings.join(" ")}</small> : null}
                    <div className="recovery-record-actions">
                      <button type="button" onClick={() => verifyExport(record)} disabled={busyId !== null}>
                        <RefreshCw size={14} className={busyId === record.id ? "spin" : ""} /> Verify
                      </button>
                      <button className="primary-action" type="button" onClick={() => onUseForTraining(record)} disabled={!valid || busyId !== null}>
                        <CheckCircle2 size={14} /> {active ? "Selected for Training" : "Use for Training"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="recovery-empty">No recovered exports are registered.</p>
          )}
          <p className="status-line" aria-live="polite">{status}</p>
        </div>
      ) : null}
    </section>
  );
}

function recoveryDirectoryPicker(): (() => Promise<string | null>) | null {
  const host = typeof window !== "undefined"
    ? (window as Window & { loraSuiteHost?: { pickDestinationPath?: () => Promise<string | string[] | null> } }).loraSuiteHost
    : undefined;
  if (host?.pickDestinationPath) {
    return async () => {
      const selection = await host.pickDestinationPath?.();
      return Array.isArray(selection) ? selection[0] ?? null : selection ?? null;
    };
  }
  try {
    if (!isTauri()) return null;
  } catch {
    return null;
  }
  return async () => {
    const selection = await open({
      directory: true,
      multiple: false,
      title: "Choose a LoraSuite dataset export",
    });
    return Array.isArray(selection) ? selection[0] ?? null : selection;
  };
}

function normalizePath(value: string): string {
  const trimmed = value.trim();
  if (trimmed.length >= 2 && trimmed[0] === trimmed.at(-1) && (trimmed[0] === "'" || trimmed[0] === '"')) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
