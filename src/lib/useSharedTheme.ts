import { useCallback, useEffect, useRef, useState } from 'react';
import { isAppTheme, type AppTheme } from '../components/ThemePicker';
import type { EngineClient } from './api';

const storageKey = 'lorasuite:theme:v1';
function cachedTheme(): AppTheme {
  const value = window.localStorage.getItem(storageKey);
  return isAppTheme(value) ? value : 'aurora';
}

export function useSharedTheme(engine: Pick<EngineClient, 'getThemePreference' | 'setThemePreference'>) {
  const [theme, setTheme] = useState<AppTheme>(cachedTheme);
  const [themeSyncError, setError] = useState('');
  const change = useRef(0);
  const pending = useRef(0);
  const writes = useRef(Promise.resolve());
  const apply = useCallback((value: AppTheme) => {
    setTheme(value); window.localStorage.setItem(storageKey, value);
  }, []);

  useEffect(() => {
    let disposed = false, reading = false;
    const refresh = async () => {
      if (reading || pending.current || document.hidden) return;
      reading = true;
      const version = change.current;
      try {
        let result = await engine.getThemePreference();
        if (disposed || pending.current || version !== change.current) return;
        if (result.theme === null) result = await engine.setThemePreference(cachedTheme(), true);
        if (!disposed && !pending.current && version === change.current && isAppTheme(result.theme)) {
          apply(result.theme); setError('');
        }
      } catch { if (!disposed) setError('Using this device’s theme. Open an updated LoraSuite engine to sync.'); }
      finally { reading = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    const onFocus = () => void refresh();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => { disposed = true; clearInterval(timer); window.removeEventListener('focus', onFocus); document.removeEventListener('visibilitychange', onFocus); };
  }, [engine, apply]);

  const selectTheme = useCallback((value: AppTheme) => {
    const version = ++change.current;
    apply(value); pending.current++;
    writes.current = writes.current.then(async () => {
      try {
        await engine.setThemePreference(value);
        if (version === change.current) setError('');
      } catch {
        if (version === change.current) setError('Theme changed here, but could not sync. Check the engine connection and select it again.');
      } finally { pending.current--; }
    });
  }, [engine, apply]);
  return { theme, selectTheme, themeSyncError };
}
