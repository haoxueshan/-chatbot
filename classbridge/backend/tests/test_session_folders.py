"""Folder classification must not change saved session evidence."""
import pytest
from test_core import factory, client, seed
from app.models import Session, SessionFolder, SegmentRevision, Translation, Event, ProcessingTask, Outbox
from app.services.events import save_final


def test_folder_lifecycle_preserves_evidence(client, factory):
    with factory() as db:
        seed(db)
        save_final(db, 'lesson', 'stream', 's1', 1, 'Evidence', 0, 1000, translation='证据')
        models = (SegmentRevision, Translation, Event, ProcessingTask, Outbox)
        before = {model: db.query(model).count() for model in models}
    response = client.post('/api/session-folders', json={'name': '  Course  A '})
    assert response.status_code == 201, response.text
    folder = response.json()
    assert folder['name'] == 'Course A'
    fid = folder['id']
    assert client.patch('/api/sessions/lesson/folder', json={'folder_id': fid}).status_code == 200
    assert client.get('/api/session-folders').json()[0]['session_count'] == 1
    assert [s['id'] for s in client.get('/api/sessions', params={'folder_id': fid}).json()] == ['lesson']
    assert client.get('/api/sessions?unfiled=true').json() == []
    assert client.get('/api/sessions', params={'folder_id': fid, 'q': 'Evidence'}).status_code == 200
    assert client.patch(f'/api/session-folders/{fid}', json={'name': 'Renamed'}).status_code == 200
    assert client.delete(f'/api/session-folders/{fid}').status_code == 200
    with factory() as db:
        assert db.get(Session, 'lesson').folder_id is None
        assert db.get(SessionFolder, fid) is None
        assert {model: db.query(model).count() for model in models} == before
        assert db.query(SegmentRevision).one().text == 'Evidence'
    assert [s['id'] for s in client.get('/api/sessions?unfiled=true').json()] == ['lesson']


def test_folder_owner_isolation(client, factory):
    with factory() as db:
        seed(db)
        seed(db, owner='bob', session_id='private', stream_id='private-stream')
        db.add(SessionFolder(id='private-folder', user_id='bob', name='Private', name_key='private'))
        db.commit()
    assert client.get('/api/session-folders').json() == []
    assert client.patch('/api/session-folders/private-folder', json={'name': 'Stolen'}).status_code == 404
    assert client.delete('/api/session-folders/private-folder').status_code == 404
    assert client.get('/api/sessions?folder_id=private-folder').status_code == 404
    assert client.patch('/api/sessions/lesson/folder', json={'folder_id': 'private-folder'}).status_code == 404
    assert client.patch('/api/sessions/private/folder', json={'folder_id': None}).status_code == 404
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/session-folders').status_code == 401


@pytest.mark.parametrize('name', ['', '   ', 'x' * 81, '\x00', 123])
def test_invalid_folder_names(client, name):
    assert client.post('/api/session-folders', json={'name': name}).status_code == 422


def test_folder_conflicts_and_selection_validation(client, factory):
    with factory() as db:
        seed(db)
    assert client.post('/api/session-folders', json={'name': 'Course'}).status_code == 201
    assert client.post('/api/session-folders', json={'name': 'ＣＯＵＲＳＥ'}).status_code == 409
    assert client.patch('/api/sessions/lesson/folder', json={}).status_code == 422
    assert client.patch('/api/sessions/lesson/folder', json={'folder_id': None, 'title': 'bad'}).status_code == 422
    assert client.get('/api/sessions?folder_id=missing&unfiled=true').status_code == 422
    assert client.patch('/api/sessions/lesson/folder', json={'folder_id': None}).status_code == 200