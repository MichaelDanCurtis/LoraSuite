// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { managerReviewURL, pageRoute, prefillManagerReview } from './routes.js';

afterEach(() => vi.restoreAllMocks());

it('routes model versions, supported ingestion and unrelated sites separately', () => {
  expect(pageRoute('https://civitai.com/models/123/name?token=private&modelVersionId=456#x')).toEqual({ kind: 'model', modelId: '123', versionId: '456', url: 'https://civitai.com/models/123?modelVersionId=456' });
  expect(pageRoute('https://civitai.red/models/123/name').kind).toBe('model');
  expect(pageRoute('https://civitai.com/models').kind).toBe('civitai');
  for (const domain of ['instagram.com', 'www.x.com', 'mobile.twitter.com', 'tiktok.com']) expect(pageRoute(`https://${domain}/post`).kind).toBe('ingestion');
  expect(pageRoute('https://civitai.com.evil.test/models/123').kind).toBe('capture');
  expect(pageRoute('https://forum.example/viewtopic.php?t=123&page=2&token=secret').url).toBe('https://forum.example/viewtopic.php?t=123&page=2');
  for (const value of ['file:///private', 'https://user:secret@civitai.com/models/1', 'https://civitai.com/models/1?modelVersionId=oops']) expect(() => pageRoute(value)).toThrow();
});

it('keeps the manager destination strictly local and category bounded', () => {
  expect(managerReviewURL('http://127.0.0.1:8189/loras', 'checkpoints')).toBe('http://127.0.0.1:8189/checkpoints');
  for (const url of ['https://example.org', 'http://127.0.0.1.evil.test', 'http://user:pass@127.0.0.1', 'http://127.0.0.1/?token=x']) expect(() => managerReviewURL(url, 'loras')).toThrow();
  expect(() => managerReviewURL('http://127.0.0.1:8189', '../settings')).toThrow();
});

it('fills the local wizard but never clicks Next or downloads', async () => {
  document.body.innerHTML = '<button data-action="download">Download</button><div id="downloadModal" style="display:none"><textarea id="modelUrl"></textarea><button id="nextFromUrl">Next</button><button id="startDownloadBtn">Start</button></div>';
  document.querySelector('[data-action="download"]').onclick = () => { document.getElementById('downloadModal').style.display = 'block'; };
  const next = vi.fn(); const download = vi.fn(); const fetch = vi.spyOn(globalThis, 'fetch');
  document.getElementById('nextFromUrl').onclick = next;
  document.getElementById('startDownloadBtn').onclick = download;
  expect(await prefillManagerReview('https://civitai.com/models/123?modelVersionId=456', location.href)).toEqual({ filled: true });
  expect(document.getElementById('modelUrl').value).toContain('modelVersionId=456');
  expect(next).not.toHaveBeenCalled(); expect(download).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  await expect(prefillManagerReview('ignored', 'http://127.0.0.1:9999/elsewhere')).rejects.toThrow('navigated');
});
