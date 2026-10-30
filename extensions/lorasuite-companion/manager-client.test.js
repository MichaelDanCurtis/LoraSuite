import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/dom';
let stored, client;
const base = 'http://127.0.0.1:8189';
const transfer = { operation: 'download', model_id: 1, version_id: 2, download_id: 'stable' };
beforeEach(async () => {
  vi.resetModules(); stored = {};
  vi.stubGlobal('chrome', { storage: { local: { get: async key => ({ [key]: stored[key] }), set: async data => Object.assign(stored, data) } } });
  let pending = Promise.resolve();
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: (_, fn) => { const result = pending.then(fn); pending = result.catch(() => {}); return result; } } });
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ success: true, queue: [], history: [] }) })));
  client = await import('./manager-client.js');
});
afterEach(() => vi.unstubAllGlobals());
it('rejects remote, credentialed, malformed and privileged destinations before fetch', async () => {
  for (const address of ['https://127.0.0.1:8189', 'http://example.com:8189', 'http://user:pass@127.0.0.1:8189', 'http://127.0.0.1:80', 'http://127.0.0.1:8189/?token=x', 'http://127.0.0.1:8189/evil']) {
    await expect(client.managerOperation(address, { operation: 'status', model_ids: [1] })).rejects.toThrow();
  }
  for (const ids of [[-1], ['1/evil'], [true], new Array(101).fill(1)]) await expect(client.managerOperation(base, { operation: 'status', model_ids: ids })).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
it('keeps long downloads in the tab and deduplicates concurrent and restarted submissions', async () => {
  let finish;
  const done = new Promise(resolve => { finish = resolve; });
  fetch.mockImplementation(async url => { if (url.endsWith('/download-model')) await done; return { ok: true, json: async () => ({ success: true }) }; });
  const results = await Promise.all([client.managerOperation(base, transfer, { allowTransfers: true }), client.managerOperation(base, { ...transfer, download_id: 'other-tab' }, { allowTransfers: true })]);
  expect(results[1].duplicate).toBe(true);
  await waitFor(() => expect(fetch.mock.calls.filter(([url]) => url.endsWith('/download-model'))).toHaveLength(1));
  expect(client.hasActiveTransfers()).toBe(true);
  expect(fetch.mock.calls.every(([url, args]) => url.startsWith(base + '/api/lm/') && !args.headers.Authorization && args.credentials === 'omit')).toBe(true);
  finish();
  await waitFor(() => expect(client.hasActiveTransfers()).toBe(false));
  vi.resetModules(); const restarted = await import('./manager-client.js');
  expect((await restarted.managerOperation(base, transfer, { allowTransfers: true })).duplicate).toBe(true);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/download-model'))).toHaveLength(1);
});
it('leaves uncertain transfers for review without replay and scopes receipts to the LM instance', async () => {
  fetch.mockRejectedValue(new Error('connection lost'));
  await client.managerOperation(base, transfer, { allowTransfers: true });
  await waitFor(() => expect(client.hasActiveTransfers()).toBe(false));
  expect(stored['lm-direct-receipts:' + base].stable.status).toBe('needs_review');
  expect((await client.managerOperation(base, transfer, { allowTransfers: true })).duplicate).toBe(true);
  expect((await client.managerOperation('http://127.0.0.1:8190', transfer, { allowTransfers: true })).duplicate).toBeUndefined();
  await waitFor(() => expect(client.hasActiveTransfers()).toBe(false));
});
it('refuses long transfers from a worker or transient popup context', async () => {
  for (const payload of [transfer, { operation: 'recipe', image_id: 1 }, { operation: 'retry', download_id: 'failed' }]) {
    await expect(client.managerOperation(base, payload)).rejects.toThrow('popup');
  }
  expect(fetch).not.toHaveBeenCalled();
});
it('reads live progress and strips local paths and upstream secret fields', async () => {
  fetch.mockImplementation(async url => ({ ok: true, json: async () => url.includes('/download-progress/')
    ? { status: 'progress', progress: 64, bytes_downloaded: 640, total_bytes: 1000, url: 'secret' }
    : url.includes('/downloads/queue') ? { queue: [{ download_id: 'q', status: 'downloading', progress: 0, file_path: '/private' }] }
      : { history: [] } }));
  const result = await client.managerOperation(base, { operation: 'queue' });
  expect(result.queue[0]).toMatchObject({ progress: 64, bytes_downloaded: 640 });
  expect(JSON.stringify(result)).not.toMatch(/secret|private/);
});
it('retries the native new ID and preserves the chosen file parameters', async () => {
  fetch.mockImplementation(async url => ({ ok: true, json: async () => url.includes('/history/retry')
    ? { item: { download_id: 'retry-id', model_id: 1, model_version_id: 2, file_params: '{"format":"SafeTensor"}' } }
    : { success: true } }));
  await client.managerOperation(base, { operation: 'retry', download_id: 'failed' }, { allowTransfers: true });
  await waitFor(() => expect(client.hasActiveTransfers()).toBe(false));
  const payload = JSON.parse(fetch.mock.calls.find(([url]) => url.endsWith('/download-model'))[1].body);
  expect(payload).toMatchObject({ download_id: 'retry-id', file_params: { format: 'SafeTensor' }, use_default_paths: true });
  expect(fetch.mock.calls.some(([url]) => url.includes('/queue/add'))).toBe(false);
});
it('deduplicates recipe imports across tabs and reopens their current resource metadata', async () => {
  fetch.mockImplementation(async url => ({ ok: true, json: async () => url.includes('/import-from-url')
    ? { recipe_id: 'local-recipe', success: true } : { loras: [{ modelId: 1, id: 2, name: 'Local', existsLocally: true }] } }));
  const payload = { operation: 'recipe', image_id: 123 };
  const [first, second] = await Promise.all([client.managerOperation(base, payload, { allowTransfers: true }), client.managerOperation(base, payload, { allowTransfers: true })]);
  expect(first.resources[0].in_library).toBe(true); expect(second.already_exists).toBe(true);
  expect(fetch.mock.calls.filter(([url]) => url.includes('/import-from-url'))).toHaveLength(1);
});
it('does not reimport a recipe after an uncertain response', async () => {
  fetch.mockRejectedValue(new Error('lost response'));
  const payload = { operation: 'recipe', image_id: 123 };
  await expect(client.managerOperation(base, payload, { allowTransfers: true })).rejects.toThrow('lost response');
  vi.resetModules(); const restarted = await import('./manager-client.js');
  await expect(restarted.managerOperation(base, payload, { allowTransfers: true })).rejects.toThrow('uncertain');
  expect(fetch).toHaveBeenCalledTimes(1);
});
