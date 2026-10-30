import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ isTauri: vi.fn(), open: vi.fn() }));
vi.mock('@tauri-apps/api/core', () => ({ isTauri: mocks.isTauri }));
vi.mock('@tauri-apps/plugin-shell', () => ({ open: mocks.open }));
import { handleDesktopLink, openDesktopWebURL } from './desktopLinks';

beforeEach(() => { vi.resetAllMocks(); mocks.open.mockResolvedValue(undefined); });
it('preserves native browser links without launching shell commands', () => {
  const event = { currentTarget: { href: 'http://127.0.0.1:8189/loras' }, preventDefault: vi.fn() };
  handleDesktopLink(event, vi.fn());
  expect(event.preventDefault).not.toHaveBeenCalled();
  expect(mocks.open).not.toHaveBeenCalled();
});
it('opens a desktop library link through the existing native opener', async () => {
  mocks.isTauri.mockReturnValue(true);
  const event = { currentTarget: { href: 'http://127.0.0.1:8189/loras' }, preventDefault: vi.fn() };
  const error = vi.fn();
  handleDesktopLink(event, error);
  await vi.waitFor(() => expect(mocks.open).toHaveBeenCalledWith(event.currentTarget.href));
  expect(event.preventDefault).toHaveBeenCalledOnce();
  expect(error).not.toHaveBeenCalled();
});
it('rejects executable/file/credential links and surfaces opener failures', async () => {
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:secret@example.org']) {
    await expect(openDesktopWebURL(url)).rejects.toThrow();
  }
  expect(mocks.open).not.toHaveBeenCalled();
  mocks.isTauri.mockReturnValue(true);
  mocks.open.mockRejectedValue(new Error('Browser unavailable'));
  const error = vi.fn();
  handleDesktopLink({ currentTarget: { href: 'http://127.0.0.1:8189/loras' }, preventDefault: vi.fn() }, error);
  await vi.waitFor(() => expect(error).toHaveBeenCalledWith('Could not open browser: Browser unavailable'));
});
