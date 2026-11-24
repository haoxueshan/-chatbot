"""Offline scoring and explicitly invoked WAV replay; no credentials loaded here."""
import asyncio
import re
import time
import unicodedata
import wave

from .base import ASRProvider


def _error_rate(reference, hypothesis):
    if not reference:return None
    previous=list(range(len(hypothesis)+1))
    for i,left in enumerate(reference,1):
        row=[i]
        for j,right in enumerate(hypothesis,1):
            row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(left!=right)))
        previous=row
    return previous[-1]/len(reference)


def score(reference: str | None, hypothesis: str, terms=()):
    """English word / Korean character / mixed token rates, not model ratings.

    NFC, case-insensitive English words; Korean whitespace and punctuation are
    excluded. Mixed tokens use English words plus individual Korean characters.
    Only supplied terms actually present in the reference form the denominator.
    """
    if reference is None:return None
    reference=unicodedata.normalize('NFC',reference).casefold()
    hypothesis=unicodedata.normalize('NFC',hypothesis).casefold()
    english=lambda text:re.findall(r"[a-z]+(?:['’\-][a-z]+)*",text)
    korean=lambda text:re.findall(r'[가-힣ᄀ-ᇿㄱ-ㆎ]',text)
    mixed=lambda text:re.findall(r"[a-z]+(?:['’\-][a-z]+)*|\d+|[^\W\d_]",text)
    selected={unicodedata.normalize('NFC',term).casefold() for term in terms if term.strip()}
    def present(term,text):return re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])',text) is not None
    selected={term for term in selected if present(term,reference)}
    return {'english_wer':_error_rate(english(reference),english(hypothesis)),
            'korean_cer':_error_rate(korean(reference),korean(hypothesis)),
            'mixed_token_error_rate':_error_rate(mixed(reference),mixed(hypothesis)),
            'term_retention':sum(present(term,hypothesis) for term in selected)/len(selected) if selected else None}


async def evaluate_wav(provider: ASRProvider, path, *, reference=None, terms=(),
                       language_hints=None, realtime=True, clock=time.monotonic, sleep=asyncio.sleep):
    """Same 20 ms PCM WAV input for any adapter. Caller authorizes real API use.

    No transcript is printed or returned in the report. This tool is for bounded
    recordings, not production capture. Exceptions propagate; partial text never
    counts as final evidence. Run sequential providers to avoid network contention.
    """
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getcomptype())!=(1,2,16000,'NONE'):
            raise ValueError('WAV must be uncompressed mono PCM16LE at 16000 Hz')
        samples=wav.getnframes()
        if not 0<samples<=16000*6300:raise ValueError('WAV must contain 0–105 minutes of audio')
        ready_at=None;audio_end=None;first_partial=None;last_final=None;frames=0;sent=0;finals={};metrics={}
        async def ready():
            nonlocal ready_at
            ready_at=clock()
        async def audio():
            nonlocal frames,sent,audio_end
            if ready_at is None:raise RuntimeError('Provider must acknowledge readiness before reading audio')
            while data:=wav.readframes(320):
                if realtime:await sleep(max(0,ready_at+sent/32000-clock()))
                frames+=1;sent+=len(data)
                yield data
            if realtime:await sleep(max(0,ready_at+sent/32000-clock()))
            audio_end=clock()
        async for event in provider.stream_asr(audio(),on_ready=ready,metrics=metrics,language_hints=language_hints):
            if event['final']:
                # One authoritative snapshot per identity, including legitimate corrections.
                finals[event['sentence_id']]=event['text'];last_final=clock()
            elif first_partial is None and event['text']:first_partial=clock()
        if sent!=samples*2 or audio_end is None:raise RuntimeError('Provider did not drain the complete WAV')
        return {'audio_ms':samples/16,'frames':frames,'forwarded_bytes':sent,'final_segments':len(finals),
                'first_partial_ms':(first_partial-ready_at)*1000 if first_partial is not None else None,
                'last_final_ms':(last_final-ready_at)*1000 if last_final is not None else None,
                'final_after_audio_ms':(last_final-audio_end)*1000 if last_final is not None else None,
                'send_wait_ms':metrics.get('send_wait_ms'),'hourly_cost':None,
                'accuracy':score(reference,' '.join(finals.values()),terms)}


def evaluation_config(provider, model=None):
    """Resolve replay-only settings without mutating shared session configuration."""
    from app.config import Settings
    from app.providers.aliyun import ProviderError
    from .registry import get_provider
    definition=get_provider(provider)
    if definition.adapter is None:
        raise ProviderError('unsupported_asr_provider','该 ASR 供应商尚未接入。')
    config=Settings(asr_provider=provider)
    resolved=model if model is not None else (config.asr_model if provider=='aliyun' else definition.default_model)
    if not isinstance(resolved,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}',resolved):
        raise ProviderError('invalid_asr_model','模型 ID 格式无效。')
    return config.model_copy(update={'asr_model':resolved})


def main():
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Explicit paid ASR WAV evaluation; no MT or automatic retry')
    parser.add_argument('wav');parser.add_argument('--provider',default='aliyun')
    parser.add_argument('--model',help='Explicit provider model ID (no automatic fallback)')
    parser.add_argument('--reference',help='UTF-8 manually corrected reference file')
    parser.add_argument('--terms',help='UTF-8 newline-separated technical terms')
    parser.add_argument('--language',choices=('auto','ko_en','ko'),default='auto')
    parser.add_argument('--allow-paid',action='store_true',help='Explicitly authorize one real ASR task')
    args=parser.parse_args()
    if not args.allow_paid:parser.error('No API called. Real replay requires explicit --allow-paid authorization.')
    # Import settings only after explicit authorization, never for offline scoring.
    from .factory import create_asr_provider
    from app.providers.aliyun import ProviderError
    from app.services.asr_options import asr_language_hints
    try:
        provider=create_asr_provider(evaluation_config(args.provider,args.model))
        provider.ensure_configured()
        report=asyncio.run(evaluate_wav(provider,args.wav,
            reference=Path(args.reference).read_text(encoding='utf-8') if args.reference else None,
            terms=Path(args.terms).read_text(encoding='utf-8').splitlines() if args.terms else (),
            language_hints=asr_language_hints(args.language)))
    except ProviderError as exc:parser.exit(1,f'ASR failed: {exc.code}\n')
    except (ValueError,OSError,wave.Error,RuntimeError):parser.exit(1,'Evaluation failed: invalid WAV/reference or incomplete audio drain\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
