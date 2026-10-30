// Direct, loopback-only LM transport shared by trusted extension contexts.
// No LoraSuite token, engine URL, Civitai cookies or remote URL is used here.
export function managerAddress(value = 'http://127.0.0.1:8188') {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.hash ||
      !['/', '/loras', '/checkpoints', '/embeddings', '/recipes'].includes(url.pathname) ||
      Number(url.port) < 1024 || Number(url.port) > 65535) throw new Error('Enter a local LM address, such as http://127.0.0.1:8188');
  return url.origin;
}

export async function managerCall(base, path, body, timeout = 25000) {
  if (!path.startsWith('/') || path.startsWith('//') || path.split('?')[0].includes('..')) throw new Error('Invalid LM operation');
  const response = await fetch(`${managerAddress(base)}/api/lm${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'omit', redirect: 'error',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeout),
  });
  if (!response.ok) throw new Error(`LoRA Manager returned HTTP ${response.status}. Review its queue or settings.`);
  const data = await response.json();
  if (!data || typeof data !== 'object' || data.success === false || data.error) throw new Error('LoRA Manager could not complete the operation. Review its queue or settings.');
  return data;
}

export async function checkManager(base) {
  const data = await managerCall(base, '/health-check', undefined, 2000);
  if (data.status !== 'ok') throw new Error('This address did not identify a ready LoRA Manager');
  return managerAddress(base);
}

export async function findManagers(preferred) {
  const candidates = [...new Set([preferred, 'http://127.0.0.1:8188'].filter(Boolean))];
  return (await Promise.all(candidates.map(base => checkManager(base).catch(() => null)))).filter(Boolean);
}

const number = value => {
  if (!/^[1-9]\d*$/.test(String(value)) || !Number.isSafeInteger(Number(value))) throw new Error('Choose a valid model, version or image ID');
  return Number(value);
};
const transferId = value => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(value)) throw new Error('Choose a valid download ID');
  return value;
};
const active = new Set();
const journalKey = base => `lm-direct-receipts:${base}`;
const readReceipts = async base => (await chrome.storage.local.get(journalKey(base)))[journalKey(base)] || {};
const lock = (base, task) => navigator.locks.request(journalKey(base), task);

async function submit(base, payload, queued = false) {
  const key = `${base}:${payload.download_id}`;
  const row = await lock(base, async () => {
    const rows = await readReceipts(base);
    if (rows[payload.download_id]) {
      const prior = rows[payload.download_id];
      if (prior.model_id !== payload.model_id || prior.model_version_id !== payload.model_version_id) throw new Error('Download ID belongs to another version');
      return { ...prior, duplicate: true };
    }
    const previousVersion = !queued && Object.values(rows).find(item => item.model_id === payload.model_id && item.model_version_id === payload.model_version_id);
    if (previousVersion) return { ...previousVersion, duplicate: true };
    if (Object.keys(rows).length >= 1000) throw new Error('Companion receipt limit reached. Use LM’s download wizard.');
    const receipt = { download_id: payload.download_id, model_id: payload.model_id, model_version_id: payload.model_version_id, status: 'submitted' };
    await chrome.storage.local.set({ [journalKey(base)]: { ...rows, [payload.download_id]: receipt } });
    return receipt;
  });
  if (row.duplicate) return row;
  active.add(key);
  // This promise belongs to a visible extension tab, never the MV3 worker.
  // Closing/reloading that tab leaves a receipt requiring review, not replay.
  void (async () => {
    let state = 'needs_review';
    try {
      if (!queued) await managerCall(base, '/downloads/queue/add?' + new URLSearchParams({ ...row, source: 'lorasuite-companion' }));
      const result = await managerCall(base, '/download-model', { ...payload, use_default_paths: true }, 86400000);
      state = result.cancelled ? 'canceled' : 'completed';
    } catch { /* LM may have accepted the request; inspect native history. */ }
    finally {
      try {
        await lock(base, async () => {
          const rows = await readReceipts(base);
          await chrome.storage.local.set({ [journalKey(base)]: { ...rows, [row.download_id]: { ...row, status: state } } });
        });
      } finally { active.delete(key); }
    }
  })().catch(() => {});
  return { ...row, success: true };
}

export function hasActiveTransfers() { return active.size > 0; }

export async function managerOperation(address, payload, { allowTransfers = false } = {}) {
  const base = managerAddress(address);
  const call = (path, body, timeout) => managerCall(base, path, body, timeout);
  switch (payload.operation) {
    case 'status': {
      if (!Array.isArray(payload.model_ids) || payload.model_ids.length > 100) throw new Error('Check at most 100 model IDs');
      const ids = [...new Set(payload.model_ids.map(number))];
      if (!ids.length) return { items: [] };
      const data = await call('/check-models-exist?' + new URLSearchParams({ modelIds: ids.join(',') }));
      return { items: (data.results || []).map(row => ({ model_id: row.modelId, version_ids: (row.versions || []).map(v => v.versionId).filter(Boolean), in_library: Boolean(row.versions?.length) })) };
    }
    case 'versions': {
      const data = await call('/model-versions-status?' + new URLSearchParams({ modelId: number(payload.model_id) }));
      return { model_id: data.modelId, name: String(data.modelName || '').slice(0, 300), versions: (data.versions || []).map(v => ({ id: v.id, name: String(v.name || '').slice(0, 300), in_library: Boolean(v.inLibrary) })) };
    }
    case 'download': {
      if (!allowTransfers) throw new Error('Open the companion popup to download');
      const model_id = number(payload.model_id), model_version_id = number(payload.version_id), download_id = transferId(payload.download_id);
      return submit(base, { model_id, model_version_id, download_id });
    }
    case 'queue': {
      const [data, history, receipts] = await Promise.all([call('/downloads/queue'), call('/downloads/history?limit=30&offset=0'), readReceipts(base)]);
      const project = row => Object.fromEntries(['download_id', 'model_id', 'model_version_id', 'model_name', 'version_name', 'status', 'progress', 'bytes_downloaded', 'total_bytes'].map(k => [k, row[k]]));
      const queue = (data.queue || []).slice(0, 100).map(project);
      const live = queue.filter(row => ['downloading', 'paused'].includes(row.status));
      live.forEach(row => { row.progress = undefined; });
      await Promise.all(live.slice(0, 5).map(async row => {
        try {
          const progress = await call('/download-progress/' + transferId(row.download_id), undefined, 2000);
          for (const k of ['progress', 'bytes_downloaded', 'total_bytes']) row[k] = progress[k];
          if (progress.status && progress.status !== 'progress') row.status = progress.status;
        } catch { /* Unknown stays unknown. */ }
      }));
      return { queue, history: (history.history || history.items || []).slice(0, 30).map(project), submissions: Object.values(receipts).slice(-100).map(row => ({ ...row, status: row.status === 'submitted' && !active.has(`${base}:${row.download_id}`) ? 'needs_review' : row.status })) };
    }
    case 'pause': case 'resume': case 'cancel': case 'retry': {
      if (payload.operation === 'retry' && !allowTransfers) throw new Error('Open the companion popup to retry');
      const routes = { pause: '/pause-download', resume: '/resume-download', cancel: '/cancel-download-get', retry: '/downloads/history/retry' };
      const result = await call(routes[payload.operation] + '?' + new URLSearchParams({ download_id: transferId(payload.download_id) }));
      if (payload.operation !== 'retry') return { success: true };
      const item = result.item;
      return submit(base, { download_id: transferId(item.download_id), model_id: number(item.model_id), model_version_id: number(item.model_version_id), file_params: typeof item.file_params === 'string' ? JSON.parse(item.file_params) : item.file_params }, true);
    }
    case 'recipe': {
      if (!allowTransfers) throw new Error('Open the companion popup to import a recipe');
      const imageId = number(payload.image_id);
      const receiptKey = `lm-recipe:${base}:${imageId}`;
      const data = await navigator.locks.request(receiptKey, async () => {
        const previous = (await chrome.storage.local.get(receiptKey))[receiptKey];
        if (previous?.status === 'completed') return { ...previous, already_exists: true };
        if (previous) throw new Error('Recipe import result is uncertain. Review Recipes in LoRA Manager; the companion will not repeat it automatically.');
        await chrome.storage.local.set({ [receiptKey]: { status: 'submitted' } });
        const result = await call('/recipes/import-from-url?' + new URLSearchParams({ image_url: `https://civitai.com/images/${imageId}` }), undefined, 180000);
        const receipt = { status: 'completed', recipe_id: transferId(result.recipe_id), name: String(result.name || '').slice(0, 300), already_exists: Boolean(result.already_exists) };
        await chrome.storage.local.set({ [receiptKey]: receipt });
        return receipt;
      });
      const id = transferId(data.recipe_id);
      const recipe = await call('/recipe/' + id);
      const identifier = value => { try { return number(value); } catch { return 0; } };
      return { success: true, recipe_id: id, name: String(data.name || '').slice(0, 300), already_exists: Boolean(data.already_exists), resources: [...(recipe.loras || []), ...(recipe.checkpoint ? [recipe.checkpoint] : [])].slice(0, 100).map(r => ({ model_id: identifier(r.modelId), version_id: identifier(r.id), name: String(r.name || 'Unnamed resource').slice(0, 300), in_library: Boolean(r.existsLocally), unavailable: Boolean(r.isDeleted) })) };
    }
    default: throw new Error('Unsupported LoRA Manager operation');
  }
}
