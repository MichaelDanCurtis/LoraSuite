import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Library, X } from 'lucide-react';
import type { EngineClient } from '../lib/api';
import type { LibraryEntry, LibraryStatus } from '../lib/library';
import { LibraryCatalog } from './LibraryCatalog';
import { TrainingLibraryExports } from './TrainingLibraryExports';
import { handleDesktopLink } from '../lib/desktopLinks';

type Client = Pick<EngineClient, 'libraryStatus' | 'configureLibrary' | 'createCompanionCode' | 'revokeCompanion' | 'importLibraryFile' | 'archiveLibraryEntry' | 'listLibraryModels' | 'listModelArtifacts' | 'exportArtifactToLibrary'> & Partial<Pick<EngineClient, 'assetUrl'>>;

export function ModelLibrary({ engine }: { engine: Client }) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<LibraryStatus | null>(null);
  const [port, setPort] = useState(8188);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [code, setCode] = useState('');
  const [selected, setSelected] = useState<LibraryEntry | null>(null);
  const [path, setPath] = useState('');
  const [modelType, setModelType] = useState('loras');
  const [showArchived, setShowArchived] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const visibleItems = snapshot?.items.filter(item => Boolean(item.archived) === showArchived) ?? [];

  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    let stopped = false;
    setBusy(true);
    engine.libraryStatus().then(data => {
      if (!stopped) { setSnapshot(data); setPort(data.port); }
    }).catch(error => { if (!stopped) setMessage(String(error)); })
      .finally(() => { if (!stopped) setBusy(false); });
    return () => { stopped = true; };
  }, [engine, open]);

  // Codes disappear when their advertised lifetime ends, not just on close.
  useEffect(() => {
    if (!code) return;
    const timer = window.setTimeout(() => setCode(''), 120000);
    return () => window.clearTimeout(timer);
  }, [code]);

  function close() { dialog.current?.close(); setOpen(false); setCode(''); opener.current?.focus(); }
  async function action(task: () => Promise<void>) {
    setBusy(true); setMessage('');
    try { await task(); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  return <>
    <button ref={opener} type="button" onClick={() => setOpen(true)} title="Model Library and browser companion"><Library size={16} aria-hidden="true" /> Model Library</button>
    {open ? createPortal(<dialog ref={dialog} className="model-library-dialog" aria-labelledby="model-library-title" onCancel={event => { event.preventDefault(); close(); }}>
      <header><h2 id="model-library-title">Model Library</h2><button type="button" aria-label="Close Model Library" onClick={close}><X size={18} /></button></header>
      <p>Connect to LoRA Manager running in ComfyUI or as a separate application. LoraSuite prepares datasets, trains LoRAs, and sends finished adapters to your library.</p>
      <p role="status" aria-live="polite">{busy ? 'Working…' : message || (snapshot?.ready ? 'LoRA Manager connected.' : snapshot?.issue || 'Checking connection…')}</p>
      {snapshot?.ready ? <LibraryCatalog engine={engine} key={snapshot.port} managerUrl={snapshot.url} /> : null}
      <details open={snapshot && !snapshot.ready ? true : undefined} className="library-connection-settings"><summary>Connection settings</summary>
      <div className="model-library-controls">
        <label>LoRA Manager port<input type="number" min={1024} max={65535} value={port} onChange={event => setPort(Number(event.target.value))} /></label>
        <button disabled={busy} onClick={() => void action(async () => { await engine.configureLibrary(port); setSnapshot(await engine.libraryStatus()); })}>Save and check</button>
        <button disabled={busy} onClick={() => void action(async () => { setSnapshot(await engine.libraryStatus()); })}>Refresh inbox</button>
        {snapshot?.ready ? <a href={snapshot.url} target="_blank" rel="noopener noreferrer" onClick={event => handleDesktopLink(event, setMessage)}>Open LoRA Manager ↗</a> : null}
      </div>
      <p>Start LoRA Manager in its own application, then save its port here. LoraSuite only connects to it.</p>
      <details><summary>Training export folder</summary><p>To receive LoraSuite adapters, add <code>{snapshot?.model_root}/loras</code> to LoRA Manager’s LoRA folders. Browsing your existing library does not require this folder.</p>{snapshot?.export_issue ? <p>{snapshot.export_issue}</p> : null}<p>Your library folders and settings are managed in LoRA Manager.</p></details>
      </details>
      {snapshot ? <TrainingLibraryExports engine={engine} initialReceipts={snapshot.training_exports} /> : null}
      <section aria-label="Browser extension pairing"><h3>Optional browser capture for projects</h3>
        <p>Load <code>extensions/lorasuite-companion</code> unpacked in Chrome. Civitai downloads and recipes connect directly to LM without pairing. Pair here only to send references into LoraSuite projects. Pairing replaces the previous project connection and expires after 30 days.</p>
        <button disabled={busy} onClick={() => void action(async () => { const result = await engine.createCompanionCode(); setCode(result.code); setMessage('Code ready. Paste it into the extension within two minutes.'); })}>Pair Chrome extension</button>
        <button disabled={busy} onClick={() => void action(async () => { await engine.revokeCompanion(); setCode(''); setMessage('Extension access revoked.'); })}>Revoke extension access</button>
        {code ? <label>One-time pairing code<input readOnly value={code} onFocus={event => event.target.select()} /></label> : null}
      </section>
      <h3>Review inbox</h3><p>This inbox holds references awaiting review. Import downloaded media into a project here. On Civitai, the companion can download models through LoRA Manager or import an image directly as an LM recipe.</p>
      <label><input type="checkbox" checked={showArchived} onChange={event => { setShowArchived(event.target.checked); setSelected(null); }} />Show archived references</label>
      <p>Archiving hides a reference only. Imported files and project media are preserved; restore it at any time.</p>
      <div className="model-library-inbox">{visibleItems.length ? visibleItems.map(item => <article key={item.id}>
        <strong>{item.title || item.kind}</strong><p>{item.kind} · {item.requested_output} · {item.status}</p>
        <small>Project: {item.project_id}</small><a href={item.page_url} target="_blank" rel="noopener noreferrer" onClick={event => handleDesktopLink(event, setMessage)}>Open source ↗</a>
        <button disabled={busy} onClick={() => void action(async () => { await engine.archiveLibraryEntry(item.id, !item.archived); setSelected(null); setSnapshot(await engine.libraryStatus()); })}>{item.archived ? 'Restore reference' : 'Archive reference'}</button>
        {!item.archived && item.status === 'pending' && ['image', 'video', 'audio', 'model'].includes(item.kind) ? <button disabled={busy} onClick={() => { setSelected(item); setPath(''); }}>Import downloaded file</button> : null}
        {item.result?.path ? <><code>{item.result.path}</code><p>Compatibility unverified. {item.result.h3_fused_layout ? 'Fused H3 tensor layout recognized; base-variant and render checks still required.' : 'Use the appropriate model engine; do not assume H3 compatibility.'}</p><small>SHA-256: {item.result.sha256}</small></> : null}
        {item.result?.media_item_ids ? <p>Added to this project’s pending curation handoff. Identity and voice are not confirmed.</p> : null}
      </article>) : <p>{showArchived ? 'No archived references.' : 'No active references. In Chrome, open the extension, choose a project, scan the page, then send selected items.'}</p>}</div>
      {selected ? <section aria-label="Import downloaded file"><h3>Import: {selected.title || selected.kind}</h3>
        <label>Downloaded file’s absolute path<input value={path} onChange={event => setPath(event.target.value)} placeholder="/Users/you/Downloads/file.safetensors" /></label>
        {selected.kind === 'model' ? <label>Library category<select value={modelType} onChange={event => setModelType(event.target.value)}><option value="loras">LoRA adapter</option><option value="checkpoints">Checkpoint</option><option value="embeddings">Embedding</option></select></label> : null}
        <button disabled={busy || !path.trim()} onClick={() => void action(async () => { await engine.importLibraryFile(selected.id, path.trim(), modelType); setSnapshot(await engine.libraryStatus()); setSelected(null); setMessage('Imported. No training or generation was started.'); })}>Confirm local import</button>
        <button disabled={busy} onClick={() => setSelected(null)}>Cancel</button>
      </section> : null}
    </dialog>, document.body) : null}
  </>;
}
