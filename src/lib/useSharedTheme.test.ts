import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useSharedTheme } from './useSharedTheme';

beforeEach(()=>window.localStorage.clear());
afterEach(()=>vi.restoreAllMocks());
it('loads the shared choice without writing an older device cache over it', async()=>{
  window.localStorage.setItem('lorasuite:theme:v1','rose');
  const engine={getThemePreference:vi.fn(async()=>({theme:'ocean',updated_at:2})),setThemePreference:vi.fn()};
  const {result}=renderHook(()=>useSharedTheme(engine));
  await waitFor(()=>expect(result.current.theme).toBe('ocean'));
  expect(engine.setThemePreference).not.toHaveBeenCalled();
  expect(window.localStorage.getItem('lorasuite:theme:v1')).toBe('ocean');
});
it('seeds a legacy cache only if no shared theme exists',async()=>{
  window.localStorage.setItem('lorasuite:theme:v1','rose');
  const engine={getThemePreference:vi.fn(async()=>({theme:null,updated_at:0})),setThemePreference:vi.fn(async()=>({theme:'rose',updated_at:1}))};
  renderHook(()=>useSharedTheme(engine));
  await waitFor(()=>expect(engine.setThemePreference).toHaveBeenCalledWith('rose',true));
});
it('ignores an old read arriving after a selection and serializes rapid selections',async()=>{
  let finishRead!: (value:{theme:string,updated_at:number})=>void;
  let finishWrite!:()=>void;
  const engine={getThemePreference:vi.fn(()=>new Promise<{theme:string,updated_at:number}>(resolve=>{finishRead=resolve;})),setThemePreference:vi.fn(async(theme:string)=>{if(theme==='acid')await new Promise<void>(resolve=>{finishWrite=resolve;});return {theme,updated_at:3};})};
  const {result}=renderHook(()=>useSharedTheme(engine));
  await act(async()=>{result.current.selectTheme('acid');result.current.selectTheme('nebula');});
  expect(engine.setThemePreference).toHaveBeenCalledTimes(1);
  await act(async()=>{finishRead({theme:'rose',updated_at:1});finishWrite();});
  await waitFor(()=>expect(engine.setThemePreference).toHaveBeenLastCalledWith('nebula'));
  expect(result.current.theme).toBe('nebula');
});
it('picks up a choice made in another client on focus',async()=>{
  const engine={getThemePreference:vi.fn(async()=>({theme:'ocean',updated_at:1})),setThemePreference:vi.fn()};
  const {result}=renderHook(()=>useSharedTheme(engine));
  await waitFor(()=>expect(result.current.theme).toBe('ocean'));
  engine.getThemePreference.mockResolvedValue({theme:'synthwave',updated_at:2});
  act(()=>window.dispatchEvent(new Event('focus')));
  await waitFor(()=>expect(result.current.theme).toBe('synthwave'));
});
