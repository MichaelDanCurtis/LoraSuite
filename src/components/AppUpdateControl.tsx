import { invoke, isTauri } from "@tauri-apps/api/core";
import { relaunch } from "@tauri-apps/plugin-process";
import {
  CheckCircle2,
  Download,
  History,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

type UpdateChannel = "stable" | "rollback";

interface DesktopUpdateStatus {
  configured: boolean;
  channel: UpdateChannel;
  current_version: string;
  available: boolean;
  version?: string | null;
  body?: string | null;
  date?: string | null;
  target?: string | null;
  download_url?: string | null;
  message: string;
}

interface UpdateJournal {
  channel: UpdateChannel;
  from_version: string;
  to_version: string;
  state: string;
  message: string;
  updated_at_unix: number;
}

export function AppUpdateControl() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<UpdateChannel | null>(null);
  const [stable, setStable] = useState<DesktopUpdateStatus | null>(null);
  const [rollback, setRollback] = useState<DesktopUpdateStatus | null>(null);
  const [journal, setJournal] = useState<UpdateJournal | null>(null);
  const [error, setError] = useState("");
  const desktop = desktopRuntimeAvailable();

  useEffect(() => {
    if (!open || !desktop || stable) return;
    void refreshChannel("stable");
    void invoke<UpdateJournal | null>("desktop_update_journal")
      .then(setJournal)
      .catch(() => undefined);
  }, [desktop, open, stable]);

  if (!desktop) return null;

  async function refreshChannel(channel: UpdateChannel) {
    setBusy(channel);
    setError("");
    try {
      const status = await invoke<DesktopUpdateStatus>("check_desktop_update", { channel });
      if (channel === "stable") setStable(status);
      else setRollback(status);
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setBusy(null);
    }
  }

  async function install(status: DesktopUpdateStatus) {
    if (!status.version) return;
    setBusy(status.channel);
    setError("");
    try {
      const result = await invoke<UpdateJournal>("install_desktop_update", {
        channel: status.channel,
        version: status.version,
      });
      setJournal(result);
      await relaunch();
    } catch (reason) {
      setError(readableError(reason));
      setBusy(null);
    }
  }

  const updateAvailable = Boolean(stable?.available);

  return (
    <div className="app-update-control">
      <button
        type="button"
        className={updateAvailable ? "app-update-button available" : "app-update-button"}
        aria-label="Application updates"
        title="Application updates"
        onClick={() => setOpen((value) => !value)}
      >
        <Download size={15} aria-hidden="true" />
        {updateAvailable ? <i aria-hidden="true" /> : null}
      </button>
      {open ? (
        <section className="app-update-panel" aria-label="Application updates">
          <header>
            <span><ShieldCheck size={17} aria-hidden="true" /><strong>Signed Updates</strong></span>
            <button type="button" onClick={() => setOpen(false)} title="Close application updates"><X size={14} /></button>
          </header>

          <UpdateChannelRow
            icon={<Download size={15} aria-hidden="true" />}
            title="Current release"
            status={stable}
            busy={busy === "stable"}
            actionLabel={stable?.available ? "Install & Restart" : "Check Now"}
            onAction={() => stable?.available ? install(stable) : refreshChannel("stable")}
          />

          <UpdateChannelRow
            icon={<History size={15} aria-hidden="true" />}
            title="Previous release"
            status={rollback}
            busy={busy === "rollback"}
            actionLabel={rollback?.available ? "Restore & Restart" : "Check Rollback"}
            onAction={() => rollback?.available ? install(rollback) : refreshChannel("rollback")}
          />

          {journal ? (
            <div className={`app-update-journal ${journal.state === "launch_verified" ? "verified" : ""}`}>
              {journal.state === "launch_verified" ? <CheckCircle2 size={14} aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}
              <span>
                <strong>{journal.from_version} to {journal.to_version}</strong>
                <small>{journal.message}</small>
              </span>
            </div>
          ) : null}
          {error ? <p className="app-update-error">{error}</p> : null}
          <small className="app-update-policy">Every installation is signature-verified. Rollback uses the separately signed previous-release manifest.</small>
        </section>
      ) : null}
    </div>
  );
}

function UpdateChannelRow({
  icon,
  title,
  status,
  busy,
  actionLabel,
  onAction,
}: {
  icon: ReactNode;
  title: string;
  status: DesktopUpdateStatus | null;
  busy: boolean;
  actionLabel: string;
  onAction(): void;
}) {
  const disabled = busy || status?.configured === false;
  return (
    <article className="app-update-channel">
      <span className="app-update-channel-icon">{busy ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : icon}</span>
      <span>
        <strong>{title}{status?.version ? ` ${status.version}` : ""}</strong>
        <small>{busy ? "Checking signed release metadata..." : status?.message ?? "Not checked"}</small>
      </span>
      <button type="button" onClick={onAction} disabled={disabled}>{actionLabel}</button>
    </article>
  );
}

function desktopRuntimeAvailable(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}

function readableError(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason || "Application update failed.");
}
