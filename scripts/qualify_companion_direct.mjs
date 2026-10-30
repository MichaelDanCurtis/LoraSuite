// Default: synthetic local HTTP contract fixture. This never hosts LM.
// --live http://127.0.0.1:8188: read-only health, installed flags and queue.
// Neither mode contacts Civitai or starts a real download.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { setTimeout as delay } from 'node:timers/promises';
import { checkManager, managerOperation, managerCall, hasActiveTransfers } from '../extensions/lorasuite-companion/manager-client.js';

const storage = {};
globalThis.chrome = { storage: { local: { get: async key => ({ [key]: storage[key] }), set: async data => Object.assign(storage, data) } } };
Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_, fn) => fn() } });
const live = process.argv[2] === '--live';
assert(live || process.argv.length === 2, 'Usage: node scripts/qualify_companion_direct.mjs [--live http://127.0.0.1:8188]');
let recipeRequests = 0, downloadRequests = 0;
const server = live ? null : createServer(async (request, response) => {
  const url = new URL(request.url, 'http://fixture.invalid');
  const path = url.pathname.replace(/^\/api\/lm/, '');
  let payload;
  switch (path) {
    case '/health-check': payload = { status: 'ok' }; break;
    case '/check-models-exist': payload = { results: [{ modelId: 1, versions: [{ versionId: 2 }] }] }; break;
    case '/downloads/queue': payload = { queue: [] }; break;
    case '/downloads/history': payload = { history: [] }; break;
    case '/downloads/queue/add': payload = { success: true }; break;
    case '/download-model': {
      let body = ''; for await (const chunk of request) body += chunk;
      const parsed = JSON.parse(body);
      assert.equal(parsed.use_default_paths, true);
      downloadRequests++;
      payload = { success: true }; break;
    }
    case '/recipes/import-from-url':
      recipeRequests++;
      payload = { recipe_id: 'local-fixture', name: 'Synthetic local recipe' }; break;
    case '/recipe/local-fixture':
      payload = { gen_params: { seed: 42, prompt: 'Synthetic local qualification' }, loras: [{ modelId: 123, id: 456, name: 'LOCAL TEST ONLY', existsLocally: false, isDeleted: true }] }; break;
    default: response.statusCode = 400; payload = { error: 'Synthetic failure' };
  }
  response.setHeader('Content-Type', 'application/json');
  response.end(JSON.stringify(payload));
});
if (server) await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = live ? process.argv[3] : `http://127.0.0.1:${server.address().port}`;
const allowed = new URL(base).origin;
const nativeFetch = globalThis.fetch;
let requests = 0;
globalThis.fetch = (url, options) => {
  assert.equal(new URL(url).origin, allowed, 'Companion may only contact the selected local endpoint');
  assert.equal(options.headers.Authorization, undefined);
  assert.equal(options.credentials, 'omit');
  requests++;
  return nativeFetch(url, options);
};
try {
  await checkManager(base);
  const status = await managerOperation(base, { operation: 'status', model_ids: [1] });
  assert(Array.isArray(status.items));
  const queue = await managerOperation(base, { operation: 'queue' });
  assert(Array.isArray(queue.queue) && Array.isArray(queue.history));
  const checks = ['direct connection', 'installed flags', 'queue/history'];
  if (!live) {
    assert.deepEqual(status.items, [{ model_id: 1, version_ids: [2], in_library: true }]);
    const recipe = await managerOperation(base, { operation: 'recipe', image_id: 9007199254740001 }, { allowTransfers: true });
    assert.deepEqual(recipe.resources, [{ model_id: 123, version_id: 456, name: 'LOCAL TEST ONLY', in_library: false, unavailable: true }]);
    const stored = await managerCall(base, '/recipe/' + recipe.recipe_id);
    assert.equal(stored.gen_params.seed, 42);
    assert.equal((await managerOperation(base, { operation: 'recipe', image_id: 9007199254740001 }, { allowTransfers: true })).already_exists, true);
    assert.equal(recipeRequests, 1, 'Recipe repeat must reuse its receipt');
    const download = { operation: 'download', model_id: 1, version_id: 2, download_id: 'local-fixture' };
    await assert.rejects(managerOperation(base, download), /popup/);
    await managerOperation(base, download, { allowTransfers: true });
    for (let attempt = 0; hasActiveTransfers() && attempt < 100; attempt++) await delay(10);
    assert.equal(hasActiveTransfers(), false);
    const duplicate = await managerOperation(base, download, { allowTransfers: true });
    assert.equal(duplicate.status, 'completed');
    assert.equal(duplicate.duplicate, true);
    assert.equal(downloadRequests, 1, 'Repeated clicks must not submit twice');
    await assert.rejects(managerCall(base, '/synthetic-error'), /HTTP 400/);
    checks.push('recipe resources and generation metadata', 'recipe deduplication', 'popup transfer gate', 'download receipt and deduplication', 'HTTP error visibility');
  }
  console.log(JSON.stringify({ result: 'passed', mode: live ? 'external-lm-read-only' : 'synthetic-http-contract', checks, requests, engine_requests: 0, pairing_required: false, remote_download_verified: false, live_install_verified: false }, null, 2));
} finally {
  globalThis.fetch = nativeFetch;
  if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}
