"""Provider-neutral failure contract; messages belong to the adapter."""


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, diagnostics=None):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable
        self.diagnostics = dict(diagnostics or {})


def classify_status(status=0, code=''):
    """Return public category/retryability without provider text or raw responses."""
    value = str(code).lower()
    if status == 402 or any(s in value for s in ('arrearage', 'quota', 'insufficient', 'balance')):
        return 'quota_exhausted', False
    if status == 401 or any(s in value for s in ('apikey', 'unauthorized', 'authentication')):
        return 'authentication_failed', False
    if status == 403 or any(s in value for s in ('accessdenied', 'permission')):
        return 'model_permission', False
    if status == 404 or 'modelnotfound' in value:
        return 'model_unavailable', False
    if status == 429 or any(s in value for s in ('throttl', 'ratelimit', 'rate_limit')):
        return 'rate_limited', True
    if status in (408, 504) or 'timeout' in value:
        return 'timeout', True
    if status in (400, 422) or 'invalid' in value or 'format' in value:
        return 'format_error', False
    return 'upstream_error', status >= 500
