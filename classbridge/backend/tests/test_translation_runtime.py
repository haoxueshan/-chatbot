"""Public configuration contract; no cloud calls or private environment edits."""
from pathlib import Path

from app.config import Settings, settings
from test_core import client, factory


BASELINE = {
    'incremental_translation_enabled': True,
    'preview_min_stable_seconds': .25,
    'preview_interval_seconds': .5,
    'preview_max_wait_seconds': 2.4,
    'preview_min_words': 2,
    'preview_min_change_chars': 4,
    'preview_concurrency': 1,
    'preview_calls_per_minute': 40,
    'translation_emit_seconds': .1,
}


def test_template_matches_code_defaults():
    template = Path(__file__).resolve().parents[2] / '.env.example'
    values = dict(
        line.split('=', 1) for line in template.read_text(encoding='utf-8').splitlines()
        if line and not line.startswith('#') and '=' in line
    )
    for name, expected in BASELINE.items():
        assert Settings.model_fields[name].default == expected
        raw = values[name.upper()]
        actual = raw.lower() == 'true' if isinstance(expected, bool) else float(raw)
        assert actual == expected, name


def test_environment_overrides_defaults(monkeypatch):
    monkeypatch.setenv('INCREMENTAL_TRANSLATION_ENABLED', 'false')
    monkeypatch.setenv('PREVIEW_INTERVAL_SECONDS', '1.2')
    config = Settings(_env_file=None)
    assert config.incremental_translation_enabled is False
    assert config.preview_interval_seconds == 1.2


def test_authenticated_runtime_reports_actual_settings(client, monkeypatch):
    monkeypatch.setattr(settings, 'preview_interval_seconds', .7)
    monkeypatch.setattr(settings, 'incremental_translation_enabled', False)
    response = client.get('/api/settings')
    assert response.status_code == 200
    runtime = response.json()['translation_runtime']
    assert runtime['preview_interval_seconds'] == .7
    assert runtime['incremental_translation_enabled'] is False
    assert runtime['mode'] == 'legacy'
    assert set(runtime) == set(BASELINE) | {
        'translation_poll_seconds', 'model', 'mode', 'budget_scope',
    }
    assert runtime['model'] == settings.translation_model
    assert runtime['budget_scope'] == 'process'
    client.post('/api/auth/logout')
    assert client.get('/api/settings').status_code == 401