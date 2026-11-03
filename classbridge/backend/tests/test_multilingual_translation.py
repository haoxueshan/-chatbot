"""All cloud calls are MockTransport/stubs; never use a real key or user DB."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from app.config import settings
from app.models import User, Session, Translation, SegmentRevision, ProcessingTask, Event, Chunk
from app.providers.aliyun import AliyunProvider, ProviderError
from app.services.events import save_final, save_translation, serialize_segment
from app.services.incremental_translation import translation_spec, spec_digest, validated_reuse, IncrementalTranslator, PreviewBudget
from app.services.translation_languages import LANGUAGES, target_name, translation_terms
from app.workers.tasks import translate
from app.ws.live import LiveCapture
from test_core import factory, client, seed
from test_providers import config, install_http
from test_incremental_translation import config as preview_config, flush


TERMS = ['인지심리학', {'source': 'memory', 'target': '记忆'},
         {'source': '기억', 'target': 'memory', 'target_language': 'en'},
         {'source': '기억', 'target': '記憶', 'target_language': 'ja'}]


@pytest.mark.parametrize('code', list(LANGUAGES))
def test_preferences_validate_and_preserve_other_fields(client, code):
    assert client.get('/api/settings').json()['target_language'] == 'zh-CN'
    response = client.patch('/api/settings', json={'target_language': code, 'asr_language_mode': 'ko_en', 'terms': TERMS})
    assert response.status_code == 200
    assert response.json()['target_language'] == code
    response = client.patch('/api/settings', json={'theme': 'dark'})
    assert response.json()['target_language'] == code
    assert response.json()['asr_language_mode'] == 'ko_en'
    assert response.json()['terms'] == TERMS


@pytest.mark.parametrize('invalid', ['English', 'xx', '', None, 7])
def test_unknown_targets_are_422_not_chinese(client, invalid):
    assert client.patch('/api/settings', json={'target_language': invalid}).status_code == 422
    assert client.post('/api/sessions', json={'target_language': invalid}).status_code == 422
    assert client.patch('/api/settings', json={'terms': [{'source':'x','target':'y','target_language':invalid}]}).status_code == 422
    assert client.get('/api/settings').json()['target_language'] == 'zh-CN'


@pytest.mark.parametrize('code', ['en', 'ko', 'ja'])
def test_session_snapshot_default_explicit_and_demo_isolation(client, monkeypatch, code):
    # Configuration validation stub only; creating a session itself never calls MT.
    monkeypatch.setattr(AliyunProvider, 'ensure_configured', lambda self: None)
    old = client.post('/api/sessions', json={}).json()
    client.patch('/api/settings', json={'target_language':code})
    implicit = client.post('/api/sessions', json={'mode':'real'}).json()
    explicit = client.post('/api/sessions', json={'mode':'real','target_language':code}).json()
    assert implicit['target_language'] == explicit['target_language'] == code
    assert client.post('/api/sessions', json={'mode':'demo'}).status_code == 422
    assert client.post('/api/sessions', json={'mode':'demo','target_language':'zh-CN'}).status_code == 201
    client.patch('/api/settings', json={'target_language':'ar'})
    assert client.get(f"/api/sessions/{old['id']}").json()['target_language'] == 'zh-CN'
    assert client.get(f"/api/sessions/{explicit['id']}").json()['target_language'] == code


@pytest.mark.asyncio
@pytest.mark.parametrize('code', list(LANGUAGES))
async def test_actual_mt_payload_for_every_registered_target(monkeypatch, code):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={'Content-Type':'text/event-stream'},
            text='data: {"choices":[{"delta":{"content":"Mock translation"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    install_http(monkeypatch, handler)
    result = [s async for s in AliyunProvider(config()).translate_stream('안녕하세요. Hello.',
        target_lang=target_name(code), terms=translation_terms(TERMS,code), require_complete=True)]
    assert ''.join(result) == 'Mock translation'
    assert len(captured) == 1
    assert captured[0]['translation_options']['target_lang'] == LANGUAGES[code]['mt_name']
    assert captured[0]['translation_options']['source_lang'] == 'auto'
    assert captured[0]['stream'] is True
    if code != 'zh-CN':assert '记忆' not in json.dumps(captured[0], ensure_ascii=False)


@pytest.mark.asyncio
async def test_provider_rejects_unknown_target_without_network():
    with pytest.raises(ProviderError) as error:
        async for _ in AliyunProvider(config()).translate_stream('source',target_lang='xx'):pass
    assert error.value.code == 'unsupported_target_language'


@pytest.mark.asyncio
async def test_formal_task_freezes_language_versions_and_rejects_mismatch(factory, monkeypatch):
    calls = []
    async def mock_mt(self, text, **kwargs):
        calls.append((text,kwargs))
        yield 'Memory is important.'
    monkeypatch.setattr(AliyunProvider,'translate_stream',mock_mt)
    with factory() as db:
        session = seed(db,mode='real');session.target_language='en'
        db.get(User,'alice').settings={'target_language':'ja','terms':TERMS};db.commit()
        save_final(db,'lesson','stream','s',2,'기억은 중요합니다.',0,1500)
        source=db.query(SegmentRevision).one()
        task=db.query(ProcessingTask).filter_by(kind='translate').one()
        assert task.payload == {'segment_id':source.id,'source_revision':2,'target_language':'en'}
        original_payload=dict(task.payload)
        task.payload={**original_payload,'target_language':'ja'}
        with pytest.raises(ValueError,match='语言或原文版本'):await translate(db,task)
        assert calls == []
        task.payload=original_payload
        await translate(db,task)
        assert len(calls)==1 and calls[0][0]=='기억은 중요합니다.'
        assert calls[0][1]['target_lang']=='English'
        assert calls[0][1]['terms']==[{'source':'기억','target':'memory'}]
        saved=db.query(Translation).one()
        assert saved.target_language=='en' and saved.text=='Memory is important.'
        assert source.text=='기억은 중요합니다.' and source.source_revision==2
        assert serialize_segment(db,source)['target_language']=='en'
        for event in db.query(Event).all():
            assert event.payload['target_language']=='en'
        assert (await translate(db,task))['skipped']=='translation_already_saved'
        assert len(calls)==1
        with pytest.raises(ValueError):save_translation(db,source.id,'wrong',target_language='ja')


@pytest.mark.asyncio
@pytest.mark.parametrize('incremental',[False,True])
async def test_live_preview_and_ready_keep_session_target(factory, monkeypatch, incremental):
    monkeypatch.setattr(settings,'incremental_translation_enabled',incremental)
    calls=[]
    async def mock_mt(self,text,**kwargs):calls.append(kwargs);yield 'English preview'
    monkeypatch.setattr(AliyunProvider,'translate_stream',mock_mt)
    with factory() as db:
        session=seed(db,mode='real');session.target_language='en'
        db.get(User,'alice').settings={'target_language':'ja','terms':TERMS};db.commit()
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.mode='real';c.started=0
    c.current_revisions['a']=1
    assert c.capture_language()=='en'
    await c.mark_ready()
    with factory() as db:
        ready=db.query(Event).filter_by(type='session.state').first()
        assert ready.payload['target_language']=='en'
        db.get(User,'alice').settings={'target_language':'ko','terms':TERMS};db.commit()
    if incremental:
        preview=c.ensure_preview()
        clock=[0.];preview.clock=lambda:clock[0];preview.budget=PreviewBudget()
        preview.update('a',1,'오늘 수업입니다.',0,1000)
        clock[0]=3;preview.tick();await flush()
        await preview.close()
    else:
        c.current_revisions['a']=1
        await c.partial_translation('a',1,'오늘 수업입니다.',0,1000)
    assert calls and calls[0]['target_lang']=='English'
    assert calls[0]['terms']==[{'source':'기억','target':'memory'}]
    assert c.ws.send_json.call_args.args[0]['target_language']=='en'
    with factory() as db:assert db.query(SegmentRevision).count()==db.query(Chunk).count()==0


def test_cache_digest_and_reuse_are_language_specific():
    from types import SimpleNamespace
    cfg=preview_config();now=datetime.now(timezone.utc)
    specs=[translation_spec(cfg,TERMS,c) for c in LANGUAGES]
    assert len({spec_digest(s) for s in specs})==14
    row=SimpleNamespace(text='hello',stream_id='s',sentence_id='a',source_revision=2)
    candidate={'complete':True,'text':row.text,'stream_id':'s','sentence_id':'a','source_revision':2,
        'translation':'你好','saved_at':now.isoformat(),'expires_at':(now+timedelta(seconds=30)).isoformat(),
        'spec_digest':spec_digest(translation_spec(cfg,TERMS,'zh-CN'))}
    assert validated_reuse(candidate,row,translation_spec(cfg,TERMS,'zh-CN'),now)=='你好'
    assert validated_reuse(candidate,row,translation_spec(cfg,TERMS,'en'),now) is None


def test_exports_use_session_language_not_latest_preference(client,factory):
    with factory() as db:
        session=seed(db,mode='real');session.target_language='en';db.commit()
        save_final(db,'lesson','stream','s',1,'기억은 중요합니다.',0,1500,translation='Memory is important.')
    client.patch('/api/settings',json={'target_language':'ja'})
    for fmt in ('md','txt'):
        response=client.get(f'/api/sessions/lesson/export?format={fmt}')
        assert response.status_code==200
        assert '字幕翻译目标语言：英语' in response.text
        assert '기억은 중요합니다.' in response.text and 'Memory is important.' in response.text


def test_non_chinese_real_mode_without_key_never_becomes_demo(client):
    response=client.post('/api/sessions',json={'mode':'real','target_language':'en'})
    assert response.status_code==503 and response.json()['detail']['code']=='missing_api_key'
    assert client.get('/api/sessions').json()==[]


@pytest.mark.asyncio
async def test_failed_non_chinese_translation_preserves_official_source(factory,monkeypatch):
    async def broken(self,*args,**kwargs):
        raise ProviderError('network_error','Mock failure')
        yield ''
    monkeypatch.setattr(AliyunProvider,'translate_stream',broken)
    with factory() as db:
        row=seed(db,mode='real');row.target_language='ja';db.commit()
        save_final(db,'lesson','stream','s',1,'한국어 원문 English evidence.',0,1000)
        task=db.query(ProcessingTask).filter_by(kind='translate').one()
        with pytest.raises(ProviderError):await translate(db,task)
        db.rollback()
        source=db.query(SegmentRevision).one()
        assert source.text=='한국어 원문 English evidence.' and source.status=='final'
        assert db.query(Translation).count()==0
