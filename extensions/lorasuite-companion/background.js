import { checkManager, managerAddress, managerOperation as directOperation } from './manager-client.js';
import { managerReviewURL, pageRoute, prefillManagerReview } from './routes.js';
import { cleanPreview } from './preview.js';

// Content scripts never receive access to pairing tokens or capture drafts.
// Set this at worker startup as well as popup startup (the page button can be
// the first entry point in a newly installed profile).
const privateStorage = Promise.all([
  chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' }),
  chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' }),
]);
// Keep a failed initialization observable on the next action, not unhandled.
void privateStorage.catch(() => {});
let handoffBusy = false;
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message?.type === 'open-model-companion') {
    void openCompanion(message, sender).then(respond).catch(error => respond({ error: error.message }));
    return true;
  }
  let popup = false;
  try {
    const url = new URL(sender.url); const expected = new URL(chrome.runtime.getURL('popup.html'));
    popup = url.protocol === expected.protocol && url.host === expected.host && url.pathname === expected.pathname;
  } catch { /* Untrusted sender. */ }
  if (popup && message?.type === 'claim-companion-overlay') {
    void claimOverlay(message, sender).then(respond).catch(error => respond({ error: error.message }));
    return true;
  }
  if (message?.type === 'lm-operation') {
    void managerOperation(message, sender, popup).then(respond).catch(error => respond({ error: error.message }));
    return true;
  }
  if (!popup || message?.type !== 'review-in-manager') return;
  if (handoffBusy) { respond({ error: 'A model handoff is already opening' }); return; }
  handoffBusy = true;
  void openReview(message).then(result => respond(result)).catch(error => respond({ error: error.message }))
    .finally(() => { handoffBusy = false; });
  return true;
});

async function openCompanion(message, sender) {
  await privateStorage;
  const fromToolbar = sender.url === chrome.runtime.getURL('popup.html');
  const tabId = fromToolbar ? message.tabId : sender.tab?.id;
  const tab = tabId ? await chrome.tabs.get(tabId) : null;
  const origin = new URL(fromToolbar ? tab?.url : sender.url).origin;
  if ((!fromToolbar && sender.frameId !== 0) || !tabId || !['https://civitai.com', 'https://www.civitai.com', 'https://civitai.red', 'https://www.civitai.red', 'https://civarchive.com', 'https://www.civarchive.com'].includes(origin)) throw new Error('Use the button on a Civitai model page');
  const selected = pageRoute(message.url);
  // A content script's sender URL can retain its original document URL after
  // pushState navigation. Validate the live tab's origin, not its old route.
  // A card may deliberately select another model on that same trusted site.
  if (!['model', 'recipe'].includes(selected.kind) || new URL(tab.url).origin !== origin || new URL(selected.url).origin !== origin) throw new Error('Page changed. Click its button again.');
  const url = new URL(chrome.runtime.getURL('popup.html'));
  url.searchParams.set('model', selected.url);
  const preview = cleanPreview(message.preview);
  if (preview.title) url.searchParams.set('title', preview.title);
  if (preview.thumbnail) url.searchParams.set('thumbnail', preview.thumbnail);
  const nonce = crypto.randomUUID();
  url.searchParams.set('overlay', nonce);
  const key = `overlay:${tabId}`;
  const previous = (await chrome.storage.session.get(key))[key];
  await chrome.storage.session.set({ [key]: { nonce, origin, model: selected.url, expires: Date.now() + 60000 } });
  try {
    const result = await chrome.tabs.sendMessage(tabId, { type: 'show-companion-overlay', url: url.href }, { frameId: 0 });
    if (!result?.opened || result.reused) {
      if (previous) await chrome.storage.session.set({ [key]: previous });
      else await chrome.storage.session.remove(key);
    }
    if (!result?.opened) throw new Error(result?.error || 'Could not open the page popup. Refresh the page and try again.');
    return { opened: true };
  } catch (error) {
    if (previous) await chrome.storage.session.set({ [key]: previous });
    else await chrome.storage.session.remove(key);
    throw error;
  }
}

async function openReview(message) {
  await privateStorage;
  const model = pageRoute(message.url);
  if (model.kind !== 'model') throw new Error('Open a specific Civitai model page first');
  const { managerConnection } = await chrome.storage.local.get('managerConnection');
  const address = managerAddress(managerConnection?.url);
  let tab;
  try {
    await chrome.storage.local.set({ lastHandoff: { url: model.url, state: 'opening', updated: Date.now() } });
    await checkManager(address);
    const url = managerReviewURL(address, message.category);
    tab = await chrome.tabs.create({ url, active: false });
    const deadline = Date.now() + 8000;
    let complete = false;
    while (Date.now() < deadline) {
      const current = await chrome.tabs.get(tab.id);
      if (current.status === 'complete') { complete = true; break; }
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    if (!complete) throw new Error('LoRA Manager page is still loading. Retry when it is available.');
    const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: prefillManagerReview, args: [model.url, url] });
    if (!result?.result?.filled) throw new Error('Model review could not be prepared');
    await chrome.storage.local.set({ lastHandoff: { url: model.url, state: 'ready_for_review', tabId: tab.id, updated: Date.now() } });
    await chrome.tabs.update(tab.id, { active: true });
    return { ready: true };
  } catch (error) {
    await chrome.storage.local.set({ lastHandoff: { url: model.url, state: 'failed', error: error.message, tabId: tab?.id, updated: Date.now() } });
    throw error;
  }
}


async function managerOperation(message, sender, popup) {
  await privateStorage;
  const payload = message.payload;
  if (!payload || typeof payload !== 'object') throw new Error('Missing operation');
  if (!popup) {
    const origin = new URL(sender.url).origin;
    if (sender.frameId !== 0 || !sender.tab?.id || !['https://civitai.com', 'https://www.civitai.com', 'https://civitai.red', 'https://www.civitai.red', 'https://civarchive.com', 'https://www.civarchive.com'].includes(origin)) throw new Error('Untrusted page');
    const current = await chrome.tabs.get(sender.tab.id);
    if (new URL(current.url).origin !== origin) throw new Error('Page changed');
    // Page scripts may only ask for local installed flags. Mutating controls
    // live in the extension-owned review page, never in page-authored HTML.
    if (payload.operation !== 'status') throw new Error('Open the companion to manage downloads');
  }
  const { managerConnection } = await chrome.storage.local.get('managerConnection');
  return directOperation(managerConnection?.url, payload);
}

async function claimOverlay(message, sender) {
  await privateStorage;
  const url = new URL(sender.url);
  const key = `overlay:${sender.tab?.id}`;
  const session = (await chrome.storage.session.get(key))[key];
  if (!sender.tab?.id || !sender.frameId || !session || session.expires < Date.now()
      || session.nonce !== message.nonce || url.searchParams.get('overlay') !== session.nonce
      || url.searchParams.get('model') !== session.model) throw new Error('Reopen the companion from the page button.');
  const tab = await chrome.tabs.get(sender.tab.id);
  if (new URL(tab.url).origin !== session.origin) throw new Error('Source page changed.');
  await chrome.storage.session.remove(key);
  return { ready: true, parentOrigin: session.origin };
}
