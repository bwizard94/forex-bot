"""Environment-driven configuration for Forex Sentinel."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


Timeframe = Literal["M1", "M5", "H1", "D1"]
BrokerEnvironment = Literal["practice", "live"]
TradingStyle = Literal["scalp", "swing"]


class Settings(BaseSettings):
    """Loads API keys, risk thresholds, and runtime options from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Market data (Twelve Data OHLCV backup) ---
    twelvedata_api_key: SecretStr = Field(default=SecretStr(""))
    twelvedata_base_url: str = "https://api.twelvedata.com"

    # --- Market data (CurrencyFreaks independent FX mids) ---
    currencyfreaks_api_key: SecretStr = Field(default=SecretStr(""))
    currencyfreaks_base_url: str = "https://api.currencyfreaks.com"
    reference_quote_ttl_seconds: int = 300
    quote_warn_pips: float = 8.0

    # --- Paper trading (OANDA v20) ---
    oanda_api_token: SecretStr = Field(default=SecretStr(""))
    oanda_account_id: str = ""
    oanda_environment: BrokerEnvironment = "practice"

    # --- Slack ---
    slack_bot_token: SecretStr = Field(default=SecretStr(""))
    slack_channel: str = "forex"
    slack_channel_id: str = ""
    slack_webhook_url: SecretStr = Field(default=SecretStr(""))

    # --- Database ---
    database_url: str = "sqlite:///./data/forex_bot.db"

    # --- Watchlist & indicators ---
    watchlist: str = "EUR/USD"
    trading_style: TradingStyle = "scalp"
    signal_timeframe: Timeframe = "M5"
    strategy_research_only: bool = False
    htf_bias_timeframe: Timeframe = "H1"
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    session_filter: bool = True
    practice_broker_market_hours: bool = False
    trade_session_start_hour: int = 0
    trade_session_end_hour: int = 22
    require_htf_trend: bool = True
    min_atr_pips: float = 0.8
    min_stop_pips: float = 5.0
    scalp_max_spread_pips: float = 1.8
    scalp_max_hold_minutes: int = 90
    max_trades_per_day: int = 8
    friday_flat_hour: int = 20
    monday_open_skip_minutes: int = 45
    max_fill_slippage_pips: float = 1.5
    slippage_cooloff_minutes: int = 20
    stale_quote_seconds: int = 90
    cost_stop_fraction: float = 0.25
    practice_sampling_enabled: bool = False
    practice_sampling_risk_cap: float = Field(default=0.001, gt=0, le=0.01)
    practice_sampling_until: datetime | None = None

    # --- Risk ---
    risk_per_trade_pct: float = 0.006
    daily_loss_limit_pct: float = 0.03
    practice_daily_loss_halt_enabled: bool = True
    practice_contextual_loss_review: bool = False
    daily_reduce_at_pct: float = 0.001
    daily_soft_halt_pct: float = 0.0025
    max_drawdown_pct: float = 0.10
    max_open_positions: int = 3
    max_same_side_positions: int = 2
    max_open_risk_pct: float = 0.025
    conviction_risk_pct: float = 0.009
    conviction_strength_min: int = 68
    addon_risk_pct: float = 0.004
    fade_risk_pct: float = 0.004
    fade_strength_min: int = 76
    addon_min_profit_pips: float = 2.0
    max_units_per_trade: int = 100_000
    max_order_notional_pct: float | None = Field(default=None, gt=0, le=1)
    min_confluence: int = 2
    confirmed_entry_policy: bool = False  # prospective candidate; evidence does not support promotion yet
    atr_sl_multiplier: float = 1.0
    atr_tp1_multiplier: float = 1.2
    atr_tp2_multiplier: float = 2.0
    min_rr_ratio: float = 1.15

    # --- Lessons (repeat-loser fingerprints) ---
    lesson_lookback_days: int = 14
    lesson_loss_high_strength: int = 1
    lesson_loss_skip: int = 2
    lesson_skip_hours: int = 72
    lesson_high_strength_min: int = 68
    lesson_scratch_usd: float = 2.0
    family_loss_skip: int = 2
    post_loss_cooldown_minutes: int = 4
    reentry_cooldown_minutes: int = 2
    max_consecutive_losses: int = 2
    news_blackout_minutes: int = 30
    briefing_hour: int = 8
    briefing_minute: int = 0
    recap_hour: int = 23
    recap_minute: int = 30
    news_scan_hour: int = 5
    news_scan_minute: int = 0
    slack_pulse_minutes: int = 15
    intel_interval_minutes: int = 20
    extra_datasets_dir: str = "extra datasets"
    tavily_api_key: SecretStr = Field(default=SecretStr(""))

    # --- Google Sheets (via Composio) ---
    composio_api_key: SecretStr = Field(default=SecretStr(""))
    composio_connected_account_id: str = ""
    google_sheets_spreadsheet_id: str = ""
    google_sheets_spreadsheet_url: str = ""
    sheets_sync_enabled: bool = True

    # --- MetaTrader 4 demo (second book beside OANDA practice) ---
    mt4_enabled: bool = True
    mt4_login: str = ""
    mt4_password: SecretStr = Field(default=SecretStr(""))
    mt4_server: str = ""
    mt4_bridge_secret: SecretStr = Field(default=SecretStr(""))
    mt4_magic: int = 212100
    metaapi_token: SecretStr = Field(default=SecretStr(""))
    metaapi_account_id: str = ""
    metaapi_region: str = "new-york"

    # --- Runtime ---
    enable_trading: bool = True
    log_level: str = "INFO"
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    fetch_interval_seconds: int = 60
    tz: str = "UTC"

    @field_validator(
        "risk_per_trade_pct",
        "daily_loss_limit_pct",
        "daily_reduce_at_pct",
        "daily_soft_halt_pct",
        "max_drawdown_pct",
        "max_open_risk_pct",
        "conviction_risk_pct",
        "addon_risk_pct",
        "fade_risk_pct",
    )
    @classmethod
    def _pct_in_range(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("percentage settings must be in (0, 1]")
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level_upper(cls, value: str) -> str:
        return value.upper()

    @property
    def symbols(self) -> list[str]:
        """Canonical display symbols. USD/EUR is stored and traded as EUR/USD."""
        from src.utils import canonical_pair

        seen: list[str] = []
        for item in self.watchlist.split(","):
            raw = item.strip()
            if not raw:
                continue
            pair = canonical_pair(raw)
            if pair not in seen:
                seen.append(pair)
        return seen or ["EUR/USD"]

    @property
    def oanda_host(self) -> str:
        if self.oanda_environment == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"

    @property
    def slack_enabled(self) -> bool:
        token = self.slack_bot_token.get_secret_value()
        has_bot = bool(token and (self.slack_channel_id or self.slack_channel))
        has_webhook = bool(self.slack_webhook_url.get_secret_value())
        return has_bot or has_webhook

    def masked_summary(self) -> dict[str, object]:
        """Safe-to-log snapshot of configuration."""
        td = self.twelvedata_api_key.get_secret_value()
        cf = self.currencyfreaks_api_key.get_secret_value()
        oa = self.oanda_api_token.get_secret_value()
        return {
            "symbols": self.symbols,
            "signal_timeframe": self.signal_timeframe,
            "trading_style": self.trading_style,
            "htf_bias_timeframe": self.htf_bias_timeframe,
            "enable_trading": self.enable_trading,
            "oanda_environment": self.oanda_environment,
            "oanda_account_id": self.oanda_account_id or "(auto-discover)",
            "database": self.database_url.split("@")[-1],
            "twelvedata_key": f"...{td[-4:]}" if len(td) >= 4 else "(missing)",
            "currencyfreaks_key": f"...{cf[-4:]}" if len(cf) >= 4 else "(missing)",
            "oanda_token": f"...{oa[-4:]}" if len(oa) >= 4 else "(missing)",
            "slack_enabled": self.slack_enabled,
            "slack_channel": self.slack_channel_id or self.slack_channel or "forex",
            "google_sheets": bool(self.google_sheets_spreadsheet_id),
            "mt4_login": (self.mt4_login or "").strip() or "(disconnected)",
            "mt4_server": (self.mt4_server or "").strip() or "(disconnected)",
            "metaapi": bool(self.metaapi_token.get_secret_value()),
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "conviction_risk_pct": self.conviction_risk_pct,
            "max_open_positions": self.max_open_positions,
            "max_same_side_positions": self.max_same_side_positions,
            "max_open_risk_pct": self.max_open_risk_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "max_trades_per_day": self.max_trades_per_day,
            "friday_flat_hour": self.friday_flat_hour,
            "extra_datasets_dir": self.extra_datasets_dir,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def upsert_env_values(updates: dict[str, str], path: str = ".env") -> None:
    """Write key=value pairs into .env without dropping unrelated rows."""
    from pathlib import Path

    target = Path(path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    lines = existing.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen and value != "":
            out.append(f"{key}={value}")
    target.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
