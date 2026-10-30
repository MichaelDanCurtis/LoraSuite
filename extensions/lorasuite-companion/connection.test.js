import { afterEach, expect, it, vi } from 'vitest';
import { findEngines } from './connection.js';
afterEach(() => vi.unstubAllGlobals());
it('finds only LoraSuite pairing challenges without credentials or remote requests', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => ({ status: 401, json: async () => ({ detail: url.includes(':8767') ? "Pair this extension in LoraSuite's Model Library" : 'another-service' }) })));
  expect(await findEngines('http://127.0.0.1:8767')).toEqual(['http://127.0.0.1:8767']);
  expect(fetch).toHaveBeenCalledTimes(3);
  for (const [url, options] of fetch.mock.calls) {
    expect(new URL(url).hostname).toBe('127.0.0.1'); expect(new URL(url).pathname).toBe('/library/companion/context');
    expect(options.credentials).toBe('omit'); expect(options.headers).toBeUndefined();
  }
});
it('returns multiple instances for explicit choice and handles offline apps', async () => {
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.includes(':8765')) throw new Error('Offline');
    return { status: 401, json: async () => ({ detail: "Pair this extension in LoraSuite's Model Library" }) };
  }));
  expect(await findEngines()).toHaveLength(2);
  await expect(findEngines('https://remote.example')).rejects.toThrow('loopback');
});
