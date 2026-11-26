from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol, TypedDict, NotRequired


class ASREvent(TypedDict):
    sentence_id: str
    text: str
    start_ms: int
    end_ms: int | None
    final: bool
    words: NotRequired[list]


class ASRProvider(Protocol):
    """Adapters must advance metrics['sent_audio_ms'] only after ws.send succeeds.

    LiveCapture uses received minus sent PCM for total admission accounting,
    including batching and in-flight frames. This is not provider ASR acknowledgement.
    Adapters must not retry uncertain audio or change the stream implicitly.
    """
    def ensure_configured(self) -> None: ...

    def stream_asr(self, audio: AsyncIterator[bytes], *, vocabulary: dict | None = None,
                   context: str | None = None, language_hints: list[str] | None = None,
                   vad_model: str | None = None, on_ready: Callable[[], Awaitable[None]] | None = None,
                   metrics: dict | None = None) -> AsyncIterator[ASREvent]: ...
