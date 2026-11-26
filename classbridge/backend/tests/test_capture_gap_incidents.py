import pytest
from unittest.mock import AsyncMock
from app.models import Event
from app.ws.live import LiveCapture
from app.services.capture_incidents import fields
from test_core import factory,seed


def test_unknown_duration_and_non_loss_classification():
    for kind in ['asr_interrupted','audio_delayed','user_paused','connection_recovered','translation_delayed']:
        value=fields('capture','stream',kind,'reason',0)
        assert value['duration_ms'] is None and value['missing_audio_ms'] is None
        assert value['recovered'] is False
    assert fields('capture','stream','audio_missing','overflow',20)['missing_audio_ms']==20
    assert fields('a','s','audio_missing','x')['incident_id']!=fields('b','s','audio_missing','x')['incident_id']
    assert fields(None,None,'x','x')['incident_id']!=fields(None,None,'x','x')['incident_id']


@pytest.mark.asyncio
async def test_incident_keeps_all_evidence_and_first_failure(factory):
    with factory() as db:seed(db,mode='real')
    c=LiveCapture(AsyncMock(),'lesson','alice');c.stream_id='stream';c.request_id='capture';c.started=1;c.received_audio_ms=1000
    await c.fail('audio_backlog','first')
    await c.gap('current frame rejected',20,kind='audio_missing')
    await c.gap('upstream incomplete',None,kind='asr_result_uncertain')
    await c.fail('upstream_disconnected','later')
    with factory() as db:
        events=db.query(Event).all();failures=[e for e in events if e.type=='processing.failed']
        gaps=[e.payload for e in events if e.type=='capture.gap']
        assert len(failures)==1 and failures[0].payload['code']=='audio_backlog'
        assert len(gaps)==2 and {g['incident_id'] for g in gaps}=={'capture:failure'}
        assert gaps[0]['missing_audio_ms']==20 and gaps[1]['duration_ms'] is None
        assert all(g['start_ms']==1000 for g in gaps) # Sample position, not wall-clock age.
        assert all(g['recoverable'] is False for g in gaps)


@pytest.mark.asyncio
async def test_interrupted_sender_persists_unsent_accounting_before_release(factory):
    from app.providers.aliyun import ProviderError
    with factory() as db:seed(db,mode='real')
    class Provider:
        async def stream_asr(self,*args,**kwargs):
            raise ProviderError('upstream_disconnected','mock disconnect')
            yield
    c=LiveCapture(AsyncMock(),'lesson','alice');c.mode='real';c.stream_id='stream';c.request_id='capture'
    c.ready=True;c.started=1;c.asr_provider=Provider()
    c.received_audio_ms=20;c.queue.put_nowait(bytes(640));c.queued_bytes=640;c.queued_frames=1
    await c.run()
    with factory() as db:
        stopped=db.query(Event).filter_by(type='session.state').all()[-1].payload
        assert db.query(Event).filter_by(type='processing.failed').one().payload['diagnostics']['retryable'] is False
        assert stopped['diagnostics']['unsent_pcm_bytes']==640
        assert stopped['diagnostics']['uncertain_delivery_pcm_bytes']==0
        assert stopped['diagnostics']['capture_state']=='STOPPED'
        assert db.query(Event).filter_by(type='capture.gap').count()>=1
    assert c.buffers_released and c.queue.empty() and c.buffer_bytes()==0
