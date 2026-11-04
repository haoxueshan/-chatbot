"""Keep certificate-store I/O off the realtime event loop; TLS stays verified."""
import asyncio
import os
import ssl
import threading

import certifi

_contexts = {}
_lock = threading.Lock()

# PCM16LE, mono, 16 kHz: 32 bytes/ms, 640 bytes per 20 ms frame.
PCM_BYTES_PER_MS = 32
PCM_FRAME_BYTES = 640
PCM_QUEUE_BYTES = 2000 * PCM_BYTES_PER_MS


async def blocking_call(function, *args):
    """Join an in-flight blocking operation before cleanup closes its resources.

    Callers create/close DB sessions INSIDE function, never across threads.
    Only ordered transactions, batches or fixed maintenance loops use this.
    """
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A write failure must remain visible even if cleanup requested cancel.
        await task
        raise


def _load_context(key):
    with _lock:
        if key not in _contexts:
            cafile, capath = key
            # Match HTTPX's trust_env precedence, including private CA overrides.
            _contexts[key] = ssl.create_default_context(
                cafile=cafile or (None if capath else certifi.where()),
                capath=capath if not cafile else None,
            )
        return _contexts[key]


async def tls_context():
    key = (os.environ.get('SSL_CERT_FILE'), os.environ.get('SSL_CERT_DIR'))
    cached = _contexts.get(key)
    if cached is not None:
        return cached
    return await asyncio.to_thread(_load_context, key)
