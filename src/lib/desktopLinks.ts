import { isTauri } from '@tauri-apps/api/core';

// Keep ordinary browser link behavior. The desktop webview has no new-window
// handler, so its reviewed HTTP links need the already-allowed native opener.
export function handleDesktopLink(
  event: { currentTarget: { href: string }; preventDefault(): void },
  reportError: (message: string) => void,
): void {
  if (!isTauri()) return;
  event.preventDefault();
  const href = event.currentTarget.href;
  void openDesktopWebURL(href).catch(error => {
    reportError(`Could not open browser: ${error instanceof Error ? error.message : String(error)}`);
  });
}

export async function openDesktopWebURL(value: string): Promise<void> {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('Only HTTP(S) links without embedded credentials can be opened');
  }
  const { open } = await import('@tauri-apps/plugin-shell');
  await open(url.href);
}
