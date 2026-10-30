import { engineURL } from './capture.js';
export const themeIds = ['aurora','ocean','solar','graphite','nebula','rose','ember','arctic','midnight','copper','acid','synthwave'];
export function validTheme(value) {
  return value && themeIds.includes(value.theme) && Number.isSafeInteger(value.updated_at) && value.updated_at > 0;
}

// Read only public appearance data. No pairing tokens or credentials needed.
export async function readLatestTheme(preferred) {
  const addresses = [...new Set([preferred, 'http://127.0.0.1:8767', 'http://127.0.0.1:8766', 'http://127.0.0.1:8765'].filter(Boolean))];
  const results = await Promise.all(addresses.map(async address => {
    try {
      const response = await fetch(`${engineURL(address)}/library/theme`, {credentials:'omit',redirect:'error',signal:AbortSignal.timeout(1500)});
      if (!response.ok) return null;
      const value = await response.json();
      return validTheme(value) ? {theme:value.theme,updated_at:value.updated_at} : null;
    } catch { return null; }
  }));
  return results.filter(Boolean).sort((a,b)=>b.updated_at-a.updated_at)[0] || null;
}

export function followTheme(apply, preferred) {
  let stopped=false, busy=false, latest;
  const refresh=async()=>{
    if(stopped||busy||document.hidden)return;
    busy=true;
    try {
      const value=await readLatestTheme(preferred);
      if(!stopped&&value&&(!latest||value.updated_at>=latest.updated_at)) {
        latest=value; apply(value.theme);
        await chrome.storage.local.set({sharedTheme:value});
      }
    } catch { /* Keep the last selected theme when LoraSuite is closed. */ }
    finally {busy=false;}
  };
  void (async()=>{
    try {const {sharedTheme}=await chrome.storage.local.get('sharedTheme');if(!stopped&&validTheme(sharedTheme)){latest=sharedTheme;apply(latest.theme);}} catch { /* First run. */ }
    await refresh();
  })();
  const timer=setInterval(()=>void refresh(),5000);
  const focus=()=>void refresh(); window.addEventListener('focus',focus);
  return ()=>{stopped=true;clearInterval(timer);window.removeEventListener('focus',focus);};
}
