import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { waitFor } from '@testing-library/dom';
let stored;
beforeEach(() => {
  vi.resetModules(); stored = {};
  document.body.innerHTML = readFileSync('extensions/lorasuite-companion/popup.html', 'utf8').match(/<body>([\s\S]*)<\/body>/)[1];
  document.body.className = '';
  vi.stubGlobal('location', new URL('chrome-extension://test/popup.html?model=https://civitai.com/models/123?modelVersionId=456'));
  vi.stubGlobal('chrome', {
    storage: {
      local: { get: vi.fn(async key => ({ [key]: stored[key] })), set: vi.fn(async data => Object.assign(stored, data)), remove: vi.fn(async key => delete stored[key]), setAccessLevel: vi.fn(async () => {}) },
      session: { get: vi.fn(async () => ({})), setAccessLevel: vi.fn(async () => {}) },
    },
    windows: { create: vi.fn(async () => ({ id: 8 })) },
    tabs: { query: vi.fn(async () => [{ id: 7, url: 'chrome-extension://test/popup.html' }]), create: vi.fn(async () => ({})) },
    runtime: { getURL: path => `chrome-extension://test/${path}`, sendMessage: vi.fn(async () => ({ ready: true })) },
  });
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.endsWith('/pair')) return { ok: true, json: async () => ({ token: 'test-only' }) };
    if (url.includes('/api/lm/')) return { ok: true, json: async () => ({ status: 'ok', success: true, queue: [], history: [] }) };
    return { status: 401, json: async () => ({ detail: url.includes(':8767') && !url.endsWith('/library/theme') ? "Pair this extension in LoraSuite's Model Library" : 'Not LoraSuite' }) };
  }));
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_, fn) => fn() } });
});
afterEach(() => { window.dispatchEvent(new Event('unload')); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const el = id => document.getElementById(id);
it('connects directly and hands off without pairing or an engine request', async () => {
  await import('./popup.js');
  expect(el('connection').open).toBe(false); expect(el('review-model').disabled).toBe(false);
  expect(el('model-identity').textContent).toContain('selected version 456');
  expect(el('manager-status').textContent).toBe('LoRA Manager connected');
  expect(fetch.mock.calls.every(([url]) => (url.startsWith('http://127.0.0.1:8188/api/lm/') || url.endsWith('/library/theme')))).toBe(true);
  expect(stored.connection).toBeUndefined();
  el('review-model').click();
  await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'review-in-manager', url: 'https://civitai.com/models/123?modelVersionId=456', category: 'loras' }));
});
it('retains optional project pairing without using its token for LM', async () => {
  await import('./popup.js');
  el('find-engine').click();
  await waitFor(() => expect(el('engine').value).toBe('http://127.0.0.1:8767'));
  el('code').value = 'test-code'; el('pair').click();
  await waitFor(() => expect(stored.connection?.token).toBe('test-only'));
  expect(fetch.mock.calls.filter(([url]) => url.includes('/api/lm/')).every(([, args]) => !args.headers.Authorization)).toBe(true);
});
it('preserves a saved project pairing when its replacement fails', async () => {
  stored.connection = { engine: 'http://127.0.0.1:8767', token: 'saved-token' };
  await import('./popup.js');
  fetch.mockResolvedValue({ ok: false, status: 403, json: async () => ({ detail: 'Pairing code expired' }) });
  el('engine').value = 'http://127.0.0.1:8766'; el('code').value = 'expired'; el('pair').click();
  await waitFor(() => expect(el('status').textContent).toBe('Pairing code expired'));
  expect(stored.connection.token).toBe('saved-token');
  expect(el('review-model').disabled).toBe(false);
});
it('selects an exact version and submits directly only after Download', async () => {
  const original = fetch.getMockImplementation();
  fetch.mockImplementation(async (url, args) => url.includes('/model-versions-status')
    ? { ok: true, json: async () => ({ modelName: 'Fixture', versions: [{ id: 456, name: 'Chosen', inLibrary: false }, { id: 789, name: 'Installed', inLibrary: true }] }) } : original(url, args));
  await import('./popup.js');
  el('load-versions').click();
  await waitFor(() => expect(el('download-model').disabled).toBe(false));
  expect(el('model-version').value).toBe('456');
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/download-model'))).toBe(false);
  el('download-model').click();
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/download-model'))).toBe(true));
  const payload = JSON.parse(fetch.mock.calls.find(([url]) => url.endsWith('/download-model'))[1].body);
  expect(payload).toMatchObject({ model_id: 123, model_version_id: 456, use_default_paths: true });
  await waitFor(() => expect(el('refresh-downloads').disabled).toBe(false));
  expect(el('download-model').disabled).toBe(true);
  el('model-version').value = '789'; el('model-version').dispatchEvent(new Event('change'));
  expect(el('download-model').disabled).toBe(true);
});
it('imports recipes directly and submits only checked missing resources', async () => {
  vi.stubGlobal('location', new URL('chrome-extension://test/popup.html?model=https://civitai.com/images/321'));
  const original = fetch.getMockImplementation();
  fetch.mockImplementation(async (url, args) => ({ ok: true, json: async () => url.includes('/recipes/import-from-url')
    ? { success: true, recipe_id: 'recipe1' } : url.endsWith('/recipe/recipe1')
      ? { loras: [{ modelId: 1, id: 2, name: 'Missing' }, { modelId: 3, id: 4, name: 'Installed', existsLocally: true }] }
      : (await original(url, args)).json() }));
  await import('./popup.js');
  el('import-recipe').click();
  await waitFor(() => expect(el('recipe-resources').querySelectorAll('input')).toHaveLength(2));
  await waitFor(() => expect(el('import-recipe').disabled).toBe(false));
  const inputs = el('recipe-resources').querySelectorAll('input');
  expect(inputs[0].checked).toBe(false); expect(inputs[1].disabled).toBe(true);
  inputs[0].click(); el('download-resources').click();
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/download-model'))).toBe(true));
  expect(JSON.parse(fetch.mock.calls.find(([url]) => url.endsWith('/download-model'))[1].body)).toMatchObject({ model_id: 1, model_version_id: 2 });
});
it('asks the source tab to show an overlay from the toolbar without opening a window', async () => {
  vi.stubGlobal('location', new URL('chrome-extension://test/popup.html'));
  chrome.tabs.query.mockResolvedValue([{ id: 7, url: 'https://civitai.com/models/123' }]);
  await import('./popup.js');
  expect(el('download-model').disabled).toBe(true);
  expect(el('open-companion-tab').hidden).toBe(false);
  chrome.runtime.sendMessage.mockResolvedValue({opened:true});
  vi.spyOn(window, 'close').mockImplementation(()=>{});
  el('open-companion-tab').click();
  await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(expect.objectContaining({type:'open-model-companion', tabId:7, url:'https://civitai.com/models/123'})));
  expect(chrome.windows.create).not.toHaveBeenCalled();
  expect(chrome.tabs.create).not.toHaveBeenCalled();
});
it('sends a model bookmark to the selected project only after an explicit capture action', async () => {
  stored.connection = { engine: 'http://127.0.0.1:8767', token: 'project-token' };
  const original = fetch.getMockImplementation();
  fetch.mockImplementation(async (url, args) => url.endsWith('/projects')
    ? { ok: true, json: async () => [{ id: 'project1', name: 'My project' }] }
    : url.endsWith('/inbox') ? { ok: true, json: async () => ({ added: 1, duplicates: 0 }) } : original(url, args));
  await import('./popup.js');
  expect(fetch.mock.calls.some(([url]) => url.includes(':8767') && !url.endsWith('/library/theme'))).toBe(false);
  el('load-projects').click();
  await waitFor(() => expect(el('project').options.length).toBe(2));
  await waitFor(() => expect(el('save-page').disabled).toBe(false));
  el('project').value = 'project1'; el('save-page').click();
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.endsWith('/inbox'))).toBe(true));
  const [, request] = fetch.mock.calls.find(([url]) => url.endsWith('/inbox'));
  expect(request.headers.Authorization).toBe('Bearer project-token');
  expect(JSON.parse(request.body).items[0]).toMatchObject({ kind: 'model', project_id: 'project1', url: 'https://civitai.com/models/123?modelVersionId=456' });
});

it('renders a bounded text title and optional thumbnail with a broken-image fallback', async () => {
  const url = new URL(location.href);
  url.searchParams.set('title', '<b>Emerald landscape</b>');
  url.searchParams.set('thumbnail', 'https://image.civitai.com/neutral-fixture.jpeg');
  vi.stubGlobal('location', url);
  await import('./popup.js');
  expect(el('model-preview').hidden).toBe(false);
  expect(el('preview-title').textContent).toBe('<b>Emerald landscape</b>');
  expect(el('preview-title').querySelector('b')).toBeNull();
  expect(el('preview-image').getAttribute('referrerpolicy')).toBe('no-referrer');
  expect(el('preview-image').src).toBe('https://image.civitai.com/neutral-fixture.jpeg');
  expect(el('preview-image').hidden).toBe(true);
  el('preview-image').dispatchEvent(new Event('load'));
  expect(el('preview-image').hidden).toBe(false);
  el('preview-image').dispatchEvent(new Event('error'));
  expect(el('preview-image').hidden).toBe(true);
  expect(el('preview-image').hasAttribute('src')).toBe(false);
  expect(el('load-versions').disabled).toBe(false);
});
it('uses the local fallback when a handoff contains an untrusted image URL', async () => {
  const url = new URL(location.href); url.searchParams.set('thumbnail', 'http://127.0.0.1:8767/private');
  vi.stubGlobal('location', url);
  await import('./popup.js');
  expect(el('preview-title').textContent).toBe('Model 123');
  expect(el('preview-image').hasAttribute('src')).toBe(false);
});

it('refuses an unissued embedded popup before reading credentials or contacting LM', async () => {
  vi.stubGlobal('location', new URL(location.href + '&overlay=forged'));
  chrome.runtime.sendMessage.mockResolvedValue({error:'Invalid session'});
  await expect(import('./popup.js')).rejects.toThrow('Unauthorized companion frame');
  expect(chrome.storage.local.get).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  expect(document.body.textContent).toContain('Reopen the companion');
});
