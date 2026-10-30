// Public display data only. Page-provided URLs never become API destinations.
export function cleanPreview(value = {}) {
  value = value && typeof value === 'object' ? value : {};
  const title = typeof value.title === 'string' ? value.title.trim().slice(0, 160) : '';
  let thumbnail = '';
  try {
    if (typeof value.thumbnail === 'string' && value.thumbnail.length <= 2048) {
      const url = new URL(value.thumbnail);
      if (url.protocol === 'https:' && url.hostname === 'image.civitai.com' && !url.port && !url.username && !url.password && !url.search && !url.hash) thumbnail = url.href;
    }
  } catch { /* A missing or unsupported cover uses the local fallback. */ }
  return { title, thumbnail };
}

// Serialized by chrome.scripting for an explicit toolbar action.
export function readPagePreview() {
  const image = document.querySelector('main img[src*="image.civitai.com"]');
  return {
    title: document.querySelector('main h1, h1')?.textContent || document.title,
    thumbnail: image?.currentSrc || image?.src || document.querySelector('meta[property="og:image"]')?.content || '',
  };
}
