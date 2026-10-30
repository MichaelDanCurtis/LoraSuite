// Extension-owned controls. All mutations are deliberate button actions.
export function createManagerControls({ route, action, status, call, managerURL }) {
  const $ = id => document.getElementById(id);
  let versions = [], resources = [], submitted = new Set();
  let refreshTimer;
  const panel = $('download-panel');
  const selected = () => versions.find(v => String(v.id) === $('model-version').value);
  function sync(disabled) {
    $('download-model').disabled = disabled || !selected() || selected().in_library || submitted.has(selected().id);
    $('download-resources').disabled = disabled || !$('recipe-resources').querySelector('input:checked');
  }
  $('model-version').addEventListener('change', () => sync($('load-versions').disabled));
  $('recipe-resources').addEventListener('change', () => sync($('import-recipe').disabled));
  action('load-versions', async () => {
    if (route?.kind !== 'model') throw new Error('Open a model first');
    const result = await call({ operation: 'versions', model_id: route.modelId });
    versions = result.versions || [];
    if (result.name) $('preview-title').textContent = String(result.name).slice(0, 160);
    $('model-version').replaceChildren(new Option('Choose a version', ''));
    for (const v of versions) $('model-version').append(new Option(`${v.name} · ${v.id}${v.in_library ? ' · Installed' : ''}`, String(v.id)));
    if (versions.some(v => String(v.id) === route.versionId)) $('model-version').value = String(route.versionId);
    status(`${result.name || 'Model'} · ${versions.length} versions. Choose one to download.`);
  });
  async function download(modelId, versionId) {
    // Stable across lost replies and reopening the page. A new transfer after a
    // failure uses LM's explicit Retry action; a second click never replays it.
    const key = `lm-download:${managerURL()}:${modelId}:${versionId}`;
    const saved = await chrome.storage.local.get(key);
    const id = saved[key] || crypto.randomUUID();
    await chrome.storage.local.set({ [key]: id });
    return call({ operation: 'download', model_id: modelId, version_id: versionId, download_id: id });
  }
  action('download-model', async () => {
    const version = selected();
    if (!version || version.in_library) throw new Error('Choose an uninstalled version');
    const result = await download(route.modelId, version.id);
    submitted.add(version.id);
    status(result.duplicate ? 'Already submitted. Refresh downloads to check its result or use Retry.' : 'Submitted to LoRA Manager. Refresh downloads for progress.');
    await refresh();
  });
  async function refresh() {
    clearTimeout(refreshTimer);
    const result = await call({ operation: 'queue' });
    const rows = new Map();
    for (const row of [...(result.submissions || []), ...(result.history || []), ...(result.queue || [])]) {
      const previous = rows.get(row.download_id);
      rows.set(row.download_id, previous?.status === 'needs_review' && row.status === 'queued' ? { ...row, status: 'needs_review' } : row);
    }
    $('download-list').replaceChildren();
    for (const row of rows.values()) {
      const entry = document.createElement('article');
      const text = document.createElement('p');
      text.textContent = `${row.model_name || `Model ${row.model_id}`} · ${row.version_name || row.model_version_id} · ${row.status}${Number.isFinite(row.progress) ? ` · ${Math.round(row.progress)}%` : ''}`;
      entry.append(text);
      const operations = ['failed', 'canceled', 'cancelled'].includes(row.status) ? ['retry']
        : row.status === 'paused' ? ['resume', 'cancel']
          : ['downloading', 'queued', 'submitted', 'pending'].includes(row.status) ? ['pause', 'cancel'] : [];
      if (row.status === 'needs_review') {
        const note = document.createElement('small'); note.textContent = 'Result uncertain. Check LoRA Manager’s queue and history before starting another transfer.'; entry.append(note);
      }
      for (const op of operations) {
        const button = document.createElement('button'); button.dataset.manager = '';  button.textContent = op[0].toUpperCase() + op.slice(1);
        button.addEventListener('click', async () => {
          for (const b of entry.querySelectorAll('button')) b.disabled = true;
          try { await call({ operation: op, download_id: row.download_id }); await refresh(); }
          catch (error) { status(error.message); for (const b of entry.querySelectorAll('button')) b.disabled = false; }
        });
        entry.append(button);
      }
      $('download-list').append(entry);
    }
    if (!rows.size) $('download-list').textContent = 'No queued or recent downloads.';
    if ([...rows.values()].some(row => ['downloading', 'queued', 'paused', 'submitted', 'pending'].includes(row.status))) {
      refreshTimer = setTimeout(() => {
        if (panel.isConnected && !document.hidden && !$('refresh-downloads').disabled) void refresh().catch(error => status(error.message));
      }, 5000);
    }
  }
  action('refresh-downloads', refresh);
  action('import-recipe', async () => {
    if (route?.kind !== 'recipe') throw new Error('Open a Civitai image page');
    status('Importing the recipe in LoRA Manager. Keep this popup open until it finishes.');
    const result = await call({ operation: 'recipe', image_id: route.imageId });
    resources = result.resources || [];
    $('recipe-resources').replaceChildren();
    resources.forEach((r, index) => {
      const label = document.createElement('label'); const input = document.createElement('input'); input.type = 'checkbox'; input.value = String(index);
      input.disabled = r.in_library || !r.model_id || !r.version_id || r.unavailable;
      const text = document.createElement('span'); text.textContent = `${r.name} · ${r.in_library ? 'Installed' : input.disabled ? 'Unavailable — review in LM' : 'Missing'}`;
      label.append(input, text); $('recipe-resources').append(label);
    });
    status(`${result.already_exists ? 'Recipe already exists' : 'Recipe imported'} in LoRA Manager. ${resources.length ? 'Select missing resources to download.' : 'No downloadable resources were identified.'}`);
  });
  action('download-resources', async () => {
    const inputs = [...$('recipe-resources').querySelectorAll('input:checked')];
    for (const input of inputs) {
      const r = resources[Number(input.value)];
      await download(r.model_id, r.version_id); input.checked = false; input.disabled = true;
    }
    status('Selected resources submitted. Refresh downloads for progress.'); await refresh();
  });
  return { sync, reset() { versions = []; resources = []; submitted.clear(); $('model-version').replaceChildren(new Option('Load versions first', '')); $('recipe-resources').replaceChildren(); $('download-list').textContent = 'Refresh to see LoRA Manager’s queue and recent history.'; clearTimeout(refreshTimer); } };
}
