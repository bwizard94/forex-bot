# EUR/USD news harvest

The desk does not trade a headline. It **logs** EUR/USD wires, guesses which way the pair should lean, then **comes back** with a later M5 close to see whether that guess was any good. Categories with a real hit rate get written into `desk/NEWS_PATTERNS.md`. A print still sits behind the ±30 minute blackout. Ox scalp + H1 still fire the ticket.

## The 05:00 UTC scan

Every morning at **05:00 UTC** (including weekends — the pair can still gap) the desk:

1. Pulls a wide EUR/USD set:
   - [Forex Factory EUR/USD market](https://www.forexfactory.com/market/eurusd) — pair news hub (Fed/ECB wires + the same-week calendar). This is the desk's primary pair-news reference.
   - [NewsNow EUR/USD](https://www.newsnow.com/us/Business/Currencies/EUR~USD) — dated aggregator (FXStreet, Investing.com, and other wires). This is the historical headline stream.
   - Google News RSS for `EUR/USD` / `EURUSD` and for ECB / Lagarde / FOMC / Fed.
   - Yahoo EURUSD RSS, ECB press RSS, Federal Reserve press RSS.
   - The intel hubs already on the 20-minute cycle (Trading Economics, FXStreet, Barchart, Investing.com, TradingView).
2. Dedupes by normalised title.
3. Classifies each story (`inflation`, `labor`, `fed`, `ecb`, `pmi`, `growth`, `yields`, `energy`, `dollar`, `risk`, `commentary`, `other`).
4. Stores a **bullish / bearish / mixed** lean from the same keyword book the intel cycle uses, plus the live EUR/USD mid.
5. Appends `desk/NEWS_LOG.md`.
6. Rewrites `desk/NEWS_PATTERNS.md`.

Intel (every 20 minutes) restocks the same table as stories land, so the book is not only a 5 a.m. snapshot.

Hub **News** tab (or `POST /api/news/scan`) runs the harvest on demand.

## Later revisit

When an item is at least one hour old, the desk looks up the nearest M5 close and measures pips vs the capture mid:

| 1-hour move | Predicted bullish | Predicted bearish | Mixed |
| --- | --- | --- | --- |
| ≥ +5 pips | correct | wrong | unclear |
| ≤ −5 pips | wrong | correct | unclear |
| inside 5 pips | unclear | unclear | unclear |

30-minute and 4-hour moves are stored too. Under 5 pips is noise, not a win. **Commentary / forecast** headlines are logged so the desk can see they do not lead the tape.

## What the bot is allowed to do with a pattern

- Sit tighter into a category that keeps scoring **wrong** (treat it as context, not a ticket).
- Notice a category that keeps scoring **correct** and name it in the playbook.
- Never size from a headline. Never skip the news blackout because a category is “usually right.”

Sources stay in this file. `desk/NEWS_PATTERNS.md` is the living scoreboard. `desk/NEWS_LOG.md` is the dated harvest tape.

## Event coverage research — 2026-09-22

The August 2026 revision of a Federal Reserve event study finds substantial additional information in FOMC press conferences. The ECB likewise publishes the policy decision and the explanatory statement/Q&A separately. A blackout centered only on the rate decision should not be assumed to cover the conference. [FRBSF study](https://www.frbsf.org/wp-content/uploads/wp2025-30.pdf), [ECB press conference](https://www.ecb.europa.eu/press/press_conference/html/index.en.html)

**Proposed, not implemented:** audit calendar coverage for each communication, model event intervals and merge overlapping blackout windows, then require fresh quotes and acceptable spreads before resuming. Retain the current ±30-minute setting. Event-study measurement windows do not establish an optimal trading blackout.

For future news evaluation, record original publication, first-seen and scoring times separately. Capture the release's contemporaneous consensus/actual/revision when available; keyword tone and an ex-post price move are not a causal trading test. EBS research finds that surprise content affects prices quickly, while even expected releases can raise activity. [Federal Reserve IFDP 823](https://www.federalreserve.gov/pubs/ifdp/2004/823/ifdp823.pdf)

The validation plan and limitations are in [RESEARCH.md](RESEARCH.md).
