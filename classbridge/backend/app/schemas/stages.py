def stage_text(value, fallback=''):
    if not isinstance(value, str) or value.strip().lower() in ('', 'none', 'null', 'undefined'):
        return fallback
    return value.strip()
