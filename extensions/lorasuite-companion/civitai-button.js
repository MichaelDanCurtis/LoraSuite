// Independent DOM integration. Only public model IDs are sent to local LM.
// Optional project credentials stay private; page text is never HTML.
(() => {
  const allowed = ['civitai.com', 'www.civitai.com', 'civitai.red', 'www.civitai.red', 'civarchive.com', 'www.civarchive.com'];
  if (location.protocol !== 'https:' || !allowed.includes(location.hostname)) return;
  const host = document.createElement('div'); host.style.position = 'relative';
  const root = host.attachShadow({ mode: 'closed' });
  const style = document.createElement('style');
  style.textContent = 'section{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:12px;background:linear-gradient(110deg,#172a21,#101c17);color:#e4f1e9;border:1px solid #3b594a;border-radius:12px;font:14px system-ui}button{font:inherit;cursor:pointer;color:#c9edda;background:#213b2d;border:1px solid #4a725c;border-radius:8px;padding:9px 12px}button:first-child{background:#9fe8be;color:#123524;font-weight:600}button:hover{filter:brightness(1.1)}button:focus-visible{outline:2px solid #a0efce;outline-offset:3px}button:disabled{opacity:.5}small{flex:1;color:#a9c3b5}';
  const bar = document.createElement('section');
  bar.setAttribute('aria-label', 'LoraSuite model handoff');
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Add to LoRA Manager';
  const hint = document.createElement('small'); hint.setAttribute('role','status');
  const hide = document.createElement('button'); hide.type='button'; hide.textContent='Hide installed'; hide.setAttribute('aria-pressed','false');
  const dismiss = document.createElement('button'); dismiss.type='button'; dismiss.textContent='×'; dismiss.setAttribute('aria-label','Hide LoraSuite controls');
  bar.append(button,hint,hide,dismiss); root.append(style,bar);
  let lastURL='', dismissed=false, busy=false, hidden=false, lastCheck=0;
  const badges = new Map();
  const hiddenCards = new Map();
  const feedback = new Map();
  let actionMessageUntil = 0;
  function actionMessage(text) { hint.textContent=text; actionMessageUntil=Date.now()+30000; }
  function libraryMessage(text) { if(Date.now()>=actionMessageUntil)hint.textContent=text; }
  function restoreCards() { for (const badge of badges.values()) badge.hidden=false; for (const [card, display] of hiddenCards) card.style.display=display; hiddenCards.clear(); }
  function identifier(value) {
    try { const u=new URL(value,location.href); if (u.protocol !== 'https:' || !allowed.includes(u.hostname)) return null;
      const match=u.pathname.match(/^\/models\/([1-9]\d*)(?:\/|$)/); if (!match) return null;
      const version=u.searchParams.get('modelVersionId');
      if (!Number.isSafeInteger(Number(match[1])) || (version && (!/^[1-9]\d*$/.test(version) || !Number.isSafeInteger(Number(version))))) return null;
      return {id:Number(match[1]),version:version ? Number(version):null,url:u.origin+'/models/'+match[1]+(version?'?modelVersionId='+version:'')};
    } catch { return null; }
  }
  function listingCard(anchor) {
    const article = anchor.closest('article');
    if (article) return article;
    if (location.hostname.replace(/^www\./, '') === 'civarchive.com' &&
        ['block', 'group', 'relative', 'rounded-lg'].every(name => anchor.classList.contains(name))) {
      return anchor.parentElement?.classList.contains('flex-shrink-0') ? anchor.parentElement : anchor;
    }
    // Public Civitai card markup observed on /models. Keep the stable module
    // names, not generated hashes. Never hide arbitrary parent containers.
    const content = anchor.closest('[class*="AspectRatioCard-"][class*="__content"]');
    const card = content?.parentElement;
    if (!card) return null;
    const wrapper = card.parentElement;
    return wrapper?.className.includes('CosmeticWrapper-') ? wrapper : card;
  }
  function previewFor(anchor) {
    const card=anchor ? listingCard(anchor) || anchor : document.querySelector('main');
    const img=card?.querySelector('img[src*="image.civitai.com"]');
    return {title:(anchor?.textContent || document.querySelector('main h1, h1')?.textContent || document.title).trim().slice(0,160),
      thumbnail:img?.currentSrc || img?.src || (!anchor ? document.querySelector('meta[property="og:image"]')?.content : '') || ''};
  }
  async function open(url,preview) {
    let timer;
    try {
      const result=await Promise.race([
        chrome.runtime.sendMessage({type:'open-model-companion',url,preview}),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('The extension did not respond. Check for an opened companion popup, then reload the extension and this page')),12000);}),
      ]);
      if (!result?.opened) throw new Error(result?.error || 'Could not open companion');
    } finally {clearTimeout(timer);}
  }
  async function openFromButton(control,url,preview) {
    if(control.disabled)return;
    const original=control.textContent;
    control.disabled=true; control.textContent='Opening companion…';
    feedback.set(control,{until:Infinity,text:control.textContent});
    actionMessage('Opening the companion popup…');
    try {
      await open(url,preview);
      control.textContent='Companion opened';
      actionMessage('Choose a version in the page popup.');
    } catch(error) {
      control.textContent='Could not open — reload page';
      control.title=error.message+'. Reload the extension, then refresh this page.';
      actionMessage(control.title);
    } finally {
      feedback.set(control,{until:Date.now()+30000,text:control.textContent});
      control.disabled=false;
      setTimeout(()=>{
        if(feedback.get(control)?.until<=Date.now()){
          feedback.delete(control);control.textContent=original;control.removeAttribute('title');lastCheck=0;
        }
      },30000);
    }
  }
  button.addEventListener('click',async event=>{
    if (!event.isTrusted || button.disabled) return;
    event.preventDefault();event.stopPropagation();
    await openFromButton(button,location.href,previewFor());
  });
  hide.addEventListener('click',event=>{if(!event.isTrusted)return; hidden=!hidden; hide.setAttribute('aria-pressed',String(hidden));hide.textContent=hidden?'Show installed':'Hide installed'; restoreCards();lastCheck=0;void refresh();});
  dismiss.addEventListener('click',()=>{dismissed=true;host.remove();restoreCards();for(const node of badges.values())node.remove();badges.clear();});
  async function refresh() {
    if (location.href!==lastURL) {lastURL=location.href;dismissed=false;lastCheck=0;restoreCards();}
    if(dismissed)return;
    if(!host.isConnected)(document.querySelector('main')||document.body)?.prepend(host);
    const image=/^\/images\/[1-9]\d*(?:\/|$)/.test(location.pathname);
    if(!feedback.has(button))button.textContent=image?'Import image as LM recipe':'Add to LoRA Manager';
    button.hidden=!image && !identifier(location.href);
    if(busy || Date.now()-lastCheck<10000 || document.hidden)return;
    busy=true;lastCheck=Date.now();
    const requestedURL = location.href;
    try {
      for(const [anchor,badge] of badges)if(!anchor.isConnected){badge.remove();badges.delete(anchor);}
      const links=[...document.querySelectorAll('a[href]')].map(anchor=>({anchor,model:identifier(anchor.href)})).filter(item=>item.model).slice(0,100);
      const current=identifier(location.href);
      const ids=[...new Set([...(current?[current.id]:[]),...links.map(item=>item.model.id)])].slice(0,100);
      if(!ids.length){libraryMessage('LoraSuite · Browse models or open an image to import a recipe.');return;}
      const result=await chrome.runtime.sendMessage({type:'lm-operation',payload:{operation:'status',model_ids:ids}});
      if (location.href !== requestedURL || dismissed) return;
      if(result?.error)throw new Error(result.error);
      const states=new Map((result?.items||[]).map(item=>[item.model_id,item]));
      libraryMessage('Connected to your local library · Open a model to choose versions and manage downloads.');
      restoreCards();
      for(const {anchor,model} of links){
        const state=states.get(model.id); if(!state)continue;
        const installed=model.version ? state.version_ids.includes(model.version):state.in_library;
        let badge=badges.get(anchor);
        if(!badge){badge=document.createElement('button');badge.type='button';badge.style.cssText='display:inline-block;margin:4px;padding:5px 8px;background:#183326;color:#c9f2d9;border:1px solid #62947a;border-radius:8px;font:12px system-ui;position:relative;z-index:2';anchor.insertAdjacentElement('afterend',badge);badges.set(anchor,badge);
          badge.addEventListener('click',async event=>{if(!event.isTrusted)return;event.preventDefault();event.stopPropagation();const selected=identifier(anchor.href);if(selected)await openFromButton(badge,selected.url,previewFor(anchor));});
        }
        if(!feedback.has(badge))badge.textContent=installed?'✓ In LM':'↓ Add to LM';
        // Hide only identifiable listing cards, never broad layout containers or
        // resources inside a model/image details page. Restoration is reversible.
        const card=listingCard(anchor);
        if(card && anchor.closest('[class*="AspectRatioCard-"]')){badge.style.position='absolute';badge.style.top='42px';badge.style.left='8px';}
        badge.hidden=Boolean(hidden&&installed&&card&&!current&&!image);
        if(hidden&&installed&&card&&!current&&!image&&!hiddenCards.has(card)){hiddenCards.set(card,card.style.display);card.style.display='none';}
      }
      if(current){const state=states.get(current.id);if(state)libraryMessage((current.version?state.version_ids.includes(current.version):state.in_library)?'This model/version is in LoRA Manager. Open to review other versions.':'This model/version is not installed. Open the companion to download.');}
    } catch(error){restoreCards();for(const [anchor,badge] of badges)if(!feedback.has(badge)){badge.remove();badges.delete(anchor);}libraryMessage(error.message+'. Open the companion to connect or retry, or reload this page.');}
    finally{busy=false;}
  }
  void refresh();setInterval(()=>void refresh(),1000);
})();
