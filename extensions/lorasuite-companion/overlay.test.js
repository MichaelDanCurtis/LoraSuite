import { afterEach, beforeEach, expect, it, vi } from 'vitest';
let listener, root, onFrameMessage;
const base = 'chrome-extension://test/popup.html';
const source = model => `${base}?model=${encodeURIComponent(`https://civitai.com/models/${model}`)}&overlay=session`;
const send = url => { const respond=vi.fn(); listener({type:'show-companion-overlay',url},{id:'test'},respond); return respond; };
beforeEach(async () => {
  vi.resetModules(); document.body.innerHTML=''; root=undefined;
  const attach=Element.prototype.attachShadow;
  vi.spyOn(Element.prototype,'attachShadow').mockImplementation(function(options){root=attach.call(this,options); return root;});
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:function(){this.open=true;}});
  Object.defineProperty(HTMLDialogElement.prototype,'close',{configurable:true,value:function(){this.open=false;}});
  vi.stubGlobal('chrome',{runtime:{id:'test',getURL:()=>base,onMessage:{addListener:fn=>{listener=fn;}}}});
  const add = window.addEventListener.bind(window);
  vi.spyOn(window,'addEventListener').mockImplementation((type,fn,...args)=>{if(type==='message')onFrameMessage=fn;return add(type,fn,...args);});
  await import('./overlay.js');
});
afterEach(()=>{root?.host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('opens a top-layer page dialog and preserves its iframe when dismissed and reopened',()=>{
  expect(send(source(123))).toHaveBeenCalledWith({opened:true});
  const dialog=root.querySelector('dialog'), frame=root.querySelector('iframe');
  expect(dialog.open).toBe(true); expect(frame.src).toBe(source(123));
  dialog.dispatchEvent(new Event('cancel',{cancelable:true})); expect(dialog.open).toBe(false);
  expect(frame.isConnected).toBe(true);
  expect(send(source(123))).toHaveBeenCalledWith({opened:true,reused:true});
  expect(root.querySelector('iframe')).toBe(frame); expect(dialog.open).toBe(true);
});
it('keeps an active model alive and ignores page-forged busy notifications',()=>{
  send(source(123)); const frame=root.querySelector('iframe');
  window.dispatchEvent(new MessageEvent('message',{origin:'https://civitai.com',data:{type:'companion-busy',busy:false}}));
  expect(send(source(789))).toHaveBeenCalledWith({error:expect.stringContaining('Finish')});
  expect(root.querySelector('iframe')).toBe(frame);
  window.dispatchEvent(new MessageEvent('message',{origin:new URL(base).origin,source:frame.contentWindow,data:{type:'companion-busy',busy:false}}));
  expect(send(source(789))).toHaveBeenCalledWith({error:expect.stringContaining('Finish')});
  onFrameMessage({isTrusted:true,origin:new URL(base).origin,source:frame.contentWindow,data:{type:'companion-busy',busy:false}});
  expect(send(source(789))).toHaveBeenCalledWith({opened:true});
  expect(root.querySelector('iframe').src).toBe(source(789));
});
it('rejects non-extension frames and messages from other extensions',()=>{
  expect(send('https://evil.test/popup.html?overlay=x')).toHaveBeenCalledWith({error:expect.any(String)});
  expect(root).toBeUndefined();
  const respond=vi.fn(); listener({type:'show-companion-overlay',url:source(123)},{id:'other'},respond);
  expect(respond).not.toHaveBeenCalled(); expect(root).toBeUndefined();
});
