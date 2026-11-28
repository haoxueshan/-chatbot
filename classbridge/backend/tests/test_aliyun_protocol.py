import pytest
from app.providers.errors import ProviderError
from app.providers.aliyun import ProviderError as LegacyError, classify_error
from app.providers.asr.soniox import soniox_error
from app.providers.asr.aliyun_protocol import normalize_sentence, parse_server_event


def sentence(**changes):
    return dict(sentence_id=1, text='한국어 English', begin_time=1000,
                end_time=None, sentence_end=False, **changes)


def test_error_compatibility():
    assert LegacyError is ProviderError
    a, b = ProviderError('a', 'a'), ProviderError('b', 'b')
    a.diagnostics['private'] = True
    assert not b.diagnostics
    for status, code in [(401, 'authentication_failed'), (402, 'quota_exhausted'),
                         (403, 'model_permission'), (429, 'rate_limited')]:
        assert classify_error(status).code == soniox_error(status).code == code
        assert '阿里云' not in soniox_error(status).message


@pytest.mark.parametrize('field,value', [('begin_time', True), ('begin_time', -1),
    ('begin_time', float('nan')), ('end_time', float('inf')), ('end_time', False),
    ('end_time', 999), ('sentence_end', 'false'), ('sentence_id', True),
    ('sentence_id', None), ('text', []), ('words', None)])
def test_strict_fields_optional_words_fallback(field, value):
    data = sentence(); data[field] = value
    if field == 'words':
        assert normalize_sentence(data)['text'] == data['text']
    else:
        with pytest.raises(ProviderError, match='协议字段'):
            normalize_sentence(data)


@pytest.mark.parametrize('field', ['sentence_id', 'text', 'begin_time', 'end_time', 'sentence_end'])
def test_required_fields(field):
    data = sentence(); del data[field]
    with pytest.raises(ProviderError): normalize_sentence(data)


def test_provisional_not_confirmed_or_stable():
    data = sentence(words=[{'text': '한국어', 'begin_time': 1000, 'end_time': 1400, 'fixed': True},
                           {'text': 'bad', 'begin_time': 1400, 'end_time': True}])
    event = normalize_sentence(data)
    assert event['end_ms'] is None and event['provisional_end_ms'] == 1400
    assert 'stable_prefix_hint' not in event
    data.update(sentence_end=True, end_time=2500)
    assert normalize_sentence(data)['end_ms'] == 2500
    data['end_time'] = None
    with pytest.raises(ProviderError): normalize_sentence(data)


def test_empty_final_and_heartbeat_are_distinct():
    data = sentence(); data.update(text='', sentence_end=True, end_time=2500)
    assert normalize_sentence(data)['final'] is True
    assert normalize_sentence({'heartbeat': True}) is None


@pytest.mark.parametrize('data', [[], None, {'header': []}, {'header': {'task_id': 't', 'event': []}},
    {'header': {'task_id': 't', 'event': 'result-generated'}, 'payload': []}])
def test_invalid_envelope(data):
    with pytest.raises(ProviderError): parse_server_event(data, 't')


def test_foreign_and_unknown_are_ignored_before_payload():
    assert parse_server_event({'header': {'task_id': 'foreign', 'event': 'result-generated'}}, 't') == ('foreign', None)
    assert parse_server_event({'header': {'task_id': 't', 'event': 'future-event'}}, 't') == ('unknown', None)
