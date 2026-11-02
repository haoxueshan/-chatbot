"""Map only source words from the owner's glossary to documented ASR vocabulary."""
from typing import Literal
import unicodedata

ASRLanguageMode = Literal['auto', 'ko_en', 'ko']


def asr_language_hints(mode):
    # Hints are recognition input languages, never the Chinese translation target.
    return {'ko_en': ['ko', 'en'], 'ko': ['ko']}.get(mode)


def asr_vocabulary_report(terms, weight=2):
    result = {};skipped=[]
    weight=weight if type(weight) is int and 2<=weight<=4 else 2
    for index,item in enumerate(terms if isinstance(terms,list) else []):
        word = item.get('source',item.get('term','')) if isinstance(item,dict) else item
        word=unicodedata.normalize('NFC',' '.join(word.split())) if isinstance(word,str) else ''
        reason=None
        if not word:reason='缺少原词'
        elif len(word)>128:reason='超过应用单词条128字符限制'
        elif not word.isascii() and len(word)>15:reason='含非ASCII字符，超过15字符限制'
        elif word.isascii() and len(word.split())>7:reason='英文词条超过7个单词'
        elif word in result:reason='重复原词，已合并'
        elif len(result)>=200:reason='超过200个热词应用限制'
        if reason:skipped.append({'index':index,'reason':reason})
        else:result[word]=weight
    return {'vocabulary':result,'skipped':skipped}


def asr_vocabulary(terms, weight=2):
    return asr_vocabulary_report(terms,weight)['vocabulary']
