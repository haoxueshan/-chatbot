"""Pure DashScope wire protocol. No transport, persistence or translation."""
from app.providers.errors import ProviderError

EVENTS = frozenset(('task-started', 'task-finished', 'task-failed', 'result-generated'))


def invalid():
    return ProviderError('protocol_error', '识别服务返回了无效的协议字段；未生成正式原文。')


def timestamp(value):
    # Wire protocol specifies integer milliseconds; bool is not an integer here.
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise invalid()
    return value


def normalize_sentence(sentence):
    if not isinstance(sentence, dict):
        raise invalid()
    if 'heartbeat' in sentence and type(sentence['heartbeat']) is not bool:
        raise invalid()
    if sentence.get('heartbeat') is True:
        return None
    sid = sentence.get('sentence_id')
    if type(sid) is not int or sid < 1 or not isinstance(sentence.get('text'), str):
        raise invalid()
    final = sentence.get('sentence_end')
    if type(final) is not bool or 'end_time' not in sentence:
        raise invalid()
    start = timestamp(sentence.get('begin_time'))
    end = sentence['end_time']
    if end is not None:
        end = timestamp(end)
        if end < start:
            raise invalid()
    elif final:
        raise invalid()
    words = []
    for word in sentence.get('words', []) if isinstance(sentence.get('words'), list) else []:
        try:
            if not isinstance(word, dict) or not isinstance(word.get('text'), str):
                continue
            begin, finish = timestamp(word.get('begin_time')), timestamp(word.get('end_time'))
            if begin < start or finish < begin or (end is not None and finish > end):
                continue
            item = {'text': word['text'], 'begin_time': begin, 'end_time': finish}
            if type(word.get('fixed')) is bool:
                item['fixed'] = word['fixed'] # diagnostic only, never permanent stability
            words.append(item)
        except ProviderError:
            continue
    result = dict(sentence_id=str(sid), text=sentence['text'], start_ms=start,
                  end_ms=end, final=final, words=words)
    if end is None and words:
        result['provisional_end_ms'] = max(w['end_time'] for w in words)
    return result


def parse_server_event(data, task_id):
    if not isinstance(data, dict) or not isinstance(data.get('header'), dict):
        raise invalid()
    header = data['header']
    if not isinstance(header.get('task_id'), str):
        raise invalid()
    if header['task_id'] != task_id:
        return 'foreign', None
    event = header.get('event')
    if not isinstance(event, str):
        raise invalid()
    if event not in EVENTS:
        return 'unknown', None
    if 'payload' in data and not isinstance(data['payload'], dict):
        raise invalid()
    if event == 'task-failed' and not isinstance(header.get('error_code', ''), str):
        raise invalid()
    if event != 'result-generated':
        return event, None
    payload = data.get('payload')
    if not isinstance(payload, dict) or not isinstance(payload.get('output'), dict):
        raise invalid()
    return event, normalize_sentence(payload['output'].get('sentence'))


def build_finish_task(task_id):
    return {'header': {'action': 'finish-task', 'task_id': task_id, 'streaming': 'duplex'},
            'payload': {'input': {}}}


def build_run_task(task_id, model, *, vocabulary=None, context=None, language_hints=None, vad_model=None, options=None):
    params = {'format': 'pcm', 'sample_rate': 16000, 'heartbeat': True}
    for key in ('max_sentence_silence','multi_threshold_mode_enabled','speech_noise_threshold','keep_dialect'):
        value=(options or {}).get(key)
        if value is None:continue
        if model != 'qwen-audio-3.1-asr-flash-streaming':
            raise ProviderError('invalid_asr_parameter','当前模型的可选 VAD 参数兼容性尚未验证。')
        valid = (type(value) is int and 200<=value<=6000) if key=='max_sentence_silence' else (
            type(value) in (int,float) and -1<=value<=1 if key=='speech_noise_threshold' else type(value) is bool)
        if not valid:raise ProviderError('invalid_asr_parameter','可选 VAD 参数类型或范围无效。')
        params[key]=value
    if vad_model is not None:
        if vad_model not in ('near_meeting_16k', 'far_field_meeting_16k'):
            raise ProviderError('invalid_asr_parameter', '不支持的拾音场景参数。')
        params['vad_model'] = vad_model
    if language_hints:
        params['language_hints'] = list(language_hints)
    if vocabulary:
        params['vocabulary'] = {str(k): max(1, min(5, int(v))) for k, v in vocabulary.items()}
    inputs = {}
    if context:
        inputs['context'] = [{'role': 'user', 'content': [{'type': 'input_text', 'text': str(context).strip()[:400]}]}]
    return {'header': {'action': 'run-task', 'task_id': task_id, 'streaming': 'duplex'},
            'payload': {'task_group': 'audio', 'task': 'asr', 'function': 'recognition',
                        'model': model, 'parameters': params, 'input': inputs}}
