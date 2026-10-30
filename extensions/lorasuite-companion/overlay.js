// Runs in Chrome's isolated content-script world. The page never receives
// extension credentials or a callable download API.
(() => {
  let host, dialog, frame, busy = true, model, previousFocus;
  function hide() { dialog?.close(); previousFocus?.focus(); }
  function show() { previousFocus = document.activeElement; if (!dialog.open) dialog.showModal(); frame.focus(); }
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id || message?.type !== 'show-companion-overlay') return;
    try {
      const url = new URL(message.url);
      const expected = new URL(chrome.runtime.getURL('popup.html'));
      if (url.protocol !== expected.protocol || url.host !== expected.host || url.pathname !== expected.pathname || !url.searchParams.has('overlay')) throw new Error('Invalid companion URL');
      const next = url.searchParams.get('model');
      if (frame && host.isConnected && (model === next || busy)) {
        show();
        respond(model !== next ? { error: 'Finish the current companion action before opening another model.' } : { opened: true, reused: true });
        return;
      }
      host?.remove();
      host = document.createElement('div');
      const root = host.attachShadow({ mode: 'closed' });
      const style = document.createElement('style');
      style.textContent = `dialog{padding:0;border:1px solid var(--companion-border-strong,#466d57);border-radius:18px;background:var(--companion-bg,#0d1211);color:var(--companion-text,#edf4f0);width:min(500px,calc(100vw - 24px));height:min(800px,calc(100dvh - 32px));max-width:none;max-height:none;box-shadow:0 24px 100px #0009;overflow:hidden}dialog::backdrop{background:#050d0bc7;backdrop-filter:blur(6px)}header{display:flex;align-items:center;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--companion-border-strong,#293832);font:12px system-ui;color:var(--companion-text,#bad2c4)}button{border:0;border-radius:6px;padding:3px 9px;background:var(--companion-panel,#213b2d);color:var(--companion-text,#e4f6ec);font:22px system-ui;cursor:pointer}button:focus-visible{outline:2px solid var(--companion-accent,#a0efce)}iframe{display:block;width:100%;height:calc(100% - 51px);border:0;background:var(--companion-bg,#0d1211)}`;
      dialog = document.createElement('dialog'); dialog.setAttribute('aria-label', 'LoRA Suite Companion');
      const header = document.createElement('header');
      const label = document.createElement('span'); label.textContent = 'LoRA Suite Companion';
      const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label', 'Dismiss companion');
      close.addEventListener('click', event => { if (event.isTrusted) hide(); });
      header.append(label, close);
      frame = document.createElement('iframe'); frame.title = 'LoRA Suite download controls'; frame.src = url.href;
      model = next; busy = true;
      dialog.append(header, frame); root.append(style, dialog); document.documentElement.append(host);
      dialog.addEventListener('cancel', event => { event.preventDefault(); hide(); });
      dialog.addEventListener('click', event => { if (event.isTrusted && event.target === dialog) { const r=dialog.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)hide(); } });
      show(); respond({ opened: true });
    } catch (error) { respond({ error: error.message }); }
  });
  window.addEventListener('message', event => {
    if (!event.isTrusted || !frame || event.source !== frame.contentWindow || event.origin !== new URL(chrome.runtime.getURL('popup.html')).origin) return;
    if (event.data?.type === 'companion-busy' && typeof event.data.busy === 'boolean') busy = event.data.busy;
    if (event.data?.type === 'companion-dismiss') hide();
    if (event.data?.type === 'companion-theme') {
      for (const key of ['bg','panel','text','border-strong','accent']) {
        const color = event.data.palette?.[key];
        if (typeof color === 'string' && /^#[0-9a-f]{6}$/i.test(color)) host.style.setProperty(`--companion-${key}`,color);
      }
    }
  });
})();
