import { expect, it } from 'vitest';
import { cleanPreview, readPagePreview } from './preview.js';

it('accepts public Civitai covers and bounds plain-text titles', () => {
  expect(cleanPreview({ title: 'x'.repeat(200), thumbnail: 'https://image.civitai.com/neutral/width=320/cover.jpeg' })).toEqual({ title: 'x'.repeat(160), thumbnail: 'https://image.civitai.com/neutral/width=320/cover.jpeg' });
});
it('falls back for malformed metadata and disallows trackers, local files, credentials and signed queries', () => {
  for (const value of [null, undefined, 123, 'text']) expect(cleanPreview(value)).toEqual({ title: '', thumbnail: '' });
  for (const thumbnail of ['javascript:alert(1)', 'data:image/png;base64,abc', 'file:///private/cover', 'http://127.0.0.1/cover', 'https://image.civitai.com.evil.test/x', 'https://user:secret@image.civitai.com/x', 'https://image.civitai.com:4433/x', 'https://image.civitai.com/x?token=secret', 'https://image.civitai.com/x#secret']) {
    expect(cleanPreview({ thumbnail }).thumbnail).toBe('');
  }
});
it('reads visible page cover metadata without a network lookup', () => {
  document.body.innerHTML = '<main><h1>Emerald landscape</h1><img src="https://image.civitai.com/neutral.jpeg"></main>';
  expect(readPagePreview()).toEqual({ title: 'Emerald landscape', thumbnail: 'https://image.civitai.com/neutral.jpeg' });
});
