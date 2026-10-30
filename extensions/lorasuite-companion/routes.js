// Explicit product routing; URLs are untrusted data, not executable instructions.
export function pageRoute(value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Open an HTTP(S) webpage without embedded credentials');
  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  if (['civitai.com', 'civitai.red', 'civarchive.com'].includes(host)) {
    const image = url.pathname.match(/^\/images\/([1-9]\d*)(?:\/|$)/);
    if (image && !Number.isSafeInteger(Number(image[1]))) throw new Error('Invalid image ID');
    if (image) return { kind: 'recipe', imageId: image[1], url: url.origin + '/images/' + image[1] };
    const model = url.pathname.match(/^\/models\/([1-9]\d*)(?:\/|$)/);
    const version = url.searchParams.get('modelVersionId');
    if (!model) return { kind: 'civitai', modelId: '', versionId: '', url: url.origin + url.pathname };
    if (!Number.isSafeInteger(Number(model[1])) || (version !== null && (!/^[1-9]\d*$/.test(version) || !Number.isSafeInteger(Number(version))))) throw new Error('Invalid Civitai model version');
    const clean = new URL(`/models/${model[1]}`, url.origin);
    if (version) clean.searchParams.set('modelVersionId', version);
    return { kind: 'model', modelId: model[1], versionId: version || '', url: clean.href };
  }
  const provider = ['instagram.com', 'x.com', 'twitter.com', 'tiktok.com'].find(domain => host === domain || host.endsWith('.' + domain));
  if (provider) return { kind: 'ingestion', provider, url: url.origin + url.pathname };
  const clean = new URL(url.origin + url.pathname);
  for (const key of ['id', 't', 'p', 'topic', 'thread', 'page']) {
    const value = url.searchParams.get(key);
    if (/^[0-9]{1,20}$/.test(value || '')) clean.searchParams.set(key, value);
  }
  return { kind: 'capture', url: clean.href };
}

export function managerReviewURL(value, category) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.hash) throw new Error('Invalid local LoRA Manager address');
  if (!['loras', 'checkpoints', 'embeddings'].includes(category)) throw new Error('Choose a model category');
  return `${url.origin}/${category}`;
}

// Injected only into the newly opened local LM tab. This uses ordinary visible
// controls and stops at URL review: no Next/Download, network request or login.
export async function prefillManagerReview(source, expectedLocation) {
  if (location.href.replace(/\/$/, '') !== expectedLocation.replace(/\/$/, '')) throw new Error('LoRA Manager navigated elsewhere; handoff stopped');
  const until = Date.now() + 10000;
  while (Date.now() < until) {
    const button = document.querySelector('button[data-action="download"]');
    const input = document.getElementById('modelUrl');
    const modal = document.getElementById('downloadModal');
    if (button && input && modal) {
      button.click();
      if (getComputedStyle(modal).display !== 'none') {
        input.value = source;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        return { filled: true };
      }
    }
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error('LoRA Manager download controls were not ready. Open Download and paste the saved model URL manually.');
}
