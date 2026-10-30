import { followTheme } from './theme.js';
import { checkManager, findManagers, managerAddress, managerOperation, hasActiveTransfers } from './manager-client.js';
import { cleanPreview, readPagePreview } from './preview.js';
import { createManagerControls } from './manager-controls.js';
import { capturePage, engineURL } from './capture.js';
import { pageRoute } from './routes.js';
import { findEngines } from './connection.js';
const $ = id => document.getElementById(id);
const overlayNonce = new URL(location.href).searchParams.get('overlay');
let parentOrigin;
if (window.top !== window || overlayNonce) {
  const claim = overlayNonce && await chrome.runtime.sendMessage({ type: 'claim-companion-overlay', nonce: overlayNonce });
  if (!claim?.ready) {
    document.body.textContent = 'Reopen the companion using Add to LM on the page.';
    throw new Error('Unauthorized companion frame');
  }
  parentOrigin = claim.parentOrigin;
}
function reportBusy() { if (parentOrigin) window.parent.postMessage({ type: 'companion-busy', busy: running || hasActiveTransfers() }, parentOrigin); }
if (parentOrigin) {
  setInterval(reportBusy, 500);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); window.parent.postMessage({ type: 'companion-dismiss' }, parentOrigin); } });
}

$('companion-version').textContent = `v${chrome.runtime.getManifest?.().version || '—'}`;
document.body.dataset.connected = 'false';
let candidates = [];
let connection = {};
let managerURL = managerAddress();
let managerReady = false;
const fullPage = new URL(location.href).searchParams.has('model') || new URL(location.href).searchParams.has('standalone');
let route;
let activeTabId;
let running = false;
let managerControls;
const status = text => { $('status').textContent = text; };
function showPreview(value) {
  const preview = cleanPreview(value);
  $('preview-title').textContent = preview.title || (route?.kind === 'recipe' ? 'Image recipe' : `Model ${route?.modelId || ''}`);
  $('preview-kind').textContent = route?.kind === 'recipe' ? 'IMAGE RECIPE' : 'MODEL';
  const img = $('preview-image');
  img.hidden = true;
  img.onload = () => { img.hidden = false; };
  img.onerror = () => { img.hidden = true; img.removeAttribute('src'); };
  img.removeAttribute('src');
  if (preview.thumbnail) img.src = preview.thumbnail;
}
function syncConnection() {
  $('connection-status').textContent = connection.token ? `Paired with ${connection.engine}` : 'Project capture: LoraSuite is not paired (optional).';
  for (const button of document.querySelectorAll('[data-paired]')) button.disabled = running || !connection.token;
  for (const button of document.querySelectorAll('[data-manager]')) button.disabled = running || !managerReady || !fullPage;
  managerControls?.sync(running || !managerReady || !fullPage);
  $('send').disabled = running || !connection.token || !candidates.length;
}
async function request(path, body, authenticated = true) {
  const response = await fetch(`${engineURL(connection.engine)}/library/${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'omit', redirect: 'error',
    headers: { 'Content-Type': 'application/json', ...(authenticated ? { Authorization: `Bearer ${connection.token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : `LoraSuite returned ${response.status}`); }
  return response.json();
}
async function projects() {
  const list = await request('projects');
  $('project').replaceChildren();
  const placeholder = new Option('Choose a project', ''); $('project').append(placeholder);
  for (const project of list) $('project').append(new Option(project.name, project.id));
  const { captureDestination } = await chrome.storage.local.get('captureDestination');
  if (list.some(project => project.id === captureDestination?.project)) {
    $('project').value = captureDestination.project;
    if ([...$('output').options].some(option => option.value === captureDestination.output)) $('output').value = captureDestination.output;
  }
  if (route?.kind === 'capture') status(list.length ? 'Connected. Choose a project, then scan this page.' : 'Create a project in LoraSuite first.');
}
function action(id, task) {
  $(id).addEventListener('click', async () => {
    if (running) return;
    running = true; reportBusy();
    for (const button of document.querySelectorAll('button')) button.disabled = true;
    try { await task(); } catch (error) { status(error.message || 'Action failed'); }
    finally {
      running = false; reportBusy();
      for (const button of document.querySelectorAll('button')) button.disabled = false;
      $('send').disabled = !candidates.length;
      syncConnection();
    }
  });
}
async function connectManager(save = false) {
  const next = managerAddress($('manager-address').value);
  await checkManager(next);
  if (save) await chrome.storage.local.set({ managerConnection: { url: next } });
  managerURL = next; managerReady = true;
  managerControls?.reset();
  $('manager-status').textContent = `LoRA Manager connected`;
  $('manager-status').title = next;
  document.body.dataset.connected = 'true';
  $('open-manager').href = next + (route?.kind === 'recipe' ? '/recipes' : '/loras');
  $('open-manager').hidden = false;
  $('manager-connection').open = false;
}
action('connect-manager', async () => {
  if (hasActiveTransfers()) throw new Error('Wait for this tab’s transfers to finish before changing libraries.');
  managerReady = false;
  document.body.dataset.connected = 'false';
  $('open-manager').hidden = true;
  try { await connectManager(true); status('LoRA Manager connected. LoraSuite pairing is optional.'); }
  catch (error) { $('manager-status').textContent = error.message; throw error; }
});
action('find-manager', async () => {
  const addresses = await findManagers($('manager-address').value);
  $('manager-choices').replaceChildren(new Option('Choose your library', ''));
  for (const address of addresses) $('manager-choices').append(new Option(address, address));
  $('manager-choices-label').hidden = addresses.length < 2;
  if (addresses.length === 1) $('manager-address').value = addresses[0];
  status(addresses.length ? 'Choose the LM address, then Save and connect.' : 'No LoRA Manager found. Start standalone LM or ComfyUI with LM installed.');
});
$('manager-choices').addEventListener('change', () => { if ($('manager-choices').value) $('manager-address').value = $('manager-choices').value; });
action('open-companion-tab', async () => {
  if (!['model', 'recipe'].includes(route?.kind) || !activeTabId) throw new Error('Open a Civitai model or image page first.');
  let preview;
  try {
    const [result] = await chrome.scripting.executeScript({ target: { tabId: activeTabId }, func: readPagePreview });
    preview = cleanPreview(result?.result);
  } catch { /* A cover is optional. */ }
  const result = await chrome.runtime.sendMessage({ type: 'open-model-companion', tabId: activeTabId, url: route.url, preview });
  if (!result?.opened) throw new Error(result?.error || 'Refresh the source page and try again.');
  window.close();
});
window.addEventListener('beforeunload', event => {
  if (hasActiveTransfers() || running) { event.preventDefault(); event.returnValue = ''; }
});
action('find-engine', async () => {
  status('Looking for LoraSuite on this computer…');
  const addresses = await findEngines($('engine').value);
  $('engine-choices').replaceChildren(new Option('Choose a running LoraSuite', ''));
  for (const address of addresses) $('engine-choices').append(new Option(address, address));
  $('engine-choices-label').hidden = addresses.length < 2;
  if (addresses.length === 1) {
    $('engine').value = addresses[0];
    status('Found LoraSuite. Get a code from Model Library → Pair Chrome extension, then paste it above.');
  } else status(addresses.length ? 'More than one LoraSuite is running. Choose the engine for the app where you generated the code.' : 'No running LoraSuite found. Open the app, or enter its custom engine address above.');
});
$('engine-choices').addEventListener('change', () => { if ($('engine-choices').value) $('engine').value = $('engine-choices').value; });
async function saveDraft() {
  await chrome.storage.session.set({ captureDraft: { page: route?.url, candidates,
    selected: [...$('items').querySelectorAll('input:checked')].map(input => input.value) } });
}
function renderCandidates(selected = []) {
  $('items').replaceChildren();
  candidates.forEach((item, index) => {
    const row = document.createElement('label');
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = String(index); checkbox.checked = selected.includes(String(index));
    checkbox.addEventListener('change', () => { void saveDraft().catch(error => status(`Could not save selection: ${error.message}`)); });
    const title = document.createElement('span'); title.textContent = `${item.kind.toUpperCase()} · ${item.title}`;
    const source = document.createElement('small'); source.textContent = item.url;
    row.append(checkbox, title, source); $('items').append(row);
  });
  $('send').disabled = !candidates.length;
}
action('pair', async () => {
  const previous = connection;
  const next = { engine: engineURL($('engine').value) };
  connection = next;
  try {
    const result = await request('pair', { code: $('code').value.trim() }, false);
    next.token = result.token;
    await chrome.storage.local.set({ connection: next });
  } catch (error) { connection = previous; throw error; }
  $('code').value = ''; $('connection').open = false;
  if (route?.kind === 'capture') await projects();
  else status('Project capture paired. Model downloads use the separate LM connection.');
});
action('disconnect', async () => {
  await chrome.storage.local.remove('connection'); connection = {};
  $('connection').open = true;
  $('project').replaceChildren(new Option('Connect first', ''));
  status('Local connection forgotten. Use Revoke in LoraSuite to revoke its token too.');
});
action('load-projects', projects);
action('save-page', async () => {
  if (!['model', 'recipe'].includes(route?.kind)) throw new Error('Open a model or image page');
  if (!$('project').value) throw new Error('Choose a destination project');
  const result = await request('inbox', { items: [{ kind: route.kind, url: route.url, page_url: route.url,
    title: route.kind === 'model' ? `Model ${route.modelId}` : `Image recipe ${route.imageId}`,
    project_id: $('project').value, requested_output: $('output').value }] });
  status(`${result.added} reference saved; ${result.duplicates} already present. Review it in LoraSuite’s Model Library.`);
});
action('scan', async () => {
  if (route?.kind !== 'capture') throw new Error('Use the page-specific workflow shown above');
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || tab.id !== activeTabId || pageRoute(tab.url).url !== route.url) throw new Error('Page changed. Reopen the companion before scanning.');
  const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: capturePage });
  candidates = result.result || [];
  renderCandidates();
  await saveDraft();
  status(`${candidates.length} references found (maximum 100). Select only what you want to send.`);
});
action('send', async () => {
  if (route?.kind !== 'capture') throw new Error('Use the page-specific workflow shown above');
  if (!$('project').value) throw new Error('Choose a destination project');
  const selected = [...$('items').querySelectorAll('input:checked')].map(el => ({ ...candidates[Number(el.value)], project_id: $('project').value, requested_output: $('output').value }));
  if (!selected.length) throw new Error('Select at least one reference');
  const result = await request('inbox', { items: selected });
  status(`${result.added} queued; ${result.duplicates} already present. Open Model Library in LoraSuite to review.`);
});
action('review-model', async () => {
  if (route?.kind !== 'model') throw new Error('Open a specific Civitai model first');
  status('Opening the LoRA Manager download review…');
  const result = await chrome.runtime.sendMessage({ type: 'review-in-manager', url: route.url, category: $('model-category').value });
  if (!result?.ready) throw new Error(result?.error || 'No handoff confirmation received. Retry from this tab.');
  status('Ready in LoRA Manager. Review the version and files before downloading.');
});
for (const id of ['project', 'output']) $(id).addEventListener('change', () => {
  void chrome.storage.local.set({ captureDestination: { project: $('project').value, output: $('output').value } }).catch(error => status(`Could not save destination: ${error.message}`));
});
await chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
await chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
connection = (await chrome.storage.local.get('connection')).connection || {};
if (connection.engine) $('engine').value = connection.engine;
const savedManager = (await chrome.storage.local.get('managerConnection')).managerConnection;
if (savedManager?.url) $('manager-address').value = savedManager.url;
if (fullPage) document.body.classList.add('full-page');
$('open-companion-tab').hidden = fullPage;
try {
  const modelParameter = new URL(location.href).searchParams.get('model');
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTabId = tab?.id;
  route = new URL(location.href).searchParams.has('standalone') ? { kind: 'library' } : pageRoute(modelParameter || tab?.url || '');
  if (modelParameter) {
    if (!['model', 'recipe'].includes(route.kind)) throw new Error('This handoff is not a supported model or image URL');
    document.body.classList.add('full-page');
  }
  $('model-handoff').hidden = route.kind !== 'model';
  $('recipe-handoff').hidden = route.kind !== 'recipe';
  $('model-preview').hidden = !['model', 'recipe'].includes(route.kind);
  if (['model', 'recipe'].includes(route.kind)) showPreview(Object.fromEntries(new URL(location.href).searchParams));
  if (route.kind === 'recipe') $('recipe-identity').textContent = `Civitai image ${route.imageId}`;
  $('quick-capture').hidden = !['capture', 'model', 'recipe'].includes(route.kind);
  $('quick-capture').open = route.kind === 'capture';
  $('scan').hidden = route.kind !== 'capture';
  $('send').hidden = route.kind !== 'capture';
  $('save-page').hidden = !['model', 'recipe'].includes(route.kind);
  $('route-description').textContent = route.kind === 'ingestion'
    ? `${route.provider} already has a dedicated ingestion workflow. Open Sources in LoraSuite to retrieve and review this media.`
    : route.kind === 'library' ? 'Manage your LoRA Manager connection and downloads directly.'
    : route.kind === 'civitai' ? 'Open a specific Civitai model page to hand it to LoRA Manager.'
      : route.kind === 'recipe' ? 'Save this image as a reusable recipe in LoRA Manager.'
      : route.kind === 'model' ? 'Choose versions and follow your downloads in LoRA Manager.'
        : 'Quick capture for websites and threads without a dedicated ingestion connector.';
  if (route.kind === 'model') {
    $('model-identity').textContent = `Model ${route.modelId} · ${route.versionId ? `selected version ${route.versionId}` : 'choose a version in LoRA Manager'}`;
    $('model-url').textContent = route.url;
  }
  const { captureDraft } = await chrome.storage.session.get('captureDraft');
  if (route.kind === 'capture' && captureDraft?.page === route.url && Array.isArray(captureDraft.candidates)) {
    candidates = captureDraft.candidates; renderCandidates(captureDraft.selected || []);
  }
} catch (error) { $('route-description').textContent = error.message; }
managerControls = createManagerControls({ route, action, status, managerURL: () => managerURL, call: payload => managerOperation(managerURL, payload, { allowTransfers: fullPage }) });
const { lastHandoff } = await chrome.storage.local.get('lastHandoff');
if (lastHandoff) {
  const interrupted = lastHandoff.state === 'opening' && Date.now() - lastHandoff.updated > 45000;
  $('last-handoff').textContent = `Last model handoff: ${interrupted ? 'interrupted — use Review in LoRA Manager to retry' : lastHandoff.state}${lastHandoff.error ? ` · ${lastHandoff.error}` : ''}`;
}
try { await connectManager(); }
catch (error) { $('manager-connection').open = true; $('manager-status').textContent = `LM unavailable. ${error.message}`; }
if (connection.token && route?.kind === 'capture') { try { await projects(); } catch (error) { status(error.message); } }
else if (route?.kind === 'capture') { $('connection').open = true; status('Pair LoraSuite only if you want to send references to a project.'); }
else status(fullPage ? 'Choose a version or import a recipe. LoraSuite pairing is optional.' : 'Open the companion popup for downloads and recipes.');
syncConnection();

reportBusy();

const stopThemeSync = followTheme(theme => {
  document.documentElement.dataset.theme = theme;
  if (parentOrigin) {
    const styles = getComputedStyle(document.documentElement);
    const palette = Object.fromEntries(['bg','panel','text','border-strong','accent'].map(key => [key, styles.getPropertyValue(`--guided-${key}`).trim()]));
    window.parent.postMessage({type:'companion-theme',palette},parentOrigin);
  }
}, connection.engine);
window.addEventListener('unload', stopThemeSync, {once:true});
