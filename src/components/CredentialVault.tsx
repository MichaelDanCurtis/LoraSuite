import {
  Check,
  KeyRound,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  credentialDefinitions,
  credentialStorageLabel,
  deleteCredential,
  getCredentialStatus,
  setCredential,
  subscribeToCredentialVaultRequests,
  type CredentialId,
} from "../lib/credentials";

export function CredentialVault() {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Partial<Record<CredentialId, string>>>({});
  const [stored, setStored] = useState<Partial<Record<CredentialId, boolean>>>({});
  const [busyId, setBusyId] = useState<CredentialId | null>(null);
  const [status, setStatus] = useState("Secrets are never written to the LoraSuite vault.");
  const storageLabel = useMemo(() => credentialStorageLabel(), [open]);

  useEffect(() => subscribeToCredentialVaultRequests(() => setOpen(true)), []);

  useEffect(() => {
    if (!open) return;
    let disposed = false;
    void Promise.all(credentialDefinitions.map((definition) => getCredentialStatus(definition.id)))
      .then((results) => {
        if (disposed) return;
        setStored(Object.fromEntries(results.map((result) => [result.id, result.stored])));
      })
      .catch((error) => {
        if (!disposed) setStatus(`Credential store unavailable: ${errorMessage(error)}`);
      });
    return () => {
      disposed = true;
    };
  }, [open]);

  async function save(id: CredentialId) {
    const value = values[id]?.trim() ?? "";
    if (!value || busyId) return;
    setBusyId(id);
    try {
      const result = await setCredential(id, value);
      setStored((current) => ({ ...current, [id]: result.stored }));
      setValues((current) => ({ ...current, [id]: "" }));
      setStatus(`Saved to ${storageLabel.toLowerCase()}.`);
    } catch (error) {
      setStatus(`Credential save failed: ${errorMessage(error)}`);
    } finally {
      setBusyId(null);
    }
  }

  async function forget(id: CredentialId) {
    if (busyId) return;
    setBusyId(id);
    try {
      const result = await deleteCredential(id);
      setStored((current) => ({ ...current, [id]: result.stored }));
      setValues((current) => ({ ...current, [id]: "" }));
      setStatus("Credential removed.");
    } catch (error) {
      setStatus(`Credential removal failed: ${errorMessage(error)}`);
    } finally {
      setBusyId(null);
    }
  }

  function close() {
    setValues({});
    setOpen(false);
  }

  return (
    <div className="credential-vault">
      <button
        type="button"
        className="credential-vault-button"
        onClick={() => setOpen((value) => !value)}
        title="Manage provider credentials"
      >
        <KeyRound size={15} aria-hidden="true" />
        <span>Credentials</span>
      </button>
      {open ? (
        <>
          <button
            type="button"
            className="credential-vault-backdrop"
            onClick={close}
            aria-label="Close provider credentials"
          />
          <section className="credential-vault-panel" aria-label="Provider credentials">
            <header>
              <div>
                <ShieldCheck size={18} aria-hidden="true" />
                <span><strong>Provider Credentials</strong><small>{storageLabel}</small></span>
              </div>
              <button type="button" onClick={close} title="Close credentials"><X size={15} /></button>
            </header>
            <p>
              Saved secrets are retrieved only when a provider action needs them.
              Existing values are never displayed.
            </p>
            <div className="credential-vault-list">
              {credentialDefinitions.map((definition) => (
                <article key={definition.id} className={stored[definition.id] ? "stored" : ""}>
                  <span className="credential-vault-provider">
                    <strong>{definition.provider}</strong>
                    <small>{definition.label} · {definition.environmentVariable}</small>
                  </span>
                  <label>
                    <span className="sr-only">{definition.provider} {definition.label}</span>
                    <input
                      aria-label={`${definition.provider} ${definition.label}`}
                      type="password"
                      autoComplete="off"
                      value={values[definition.id] ?? ""}
                      onChange={(event) => setValues((current) => ({
                        ...current,
                        [definition.id]: event.target.value,
                      }))}
                      placeholder={stored[definition.id] ? "Stored securely" : "Enter secret"}
                      disabled={busyId === definition.id}
                    />
                  </label>
                  <span className="credential-vault-state">
                    {stored[definition.id] ? <><Check size={12} /> Stored</> : "Not stored"}
                  </span>
                  <button
                    type="button"
                    onClick={() => void save(definition.id)}
                    disabled={!values[definition.id]?.trim() || Boolean(busyId)}
                    title={`Save ${definition.provider} ${definition.label}`}
                  >
                    <Save size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => void forget(definition.id)}
                    disabled={!stored[definition.id] || Boolean(busyId)}
                    title={`Forget ${definition.provider} ${definition.label}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </article>
              ))}
            </div>
            <p className="status-line" aria-live="polite">{status}</p>
          </section>
        </>
      ) : null}
    </div>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
