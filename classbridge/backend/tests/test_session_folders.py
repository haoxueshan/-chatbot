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


def test_create_session_in_owned_folder(client, factory):
    response = client.post('/api/session-folders', json={'name': 'Course'})
    assert response.status_code == 201
    fid = response.json()['id']
    created = client.post('/api/sessions', json={'title': 'New lesson', 'folder_id': fid})
    assert created.status_code == 201, created.text
    sid = created.json()['id']
    assert created.json()['folder_id'] == fid
    assert client.get('/api/session-folders').json()[0]['session_count'] == 1
    assert [s['id'] for s in client.get('/api/sessions', params={'folder_id': fid}).json()] == [sid]
    assert client.get('/api/sessions?unfiled=true').json() == []
    with factory() as db:
        assert db.get(Session, sid).folder_id == fid
    for body in ({'title': 'Default'}, {'title': 'Explicit', 'folder_id': None}):
        response = client.post('/api/sessions', json=body)
        assert response.status_code == 201
        assert response.json()['folder_id'] is None


def test_create_rejects_foreign_missing_or_deleted_folder_without_insertion(client, factory):
    with factory() as db:
        seed(db, owner='bob', session_id='private', stream_id='private-stream')
        db.add(SessionFolder(id='private-folder', user_id='bob', name='Private', name_key='private'))
        db.commit()
        before = db.query(Session).count()
    created = client.post('/api/session-folders', json={'name': 'Deleted'})
    assert created.status_code == 201
    deleted = created.json()['id']
    assert client.delete(f'/api/session-folders/{deleted}').status_code == 200
    for fid in ('private-folder', 'missing', deleted):
        response = client.post('/api/sessions', json={'folder_id': fid})
        assert response.status_code == 404, response.text
    for fid in ('', 'x' * 37, 123):
        assert client.post('/api/sessions', json={'folder_id': fid}).status_code == 422
    with factory() as db:
        assert db.query(Session).count() == before


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


def test_batch_move_is_atomic_and_owner_scoped(client, factory):
    with factory() as db:
        seed(db)
        seed(db, owner='bob', session_id='private', stream_id='private-stream')
        db.add(SessionFolder(id='private-folder', user_id='bob', name='Private', name_key='private'))
        save_final(db, 'lesson', 'stream', 's1', 1, 'Evidence', 0, 1000, translation='证据')
        db.commit()
        models = (SegmentRevision, Translation, Event, ProcessingTask, Outbox)
        before = {model: db.query(model).count() for model in models}
    fid = client.post('/api/session-folders', json={'name': 'Batch'}).json()['id']
    sid = client.post('/api/sessions', json={'title': 'Second'}).json()['id']
    endpoint = '/api/session-folders/move-sessions'
    for ids, target in [
        (['lesson', 'private'], fid),
        (['lesson', 'missing'], fid),
        (['lesson', sid], 'private-folder'),
        (['lesson', sid], 'missing'),
    ]:
        assert client.post(endpoint, json={'session_ids': ids, 'folder_id': target}).status_code == 404
        with factory() as db:
            assert db.get(Session, 'lesson').folder_id is None
            assert db.get(Session, sid).folder_id is None
    response = client.post(endpoint, json={'session_ids': ['lesson', sid], 'folder_id': fid})
    assert response.status_code == 200, response.text
    assert response.json() == {'ok': True, 'moved': 2}
    assert client.get('/api/session-folders').json()[0]['session_count'] == 2
    assert client.post(endpoint, json={'session_ids': ['lesson', sid], 'folder_id': None}).status_code == 200
    with factory() as db:
        assert db.get(Session, 'lesson').folder_id is None
        assert db.get(Session, sid).folder_id is None
        assert db.get(Session, 'private').folder_id is None
        assert {model: db.query(model).count() for model in models} == before
        assert db.query(SegmentRevision).one().text == 'Evidence'
    assert client.post('/api/auth/logout').status_code == 200
    assert client.post(endpoint, json={'session_ids': ['lesson'], 'folder_id': None}).status_code == 401


@pytest.mark.parametrize('ids', [[], ['lesson', 'lesson'], [''], ['x' * 37], [123],
                                      [str(i) for i in range(101)]])
def test_batch_move_rejects_invalid_selection(client, ids):
    assert client.post('/api/session-folders/move-sessions',
                       json={'session_ids': ids, 'folder_id': None}).status_code == 422


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