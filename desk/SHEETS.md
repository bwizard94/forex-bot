# Google Sheets book

The EUR/USD desk keeps a living Google workbook of every ticket and the notes around it. It is rewritten on startup, after each fill and close, and after each intel cycle. Do not hand-edit the tabs — the next push overwrites them.

Standing notes for the specialist. The live file is a Google Sheet owned by the operator; this markdown is the recipe.

## What gets written

| Tab | Contents |
| --- | --- |
| **Overview** | NAV, balance, open/closed ticket counts, last push UTC, version |
| **Trades** | Every local ticket: side, units, fill, SL/TP, slippage, P/L, close reason, broker id |
| **Journal** | Entry thesis, post-mortem, outcome, fingerprint, mistake tags |
| **DailyPnL** | UTC day P/L, trades opened/closed, halt flag |
| **Lessons** | Learned fingerprints (skip / high-strength / prefer) and net P/L |
| **Account** | Recent NAV snapshots, drawdown, margin |
| **Signals** | Recent **live** tape (history-replay rows stay out of this tab) |
| **Open** | Tickets still open or partial, including operator fills the desk will not flatten |
| **News** | Harvested EUR/USD headlines: category, predicted lean, 1h tape check |
| **NewsPatterns** | Hit rate by category (inflation, labor, Fed, ECB, …) |

A packed copy also lands at `data/sheets_payload.json` so a push can complete even if Google is briefly unreachable.

## How it connects

1. Composio toolkit `googlesheets` must be **Active** in this chat (OAuth to the Google account that should own the sheet).
2. The live process needs `COMPOSIO_API_KEY` in `.env` (or pasted on Overview). MCP in this chat is not visible to `python -m src.main`.
3. First successful push creates **Forex Sentinel — EUR/USD book** and stores `GOOGLE_SHEETS_SPREADSHEET_ID` / `GOOGLE_SHEETS_SPREADSHEET_URL`.
4. Optional: paste an existing spreadsheet ID or URL on Overview if you already made the workbook.

Without a key the desk still packs the JSON locally. Overview **Sync now** does the same.

## Env

```
COMPOSIO_API_KEY=
COMPOSIO_CONNECTED_ACCOUNT_ID=
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_SPREADSHEET_URL=
SHEETS_SYNC_ENABLED=true
```

Sheets API budget is about 60 reads/writes per minute. The desk writes one tab at a time off the quote clock (a background thread), not on the 15-second poll.

## Operator rules that still apply

- EUR/USD only.
- Operator demo fills stay `OPEN_ONLY` / hands-off — they appear on **Open** and **Trades** with `source=operator`.
- The sheet is a mirror, not a second brain. Tickets still come from Ox scalp + H1, not from a cell formula.
