import pytest
from app.services.stable_prefix import StablePrefixProcessor
from app.services.translation_timing import TranslationTiming, wall_queue_ms
from datetime import datetime, timedelta, timezone


@pytest.mark.parametrize('a,b,expected', [
    ('오늘은 인공지능을 배', '오늘은 인공지능을 배웁니다', '오늘은 인공지능을 '),
    ('We study neural net', 'We study neural networks', 'We study neural '),
    ('오늘은 RAG retrieval 배', '오늘은 RAG retrieval 배웁니다.', '오늘은 RAG retrieval '),
    ('학생이 공부합', '학생이 공부합니다', '학생이 '),
])
def test_whole_word_agreement(a,b,expected):
    p=StablePrefixProcessor()
    assert p.update('s','1',a,0).stable_preview==''
    result=p.update('s','1',b,.5)
    assert result.stable_preview==expected
    assert result.stable_preview+result.unstable_tail==b
    assert not result.is_final


def test_duplicates_do_not_confirm_and_time_alone_is_not_agreement():
    p=StablePrefixProcessor()
    a=p.update('s','1','The first word.',0)
    b=p.update('s','1','The first word.',2)
    assert a.hypothesis_revision==b.hypothesis_revision==1
    assert b.stable_preview==''


def test_minimum_age_rollback_and_suffix_change():
    p=StablePrefixProcessor()
    p.update('s','1','학생이 공부합니다. 다음',0)
    assert p.update('s','1','학생이 공부합니다. 다음은',.1).stable_preview==''
    assert p.view('s','1',.5).stable_preview=='학생이 공부합니다. '
    assert p.update('s','1','학생이 공부했어요. 다음은',.6).stable_preview=='학생이 '
    assert p.rollbacks==1
    assert p.update('s','1','교수가',.7).stable_preview==''


def test_bounds_final_and_stream_reset():
    p=StablePrefixProcessor(max_sentences=4,max_chars=30,ttl_seconds=5)
    for i in range(10000):p.update('s',str(i),'hello world',i/10000)
    assert len(p.states)==4
    p.update('s','big','x'*31,1)
    assert ('s','big') not in p.states
    assert p.finalize('s','9999').is_final
    p.update('new','1','new stream',2)
    p.reset_stream('s')
    assert list(p.states)==[('new','1')]
    p.expire(10)
    assert not p.states


def test_timing_separates_monotonic_model_from_wall_queue():
    clock=[10.0];t=TranslationTiming(lambda:clock[0])
    clock[0]=10.25;t.token();clock[0]=10.5
    assert t.finish()=={'translation_model_first_ms':250,'translation_model_final_ms':500}
    now=datetime.now(timezone.utc)
    assert wall_queue_ms(now,now+timedelta(milliseconds=120))==(120,False)
    assert wall_queue_ms(now,now-timedelta(seconds=1))==(0,True)
