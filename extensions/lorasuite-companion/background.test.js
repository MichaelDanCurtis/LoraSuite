import { afterEach, beforeEach, expect, it, vi } from 'vitest';

let listener;
let stored;
let chromeMock;
beforeEach(async () => {
  vi.resetModules();
  stored = { managerConnection: { url: 'http://127.0.0.1:8189' } };
  chromeMock = {
    runtime: { id: 'test-extension', getURL: path => `chrome-extension://test-extension/${path}`, onMessage: { addListener: fn => { listener = fn; } } },
    storage: {
      local: { get: vi.fn(async key => ({ [key]: stored[key] })), set: vi.fn(async data => { Object.assign(stored, data); }), setAccessLevel: vi.fn(async () => {}) },
      session: { get: vi.fn(async key => ({[key]:stored[key]})), set: vi.fn(async data => Object.assign(stored,data)), remove: vi.fn(async key => delete stored[key]), setAccessLevel: vi.fn(async () => {}) },
    },
    windows: { create: vi.fn(async () => ({ id: 8 })) },
    tabs: { sendMessage: vi.fn(async () => ({opened:true})), create: vi.fn(async () => ({ id: 7 })), get: vi.fn(async () => ({ status: 'complete' })), update: vi.fn(async () => ({})) },
    scripting: { executeScript: vi.fn(async () => [{ result: { filled: true } }]) },
  };
  vi.stubGlobal('chrome', chromeMock);
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ status: 'ok' }) })));
  await import('./background.js');
});
afterEach(() => vi.unstubAllGlobals());
const sender = { id: 'test-extension', url: 'chrome-extension://test-extension/popup.html' };
const message = { type: 'review-in-manager', url: 'https://civitai.com/models/123?modelVersionId=456', category: 'loras' };
const send = () => new Promise(resolve => listener(message, sender, resolve));

it('hands off to a new local review tab and persists a receipt, with no remote requests', async () => {
  expect(await send()).toEqual({ ready: true });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe('http://127.0.0.1:8189/api/lm/health-check');
  expect(chromeMock.tabs.create).toHaveBeenCalledWith({ url: 'http://127.0.0.1:8189/loras', active: false });
  expect(chromeMock.scripting.executeScript.mock.calls[0][0].args).toEqual([message.url, 'http://127.0.0.1:8189/loras']);
  expect(stored.lastHandoff).toMatchObject({ state: 'ready_for_review', tabId: 7, url: message.url });
});
it('rejects page senders and persists a recoverable unavailable-manager failure', async () => {
  const respond = vi.fn();
  expect(listener(message, { ...sender, url: 'https://evil.test/' }, respond)).toBeUndefined();
  expect(respond).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'wrong-service' }) });
  expect(await send()).toMatchObject({ error: expect.stringContaining('ready LoRA Manager') });
  expect(stored.lastHandoff.state).toBe('failed'); expect(chromeMock.tabs.create).not.toHaveBeenCalled();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(await send()).toEqual({ ready: true });
});

it('opens a compact companion popup without navigating the source tab from a validated top-level Civitai page without networking', async () => {
  expect(chromeMock.storage.local.setAccessLevel).toHaveBeenCalledWith({ accessLevel: 'TRUSTED_CONTEXTS' });
  expect(chromeMock.storage.session.setAccessLevel).toHaveBeenCalledWith({ accessLevel: 'TRUSTED_CONTEXTS' });
  chromeMock.tabs.get.mockResolvedValue({ url: message.url });
  const result = await new Promise(resolve => listener({ type: 'open-model-companion', url: message.url }, { id: sender.id, url: message.url, tab: { id: 42 }, frameId: 0 }, resolve));
  expect(result).toEqual({ opened: true });
  const url = new URL(chromeMock.tabs.sendMessage.mock.calls[0][1].url);
  expect(url.protocol).toBe('chrome-extension:'); expect(url.host).toBe(sender.id);
  expect(url.pathname).toBe('/popup.html'); expect(url.searchParams.get('model')).toBe(message.url);
  expect(chromeMock.tabs.sendMessage).toHaveBeenCalledWith(42, { type:'show-companion-overlay', url:url.href }, {frameId:0});
  expect(chromeMock.windows.create).not.toHaveBeenCalled();
  expect(chromeMock.tabs.create).not.toHaveBeenCalled();
  expect(chromeMock.tabs.update).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled(); expect(chromeMock.scripting.executeScript).not.toHaveBeenCalled();
});

it('rejects forged, subframe, and stale model entry points', async () => {
  chromeMock.tabs.get.mockResolvedValue({ url: 'https://evil.test/' });
  for (const candidate of [
    { url: 'https://evil.test/', frameId: 0 },
    { url: 'https://civitai.com.evil.test/models/123', frameId: 0 },
    { url: message.url, frameId: 1 },
    { url: message.url, frameId: 0 },
  ]) {
    const result = await new Promise(resolve => listener({ type: 'open-model-companion', url: message.url }, { id: sender.id, tab: { id: 42 }, ...candidate }, resolve));
    expect(result.error).toBeTruthy();
  }
  expect(chromeMock.tabs.create).not.toHaveBeenCalled(); expect(chromeMock.windows.create).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
});

it('opens a model after same-document navigation leaves the sender URL at the listing', async () => {
  const current = 'https://civitai.red/models/123/example-model';
  chromeMock.tabs.get.mockResolvedValue({ url: current });
  const result = await new Promise(resolve => listener({ type: 'open-model-companion', url: current },
    { id: sender.id, url: 'https://civitai.red/models', tab: { id: 42 }, frameId: 0 }, resolve));
  expect(result).toEqual({ opened: true });
  expect(chromeMock.tabs.sendMessage).toHaveBeenCalledWith(42, {type:'show-companion-overlay', url:expect.stringContaining('model=https%3A%2F%2Fcivitai.red%2Fmodels%2F123')}, {frameId:0});
  expect(chromeMock.windows.create).not.toHaveBeenCalled();
});

it('allows the extension-owned review tab, but not another extension page, to hand off', async () => {
  const result = await new Promise(resolve => listener(message, { ...sender, url: sender.url + '?model=' + encodeURIComponent(message.url) }, resolve));
  expect(result).toEqual({ ready: true });
  const respond = vi.fn();
  expect(listener(message, { ...sender, url: sender.url.replace('popup.html', 'other.html') }, respond)).toBeUndefined();
  expect(respond).not.toHaveBeenCalled();
});

it('allows page installed flags but keeps mutation privileges and tokens in extension-owned contexts', async () => {
  chromeMock.tabs.get.mockResolvedValue({ url: 'https://civitai.com/' });
  const page = { id: sender.id, url: 'https://civitai.com/', tab: { id: 42 }, frameId: 0 };
  const request = payload => new Promise(resolve => listener({ type: 'lm-operation', payload }, page, resolve));
  expect(await request({ operation: 'download', model_id: 1, version_id: 2 })).toMatchObject({ error: expect.any(String) });
  expect(fetch).not.toHaveBeenCalled();
  fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ results: [{ modelId: 1, versions: [{ versionId: 2 }], filePath: '/private' }] }) });
  expect(await request({ operation: 'status', model_ids: [1] })).toEqual({ items: [{ model_id: 1, version_ids: [2], in_library: true }] });
  expect(fetch.mock.calls[0][0]).toBe('http://127.0.0.1:8189/api/lm/check-models-exist?modelIds=1');
  expect(fetch.mock.calls[0][1].headers.Authorization).toBeUndefined();
});

it('carries only validated cover metadata into the popup URL', async () => {
  chromeMock.tabs.get.mockResolvedValue({ url: message.url });
  const open = preview => new Promise(resolve => listener({ type: 'open-model-companion', url: message.url, preview }, { id: sender.id, url: message.url, tab: { id: 42 }, frameId: 0 }, resolve));
  expect(await open({ title: 'Emerald landscape', thumbnail: 'https://image.civitai.com/neutral.jpeg', token: 'ignored' })).toEqual({ opened: true });
  let url = new URL(chromeMock.tabs.sendMessage.mock.calls.at(-1)[1].url);
  expect(url.searchParams.get('title')).toBe('Emerald landscape');
  expect(url.searchParams.get('thumbnail')).toBe('https://image.civitai.com/neutral.jpeg');
  expect(url.searchParams.has('token')).toBe(false);
  expect(await open({ thumbnail: 'https://tracker.example/cover' })).toEqual({ opened: true });
  url = new URL(chromeMock.tabs.sendMessage.mock.calls.at(-1)[1].url);
  expect(url.searchParams.has('thumbnail')).toBe(false);
});

it('authorizes only the issued frame session on the source tab and consumes it once', async () => {
  chromeMock.tabs.get.mockResolvedValue({url:message.url});
  await new Promise(resolve=>listener({type:'open-model-companion',url:message.url},{id:sender.id,url:message.url,tab:{id:42},frameId:0},resolve));
  const url = chromeMock.tabs.sendMessage.mock.calls.at(-1)[1].url;
  const nonce = new URL(url).searchParams.get('overlay');
  const claim = (tabId=42, key=nonce) => new Promise(resolve=>listener({type:'claim-companion-overlay',nonce:key},{id:sender.id,url,tab:{id:tabId},frameId:2},resolve));
  expect(await claim(43)).toMatchObject({error:expect.any(String)});
  expect(await claim(42,'forged')).toMatchObject({error:expect.any(String)});
  expect(await claim()).toEqual({ready:true,parentOrigin:'https://civitai.com'});
  expect(await claim()).toMatchObject({error:expect.any(String)});
});
it('opens the page overlay for an extension toolbar request without creating a window or tab',async()=>{
  chromeMock.tabs.get.mockResolvedValue({url:message.url});
  expect(await new Promise(resolve=>listener({type:'open-model-companion',url:message.url,tabId:42},sender,resolve))).toEqual({opened:true});
  expect(chromeMock.tabs.sendMessage).toHaveBeenCalled();
  expect(chromeMock.tabs.create).not.toHaveBeenCalled(); expect(chromeMock.windows.create).not.toHaveBeenCalled();
});
