"""UI locale persistence uses only isolated fixture databases; no provider calls."""
import pytest
from app.models import User
from test_core import client, factory, PASSWORD


def test_default_ui_language(client):
    assert client.get('/api/settings').json()['ui_language'] == 'zh-CN'


@pytest.mark.parametrize('language', ['zh-CN', 'en', 'ko'])
def test_ui_language_patch_is_independent(client, factory, language):
    original = {
        'target_language': 'zh-CN', 'asr_language_mode': 'ko_en',
        'theme': 'dark', 'terms': ['ClassBridge'], 'retain_audio': True,
    }
    assert client.patch('/api/settings', json=original).status_code == 200
    response = client.patch('/api/settings', json={'ui_language': language})
    assert response.status_code == 200
    assert response.json()['ui_language'] == language
    with factory() as db:
        saved = db.get(User, 'alice').settings
        for key, value in original.items():
            assert saved[key] == value
        assert saved['ui_language'] == language
    assert client.patch('/api/settings', json={'subtitle_size': 28}).json()['ui_language'] == language


@pytest.mark.parametrize('invalid', ['fr', '', None, 42])
def test_invalid_new_language_rejected(client, invalid):
    assert client.patch('/api/settings', json={'ui_language': invalid}).status_code == 422


@pytest.mark.parametrize('old', [{}, {'ui_language': 'retired'}, {'ui_language': None}])
def test_legacy_language_falls_back_without_rewriting_history(client, factory, old):
    old = {**old, 'asr_profiles_initialized': True}
    with factory() as db:
        user = db.get(User, 'alice')
        user.settings = old
        db.commit()
    assert client.get('/api/settings').json()['ui_language'] == 'zh-CN'
    with factory() as db:
        assert db.get(User, 'alice').settings == old


def test_ui_language_is_user_scoped(client):
    assert client.patch('/api/settings', json={'ui_language': 'ko'}).status_code == 200
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login', json={'username': 'bob', 'password': PASSWORD}).status_code == 200
    assert client.get('/api/settings').json()['ui_language'] == 'zh-CN'
    assert client.patch('/api/settings', json={'ui_language': 'en'}).status_code == 200
    client.post('/api/auth/logout')
    client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD})
    assert client.get('/api/settings').json()['ui_language'] == 'ko'