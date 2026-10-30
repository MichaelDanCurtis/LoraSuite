// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { capturePage, engineURL } from './capture.js';

describe('private companion', () => {
  it('only permits a loopback engine', () => {
    expect(engineURL('http://127.0.0.1:8766')).toBe('http://127.0.0.1:8766');
    for (const url of ['https://example.org', 'http://127.0.0.1.evil.org', 'http://user:secret@127.0.0.1', 'http://127.0.0.1/path']) expect(() => engineURL(url)).toThrow();
  });
  it('collects visible references only without fetching or injecting HTML', () => {
    document.body.innerHTML = '<a href="https://example.org/a.safetensors?token=secret">Adapter</a><video></video><a href="https://example.org/a.mp3">Audio</a>';
    for (const el of document.querySelectorAll('a,video')) el.getClientRects = () => [{ width: 200 }];
    const result = capturePage();
    expect(result.some(item => item.kind === 'model' && item.url === 'https://example.org/a.safetensors')).toBe(true);
    expect(result.some(item => item.kind === 'audio')).toBe(true);
    expect(result.some(item => item.kind === 'video')).toBe(false);
    expect(JSON.stringify(result)).not.toContain('secret');
  });
  it('has no broad host, cookies, downloads, or external messaging permissions', () => {
    const manifest = JSON.parse(readFileSync('extensions/lorasuite-companion/manifest.json', 'utf8'));
    const civitai = ['https://civitai.com/*', 'https://www.civitai.com/*', 'https://civitai.red/*', 'https://www.civitai.red/*', 'https://civarchive.com/*', 'https://www.civarchive.com/*'];
    expect(manifest.host_permissions).toEqual(['http://127.0.0.1/*', ...civitai]);
    expect(manifest.permissions).toEqual(['activeTab', 'scripting', 'storage']);
    expect(manifest.externally_connectable).toBeUndefined();
    expect(manifest.web_accessible_resources).toEqual([{resources:['popup.html'], matches:civitai}]);
    expect(manifest.content_scripts).toEqual([{ matches: civitai, js: ['overlay.js', 'civitai-button.js'], run_at: 'document_idle' }]);
  });
});
