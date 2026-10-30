import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { TrainingLibraryExports } from './TrainingLibraryExports';
const fixture = { id: 'artifact1', checkpoint_name: 'Identity', checkpoint_path: '/training/identity.safetensors', base_model: 'FLUX', model_family: 'flux', modality: 'image', project_id: 'project1', training_run_id: 'run1', trigger_token: 'person1', sample_paths: ['/vault/front.png', '/vault/body.jpg', '/vault/clip.mp4'] };

it('sends the reviewed metadata and selected images only after explicit submission', async () => {
  const engine = {
    listModelArtifacts: vi.fn().mockResolvedValue([fixture]),
    exportArtifactToLibrary: vi.fn().mockResolvedValue({ artifact_id: 'artifact1', path: '/library/hash.safetensors', sha256: 'abc', compatibility: 'unverified', manager_synced: true, gallery_imported_paths: ['cover.png'] }),
  };
  render(<TrainingLibraryExports engine={engine} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Send to LoRA Manager…' }));
  expect(engine.exportArtifactToLibrary).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Reviewed identity' } });
  fireEvent.change(screen.getByLabelText('Tags, separated by commas'), { target: { value: 'portrait, trained' } });
  fireEvent.click(screen.getByLabelText('body.jpg'));
  expect(screen.queryByLabelText('clip.mp4')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Send to LoRA Manager' }));
  await screen.findByText('/library/hash.safetensors');
  expect(engine.exportArtifactToLibrary).toHaveBeenCalledWith('artifact1', { title: 'Reviewed identity', base_model: 'FLUX', trigger_words: ['person1'], tags: ['portrait', 'trained'], description: '', preview_paths: ['/vault/body.jpg'], replace_metadata: false });
  expect(screen.getByRole('button', { name: 'Review / sync library copy' })).toBeEnabled();
});

it('retains the form and edits on failure, and distinguishes offline sync from completion', async () => {
  const engine = { listModelArtifacts: vi.fn().mockResolvedValue([fixture]), exportArtifactToLibrary: vi.fn().mockRejectedValueOnce(new Error('Checkpoint changed; revalidate it')).mockResolvedValue({ artifact_id: 'artifact1', path: '/library/hash.safetensors', manager_synced: false, sync_issue: 'Start LoRA Manager' }) };
  render(<TrainingLibraryExports engine={engine} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Send to LoRA Manager…' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send to LoRA Manager' }));
  await screen.findByText('Checkpoint changed; revalidate it');
  expect(screen.getByLabelText('Display name')).toHaveValue('Identity');
  fireEvent.click(screen.getByRole('button', { name: 'Send to LoRA Manager' }));
  await screen.findByText('Library copy saved. Start LoRA Manager');
  expect(screen.queryByText(/^Available in LoRA Manager/)).not.toBeInTheDocument();
});
