"""The JSON registry is shared with the frontend; target codes never go to ASR."""
import json
from pathlib import Path
from typing import Literal

LANGUAGES=json.loads((Path(__file__).resolve().parents[1]/'data'/'translation_languages.json').read_text(encoding='utf8'))
SupportedTargetLanguage=Literal[tuple(LANGUAGES)]


def target_code(value='zh-CN'):
    if not isinstance(value,str) or value not in LANGUAGES:
        raise ValueError('不支持的字幕目标语言')
    return value


def target_name(code='zh-CN'):
    return LANGUAGES[target_code(code)]['mt_name']


def translation_terms(terms,code='zh-CN'):
    target_code(code)
    return [{'source':str(t['source']),'target':str(t['target'])} for t in (terms or [])
            if isinstance(t,dict) and t.get('source') and t.get('target')
            and t.get('target_language','zh-CN')==code][:100]
