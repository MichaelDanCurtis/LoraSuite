// Independent implementation; no LM extension source or assets are used.
// Runs only following an explicit toolbar click, and never fetches a resource.
export function capturePage() {
  const clean = value => {
    if (typeof value !== 'string' || !value) return null;
    try {
      const url = new URL(value, location.href);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
      const query = new URLSearchParams();
      for (const key of ['modelVersionId', 'id', 't', 'p', 'topic', 'thread', 'page']) {
        const value = url.searchParams.get(key);
        if (/^[0-9]{1,20}$/.test(value || '')) query.set(key, value);
      }
      url.search = ''; url.hash = '';
      url.search = query.toString();
      return url.href;
    } catch { return null; }
  };
  const page = clean(location.href);
  if (!page) throw new Error('Open an HTTP(S) webpage first.');
  const found = new Map();
  const add = (kind, url, title) => {
    const cleaned = clean(url);
    if (cleaned && found.size < 100) found.set(`${kind}:${cleaned}`, { kind, url: cleaned, page_url: page, title: (title || document.title || kind).slice(0, 300) });
  };
  const isCivitai = /(^|\.)civitai\.(com|red)$/.test(location.hostname);
  const modelPage = isCivitai && /^\/models\/\d+/.test(location.pathname);
  add(modelPage ? 'model' : 'page', page, document.title);
  for (const el of document.querySelectorAll('img,video,audio,a[href]')) {
    if (!el.getClientRects().length) continue;
    if (el.tagName === 'IMG') {
      if (el.naturalWidth >= 128 && el.naturalHeight >= 128) add('image', el.currentSrc || el.src, el.alt);
    } else if (el.tagName === 'VIDEO' || el.tagName === 'AUDIO') {
      add(el.tagName.toLowerCase(), el.currentSrc || el.src || el.querySelector('source')?.src, el.getAttribute('aria-label'));
    } else {
      const pathname = (() => { try { return new URL(el.href).pathname.toLowerCase(); } catch { return ''; } })();
      if (/\.(safetensors|ckpt|gguf|pt|pth)$/.test(pathname)) add('model', el.href, el.textContent);
      else if (/\.(png|jpg|jpeg|webp|avif)$/.test(pathname)) add('image', el.href, el.textContent);
      else if (/\.(mp4|webm|mov|m4v)$/.test(pathname)) add('video', el.href, el.textContent);
      else if (/\.(wav|mp3|m4a|flac|ogg)$/.test(pathname)) add('audio', el.href, el.textContent);
    }
  }
  return [...found.values()];
}

export function engineURL(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('Use a loopback engine address, e.g. http://127.0.0.1:8766');
  return url.origin;
}
