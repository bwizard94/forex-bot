# Forex Sentinel

A **Python EUR/USD specialist**: live analysis, alerting, journaling, and **practice** trading on one pair. It is trying to become a better *intraday scalper* of EUR/USD — not a multi-pair platform, not a swing book, and not a machine-learning classifier of the next 5 minutes.

```
Fetch EUR/USD → Indicators → H1+D1 bias → Session / news / lessons → Risk → Demo fill (OANDA, then MT4 copy) → Journal → Slack / Sheets / SQLite → Rewrite living desk docs
```

Version lives in `src/__init__.py`. The live loop is `python -m src.main` (FastAPI hub + APScheduler). Default hub: `http://127.0.0.1:8765`. All clocks are **UTC**.

---

## If you are another AI (read this first)

You are joining an existing EUR/USD **practice desk**, not a greenfield trading platform. Scan this file, then `desk/OPERATING.md`, `desk/SCALPING.md`, `desk/MISTAKES.md`, and `desk/MT4.md` before changing strategy code.

### Standing orders (do not violate)

| Rule | Meaning |
| --- | --- |
| **EUR/USD only** | Canonical pair is `EUR/USD`. `USD/EUR` is stored and traded as EUR/USD. Do not add other FX pairs, crypto, or stocks. |
| **Ox scalp, not ML** | Live tickets come from the Ox triad (LWMA 48, Trend Envelopes period 2, DSS) plus H1/D1 bias and named setups. **Do not replace that with Random Forest / LSTM / “predict next bar”.** Name the regime (squeeze / trend / rip / washout / chop). Skip a continuation doji. |
| **Operator fills are sacred** | Anything on the OANDA practice account that is not a bot `fs-…` stamp is **human**. Never flatten, TP1, time-stop, or net-close it. New desk orders use **`OPEN_ONLY`** so they sit beside a teacher ticket. Same on MT4: magic **212100** is the desk; any other magic is hands-off. |
| **Washout is not a ticket** | Never **short** RSI ≤ 40 / lower Bollinger / WaveTrend ≤ −53. Never **buy** RSI ≥ 60 / upper band / WaveTrend ≥ 53. Fade the *rip*, not the dump. |
| **5-pip stop floor** | ATR stop, floor **5.0 pips**; outcome statistics do not automatically widen it. No 2-pip ECN sniper. |
| **Capital first** | 0.6% / 0.9% / 0.4% / 0.4% risk table. Combined open desk risk **2.5%** NAV. Daily halt **3%**. Drawdown breaker **10%**. Max **3** bot positions, **2** same-side. Cap **100k** units. Max **8** desk fills per UTC day. |
| **No martingale / grid** | Add-on only if the open ticket is already **≥ +2 pips**, then at 0.4%. After a real loss today, next size is *reduced*. Two consecutive losses sit until the next session. |
| **Expectancy, not one outlier** | A fat winner (e.g. +$775) does **not** license more sells into a hole. Growth uses median P/L and last-two-stop streaks, not the mean. Skip a named setup whose historical expectancy is negative. |
| **Intel is context, not a ticket** | TE / FXStreet / Barchart / Investing / TradingView / Forex Factory / headlines inform the playbook. They do not fire `OrderCreate`. News is a **±30 minute blackout**, then trade the H1 reaction. |
| **Weekend gap** | Friday **flat after 20:00 UTC**. **No Sunday reopen.** Monday Tokyo **first 45 minutes** sit out. Session otherwise **00:00–22:00 UTC weekdays**. |
| **Secrets stay in `.env`** | Never commit tokens, passwords, or `MT4_BRIDGE_SECRET`. `.env` is gitignored. The operator Drive / Desktop `forex` copy **does** include `.env` (practice keys) so a successor agent can fill OANDA and MT4 demos. Git clones must copy that file in, never the other way around. |
| **Practice host** | `OANDA_ENVIRONMENT=practice` unless a human deliberately changed it. Do not point this at live fxTrade by accident. |
| **Keep the loop alive** | `python -m src.main` is the desk. Do not stop it to “clean up.” Do not turn the app into a static page or a Vercel-only deploy. |

### How to work this repo

1. **Language / stack:** Python 3.12, FastAPI + uvicorn, APScheduler (UTC), SQLAlchemy 2 + SQLite WAL (`data/forex_bot.db`), pandas/numpy, loguru, pydantic-settings, pytest. UI is the dashboard in `src/dashboard/` (static HTML/JS on `:8765`).
2. **Change strategy in code + tests**, then rewrite standing notes in `desk/OPERATING.md` / `desk/SCALPING.md` / `desk/MISTAKES.md` if the rule actually changed. The bot already rewrites living files (`EURUSD_PLAYBOOK.md`, `LEARNING_LOG.md`, `GROWTH.md`, `HISTORY.md`, `NEWS_LOG.md`, `NEWS_PATTERNS.md`) every cycle — **do not commit that churn** unless the human asked for a doc dump.
3. **Cloud agents cannot see the operator’s Desktop.** Extra historical dumps belong in this repo’s `extra datasets/` folder. A local folder named “extra datasets” on the laptop is invisible here.
4. **Dual venue:** OANDA practice is primary. MT4 demo gets a **copy** after a successful OANDA fill. An MT4 reject does **not** flatten OANDA. See `desk/MT4.md`.
5. **Tests:** `pytest` from the repo root (venv). Add tests when you change signals, risk, trade_guard, MT4, or news rules (`tests/test_*.py`).
6. **Times:** UTC everywhere (briefing 08:00, recap 23:30, news harvest 05:00, session filter).
7. **Do not add** auth, a second component library, or unrelated services unless the human asked. Slack `#forex` and Google Sheets are optional integrations; missing tokens must degrade to local storage, not crash the loop.
