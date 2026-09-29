"""Slack Block Kit alerts for signals, fills, and end-of-day P/L."""

from __future__ import annotations

from typing import Any

from loguru import logger
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.webhook import WebhookClient

from src.analysis.signals import TradeSignal
from src.config import Settings, get_settings
from src.data.storage import NotificationLog, session_scope
from src.utils import format_price, utcnow


def _header_text(signal: TradeSignal) -> str:
    if signal.action == "BUY":
        return f":large_green_circle: {signal.symbol} — Long Signal"
    if signal.action == "SELL":
        return f":red_circle: {signal.symbol} — Short Signal"
    return f":white_circle: {signal.symbol} — Hold"


def _rr(signal: TradeSignal) -> str:
    if signal.risk_reward is None:
        return "n/a"
    return f"1 : {signal.risk_reward:.2f}"


def signal_blocks(
    signal: TradeSignal,
    *,
    order_status: str | None = None,
    lot_size: int | None = None,
) -> list[dict[str, Any]]:
    confluence = ", ".join(signal.confluence) if signal.confluence else signal.reason
    fields = [
        {"type": "mrkdwn", "text": f"*Current Price*\n`{format_price(signal.symbol, signal.price)}`"},
        {"type": "mrkdwn", "text": f"*Timeframe*\n`{signal.timeframe}`  ·  HTF `{signal.htf_bias}`"},
        {
            "type": "mrkdwn",
            "text": (
                "*Oscillators*\n"
                f"RSI `{signal.rsi:.1f}`" if signal.rsi is not None else "*Oscillators*\nRSI `n/a`"
            )
            + (
                f"  ·  Stoch `{signal.stoch_k:.0f}`" if signal.stoch_k is not None else ""
            )
            + (f"  ·  ADX `{signal.adx:.0f}`" if signal.adx is not None else "")
            + (f"  ·  CCI `{signal.cci:.0f}`" if signal.cci is not None else ""),
        },
        {"type": "mrkdwn", "text": f"*Strength*\n`{signal.strength}/100`"},
    ]
    risk_fields = []
    if signal.entry is not None:
        risk_fields = [
            {"type": "mrkdwn", "text": f"*Entry*\n`{format_price(signal.symbol, signal.entry)}`"},
            {
                "type": "mrkdwn",
                "text": f"*Stop Loss*\n`{format_price(signal.symbol, signal.stop_loss or 0)}`",
            },
            {
                "type": "mrkdwn",
                "text": f"*Take Profit 1*\n`{format_price(signal.symbol, signal.take_profit_1 or 0)}`",
            },
            {
                "type": "mrkdwn",
                "text": f"*Take Profit 2*\n`{format_price(signal.symbol, signal.take_profit_2 or 0)}`",
            },
            {"type": "mrkdwn", "text": f"*Risk / Reward*\n`{_rr(signal)}`"},
            {"type": "mrkdwn", "text": f"*ATR*\n`{(signal.atr or 0):.5f}`"},
        ]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _header_text(signal), "emoji": True}},
        {"type": "section", "fields": fields},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Why*\n{signal.reason}"}},
    ]
    if risk_fields:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Risk Parameters*"},
            }
        )
        blocks.append({"type": "section", "fields": risk_fields})
    if order_status:
        lots = f" · `{lot_size}` units" if lot_size else ""
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: *Demo Order Status:* `{order_status}`{lots}",
                    }
                ],
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Forex Sentinel  ·  {utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                }
            ],
        }
    )
    return blocks


def fill_blocks(
    *,
    symbol: str,
    side: str,
    trade_id: str,
    units: int,
    fill_price: float,
    stop_loss: float,
    take_profit: float,
    slippage_pips: float | None,
) -> list[dict[str, Any]]:
    arrow = "Long" if side.upper() == "BUY" else "Short"
    emoji = ":large_green_circle:" if side.upper() == "BUY" else ":red_circle:"
    slip = f"{slippage_pips:+.1f} pips" if slippage_pips is not None else "n/a"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {symbol} — Demo Fill ({arrow})",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Demo Order Placed*\n`#{trade_id}`"},
                {"type": "mrkdwn", "text": f"*Filled Lot Size*\n`{units}` units"},
                {"type": "mrkdwn", "text": f"*Fill Price*\n`{format_price(symbol, fill_price)}`"},
                {"type": "mrkdwn", "text": f"*Slippage*\n`{slip}`"},
                {"type": "mrkdwn", "text": f"*Stop Loss*\n`{format_price(symbol, stop_loss)}`"},
                {"type": "mrkdwn", "text": f"*Take Profit*\n`{format_price(symbol, take_profit)}`"},
            ],
        },
    ]


def eod_blocks(
    *,
    day: str,
    starting_balance: float,
    ending_nav: float,
    realized_pl: float,
    unrealized_pl: float,
    trades_opened: int,
    trades_closed: int,
    drawdown_pct: float,
) -> list[dict[str, Any]]:
    tone = ":chart_with_upwards_trend:" if realized_pl >= 0 else ":chart_with_downwards_trend:"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{tone} End of Day — {day}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Starting Balance*\n`${starting_balance:,.2f}`"},
                {"type": "mrkdwn", "text": f"*Ending NAV*\n`${ending_nav:,.2f}`"},
                {"type": "mrkdwn", "text": f"*Realized P/L*\n`${realized_pl:+,.2f}`"},
                {"type": "mrkdwn", "text": f"*Unrealized P/L*\n`${unrealized_pl:+,.2f}`"},
                {"type": "mrkdwn", "text": f"*Trades Opened / Closed*\n`{trades_opened}` / `{trades_closed}`"},
                {"type": "mrkdwn", "text": f"*Drawdown*\n`{drawdown_pct:.2%}`"},
            ],
        },
    ]


def _clip(text: str | None, limit: int = 2800) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def journal_blocks(journal: Any) -> list[dict[str, Any]]:
    verb = "Why I bought" if journal.side == "BUY" else "Why I sold"
    emoji = ":large_green_circle:" if journal.side == "BUY" else ":red_circle:"
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {journal.symbol} — {verb}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Thesis*\n{_clip(journal.entry_thesis)}"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Fingerprint `{journal.fingerprint}`  ·  trade #{journal.trade_id}",
                }
            ],
        },
    ]


def postmortem_blocks(journal: Any) -> list[dict[str, Any]]:
    if journal.outcome == "loss":
        title = f":rotating_light: {journal.symbol} — What went wrong"
        body = journal.what_went_wrong or journal.lesson or ""
        extra = journal.how_to_avoid or ""
        extra_label = "How to avoid it"
        tags = getattr(journal, "mistakes", None) or []
        if tags:
            extra = (extra + "\n" if extra else "") + "Tags: `" + "`, `".join(tags) + "`"
    elif journal.outcome == "win":
        title = f":white_check_mark: {journal.symbol} — What went right"
        body = journal.what_went_right or journal.lesson or ""
        extra = ""
        extra_label = ""
    else:
        title = f":white_circle: {journal.symbol} — Scratch / review"
        body = journal.what_went_right or journal.lesson or ""
        extra = ""
        extra_label = ""
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Outcome*\n`{journal.outcome}`"},
                {"type": "mrkdwn", "text": f"*P/L*\n`${float(journal.realized_pl or 0):+,.2f}`"},
                {"type": "mrkdwn", "text": f"*Exit*\n`{journal.close_reason or 'n/a'}`"},
                {"type": "mrkdwn", "text": f"*Side*\n`{journal.side}`"},
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Review*\n{_clip(body)}"}},
    ]
    if extra:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{extra_label}*\n{_clip(extra)}"}}
        )
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Lesson · `{journal.fingerprint}`"}],
        }
    )
    return blocks


def intel_blocks(report: Any) -> list[dict[str, Any]]:
    price = getattr(report, "price", None)
    verdict = getattr(price, "verdict", "watch") if price is not None else "watch"
    emoji = {"consistent": ":white_check_mark:", "watch": ":eyes:", "disagree": ":warning:"}.get(
        verdict, ":memo:"
    )
    mid = getattr(price, "oanda_mid", None) if price is not None else None
    cf = getattr(price, "cf_mid", None) if price is not None else None
    div = getattr(price, "oanda_vs_cf_pips", None) if price is not None else None
    spread = getattr(price, "spread_pips", None) if price is not None else None
    fields = [
        {"type": "mrkdwn", "text": f"*OANDA*\n`{mid:.5f}`" if mid is not None else "*OANDA*\n`n/a`"},
        {"type": "mrkdwn", "text": f"*CurrencyFreaks*\n`{cf:.5f}`" if cf is not None else "*CurrencyFreaks*\n`n/a`"},
        {
            "type": "mrkdwn",
            "text": f"*Divergence*\n`{div:+.1f} pips`" if div is not None else "*Divergence*\n`n/a`",
        },
        {
            "type": "mrkdwn",
            "text": f"*Spread*\n`{spread:.1f} pips`" if spread is not None else "*Spread*\n`n/a`",
        },
        {"type": "mrkdwn", "text": f"*Integrity*\n`{verdict}`"},
        {"type": "mrkdwn", "text": f"*News*\n`{getattr(report, 'sentiment_label', 'n/a')}`"},
    ]
    te_mid = getattr(price, "te_mid", None) if price is not None else None
    te_div = getattr(price, "oanda_vs_te_pips", None) if price is not None else None
    if te_mid is not None or te_div is not None:
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*Trading Economics*\n`{te_mid:.5f}`" if te_mid is not None else "*Trading Economics*\n`n/a`",
            }
        )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*vs TE*\n`{te_div:+.1f} pips`" if te_div is not None else "*vs TE*\n`n/a`",
            }
        )
    fxs_mid = getattr(price, "fxs_mid", None) if price is not None else None
    fxs_div = getattr(price, "oanda_vs_fxs_pips", None) if price is not None else None
    if fxs_mid is not None or fxs_div is not None:
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*FXStreet*\n`{fxs_mid:.5f}`" if fxs_mid is not None else "*FXStreet*\n`n/a`",
            }
        )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*vs FXS*\n`{fxs_div:+.1f} pips`" if fxs_div is not None else "*vs FXS*\n`n/a`",
            }
        )
    bc_mid = getattr(price, "bc_mid", None) if price is not None else None
    bc_div = getattr(price, "oanda_vs_bc_pips", None) if price is not None else None
    if bc_mid is not None or bc_div is not None:
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*Barchart*\n`{bc_mid:.5f}`" if bc_mid is not None else "*Barchart*\n`n/a`",
            }
        )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*vs BC*\n`{bc_div:+.1f} pips`" if bc_div is not None else "*vs BC*\n`n/a`",
            }
        )
    inv_mid = getattr(price, "inv_mid", None) if price is not None else None
    inv_div = getattr(price, "oanda_vs_inv_pips", None) if price is not None else None
    if inv_mid is not None or inv_div is not None:
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*Investing.com*\n`{inv_mid:.5f}`" if inv_mid is not None else "*Investing.com*\n`n/a`",
            }
        )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*vs INV*\n`{inv_div:+.1f} pips`" if inv_div is not None else "*vs INV*\n`n/a`",
            }
        )
    tv_mid = getattr(price, "tv_mid", None) if price is not None else None
    tv_div = getattr(price, "oanda_vs_tv_pips", None) if price is not None else None
    if tv_mid is not None or tv_div is not None:
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*TradingView*\n`{tv_mid:.5f}`" if tv_mid is not None else "*TradingView*\n`n/a`",
            }
        )
        fields.append(
            {
                "type": "mrkdwn",
                "text": f"*vs TV*\n`{tv_div:+.1f} pips`" if tv_div is not None else "*vs TV*\n`n/a`",
            }
        )
    drivers = getattr(report, "drivers", None) or []
    driver_txt = "\n".join(f"• {d}" for d in drivers[:6]) or "• No driver list this cycle."
    headlines = getattr(report, "headlines", None) or []
    head_txt = "\n".join(
        f"• {h.get('title')}" for h in headlines[:4] if isinstance(h, dict) and h.get("title")
    )
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} EUR/USD intel — #forex",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Stance*\n{_clip(getattr(report, 'stance', ''), 1800)}"},
        },
        {"type": "section", "fields": fields},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*What can move EUR/USD*\n{_clip(driver_txt, 2400)}"},
        },
    ]
    if head_txt:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Headlines*\n{_clip(head_txt, 1800)}"},
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "Playbook rewritten at `desk/EURUSD_PLAYBOOK.md`  ·  "
                        "TE `desk/TRADINGECONOMICS.md`  ·  "
                        "FXS `desk/FXSTREET.md`  ·  "
                        "BC `desk/BARCHART.md`  ·  "
                        "INV `desk/INVESTING.md`  ·  "
                        "FF `desk/FOREXFACTORY.md`  ·  "
                        "TV `desk/TRADINGVIEW.md`  ·  "
                        "OPS `desk/OPERATING.md`  ·  "
                        "SCALP `desk/SCALPING.md`  ·  "
                        "MISTAKES `desk/MISTAKES.md`  ·  "
                        f"{utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                }
            ],
        }
    )
    return blocks


class SlackNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        token = self.settings.slack_bot_token.get_secret_value()
        webhook = self.settings.slack_webhook_url.get_secret_value()
        self._client = WebClient(token=token) if token else None
        self._webhook = WebhookClient(webhook) if webhook else None
        self._channel_id: str | None = self.settings.slack_channel_id.strip() or None
        self._channel_name = (self.settings.slack_channel or "forex").lstrip("#").strip() or "forex"
        self._ready = False

    @property
    def target_label(self) -> str:
        if self._channel_id:
            return f"#{self._channel_name} ({self._channel_id})"
        return f"#{self._channel_name}"

    def _looks_like_id(self, value: str) -> bool:
        return len(value) >= 9 and value[0] in {"C", "G", "D"} and value.replace("_", "").isalnum()

    def _join(self, channel_id: str) -> None:
        if not self._client:
            return
        try:
            self._client.conversations_join(channel=channel_id)
        except SlackApiError as exc:
            err = str(exc.response.get("error") if exc.response else exc)
            if err in {"already_in_channel", "method_not_supported_for_channel_type"}:
                return
            logger.warning("Slack join #{} failed: {}", self._channel_name, err)

    def resolve_channel(self) -> str | None:
        """Return the Slack channel ID for #forex (or the configured name/id)."""
        if self._channel_id:
            return self._channel_id
        configured = (self.settings.slack_channel_id or self.settings.slack_channel or "forex").strip()
        if not configured:
            configured = "forex"
        if self._looks_like_id(configured):
            self._channel_id = configured
            self._join(configured)
            return self._channel_id
        self._channel_name = configured.lstrip("#").lower()
        if not self._client:
            return None
        cursor = None
        try:
            while True:
                payload = self._client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True,
                    limit=200,
                    cursor=cursor or "",
                )
                for ch in payload.get("channels") or []:
                    if str(ch.get("name") or "").lower() == self._channel_name:
                        self._channel_id = str(ch["id"])
                        self._join(self._channel_id)
                        logger.info("Slack resolved #{} → {}", self._channel_name, self._channel_id)
                        return self._channel_id
                cursor = (payload.get("response_metadata") or {}).get("next_cursor") or None
                if not cursor:
                    break
        except SlackApiError as exc:
            logger.error("Slack channel lookup failed: {}", exc.response.get("error") if exc.response else exc)
            return None
        logger.error("Slack channel #{} was not found in this workspace", self._channel_name)
        return None

    def ensure_channel(self) -> tuple[bool, str]:
        """Resolve + join #forex. Webhooks skip lookup (they are bound to one channel)."""
        if self._webhook and not self._client:
            self._ready = True
            return True, f"webhook → #{self._channel_name}"
        if not self._client:
            return False, "no Slack bot token (SLACK_BOT_TOKEN)"
        cid = self.resolve_channel()
        if not cid:
            return False, f"#{self._channel_name} not found or bot cannot see it"
        self._ready = True
        return True, f"#{self._channel_name} ({cid})"

    def send_blocks(
        self,
        *,
        kind: str,
        title: str,
        blocks: list[dict[str, Any]],
        fallback: str,
        session=None,
        reuse=None,
    ) -> bool:
        delivered = False
        error: str | None = None
        if not self.settings.slack_enabled:
            error = "Slack not configured — paste a bot token or webhook on the hub"
            logger.info("Slack disabled — storing {} locally: {}", kind, title)
        else:
            try:
                channel = None
                if self._client:
                    channel = self.resolve_channel()
                if self._client and channel:
                    self._client.chat_postMessage(
                        channel=channel,
                        text=fallback,
                        blocks=blocks,
                    )
                    delivered = True
                elif self._webhook:
                    self._webhook.send(text=fallback, blocks=blocks)
                    delivered = True
                else:
                    error = f"#{self._channel_name} is not reachable"
                    logger.error("Slack send skipped: {}", error)
            except SlackApiError as exc:
                error = str(exc.response.get("error") if exc.response else exc)
                if error == "not_in_channel" and self._channel_id:
                    self._join(self._channel_id)
                    try:
                        self._client.chat_postMessage(  # type: ignore[union-attr]
                            channel=self._channel_id,
                            text=fallback,
                            blocks=blocks,
                        )
                        delivered = True
                        error = None
                    except Exception as retry_exc:  # noqa: BLE001
                        error = str(retry_exc)
                        logger.error("Slack API error: {}", error)
                else:
                    logger.error("Slack API error: {}", error)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                logger.error("Slack send failed: {}", exc)
        if reuse is not None:
            reuse.delivered = delivered
            reuse.error = error
            reuse.payload = {"blocks": blocks, "fallback": fallback, "channel": self.target_label}
            return delivered
        row = NotificationLog(
            ts=utcnow(),
            kind=kind,
            title=title,
            payload={"blocks": blocks, "fallback": fallback, "channel": self.target_label},
            delivered=delivered,
            error=error,
        )
        if session is not None:
            session.add(row)
        else:
            with session_scope() as own:
                own.add(row)
        return delivered

    def signal(
        self,
        signal: TradeSignal,
        *,
        order_status: str | None = None,
        lot_size: int | None = None,
        session=None,
    ) -> bool:
        blocks = signal_blocks(signal, order_status=order_status, lot_size=lot_size)
        return self.send_blocks(
            kind="signal",
            title=_header_text(signal),
            blocks=blocks,
            fallback=signal.summary(),
            session=session,
        )

    def fill(self, session=None, **kwargs: Any) -> bool:
        blocks = fill_blocks(**kwargs)
        title = f"Demo Order Placed (#{kwargs.get('trade_id')})"
        return self.send_blocks(kind="fill", title=title, blocks=blocks, fallback=title, session=session)

    def journal(self, journal, session=None) -> bool:
        verb = "Why I bought" if journal.side == "BUY" else "Why I sold"
        title = f"{journal.symbol} — {verb}"
        return self.send_blocks(
            kind="journal",
            title=title,
            blocks=journal_blocks(journal),
            fallback=title,
            session=session,
        )

    def postmortem(self, journal, session=None) -> bool:
        title = f"{journal.symbol} — {journal.outcome} post-mortem"
        return self.send_blocks(
            kind="postmortem",
            title=title,
            blocks=postmortem_blocks(journal),
            fallback=title,
            session=session,
        )

    def eod(self, **kwargs: Any) -> bool:
        blocks = eod_blocks(**kwargs)
        title = f"End of Day — {kwargs.get('day')}"
        return self.send_blocks(kind="eod", title=title, blocks=blocks, fallback=title)

    def warning(self, title: str, detail: str) -> bool:
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f":warning: {title}", "emoji": True},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
        ]
        return self.send_blocks(kind="warning", title=title, blocks=blocks, fallback=f"{title}: {detail}")

    def intel(self, report: Any, session=None) -> bool:
        blocks = intel_blocks(report)
        stance = getattr(report, "stance", None) or "EUR/USD intel"
        return self.send_blocks(
            kind="intel",
            title="EUR/USD intel",
            blocks=blocks,
            fallback=f"EUR/USD intel — {stance}",
            session=session,
        )

    def startup_ping(self) -> bool:
        ok, detail = self.ensure_channel()
        if not ok:
            logger.warning("Slack not posting to #{}: {}", self._channel_name, detail)
            return False
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":chart_with_upwards_trend: Forex Sentinel — #forex",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"Live on *{detail}*. Intel (price integrity + EUR/USD news), "
                        "signals, demo fills, theses, post-mortems, and the daily recap land here."
                    ),
                },
            },
        ]
        return self.send_blocks(
            kind="startup",
            title="Forex Sentinel online",
            blocks=blocks,
            fallback="Forex Sentinel is posting to #forex",
        )

    def desk_note(self, note, session=None) -> bool:
        kind = note.kind or "morning"
        if kind == "morning":
            title = f"EUR/USD morning briefing — {note.day}"
            header = f":sunrise: EUR/USD — {note.sentiment or 'Morning briefing'}"
            chunks = [
                ("*Sentiment*", note.why or note.sentiment or ""),
                ("*What I am looking for*", note.looking_for or ""),
                ("*Goals for the day*", note.goals or ""),
            ]
            news = (note.news or {}).get("events") or []
            if news:
                lines = []
                for ev in news[:6]:
                    lines.append(
                        f"• `{ev.get('ts') or ''}` {ev.get('country')} {ev.get('impact')}: {ev.get('title')}"
                    )
                chunks.append(("*News that can move EUR/USD*", "\n".join(lines)))
            headlines = (note.news or {}).get("headlines") or []
            if headlines:
                chunks.append(
                    (
                        "*Headlines*",
                        "\n".join(f"• {h.get('title')}" for h in headlines[:5]),
                    )
                )
        else:
            title = f"EUR/USD daily analysis — {note.day}"
            header = f":moon: EUR/USD — {(note.verdict or 'recap').upper()} day"
            chunks = [
                ("*Why*", note.why or ""),
                ("*What went right*", note.what_went_right or ""),
                ("*What went wrong*", note.what_went_wrong or ""),
                ("*What I learned*", note.learned or ""),
            ]
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": header[:150], "emoji": True}}
        ]
        for label, text in chunks:
            if not text:
                continue
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"{label}\n{_clip(str(text), 2800)}"},
                }
            )
        return self.send_blocks(kind=kind, title=title, blocks=blocks, fallback=title, session=session)

    def news_scan(self, result: dict[str, Any], headlines: list, *, session=None) -> bool:
        added = result.get("added") or 0
        stored = result.get("stored") or 0
        pending = result.get("pending") or 0
        lines = [
            f"Stored *{added}* new EUR/USD wires (book {stored}, {pending} waiting on a later M5 close)."
        ]
        for item in headlines[:6]:
            title = getattr(item, "title", None) or (item.get("title") if isinstance(item, dict) else "")
            source = getattr(item, "source", None) or (item.get("source") if isinstance(item, dict) else "")
            if title:
                lines.append(f"• {source}: {title}")
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":newspaper: EUR/USD news scan", "emoji": True},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": _clip("\n".join(lines), 2800)}},
        ]
        return self.send_blocks(
            kind="news_scan",
            title="EUR/USD news scan",
            blocks=blocks,
            fallback="EUR/USD news scan",
            session=session,
        )

    def tape(self, body: str, *, symbol: str = "EUR/USD", action: str = "HOLD", session=None) -> bool:
        header = f":memo: {symbol} tape — {action}"
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": header[:150], "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": _clip(body, 2800)}},
        ]
        return self.send_blocks(
            kind="tape",
            title=header,
            blocks=blocks,
            fallback=body.splitlines()[0][:180] if body else header,
            session=session,
        )

    def replay_outbox(self, session, limit: int = 12) -> int:
        from src.data.storage import get_undelivered_notifications

        sent = 0
        for row in get_undelivered_notifications(session, limit=limit):
            payload = row.payload or {}
            blocks = payload.get("blocks")
            if not isinstance(blocks, list) or not blocks:
                continue
            ok = self.send_blocks(
                kind=row.kind,
                title=row.title,
                blocks=blocks,
                fallback=str(payload.get("fallback") or row.title),
                session=session,
                reuse=row,
            )
            if ok:
                sent += 1
        return sent

    def apply_credentials(self, settings: Settings) -> None:
        self.settings = settings
        token = settings.slack_bot_token.get_secret_value()
        webhook = settings.slack_webhook_url.get_secret_value()
        self._client = WebClient(token=token) if token else None
        self._webhook = WebhookClient(webhook) if webhook else None
        self._channel_id = settings.slack_channel_id.strip() or None
        self._channel_name = (settings.slack_channel or "forex").lstrip("#").strip() or "forex"
        self._ready = False
