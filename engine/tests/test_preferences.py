from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from lorasuite_engine.api import create_app
from lorasuite_engine.preferences import Preferences, ThemeSelection


def test_clients_share_last_choice_and_old_cache_cannot_overwrite(tmp_path):
    web, desktop = Preferences(tmp_path), Preferences(tmp_path)
    assert web.read()['theme'] is None
    web.select(ThemeSelection(theme='rose', only_if_unset=True))
    desktop.select(ThemeSelection(theme='ocean'))
    assert web.select(ThemeSelection(theme='rose', only_if_unset=True))['theme'] == 'ocean'
    assert Preferences(tmp_path).read()['theme'] == 'ocean'
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda theme: Preferences(tmp_path).select(ThemeSelection(theme=theme)), ['acid', 'nebula']))
    assert web.read() == max(results, key=lambda value: value['updated_at'])


def test_theme_bridge_is_public_read_only_and_does_not_expose_other_preferences(tmp_path):
    client = TestClient(create_app(tmp_path))
    origin = {'Origin':'chrome-extension://'+'a'*32}
    assert client.post('/preferences/theme',json={'theme':'synthwave'}).status_code == 200
    response = client.get('/library/theme',headers=origin)
    assert response.status_code == 200
    assert set(response.json()) == {'theme','updated_at'}
    assert response.json()['theme'] == 'synthwave'
    assert response.headers['access-control-allow-origin'] == origin['Origin']
    assert client.post('/library/theme',json={'theme':'acid'},headers=origin).status_code == 405
    assert client.post('/preferences/theme',json={'theme':'acid'},headers=origin).status_code == 403
    assert client.post('/preferences/theme',json={'theme':'evil; background:url(x)'}).status_code == 422


def test_workspace_partial_changes_preserve_other_client_fields_and_restart(tmp_path):
    from lorasuite_engine.preferences import WorkspaceSelection
    web, desktop = Preferences(tmp_path), Preferences(tmp_path)
    web.select_workspace(WorkspaceSelection(active_project_id='project-a', target='video', stage='prepare'))
    desktop.select_workspace(WorkspaceSelection(experience='studio'))
    assert web.select_workspace(WorkspaceSelection(stage='create', only_if_unset=True))['workspace']['stage'] == 'prepare'
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda patch: Preferences(tmp_path).select_workspace(WorkspaceSelection(**patch)), [{'stage': 'verify'}, {'target': 'image'}]))
    assert Preferences(tmp_path).read_workspace()['workspace'] == {
        'active_project_id': 'project-a', 'target': 'image', 'stage': 'verify', 'experience': 'studio',
    }


def test_workspace_api_validates_inputs_and_public_theme_does_not_leak_project(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post('/preferences/workspace', json={'active_project_id':'private-project', 'stage':'prepare'}).status_code == 200
    assert client.get('/preferences/workspace').json()['workspace']['stage'] == 'prepare'
    assert client.post('/preferences/workspace', json={'stage':'native-render'}).status_code == 422
    assert client.post('/preferences/workspace', json={'api_key':'secret'}).status_code == 422
    assert 'private-project' not in client.get('/library/theme').text


def test_preparation_survives_restart_and_is_scoped_to_project_and_output(tmp_path):
    from lorasuite_engine.preferences import PreparationSelection
    web = Preferences(tmp_path)
    checkpoint = {'sourceItems': [{'id': 'media-1'}], 'analysisJobId': 'job-1', 'includedIds': ['media-1']}
    web.save_preparation('project-a', 'image', PreparationSelection(checkpoint=checkpoint))
    desktop = Preferences(tmp_path)
    assert desktop.read_preparation('project-a', 'image')['checkpoint'] == checkpoint
    assert desktop.read_preparation('project-b', 'image')['checkpoint'] is None
    assert desktop.read_preparation('project-a', 'video')['checkpoint'] is None
    stale = PreparationSelection(checkpoint={'sourceItems': []}, only_if_unset=True)
    assert desktop.save_preparation('project-a', 'image', stale)['checkpoint'] == checkpoint


def test_preparation_api_is_private_and_validates_output(tmp_path):
    client = TestClient(create_app(tmp_path))
    route = '/preferences/preparation/project-a/image'
    assert client.post(route, json={'checkpoint': {'sourceItems': []}}).status_code == 200
    assert client.get(route).json() == {'checkpoint': {'sourceItems': []}}
    origin = {'Origin': 'chrome-extension://' + 'a' * 32}
    assert client.get(route, headers=origin).status_code == 403
    assert client.post('/preferences/preparation/project-a/invalid', json={'checkpoint': {}}).status_code == 422
