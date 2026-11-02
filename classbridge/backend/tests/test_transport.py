import asyncio
import ssl
import threading
import time

import pytest

from app.providers import transport


@pytest.mark.asyncio
async def test_slow_certificate_load_is_shared_and_does_not_stall_audio_loop(monkeypatch):
    monkeypatch.setattr(transport, '_contexts', {})
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    loop_thread = threading.get_ident()
    calls = []
    context = object()

    def slow_store(**kwargs):
        assert threading.get_ident() != loop_thread
        calls.append(kwargs)
        time.sleep(.12)
        return context

    monkeypatch.setattr(transport.ssl, 'create_default_context', slow_store)
    tasks = [asyncio.create_task(transport.tls_context()) for _ in range(4)]
    audio_ticks = 0
    while not all(task.done() for task in tasks):
        audio_ticks += 1
        await asyncio.sleep(.01)
    assert await asyncio.gather(*tasks) == [context] * 4
    assert len(calls) == 1
    assert audio_ticks >= 5, '20 ms PCM handling must keep running during certificate I/O'
    assert await transport.tls_context() is context
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tls_verification_and_private_ca_precedence_are_preserved(monkeypatch):
    monkeypatch.setattr(transport, '_contexts', {})
    monkeypatch.delenv('SSL_CERT_FILE', raising=False)
    monkeypatch.delenv('SSL_CERT_DIR', raising=False)
    context = await transport.tls_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    calls = []
    monkeypatch.setattr(transport.ssl, 'create_default_context', lambda **kw: calls.append(kw) or context)
    monkeypatch.setenv('SSL_CERT_FILE', 'private-ca.pem')
    monkeypatch.setenv('SSL_CERT_DIR', 'private-certs')
    await transport.tls_context()
    assert calls == [{'cafile': 'private-ca.pem', 'capath': None}]


def test_asr_glossary_uses_valid_source_words_without_translation_or_foreign_data():
    from app.services.asr_options import asr_vocabulary
    result = asr_vocabulary([
        {'source': 'working memory', 'target': '工作记忆'}, '인지 부하',
        {'term': 'RAG'}, 'working memory', {'source': None},
        '가' * 16, 'one two three four five six seven eight',
    ])
    assert result == {'working memory': 2, '인지 부하': 2, 'RAG': 2}
    assert len(asr_vocabulary([f'term{i}' for i in range(250)])) == 200


def test_glossary_reports_skipped_terms_and_normalizes_korean_without_inventing_words():
    import unicodedata
    from app.services.asr_options import asr_vocabulary_report
    word='작업기억'
    report=asr_vocabulary_report([unicodedata.normalize('NFD',word),word,'가'*16,
        'one two three four five six seven eight',{'source':''}, {'source':'인지부하','target':'认知负荷'}],4)
    assert report['vocabulary']=={'작업기억':4,'인지부하':4}
    assert [item['index'] for item in report['skipped']]==[1,2,3,4]
    assert '重复' in report['skipped'][0]['reason']
    assert '15' in report['skipped'][1]['reason']
    assert '7' in report['skipped'][2]['reason']
    assert asr_vocabulary_report([],4)=={'vocabulary':{},'skipped':[]}
