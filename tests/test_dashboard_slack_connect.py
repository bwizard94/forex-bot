from types import SimpleNamespace

from src.config import Settings
from src.pipeline import TradingPipeline


def test_explicit_slack_connection_overrides_empty_service_environment(monkeypatch):
    import src.config as config
    monkeypatch.setenv('SLACK_BOT_TOKEN', '')
    monkeypatch.setenv('SLACK_WEBHOOK_URL', '')
    monkeypatch.setenv('SLACK_CHANNEL', 'forex')
    saved = {}
    applied = []
    monkeypatch.setattr(config, 'upsert_env_values', lambda updates: saved.update(updates))
    monkeypatch.setattr(config, 'reload_settings', lambda: Settings(_env_file=None))
    pipe = TradingPipeline.__new__(TradingPipeline)
    pipe.settings = Settings(_env_file=None)
    pipe.slack = SimpleNamespace(apply_credentials=lambda settings: applied.append(settings),
                                 ensure_channel=lambda: (False, 'mock connection check'),
                                 _ready=False, target_label='#forex')
    result = pipe.connect_slack(bot_token='xoxb-test-placeholder', channel='forex')
    assert not result['ok']
    assert saved['SLACK_BOT_TOKEN'] == 'xoxb-test-placeholder'
    assert applied[0].slack_bot_token.get_secret_value() == 'xoxb-test-placeholder'
