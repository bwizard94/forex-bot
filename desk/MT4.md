# MetaTrader 4 demo venue

EUR/USD desk tickets fill on **OANDA practice first**, then a copy is sent to an MT4 demo so both books move together. This process runs on Linux. A Wine + Xvfb MetaTrader 4 on the same MetaQuotes demo is the live second book (so fills also show on a laptop terminal logged into that account). Copies go out in this order:

1. **MetaApi** — if `METAAPI_TOKEN` is set, the hub provisions a hosted MT4 terminal and trades through its REST API.
2. **Expert Advisor** — `mt4/ForexSentinelBridge.mq4` polls `GET /api/mt4/bridge` and posts fills to `POST /api/mt4/bridge`.
3. **Local ledger** — until (1) or (2) is live, copies are booked here as `ledger-…` tickets at the OANDA mid. Those rows are **not on MetaQuotes**. When the EA heartbeats, *new* tickets go to the terminal; existing ledger rows stay local so they are not double-filled.

## Connect

On the hub **Overview**, paste:

- MT4 demo **login**
- **password** (master, so the EA / MetaApi can trade)
- **server** (the exact string from the MT4 login box, e.g. `ICMarkets-Demo`)
- optional **MetaApi token** from [app.metaapi.cloud](https://app.metaapi.cloud)

The same values can live in `.env` (`MT4_LOGIN`, `MT4_PASSWORD`, `MT4_SERVER`, `METAAPI_TOKEN`). A `MT4_BRIDGE_SECRET` is generated on first connect and shown once — paste it into the EA inputs.

## Expert Advisor

1. Copy `mt4/ForexSentinelBridge.mq4` into `MQL4/Experts/` and compile.
2. Tools → Options → Expert Advisors: allow WebRequest for the hub URL (the machine that serves `:8765`).
3. Attach the EA to an **EURUSD** chart. Inputs: `HubUrl`, `BridgeSecret`, `Magic=212100`.
4. The EA heartbeats every few seconds. Mode on Overview flips to **bridge**.

On this Linux desk the terminal is already installed under Wine. `scripts/start_mt4_wine.sh` logs into `MT4_LOGIN` / `MT4_SERVER`, attaches `ForexSentinelBridge` to EURUSD M5, and allows WebRequest to the hub (Wine talks to the container IP, not only `127.0.0.1`). Keep that script in tmux session `mt4-wine`. Your laptop MT4 on the **same** demo login sees every fill this terminal sends.

## Risk and operator fills

- Magic **212100** marks desk copies. Any other magic is **operator** and stays hands-off (no TP1, no time-stop, no flatten).
- MT4 copies do **not** count toward OANDA `max_open_positions`, same-side caps, or open-risk. They are the same ticket on a second venue.
- An MT4 reject does **not** flatten the OANDA fill. OPEN_ONLY still applies on OANDA so a teacher 1-unit ticket is never netted closed.
- Lots = OANDA units / 100,000, floor **0.01**.

## What “demo on both” means

| Mode | Where the copy lives |
| --- | --- |
| `disconnected` | Credentials missing. Form on Overview. |
| `ledger` | Local SQLite row, ticket `ledger-…`. Visible on the hub, not in MT4. |
| `bridge` | EA executed `OrderSend` on the demo. |
| `metaapi` | Hosted terminal via MetaApi. |

Weekend, news blackout, and the Ox scalp rules are unchanged. The second venue is execution, not a second strategy.
