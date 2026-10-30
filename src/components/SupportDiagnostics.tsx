import {
  Download,
  LifeBuoy,
  PackageCheck,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import type { EngineClient } from "../lib/api";
import type {
  ComfyInstallation,
  DiagnosticBundleRecord,
  StateMigrationReport,
} from "../lib/types";

type DiagnosticsEngine = Pick<
  EngineClient,
  | "inspectStateMigrations"
  | "applyStateMigrations"
  | "listDiagnosticBundles"
  | "createDiagnosticBundle"
  | "diagnosticBundleDownloadUrl"
  | "listComfyInstallations"
>;

interface SupportDiagnosticsProps {
  engine: DiagnosticsEngine;
  activeProjectId?: string;
}

export function SupportDiagnostics({ engine, activeProjectId = "" }: SupportDiagnosticsProps) {
  const [open, setOpen] = useState(false);
  const [stateReport, setStateReport] = useState<StateMigrationReport | null>(null);
  const [bundles, setBundles] = useState<DiagnosticBundleRecord[]>([]);
  const [installations, setInstallations] = useState<ComfyInstallation[]>([]);
  const [includeComfy, setIncludeComfy] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Ready.");
  const supported = Boolean(
    engine.inspectStateMigrations
    && engine.applyStateMigrations
    && engine.listDiagnosticBundles
    && engine.createDiagnosticBundle
    && engine.diagnosticBundleDownloadUrl,
  );

  useEffect(() => {
    if (!open || !supported) return;
    let disposed = false;
    setBusy(true);
    Promise.all([
      engine.inspectStateMigrations?.(),
      engine.listDiagnosticBundles?.(),
      engine.listComfyInstallations(),
    ])
      .then(([migrationPayload, bundlePayload, installationPayload]) => {
        if (disposed) return;
        setStateReport(migrationPayload ?? null);
        setBundles(Array.isArray(bundlePayload) ? bundlePayload : []);
        setInstallations(Array.isArray(installationPayload) ? installationPayload : []);
        setStatus("Diagnostics are ready.");
      })
      .catch((error) => {
        if (!disposed) setStatus(`Diagnostics unavailable: ${errorMessage(error)}`);
      })
      .finally(() => {
        if (!disposed) setBusy(false);
      });
    return () => {
      disposed = true;
    };
  }, [engine, open, supported]);

  async function applyMigrations() {
    if (!engine.applyStateMigrations || busy) return;
    setBusy(true);
    setStatus("Backing up and migrating recognized state files...");
    try {
      const report = await engine.applyStateMigrations();
      setStateReport(report);
      setStatus(
        report.ready
          ? `State is current. ${report.updated_count} file${report.updated_count === 1 ? "" : "s"} updated.`
          : "State migration needs manual review.",
      );
    } catch (error) {
      setStatus(`Migration failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function createBundle() {
    if (!engine.createDiagnosticBundle || busy) return;
    setBusy(true);
    setStatus("Building a privacy-safe support package...");
    try {
      const comfyRoot = includeComfy ? installations[0]?.root : undefined;
      const record = await engine.createDiagnosticBundle({
        comfy_root: comfyRoot,
        project_id: activeProjectId || undefined,
      });
      setBundles((current) => [record, ...current.filter((item) => item.id !== record.id)]);
      setStatus(
        record.partner_qualification_included
          ? "Support package created with this project's qualification gates."
          : "Support package created. It contains no media or credentials.",
      );
    } catch (error) {
      setStatus(`Support package failed: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  const stateBlocked = Boolean(
    stateReport && (stateReport.invalid_count > 0 || stateReport.future_count > 0),
  );
  return (
    <div className="support-diagnostics">
      <button type="button" className="support-diagnostics-button" onClick={() => setOpen((value) => !value)} title="Support and diagnostics">
        <LifeBuoy size={15} aria-hidden="true" />
        <span>Support</span>
      </button>
      {open ? (
        <>
          <button
            type="button"
            className="support-diagnostics-backdrop"
            onClick={() => setOpen(false)}
            aria-label="Close support and diagnostics"
          />
          <section className="support-diagnostics-panel" aria-label="Support and diagnostics">
            <header>
              <div>
                <LifeBuoy size={17} aria-hidden="true" />
                <span><strong>Support & Diagnostics</strong><small>Private by construction</small></span>
              </div>
              <button type="button" onClick={() => setOpen(false)} title="Close support diagnostics"><X size={15} /></button>
            </header>
            {!supported ? (
              <p className="support-diagnostics-warning"><ShieldAlert size={14} /> Update the local engine to use diagnostics.</p>
            ) : (
              <>
                <section className={`support-state-status ${stateReport?.ready ? "ready" : stateBlocked ? "blocked" : "pending"}`}>
                  {stateReport?.ready ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}
                  <span>
                    <strong>{stateReport?.ready ? "State schema current" : stateBlocked ? "State needs manual review" : "State migration available"}</strong>
                    <small>
                      {stateReport
                        ? `${stateReport.pending_count} pending · ${stateReport.invalid_count} invalid · ${stateReport.future_count} future`
                        : "Checking persistent state..."}
                    </small>
                  </span>
                  <button type="button" onClick={applyMigrations} disabled={busy || !stateReport?.pending_count || stateBlocked}>
                    <RefreshCw size={14} className={busy ? "spin" : ""} /> Apply
                  </button>
                </section>
                <section className="support-bundle-builder">
                  <div>
                    <PackageCheck size={18} />
                    <span><strong>Create support package</strong><small>Runtime facts and partner contracts only</small></span>
                  </div>
                  {installations.length ? (
                    <label>
                      <input type="checkbox" checked={includeComfy} onChange={(event) => setIncludeComfy(event.target.checked)} />
                      Include ComfyUI runtime status
                    </label>
                  ) : null}
                  <button className="primary-action" type="button" onClick={createBundle} disabled={busy}>
                    <PackageCheck size={14} /> Create Bundle
                  </button>
                </section>
                <p className="support-privacy-note">
                  Excludes credentials, media, captions, transcripts, prompts, source URLs, handles, and absolute paths.
                </p>
                {bundles.length ? (
                  <div className="support-bundle-list">
                    {bundles.slice(0, 4).map((bundle) => (
                      <article key={bundle.id}>
                        <span>
                          <strong>{new Date(bundle.created_at).toLocaleString()}</strong>
                          <small>{formatBytes(bundle.size_bytes)} · SHA {bundle.archive_sha256.slice(0, 12)}</small>
                        </span>
                        <a href={engine.diagnosticBundleDownloadUrl?.(bundle.id)} download>
                          <Download size={14} /> Download
                        </a>
                      </article>
                    ))}
                  </div>
                ) : null}
              </>
            )}
            <p className="status-line" aria-live="polite">{status}</p>
          </section>
        </>
      ) : null}
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
