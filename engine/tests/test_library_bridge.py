import json
import struct
import time
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from lorasuite_engine.api import create_app
from lorasuite_engine.curation import CurationService
from lorasuite_engine.dataset_projects import CharacterProjectService
from lorasuite_engine.library_bridge import Capture, CaptureBatch, ImportFile, LibraryBridge, public_url

ORIGIN = 'chrome-extension://' + 'a' * 32


@pytest.fixture
def bridge(tmp_path):
    service = LibraryBridge(tmp_path)
    project = CharacterProjectService(tmp_path).create_project(name='Test person')
    return service, project.id


def batch(project, kind='image', url='https://example.org/picture.jpg'):
    return CaptureBatch(items=[Capture(kind=kind, url=url, page_url='https://example.org/post', title='Example', project_id=project, requested_output='image')])


def test_pair_is_one_time_origin_bound_and_revocable(bridge):
    service, _ = bridge
    code = service.issue_code()['code']
    with pytest.raises(ValueError):
        service.pair(code, 'https://evil.example')
    token = service.pair(code, ORIGIN)['token']
    assert service.authorize(token, ORIGIN)
    assert not service.authorize(token, 'chrome-extension://' + 'b' * 32)
    assert not service.authorize('wrong', ORIGIN)
    with pytest.raises(ValueError):
        service.pair(code, ORIGIN)
    assert token not in service.auth.read_text() and code not in service.auth.read_text()
    service.write_auth({})
    assert not service.authorize(token, ORIGIN)


def test_expiration_attempt_limit_and_restart(bridge):
    service, _ = bridge
    code = service.issue_code()['code']
    for _ in range(5):
        with pytest.raises(ValueError):
            service.pair('incorrect-but-long-enough', ORIGIN)
    with pytest.raises(ValueError):
        service.pair(code, ORIGIN)
    code = service.issue_code()['code']
    token = service.pair(code, ORIGIN)['token']
    assert LibraryBridge(service.root).authorize(token, ORIGIN)
    data = json.loads(service.auth.read_text()); data['expires'] = time.time() - 1
    service.write_auth(data)
    assert not service.authorize(token, ORIGIN)


def test_reference_dedupe_scope_and_no_download(bridge):
    service, project = bridge
    assert service.enqueue(batch(project))['added'] == 1
    assert service.enqueue(batch(project))['duplicates'] == 1
    other = CharacterProjectService(service.root).create_project(name='Other')
    assert service.enqueue(batch(other.id))['added'] == 1
    assert not (service.root / 'raw').exists()
    with pytest.raises(ValueError):
        service.enqueue(batch('nonexistent'))
    assert len(LibraryBridge(service.root).read()['items']) == 2


def test_urls_strip_secrets_and_reject_local_schemes():
    assert public_url('https://example.org/models/1?token=secret&modelVersionId=42#private') == 'https://example.org/models/1?modelVersionId=42'
    assert public_url('https://forum.example/viewtopic.php?t=123&page=2&token=secret') == 'https://forum.example/viewtopic.php?t=123&page=2'
    for url in ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:password@example.org/x']:
        with pytest.raises(ValueError):
            public_url(url)


def test_media_import_is_pending_project_scoped_and_idempotent(bridge):
    service, project = bridge
    item = service.enqueue(batch(project))['items'][0]
    image = service.root / 'example.png'
    Image.new('RGB', (32, 32), 'orange').save(image)
    imported = service.import_file(item['id'], ImportFile(path=str(image)))
    handoff = CurationService(service.root).get_handoff(project_id=project, requested_output='image')
    assert len(handoff.items) == 1 and handoff.items[0].review_status == 'pending'
    assert service.import_file(item['id'], ImportFile(path='/no-longer-needed')) == imported
    assert CurationService(service.root).get_handoff(project_id='other').items == []


def test_model_copy_not_activation_and_pickle_rejected(bridge):
    service, project = bridge
    item = service.enqueue(batch(project, 'model'))['items'][0]
    path = service.root / 'adapter.safetensors'
    header = json.dumps({'some.weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
    path.write_bytes(struct.pack('<Q', len(header)) + header + struct.pack('<f', 1.0))
    result = service.import_file(item['id'], ImportFile(path=str(path)))['result']
    assert result['compatibility'] == 'unverified' and not result['h3_fused_layout']
    assert path.exists() and not (service.root / 'h3_loras.json').exists()
    other = service.enqueue(batch(project, 'model', 'https://example.org/other'))['items'][0]
    pickle = service.root / 'unsafe.ckpt'; pickle.write_bytes(b'not executed')
    with pytest.raises(ValueError, match='safetensors'):
        service.import_file(other['id'], ImportFile(path=str(pickle)))


def test_api_extension_cannot_admin_or_import(tmp_path, monkeypatch):
    monkeypatch.setattr(LibraryBridge, 'manager', lambda self: {'items': []})
    with TestClient(create_app(vault_root=tmp_path)) as client:
        headers = {'Origin': ORIGIN}
        assert client.post('/library/pairing-code', json={}, headers=headers).status_code == 403
        code = client.post('/library/pairing-code', json={}).json()['code']
        result = client.post('/library/pair', json={'code': code}, headers=headers)
        assert result.status_code == 200
        headers['Authorization'] = 'Bearer ' + result.json()['token']
        assert client.get('/library/projects', headers=headers).status_code == 200
        assert client.post('/library/inbox/x/import', json={'path': '/etc/passwd'}, headers=headers).status_code == 403
        assert client.post('/library/inbox/x/archive', json={'archived': True}, headers=headers).status_code == 403
        assert set(client.get('/library/companion/context', headers=headers).json()) == {'manager_ready', 'manager_url'}
        assert client.get('/library/status', headers=headers).status_code == 403
        assert client.get('/library/models', headers=headers).status_code == 403
        assert client.post('/library/runtime/start', json={}, headers=headers).status_code == 404
        assert client.post('/library/runtime/stop', json={}, headers=headers).status_code == 404
        assert client.post('/library/runtime/config', json={'autostart': True}, headers=headers).status_code == 404
        assert client.post('/library/training-artifacts/test', json={}, headers=headers).status_code == 403
        assert client.post('/library/config', json={'port': 1234}, headers=headers).status_code == 403
        assert client.get('/library/projects').status_code == 401
        assert client.get('/vault/media', headers=headers).status_code == 403
        cors = client.options('/library/inbox', headers={'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST'})
        assert cors.headers['access-control-allow-origin'] == ORIGIN
        unrelated = client.options('/vault/media', headers={'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST'})
        assert 'access-control-allow-origin' not in unrelated.headers


def test_archive_restore_preserves_import_receipts_and_media(bridge):
    service, project = bridge
    item = service.enqueue(batch(project))['items'][0]
    image = service.root / 'retained.png'
    Image.new('RGB', (32, 32), 'orange').save(image)
    imported = service.import_file(item['id'], ImportFile(path=str(image)))
    archived = service.archive(item['id'], True)
    assert archived['archived'] and archived['result'] == imported['result']
    assert service.enqueue(batch(project))['duplicates'] == 1
    assert LibraryBridge(service.root).read()['items'][0]['archived']
    assert image.exists() and len(CurationService(service.root).get_handoff(project_id=project, requested_output='image').items) == 1
    assert service.archive(item['id'], False)['status'] == 'imported'
    with pytest.raises(ValueError, match='not found'):
        service.archive('missing', True)


def test_archived_pending_reference_must_be_restored_before_import(bridge):
    service, project = bridge
    item = service.enqueue(batch(project))['items'][0]
    service.archive(item['id'], True)
    with pytest.raises(ValueError, match='[Rr]estore'):
        service.import_file(item['id'], ImportFile(path='/not-read'))


def test_catalog_projects_only_safe_display_fields(bridge, monkeypatch):
    service, _ = bridge
    models = service.root / 'model_library' / 'loras'
    models.mkdir(parents=True)
    path = models / 'style.safetensors'; path.write_bytes(b'catalog does not execute this')
    outside = service.root / 'outside.safetensors'; outside.write_bytes(b'outside roots')
    calls = []
    def manager(category='loras', page=1, *, roots=False, search=''):
        calls.append((category, page, roots, search))
        if roots:
            return {'roots': [str(models)]}
        return {'items': [
            {'file_path': str(path), 'model_name': '<script>untrusted</script>', 'base_model': 'H3', 'civitai': {'trainedWords': ['film'], 'private': 'secret'}, 'unexpected': 'secret'},
            {'file_path': str(outside)}, {'file_path': str(models / 'missing.safetensors')},
        ], 'total': 30, 'total_pages': 2}
    monkeypatch.setattr(service, 'manager', manager)
    result = service.catalog('loras', 2, 'film')
    assert result['page'] == 2 and result['total'] == 30
    assert calls[0] == ('loras', 2, False, 'film')
    first = result['items'][0]
    assert first['selectable'] and first['trigger_words'] == ['film']
    assert first['compatibility'] == 'unverified' and first['name'].startswith('<script>')
    assert 'secret' not in json.dumps(result)
    assert not any(item['selectable'] for item in result['items'][1:])


def test_catalog_query_is_bounded_and_local_ui_only(tmp_path, monkeypatch):
    monkeypatch.setattr(LibraryBridge, 'catalog', lambda self, category, page, search: {'items': [], 'total': 0, 'page': page, 'total_pages': 0})
    with TestClient(create_app(vault_root=tmp_path)) as client:
        assert client.get('/library/models?category=loras&page=2&search=film').json()['page'] == 2
        for query in ['page=0', 'page=100001', 'category=../settings', 'search=' + 'x' * 201]:
            assert client.get('/library/models?' + query).status_code == 422
        assert client.get('/library/models', headers={'Origin': 'https://evil.example'}).status_code == 403
    with pytest.raises(ValueError, match='category'):
        LibraryBridge(tmp_path).manager('../settings')


def test_training_artifact_export_reuses_registry_hash_and_preserves_user_metadata(bridge, monkeypatch):
    from lorasuite_engine.model_registry import ModelRegistryService
    service, project = bridge
    path = service.root / 'trained.safetensors'
    header = json.dumps({'some.weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
    path.write_bytes(struct.pack('<Q', len(header)) + header + struct.pack('<f', 1.0))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = SimpleNamespace(id='artifact_one', training_run_id='run_one', project_id=project,
        snapshot_id='snapshot_one', dataset_fingerprint='fingerprint', model_family='flux',
        checkpoint_path=path, checkpoint_name='Trained identity', checkpoint_sha256=digest,
        base_model='FLUX.1', trigger_token='person1')
    monkeypatch.setattr(ModelRegistryService, 'get_artifact', lambda self, artifact_id: artifact if artifact_id == artifact.id else None)
    receipt = service.register_artifact(artifact.id)
    target = Path(receipt['path'])
    assert target.read_bytes() == path.read_bytes()
    assert receipt['provenance']['training_run_id'] == 'run_one'
    sidecar = target.with_suffix('.metadata.json')
    data = json.loads(sidecar.read_text())
    assert data['model_name'] == 'Trained identity' and data['trainedWords'] == ['person1']
    assert data['skip_metadata_refresh'] is True
    data['model_name'] = 'User renamed this'
    sidecar.write_text(json.dumps(data))
    assert service.register_artifact(artifact.id) == receipt
    assert json.loads(sidecar.read_text())['model_name'] == 'User renamed this'
    assert len(list(target.parent.glob('*.safetensors'))) == 1
    assert LibraryBridge(service.root).read()['training_exports'][artifact.id] == receipt
    assert not (service.root / 'h3_loras.json').exists()
    path.write_bytes(path.read_bytes()[:-4] + struct.pack('<f', 2.0))
    with pytest.raises(ValueError, match='changed'):
        service.register_artifact(artifact.id)
    with pytest.raises(ValueError, match='Register and validate'):
        service.register_artifact('missing')


@pytest.mark.parametrize('origin', [
    'tauri://localhost', 'http://tauri.localhost', 'https://tauri.localhost',
    'http://localhost:5175', 'http://127.0.0.1:5173',
])
def test_library_ui_uses_engine_local_origins(tmp_path, monkeypatch, origin):
    monkeypatch.setattr(LibraryBridge, 'manager', lambda self, **kwargs: {'roots': [], 'items': []})
    monkeypatch.setattr(LibraryBridge, 'catalog', lambda *args: {'items': []})
    with TestClient(create_app(vault_root=tmp_path)) as client:
        headers = {'Origin': origin}
        preflight = client.options('/library/pairing-code', headers={
            **headers, 'Access-Control-Request-Method': 'POST',
        })
        assert preflight.status_code == 200
        assert preflight.headers['access-control-allow-origin'] == origin
        for path in ['/library/status', '/library/models']:
            result = client.get(path, headers=headers)
            assert result.status_code == 200
            assert result.headers['access-control-allow-origin'] == origin
        assert client.post('/library/pairing-code', json={}, headers=headers).status_code == 200
        # Reaches the export handler, which rejects this nonexistent artifact.
        assert client.post('/library/training-artifacts/missing', json={}, headers=headers).status_code == 400


@pytest.mark.parametrize('origin', [
    'https://evil.example', 'http://tauri.localhost.evil.example',
    'https://tauri.localhost:444', 'http://other.localhost',
    'tauri://localhost.evil.example', 'null', ORIGIN,
])
def test_library_admin_rejects_non_ui_origins_before_mutation(tmp_path, origin):
    with TestClient(create_app(vault_root=tmp_path)) as client:
        headers = {'Origin': origin}
        assert client.post('/library/pairing-code', json={}, headers=headers).status_code == 403
        assert client.post('/library/config', json={'port': 9000}, headers=headers).status_code == 403
        assert client.get('/library/models', headers=headers).status_code == 403
        assert not LibraryBridge(tmp_path).auth.exists()
        assert LibraryBridge(tmp_path).read()['port'] == 8188
