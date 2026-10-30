import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { LibraryCatalog } from './LibraryCatalog';

const model = { path: '/models/test.safetensors', name: 'Test style', category: 'loras', base_model: 'H3', sha256: '', trigger_words: ['cinematic'], available: true, selectable: true, compatibility: 'unverified' };
it('searches and pages the upstream catalog without activating models', async () => {
  const engine = { listLibraryModels: vi.fn().mockResolvedValue({ items: [model], total: 30, page: 1, page_size: 24, total_pages: 2 }) };
  const select = vi.fn(); render(<LibraryCatalog engine={engine} onSelect={select} />);
  await screen.findByText('Test style');
  expect(engine.listLibraryModels).toHaveBeenCalledWith('loras', 1, '');
  expect(select).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /Use Test style/ }));
  expect(select).toHaveBeenCalledWith(model);
  fireEvent.click(screen.getByRole('button', { name: 'Next models' }));
  await waitFor(() => expect(engine.listLibraryModels).toHaveBeenLastCalledWith('loras', 2, ''));
  await screen.findByText('Test style');
  fireEvent.click(screen.getByText('Search this library (optional)'));
  fireEvent.change(screen.getByLabelText('Search installed models'), { target: { value: 'portrait' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search catalog' }));
  await waitFor(() => expect(engine.listLibraryModels).toHaveBeenLastCalledWith('loras', 1, 'portrait'));
});

it('browses categories without entering a search and clears old search terms on category changes', async () => {
  const engine = { listLibraryModels: vi.fn().mockResolvedValue({ items: [model], total: 1, page: 1, page_size: 24, total_pages: 1 }) };
  render(<LibraryCatalog engine={engine} managerUrl="http://127.0.0.1:8189/loras" />);
  await screen.findByText('Test style');
  expect(screen.getByRole('link', { name: /Open full library browser/ })).toHaveAttribute('href', 'http://127.0.0.1:8189/loras');
  expect(screen.getByRole('button', { name: 'LoRA adapters' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText('Search this library (optional)').closest('details')).not.toHaveAttribute('open');
  fireEvent.click(screen.getByRole('button', { name: 'Checkpoints' }));
  await waitFor(() => expect(engine.listLibraryModels).toHaveBeenLastCalledWith('checkpoints', 1, ''));
  expect(screen.getByRole('link', { name: /Open full library browser/ })).toHaveAttribute('href', 'http://127.0.0.1:8189/checkpoints');
  fireEvent.click(screen.getByText('Search this library (optional)'));
  fireEvent.change(screen.getByLabelText('Search installed models'), { target: { value: 'old query' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search catalog' }));
  await waitFor(() => expect(engine.listLibraryModels).toHaveBeenLastCalledWith('checkpoints', 1, 'old query'));
  fireEvent.click(screen.getByRole('button', { name: 'Embeddings' }));
  await waitFor(() => expect(engine.listLibraryModels).toHaveBeenLastCalledWith('embeddings', 1, ''));
  expect(screen.getByLabelText('Search installed models')).toHaveValue('');
});

it('distinguishes an empty installed library from a search with no matches and lets users return to browsing', async () => {
  const engine = { listLibraryModels: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 24, total_pages: 0 }) };
  render(<LibraryCatalog engine={engine} />);
  await screen.findByText('No lora adapters installed here yet');
  expect(screen.getByText(/downloaded library, not a search of Civitai/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Search this library (optional)'));
  fireEvent.change(screen.getByLabelText('Search installed models'), { target: { value: 'missing' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search catalog' }));
  await screen.findByText('No matches for this search');
  fireEvent.click(screen.getByRole('button', { name: 'Clear search — browse all' }));
  await waitFor(() => expect(engine.listLibraryModels).toHaveBeenLastCalledWith('loras', 1, ''));
});
it('disables missing files and reports a failed refresh without stale choices', async () => {
  const engine = { listLibraryModels: vi.fn().mockResolvedValue({ items: [{ ...model, available: false, selectable: false }], total: 1, page: 1, page_size: 24, total_pages: 1 }) };
  render(<LibraryCatalog engine={engine} onSelect={vi.fn()} />);
  expect(await screen.findByRole('button', { name: /Use Test style/ })).toBeDisabled();
  engine.listLibraryModels.mockRejectedValue(new Error('Library unavailable'));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh catalog' }));
  await screen.findByText('Library unavailable');
  expect(screen.queryByRole('button', { name: /Use Test style/ })).not.toBeInTheDocument();
});
