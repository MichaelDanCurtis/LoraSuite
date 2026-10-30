// Inert public-page fixtures; no remote browser or network requests.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
let root;
let clicks;
const trustedClick = () => ({ isTrusted: true, preventDefault: vi.fn(), stopPropagation: vi.fn() });
beforeEach(() => {
  vi.resetModules(); vi.useFakeTimers(); root = undefined; clicks = new Map();
  document.body.innerHTML = '<main><article><a href="/models/123?modelVersionId=456">Installed fixture</a></article><article><a href="/models/789">Missing fixture</a></article><button id="site-download">Original download</button></main>';
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  const original = Element.prototype.attachShadow;
  vi.spyOn(Element.prototype, 'attachShadow').mockImplementation(function(options) { root = original.call(this, options); return root; });
  const add = EventTarget.prototype.addEventListener;
  vi.spyOn(EventTarget.prototype, 'addEventListener').mockImplementation(function(type, listener, options) {
    if (type === 'click') clicks.set(this, listener);
    return add.call(this, type, listener, options);
  });
  vi.stubGlobal('location', new URL('https://civitai.com/models/123?modelVersionId=456'));
  // jsdom anchor resolution uses the document origin, independently of location.
  for (const a of document.querySelectorAll('a')) a.href = 'https://civitai.com' + a.getAttribute('href');
  vi.stubGlobal('chrome', { runtime: { sendMessage: vi.fn(async message => message.type === 'lm-operation'
    ? { items: [{ model_id: 123, version_ids: [456], in_library: true }, { model_id: 789, version_ids: [], in_library: false }] } : { opened: true }) } });
});
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('shows installed version badges, ignores untrusted clicks and follows SPA navigation', async () => {
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  expect(root.host.parentNode).toBe(document.querySelector('main')); expect(root.host.shadowRoot).toBeNull();
  expect(document.querySelector('article button').textContent).toBe('✓ In LM');
  root.querySelector('button').click();
  expect(chrome.runtime.sendMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'open-model-companion' }));
  root.querySelector('button[aria-label]').click(); expect(root.host.isConnected).toBe(false);
  await vi.advanceTimersByTimeAsync(1000); expect(root.host.isConnected).toBe(false);
  vi.stubGlobal('location', new URL('https://civitai.com/search/models'));
  await vi.advanceTimersByTimeAsync(1000); expect(root.host.isConnected).toBe(true); expect(root.querySelector('button').hidden).toBe(true);
  expect(document.getElementById('site-download')).toBeTruthy();
});
it('does not touch an unpermitted host', async () => {
  vi.stubGlobal('location', new URL('https://civitai.com.evil.test/models/123'));
  await import('./civitai-button.js'); expect(root).toBeUndefined();
});
it('restores hidden cards when the user shows installed items or connection fails', async () => {
  vi.stubGlobal('location', new URL('https://civarchive.com/'));
  for (const a of document.querySelectorAll('a')) a.href = a.href.replace('civitai.com', 'civarchive.com');
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  const hide = root.querySelector('[aria-pressed]');
  await clicks.get(hide)(trustedClick()); await vi.advanceTimersByTimeAsync(1);
  expect(document.querySelector('article').style.display).toBe('none');
  chrome.runtime.sendMessage.mockResolvedValueOnce({ error: 'Connection lost' });
  await vi.advanceTimersByTimeAsync(11000);
  expect(document.querySelector('article').style.display).toBe('');
  expect(document.querySelector('article button')).toBeNull();
});
it('a trusted click opens the companion and recovers after an invalidated extension', async () => {
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  const button = root.querySelector('button');
  chrome.runtime.sendMessage.mockRejectedValueOnce(new Error('Extension context invalidated'));
  await clicks.get(button)(trustedClick());
  expect(root.querySelector('small').textContent).toContain('Reload the extension'); expect(button.disabled).toBe(false);
  await clicks.get(button)(trustedClick());
  expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith(expect.objectContaining({ type: 'open-model-companion', url: location.href }));
});

it('recognizes the observed Civitai card wrapper without hiding a whole grid row', async () => {
  vi.stubGlobal('location', new URL('https://civitai.red/models'));
  document.body.innerHTML = '<main><div data-index="0"><div class="CosmeticWrapper-module__wrapper"><div><div class="AspectRatioCard-module__content"><a href="https://civitai.red/models/123">Installed</a></div></div></div><div id="unrelated">Other content</div></div></main>';
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  const hide = root.querySelector('[aria-pressed]');
  await clicks.get(hide)(trustedClick()); await vi.advanceTimersByTimeAsync(1);
  expect(document.querySelector('[class*=CosmeticWrapper]').style.display).toBe('none');
  expect(document.querySelector('[data-index]').style.display).toBe('');
  expect(document.getElementById('unrelated').style.display).toBe('');
});

it('recognizes CivArchive linked cards without hiding adjacent entries', async () => {
  vi.stubGlobal('location', new URL('https://civarchive.com/'));
  document.body.innerHTML = '<main><div class="flex md:grid"><div class="flex-shrink-0"><a class="block group relative rounded-lg" href="https://civarchive.com/models/123?modelVersionId=456">Installed</a></div><div id="other">Other</div></div></main>';
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  await clicks.get(root.querySelector('[aria-pressed]'))(trustedClick()); await vi.advanceTimersByTimeAsync(1);
  expect(document.querySelector('.flex-shrink-0').style.display).toBe('none');
  expect(document.getElementById('other').style.display).toBe('');
});

it('shows card-click failures on the clicked button and preserves them through status polling', async () => {
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  const badge = document.querySelectorAll('article button')[1];
  chrome.runtime.sendMessage.mockImplementation(async message => message.type === 'open-model-companion'
    ? { error: 'Could not create tab' } : { items: [{ model_id: 789, version_ids: [], in_library: false }] });
  await clicks.get(badge)(trustedClick());
  expect(badge.textContent).toBe('Could not open — reload page');
  expect(badge.title).toContain('Could not create tab');
  await vi.advanceTimersByTimeAsync(11000);
  expect(badge.textContent).toBe('Could not open — reload page');
  expect(root.querySelector('small').textContent).toContain('Could not create tab');
  expect(badge.disabled).toBe(false);
});

it('shows immediate card feedback and recovers when the worker never responds', async () => {
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  const badge = document.querySelectorAll('article button')[1];
  chrome.runtime.sendMessage.mockImplementation(message => message.type === 'open-model-companion'
    ? new Promise(() => {}) : Promise.resolve({ items: [] }));
  const click = clicks.get(badge)(trustedClick());
  expect(badge.textContent).toBe('Opening companion…'); expect(badge.disabled).toBe(true);
  await vi.advanceTimersByTimeAsync(12000); await click;
  expect(badge.disabled).toBe(false);
  expect(badge.textContent).toBe('Could not open — reload page');
  expect(badge.title).toContain('did not respond');
});

it('passes the clicked card cover instead of the neighbouring model image', async () => {
  document.querySelectorAll('article')[0].insertAdjacentHTML('afterbegin', '<img src="https://image.civitai.com/first.jpeg">');
  document.querySelectorAll('article')[1].insertAdjacentHTML('afterbegin', '<img src="https://image.civitai.com/second.jpeg">');
  await import('./civitai-button.js'); await vi.advanceTimersByTimeAsync(1);
  await clicks.get(document.querySelectorAll('article button')[1])(trustedClick());
  expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith({ type: 'open-model-companion', url: 'https://civitai.com/models/789', preview: { title: 'Missing fixture', thumbnail: 'https://image.civitai.com/second.jpeg' } });
});
