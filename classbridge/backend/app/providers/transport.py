"""Keep certificate-store I/O off the realtime event loop; TLS stays verified."""
import asyncio
import os
import ssl
import threading

import certifi

_contexts = {}
_lock = threading.Lock()


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
