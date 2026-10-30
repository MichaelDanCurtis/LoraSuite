import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ModelLibrary } from './ModelLibrary';

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
const engine = () => ({
  libraryStatus: vi.fn().mockResolvedValue({ ready: true, port: 8188, url: 'http://127.0.0.1:8188/loras', model_root: '/test/models', items: [] }),
  configureLibrary: vi.fn().mockResolvedValue({ port: 8188 }),
  createCompanionCode: vi.fn().mockResolvedValue({ code: 'one-time-code', expires_in: 120 }),
  revokeCompanion: vi.fn().mockResolvedValue({ revoked: true }),
  importLibraryFile: vi.fn(),
  archiveLibraryEntry: vi.fn(),
  startLibraryRuntime: vi.fn(),
  stopLibraryRuntime: vi.fn(),
  configureLibraryAutostart: vi.fn(),
  listModelArtifacts: vi.fn().mockResolvedValue([]),
  exportArtifactToLibrary: vi.fn(),
  listLibraryModels: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 24, total: 0, total_pages: 0 }),
});
it('loads only when opened, pairs explicitly, and closes', async () => {
  const api = engine(); render(<ModelLibrary engine={api} />);
  expect(api.libraryStatus).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Model Library' }));
  await screen.findByText('LoRA Manager connected.');
  expect(screen.getByRole('link', { name: /Open full library browser/ })).toHaveAttribute('href', 'http://127.0.0.1:8188/loras');
  expect(screen.getByText('Connection settings').closest('details')).not.toHaveAttribute('open');
  fireEvent.click(screen.getByRole('button', { name: 'Pair Chrome extension' }));
  await screen.findByDisplayValue('one-time-code');
  fireEvent.click(screen.getByRole('button', { name: 'Close Model Library' }));
  expect(screen.queryByDisplayValue('one-time-code')).not.toBeInTheDocument();
});
it('reports backend errors instead of claiming connected', async () => {
  const api = engine(); api.libraryStatus.mockRejectedValue(new Error('Engine offline'));
  render(<ModelLibrary engine={api} />);
  fireEvent.click(screen.getByRole('button', { name: 'Model Library' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Engine offline'));
});
it('does not offer to stop an independently started library', async () => {
  const api = engine();
  api.libraryStatus.mockResolvedValue({ ready: true, port: 8188, url: 'http://127.0.0.1:8188/loras', model_root: '/models', items: [], runtime: {
    phase: 'external', owned: false, configured: true, autostart: true, issue: '', log_path: '/runtime.log',
  } });
  render(<ModelLibrary engine={api} />);
  fireEvent.click(screen.getByRole('button', { name: 'Model Library' }));
  await screen.findByText('LoRA Manager connected.');
  fireEvent.click(screen.getByText('Connection settings'));
  expect(screen.queryByRole('button', { name: /Start LoRA Manager|Stop managed/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: /Start automatically/ })).not.toBeInTheDocument();
  expect(api.stopLibraryRuntime).not.toHaveBeenCalled();
});

it('archives and restores references without importing or deleting files', async () => {
  const api = engine();
  const item = { id: 'reference-one', title: 'Sample reference', status: 'pending', kind: 'image', requested_output: 'image', project_id: 'project-one', page_url: 'https://example.org/thread' };
  const snapshot = { ready: true, port: 8188, url: 'http://127.0.0.1:8188/loras', model_root: '/models', items: [item] };
  api.libraryStatus.mockResolvedValue(snapshot);
  render(<ModelLibrary engine={api} />);
  fireEvent.click(screen.getByRole('button', { name: 'Model Library' }));
  await screen.findByText('Sample reference');
  api.libraryStatus.mockResolvedValue({ ...snapshot, items: [{ ...item, archived: true }] });
  fireEvent.click(screen.getByRole('button', { name: 'Archive reference' }));
  await waitFor(() => expect(screen.queryByText('Sample reference')).not.toBeInTheDocument());
  expect(api.archiveLibraryEntry).toHaveBeenCalledWith('reference-one', true);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Show archived references' }));
  expect(screen.getByText('Sample reference')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Import downloaded file' })).not.toBeInTheDocument();
  api.libraryStatus.mockResolvedValue(snapshot);
  fireEvent.click(screen.getByRole('button', { name: 'Restore reference' }));
  await waitFor(() => expect(api.archiveLibraryEntry).toHaveBeenCalledWith('reference-one', false));
  expect(api.importLibraryFile).not.toHaveBeenCalled();
});
