import hashlib
import json
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from lorasuite_engine.api import create_app
from lorasuite_engine.library_bridge import LibraryBridge
from lorasuite_engine.library_artifacts import ArtifactLibraryOptions, prepare_previews
from lorasuite_engine.model_registry import ModelRegistryService


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    path = tmp_path / 'fixture.safetensors'
    header = json.dumps({'some.weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
    path.write_bytes(struct.pack('<Q', len(header)) + header + struct.pack('<f', 1))
    record = SimpleNamespace(id='fixture', checkpoint_path=path, checkpoint_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        checkpoint_name='Fixture', base_model='H3', trigger_token='fixture', training_run_id='run', project_id='project',
        snapshot_id='snapshot', dataset_fingerprint='dataset', model_family='h3')
    monkeypatch.setattr(ModelRegistryService, 'get_artifact', lambda self, key: record)
    return record


def mock_manager(bridge, monkeypatch):
    monkeypatch.setattr(bridge, 'manager', lambda **kwargs: {'roots': [str(bridge.root / 'model_library/loras')]})
    monkeypatch.setattr(bridge, 'manager_media_ready', lambda path: True)
    manager = Mock(side_effect=lambda route, payload=None: {'status': 'success'} if route == '/loras/scan'
        else {'files': [{'name': 'custom.png'}], 'errors': []} if route == '/import-example-images' or route.startswith('/example-image-files')
        else {'settings': {'example_images_path': '/configured/gallery'}})
    monkeypatch.setattr(bridge, 'manager_api', manager)
    return manager


def test_artifact_bundle_metadata_images_retries_and_preserved_edits(tmp_path, monkeypatch, artifact):
    bridge = LibraryBridge(tmp_path)
    manager = mock_manager(bridge, monkeypatch)
    image = tmp_path / 'sample.png'; Image.new('RGB', (20, 20), 'blue').save(image)
    options = ArtifactLibraryOptions(title='Reviewed title', base_model='H3 Ref2VA', trigger_words=[' fixture '],
        tags=['test'], description='Reviewed description', preview_paths=[str(image), str(image)])
    result = bridge.register_artifact('fixture', options)
    assert result['manager_synced'] and len(result['gallery_imported_paths']) == 1
    assert hashlib.sha256(Path(result['path']).read_bytes()).hexdigest() == artifact.checkpoint_sha256
    sidecar = Path(result['path']).with_suffix('.metadata.json')
    data = json.loads(sidecar.read_text())
    assert data['model_name'] == 'Reviewed title' and data['base_model'] == 'H3 Ref2VA'
    assert data['civitai'] == {'trainedWords': ['fixture']}
    assert data['tags'] == ['test'] and data['notes'] == 'Reviewed description'
    assert Path(data['preview_url']).is_file() and not data['from_civitai']
    data['model_name'] = 'Edited in LM'; sidecar.write_text(json.dumps(data))
    restarted = LibraryBridge(tmp_path); mock_manager(restarted, monkeypatch)
    second = restarted.register_artifact('fixture', options)
    assert second['metadata_preserved'] and second['manager_synced']
    assert json.loads(sidecar.read_text())['model_name'] == 'Edited in LM'
    assert not any(call.args[0] == '/import-example-images' for call in restarted.manager_api.call_args_list)
    third = restarted.register_artifact('fixture', options.model_copy(update={'replace_metadata': True}))
    assert third['manager_synced'] and json.loads(sidecar.read_text())['model_name'] == 'Reviewed title'


def test_ambiguous_image_import_is_not_replayed_after_restart(tmp_path, monkeypatch, artifact):
    bridge = LibraryBridge(tmp_path); manager = mock_manager(bridge, monkeypatch)
    image = tmp_path / 'sample.png'; Image.new('RGB', (20, 20)).save(image)
    options = ArtifactLibraryOptions(preview_paths=[str(image)])
    normal = manager.side_effect
    manager.side_effect = lambda route, payload=None: (_ for _ in ()).throw(TimeoutError()) if route == '/import-example-images' else normal(route, payload)
    result = bridge.register_artifact('fixture', options)
    assert not result['manager_synced']
    restarted = LibraryBridge(tmp_path); manager = mock_manager(restarted, monkeypatch)
    result = restarted.register_artifact('fixture', options)
    assert not result['manager_synced'] and 'uncertain' in result['sync_issue']
    assert not any(call.args[0] == '/import-example-images' for call in manager.call_args_list)


def test_existing_inbox_metadata_survives_first_artifact_handoff(tmp_path, monkeypatch, artifact):
    bridge = LibraryBridge(tmp_path); mock_manager(bridge, monkeypatch)
    result = bridge.copy_model(artifact.checkpoint_path, 'loras', title='Existing name')
    bridge.register_artifact('fixture', ArtifactLibraryOptions(title='Do not overwrite'))
    assert json.loads(Path(result['path']).with_suffix('.metadata.json').read_text())['model_name'] == 'Existing name'
    with pytest.raises(ValueError): prepare_previews([str(artifact.checkpoint_path)])






def test_paired_api_only_and_no_arbitrary_operations(tmp_path, monkeypatch):
    monkeypatch.setattr(LibraryBridge, 'manager_api', lambda *args: {'results': []})
    with TestClient(create_app(vault_root=tmp_path)) as client:
        body = {'operation': 'status', 'model_ids': [1]}
        assert client.post('/library/companion/operation', json=body).status_code == 401
        origin = 'chrome-extension://' + 'a' * 32
        code = client.post('/library/pairing-code', json={}).json()['code']
        token = client.post('/library/pair', json={'code': code}, headers={'Origin': origin}).json()['token']
        headers = {'Origin': origin, 'Authorization': 'Bearer ' + token}
        assert client.post('/library/companion/operation', json=body, headers=headers).status_code == 410
        assert client.post('/library/companion/operation', json={'operation': '/settings'}, headers=headers).status_code == 410
        assert client.post('/library/training-artifacts/fixture', json={'preview_paths': ['/private']}, headers=headers).status_code == 403




def test_wrong_library_does_not_change_lm_settings_or_import_images(tmp_path, monkeypatch, artifact):
    bridge = LibraryBridge(tmp_path)
    monkeypatch.setattr(bridge, 'manager', lambda **kwargs: {'roots': ['/another/library']})
    manager = Mock(); monkeypatch.setattr(bridge, 'manager_api', manager)
    result = bridge.register_artifact('fixture', ArtifactLibraryOptions(title='Reviewed'))
    assert not result['manager_synced'] and 'another library' in result['sync_issue']
    manager.assert_not_called()
