import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { followTheme, readLatestTheme, themeIds } from './theme.js';
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
it('covers every theme in the shared app palette',()=>{
  const css=readFileSync('extensions/lorasuite-companion/themes.css','utf8');
  expect([...css.matchAll(/data-theme="([a-z]+)"/g)].map(match=>match[1])).toEqual(themeIds);
});
it('reads the latest public theme without any credentials or broader engine API',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>({theme:url.includes(':8767')?'rose':'ocean',updated_at:url.includes(':8767')?2:1})})));
  expect(await readLatestTheme()).toEqual({theme:'rose',updated_at:2});
  for(const [url,args] of fetch.mock.calls){expect(url).toMatch(/^http:\/\/127.0.0.1:876[567]\/library\/theme$/);expect(args.credentials).toBe('omit');expect(args.headers).toBeUndefined();}
});
it('rejects invalid theme data and non-loopback destinations',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({theme:'injected',updated_at:2})})));
  expect(await readLatestTheme('https://evil.test')).toBeNull();
  expect(fetch.mock.calls.every(([url])=>url.startsWith('http://127.0.0.1:'))).toBe(true);
});
it('keeps the last shared theme when LoraSuite is closed',async()=>{
  vi.useFakeTimers();
  vi.stubGlobal('chrome',{storage:{local:{get:async()=>({sharedTheme:{theme:'nebula',updated_at:4}}),set:vi.fn()}}});
  vi.stubGlobal('fetch',vi.fn(async()=>{throw new Error('Offline');}));
  const apply=vi.fn(); const stop=followTheme(apply);
  await vi.advanceTimersByTimeAsync(10);
  expect(apply).toHaveBeenLastCalledWith('nebula'); stop();
});
