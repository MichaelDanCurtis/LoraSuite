import { useEffect, useState } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { open } from '@tauri-apps/plugin-dialog';
import type { EngineClient } from '../lib/api';
import type { ModelArtifactRecord } from '../lib/types';
import type { LibraryArtifactOptions, LibraryTrainingExport } from '../lib/library';

type Client = Pick<EngineClient, 'listModelArtifacts' | 'exportArtifactToLibrary'> & Partial<Pick<EngineClient, 'assetUrl'>>;
export function TrainingLibraryExports({ engine, initialReceipts = [] }: {
  engine: Client;
  initialReceipts?: LibraryTrainingExport[];
}) {
  const [artifacts, setArtifacts] = useState<ModelArtifactRecord[]>([]);
  const [receipts, setReceipts] = useState(initialReceipts);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('Loading registered training outputs…');
  useEffect(() => {
    let disposed = false;
    engine.listModelArtifacts().then(items => {
      if (!disposed) { setArtifacts(items); setMessage(''); }
    }).catch(error => { if (!disposed) setMessage(String(error)); })
      .finally(() => { if (!disposed) setBusy(false); });
    return () => { disposed = true; };
  }, [engine]);
  async function publish(artifact: ModelArtifactRecord, options: LibraryArtifactOptions) {
    setBusy(true); setMessage('Verifying the checkpoint and sending metadata and images to LoRA Manager…');
    try {
      const receipt = await engine.exportArtifactToLibrary(artifact.id, options);
      setReceipts(items => [...items.filter(item => item.artifact_id !== artifact.id), receipt]);
      setMessage(receipt.manager_synced ? `Available in LoRA Manager with ${receipt.gallery_imported_paths?.length ?? 0} example images.${receipt.metadata_preserved ? ' Existing metadata was preserved.' : ''}`
        : `Library copy saved. ${receipt.sync_issue || 'Start LoRA Manager, then send again to finish syncing.'}`);
      setSelected(null);
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  return <section aria-label="Training outputs to library" className="library-catalog">
    <h3>Training outputs → LoRA Manager</h3>
    <p>Choose a registered checkpoint, review its name, trigger words and images, then send it to your library. The source stays intact and training provenance travels with the copy.</p>
    {message ? <p role="status">{message}</p> : null}
    {!busy && !artifacts.length ? <p>No registered training outputs yet. Register a returned checkpoint in the training console first.</p> : null}
    <div className="library-catalog-items">{artifacts.map(artifact => {
      const receipt = receipts.find(item => item.artifact_id === artifact.id);
      return <article key={artifact.id}>
        <strong>{artifact.checkpoint_name}</strong><p>{artifact.base_model || artifact.model_family} · {artifact.modality}</p>
        <small>Project {artifact.project_id || 'unspecified'} · Run {artifact.training_run_id}</small>
        {receipt ? <><p>{receipt.manager_synced ? 'Available in LoRA Manager' : 'Library copy saved · Sync needs attention'} · Compatibility unverified</p><code>{receipt.path}</code></> : null}
        {selected === artifact.id ? <ExportReview key={artifact.id} artifact={artifact} receipt={receipt} busy={busy} assetUrl={engine.assetUrl}
          onCancel={() => setSelected(null)} onSend={options => void publish(artifact, options)} />
          : <button type="button" disabled={busy || !artifact.checkpoint_path.toLowerCase().endsWith('.safetensors')} onClick={() => setSelected(artifact.id)}>{receipt ? 'Review / sync library copy' : 'Send to LoRA Manager…'}</button>}
      </article>;
    })}</div>
  </section>;
}

function ExportReview({ artifact, receipt, busy, assetUrl, onCancel, onSend }: {
  artifact: ModelArtifactRecord; receipt?: LibraryTrainingExport; busy: boolean; assetUrl?: (path: string) => string;
  onCancel: () => void; onSend: (options: LibraryArtifactOptions) => void;
}) {
  const card = artifact.model_card;
  const [title, setTitle] = useState(card?.display_name || artifact.checkpoint_name);
  const [base, setBase] = useState(artifact.base_model || card?.base_model || 'Unknown');
  const [triggers, setTriggers] = useState(artifact.trigger_token || card?.trigger_token || '');
  const [tags, setTags] = useState(card?.tags?.join(', ') || '');
  const [description, setDescription] = useState(card?.description || '');
  const [replace, setReplace] = useState(false);
  const samples = (artifact.sample_paths || []).filter(path => /\.(png|jpe?g|webp)$/i.test(path));
  const [images, setImages] = useState<string[]>([]);
  const [extraPaths, setExtraPaths] = useState('');
  const [reviewIssue, setReviewIssue] = useState('');
  async function chooseImages() {
    try {
      const selected = await open({ multiple: true, directory: false, filters: [{ name: 'Preview images', extensions: ['png', 'jpg', 'jpeg', 'webp'] }] });
      if (selected) setExtraPaths(paths => [...new Set([...paths.split('\n').filter(Boolean), ...(Array.isArray(selected) ? selected : [selected])])].join('\n'));
    } catch (error) { setReviewIssue(error instanceof Error ? error.message : String(error)); }
  }
  const split = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean);
  return <form className="library-export-review" onSubmit={event => {
    event.preventDefault();
    const previews = [...new Set([...images, ...extraPaths.split('\n').map(path => path.trim()).filter(Boolean)])];
    if (previews.length > 12) { setReviewIssue('Choose at most 12 preview images.'); return; }
    setReviewIssue('');
    onSend({ title, base_model: base, trigger_words: split(triggers), tags: split(tags), description, preview_paths: previews, replace_metadata: replace });
  }}>
    <fieldset disabled={busy}><legend>Review library entry</legend>
      <label>Display name<input required maxLength={300} value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label>Base model<input required maxLength={200} value={base} onChange={event => setBase(event.target.value)} /></label>
      <label>Trigger words, separated by commas<input value={triggers} onChange={event => setTriggers(event.target.value)} /></label>
      <label>Tags, separated by commas<input value={tags} onChange={event => setTags(event.target.value)} /></label>
      <label>Description<textarea maxLength={10000} value={description} onChange={event => setDescription(event.target.value)} /></label>
      <p>Choose up to 12 images. The first selected image becomes the cover. Selected images also appear in LoRA Manager’s example gallery.</p>
      <div className="library-export-samples">{samples.map(path => <label key={path}>
        <input type="checkbox" checked={images.includes(path)} onChange={event => setImages(items => event.target.checked ? [...items, path] : items.filter(item => item !== path))} />
        {assetUrl ? <img src={assetUrl(path)} alt={`Training sample ${path.split(/[\\/]/).pop()}`} loading="lazy" /> : null}
        <span>{path.split(/[\\/]/).pop()}{images[0] === path ? ' · Cover' : ''}</span>
      </label>)}</div>
      {isTauri() ? <button type="button" onClick={() => void chooseImages()}>Choose preview images…</button> : null}
      <label>Additional image paths, one per line<textarea placeholder="/path/to/preview.png" value={extraPaths} onChange={event => setExtraPaths(event.target.value)} /></label>
      <p>PNG, JPEG or WebP. Images are copied; originals are preserved.</p>
      <label><input type="checkbox" checked={replace} onChange={event => setReplace(event.target.checked)} />Replace existing library metadata and cover with these reviewed values</label>
      <small>{receipt ? 'Sending again verifies the copy and syncs any pending images.' : 'If this checkpoint is already in the library, existing metadata is preserved unless you select replacement.'} This handoff does not qualify model quality or compatibility.</small>
      {reviewIssue ? <p role="alert">{reviewIssue}</p> : null}
      <button type="submit">Send to LoRA Manager</button><button type="button" onClick={onCancel}>Cancel</button>
    </fieldset>
  </form>;
}
