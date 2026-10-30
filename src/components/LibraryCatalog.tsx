import { useEffect, useState } from 'react';
import type { EngineClient } from '../lib/api';
import type { LibraryCatalog as Catalog, LibraryCategory, LibraryModel } from '../lib/library';
import { Layers, Box, BookOpen } from 'lucide-react';
import { handleDesktopLink } from '../lib/desktopLinks';

const categories = [
  { id: 'loras' as const, label: 'LoRA adapters', icon: Layers },
  { id: 'checkpoints' as const, label: 'Checkpoints', icon: Box },
  { id: 'embeddings' as const, label: 'Embeddings', icon: BookOpen },
];

export function LibraryCatalog({ engine, onSelect, lorasOnly = false, managerUrl }: {
  engine: Pick<EngineClient, 'listLibraryModels'>;
  onSelect?: (model: LibraryModel) => void;
  lorasOnly?: boolean;
  managerUrl?: string;
}) {
  const [query, setQuery] = useState({ category: 'loras' as LibraryCategory, page: 1, search: '', revision: 0 });
  const [search, setSearch] = useState('');
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const category = categories.find(item => item.id === query.category)!;
  const browseUrl = managerUrl ? new URL(`/${query.category}`, managerUrl).href : undefined;

  function browseCategory(value: LibraryCategory) {
    setSearch('');
    setQuery(current => ({ ...current, category: value, page: 1, search: '' }));
  }

  useEffect(() => {
    let disposed = false;
    setBusy(true); setError(''); setCatalog(null);
    engine.listLibraryModels(query.category, query.page, query.search)
      .then(data => { if (!disposed) setCatalog(data); })
      .catch(reason => { if (!disposed) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (!disposed) setBusy(false); });
    return () => { disposed = true; };
  }, [engine, query]);

  return <section aria-label="LoRA Manager catalog" className="library-catalog">
    <div className="library-browse-heading"><div><h3>{onSelect ? 'Choose from your library' : 'Browse library'}</h3>
      <p>Your installed models, ready to browse. No search needed.</p></div>
      {browseUrl ? <a className="library-browse-launch" href={browseUrl} target="_blank" rel="noopener noreferrer" onClick={event => handleDesktopLink(event, setError)}>Open full library browser ↗<small>Folders · preview gallery · favorites · filters</small></a> : null}
    </div>
    {!lorasOnly ? <nav className="library-category-nav" aria-label="Browse model categories">{categories.map(({ id, label, icon: Icon }) =>
      <button key={id} type="button" aria-pressed={query.category === id} onClick={() => browseCategory(id)}><Icon size={20} aria-hidden="true" />{label}</button>
    )}</nav> : null}
    <div className="library-browse-toolbar">
      <button type="button" disabled={busy} onClick={() => setQuery(current => ({ ...current, revision: current.revision + 1 }))}>Refresh catalog</button>
      {query.search ? <button type="button" onClick={() => browseCategory(query.category)}>Clear search — browse all</button> : null}
      <details><summary>Search this library (optional)</summary>
        <form onSubmit={event => { event.preventDefault(); setQuery(current => ({ ...current, page: 1, search: search.trim(), revision: current.revision + 1 })); }}>
          <label>Search installed models<input maxLength={200} value={search} onChange={event => setSearch(event.target.value)} /></label>
          <button type="submit" disabled={busy}>Search catalog</button>
        </form>
      </details>
    </div>
    <p role="status">{busy ? `Loading ${category.label.toLowerCase()}…` : error || `${catalog?.total ?? 0} ${query.search ? 'matching' : 'installed'} ${category.label.toLowerCase()}${query.search ? ` for “${query.search}”` : ''}`}</p>
    {!busy && !error && catalog?.items.length === 0 ? <div className="library-empty-browse"><category.icon size={32} aria-hidden="true" />
      <h4>{query.search ? 'No matches for this search' : `No ${category.label.toLowerCase()} installed here yet`}</h4>
      <p>{query.search ? 'Clear the search or choose another category to keep browsing.' : 'This is your downloaded library, not a search of Civitai. Download a model through the companion or add your existing model folder in LoRA Manager, then refresh here.'}</p>
      {browseUrl ? <a href={browseUrl} target="_blank" rel="noopener noreferrer" onClick={event => handleDesktopLink(event, setError)}>Open LoRA Manager to add or browse folders ↗</a> : null}
    </div> : null}
    <div className="library-catalog-items">{catalog?.items.map(model => <article key={model.path}>
      <div className="library-model-badge"><category.icon size={28} aria-hidden="true" /><span>{model.base_model}</span></div>
      <strong>{model.name}</strong>
      {model.trigger_words.length ? <p>Trigger words: {model.trigger_words.join(', ')}</p> : null}
      {!model.available ? <p>File missing or outside the configured library roots. Rescan in LoRA Manager.</p> : onSelect && !model.selectable ? <p>This file format is not supported by this compatibility check.</p> : null}
      <details><summary>Model details</summary><p>{model.base_model} · {model.category} · Compatibility unverified</p><code>{model.path}</code>
        {model.sha256 ? <small>SHA-256 reported by library: {model.sha256}</small> : null}
      </details>
      {onSelect ? <button type="button" disabled={!model.selectable || busy} onClick={() => onSelect(model)}>Use {model.name} for compatibility check</button> : null}
    </article>)}</div>
    {catalog && catalog.total_pages > 1 ? <nav aria-label="Model catalog pages">
      <button type="button" disabled={busy || query.page <= 1} onClick={() => setQuery(current => ({ ...current, page: current.page - 1 }))}>Previous models</button>
      <span>Page {catalog.page} of {catalog.total_pages}</span>
      <button type="button" disabled={busy || query.page >= catalog.total_pages} onClick={() => setQuery(current => ({ ...current, page: current.page + 1 }))}>Next models</button>
    </nav> : null}
  </section>;
}
