# Forex Factory — EUR/USD market news

Standing notes for the EUR/USD specialist. Live wires are rewritten into
`desk/EURUSD_PLAYBOOK.md` every intel cycle and into the 05:00 UTC news
book. This file is the desk's memory of **how to read**
[forexfactory.com/market/eurusd](https://www.forexfactory.com/market/eurusd).

Direct HTTP is Cloudflare 403. A blocked fetch never stops the intel
cycle. The JS shell still embeds `/news/{id}-slug` links, so titles can
be recovered even when the rendered markdown is empty. The week calendar
JSON on `nfs.faireconomy.media` is the same feed that already runs the
±30 minute blackout.

The skim below is from 19 September 2026.

## What the page is

Forex Factory's EUR/USD **market hub** is the pair's news desk:

- Live quote (JS scanner — not the fill)
- Pair news stream (Fed, ECB speakers, geopolitics that can bid USD)
- The same-week economic calendar (red/orange EUR and USD prints)
- Related FF threads

It is slower than OANDA M5 and it is **not an order book**. Use it to
know what the street is reading and which print is next. The desk still
only trades EUR/USD. A headline is never a ticket.

## How the bot uses it

Every 20 minutes the intel loop, and every morning at 05:00 UTC the news
scan, try the public HTML and:

1. Parse `/news/{id}-slug` links (and anchor text when the HTML has it).
2. Attach upcoming High/Medium EUR and USD calendar rows from the week
   JSON. That is the same blackout source `NewsDesk` already uses.
3. Write the wires into the playbook and into `news_items` with a
   predicted lean. Later M5 closes score whether the lean was any good.
4. A Cloudflare block is logged, not a halt. Calendar JSON can still
   land even when the market page does not.

Source module: `src/data/forexfactory.py`.

## Skim — 19 September 2026

Wires on the pair hub (titles recovered from slugs; context, not tickets):

| Story | Read for this pair |
| --- | --- |
| The Fed is fighting the wrong war on | Fed-path commentary. USD bid if the street reads hawkish; not a scalp trigger. |
| ECB's Kazaks: if our baseline materializes | ECB speaker. Hawkish language supports EUR; dovish baseline talk caps it. |
| ECB's Lagarde: rates won't move in lockstep with | Lagarde decoupling the ECB from the Fed. Mixed for EUR/USD until H1 reacts. |
| ECB's Nagel unlikely to get German nomination | Personnel, not a print. Log it; do not size it. |
| The Fed hasn't been this terse since 2007 | Fed communication. Tight-lipped FOMC usually keeps USD bid until the next print. |
| Three words from Kevin Warsh / Warsh did well but where does the Fed | Warsh is Fed-path colour. Classify as **fed**. Not a ticket. |
| WH confirms Trump to sign Russia sanctions bill | Geopolitics / risk. USD often catches the first bid. Wait for H1. |

Net: the pair hub is **Fed + ECB speakers** this tape, plus a sanctions
risk headline. That matches the existing blackout book (FOMC, Lagarde,
CPI, NFP). Do not short a washout because a Fed wire sounded hawkish.

## How to use it without getting hurt

- Forex Factory news is **context**. Ox scalp + H1 still fire the ticket.
- Red EUR or USD prints: stand aside ±30 minutes. Trade the H1 reaction,
  not the first tick.
- Speaker headlines (Lagarde, Kazaks, Nagel, Warsh, Powell) go in the
  news book as `ecb` / `fed`. Commentary without a print is logged so
  the desk can see it does not lead the tape.
- Cloudflare may empty the page. The calendar JSON is the reliable half
  of this hub. Missing wires are not a reason to sit the whole session.
- Never size from a FF title. Never skip the blackout because a category
  is “usually right.”
