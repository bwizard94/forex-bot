# 2.24.0 — recurring diagnostics and execution research

Implemented the five requested improvements in order. No external bot source was
imported and no new entry strategy was promoted.

1. Attribution runs hourly; cost research every six hours, both at startup. Each
   uses a subprocess, OS-level overlap lock and a timeout (120/900 seconds).
   Immutable timestamped artifacts retain earlier runs. Dashboard Overview and
   health expose completion, failure and stale status. Generated desk reports
   feed the existing hourly knowledge index. A calendar archive observes the
   already-fetched feed every five minutes without additional network requests.
2. Cost workers receive a deep-copied, allowlisted active-process configuration
   with a SHA-256 digest. Secrets are excluded; reload verifies the digest and
   supplies explicit defaults so environment changes cannot override it. M1/M5
   follow the captured signal timeframe. This is an active-settings diagnostic,
   not a reconstruction of the settings used on every historical date.
3. A separate diagnostic replay records first rejection reason, all failed fill
   checks, hold reasons, directional signals and accepted entries. Counts explain
   zero-trade outcomes without loosening trading gates. First reasons are mutually
   exclusive; all-failed counts can overlap. Missing next bars are explicit.
4. Attribution now pairs versions/configurations within matching timeframe, side,
   session and higher-timeframe bias. Reports include both groups, costs and mean-R
   differences. Fewer than 30 recorded-risk samples per group is labeled
   insufficient. Larger samples remain descriptive, not statistically validated;
   dates and costs may still confound the comparison. Unknown contexts do not
   produce comparisons. A generated Markdown table makes pairs directly readable.
5. Diagnostic replay supports simultaneous positions, position/same-side/daily
   entry caps, reserved open-risk fractions, sampling cost/risk policy, explicit
   round-trip commission and signed carry assumptions, and EUR/USD high-impact
   news windows using only events known by the simulated entry time.

## Boundaries

The original replay.py and registered strategy-lab sources remain untouched.
Diagnostic replay is versioned separately as diagnostic_ohlc_v4; its results must
not be appended to generation 0004 as though its model were unchanged.

Portfolio simulation reserves a fixed risk fraction per trade, capped by the
sampling risk policy. It does not reproduce adaptive conviction/add-on sizing,
notional/margin restrictions, daily monetary halts, human positions or broker
rejections. Reserved risk stays conservative after a partial exit. Results are
per-original-unit pips, not a compounded account balance. Same-bar management
uses stop-first ambiguity and next-bar entry; OHLC cannot resolve intrabar paths.

Commission is pips per complete round trip. Carry is signed pips per day charged
continuously for elapsed time and remaining size; this is not an exact broker
rollover/holiday/triple-swap schedule. Before-fee pips already include spread and
slippage. Neither costs nor financing are subtracted again from actual trade P/L.

Without explicit local cost calibration, zero-fee results are labeled
fees_unknown_zero_cost_reference. Calendar snapshots begin when observed and
cannot backfill unobserved history. Empty event history is not proof of no news.
An event_id can identify supplied schedule revisions; absent one, distinct event
timestamps remain distinct because rescheduling cannot be safely inferred.

Optional local calibration (ignored runtime file):
`data/research/diagnostics/execution-costs.json`, with only
`commission_pips_roundtrip`, `long_carry_pips_per_day`, and
`short_carry_pips_per_day`. Values must be finite; commission must be nonnegative.
Use documented account costs, or clearly labeled hypothetical sensitivity rates.

Standalone cost runs also accept `--settings-snapshot` and `--assumptions`.
Assumption JSON may supply events with `ts`, `known_at`, `currency`, `impact`,
optional `title` and stable `event_id`; timestamps require timezones. No historical
result or surviving winning streak grants execution authority.

## Verification

Tests cover known long/short/no-trade controls; stop-first replay; simultaneous
positions and exposure rejections; known-at news timing; independent fee/carry
arithmetic; snapshot tampering, secret exclusion and environment isolation;
matched-context comparisons; worker lock, timeout, and success; scheduler cadence;
and coverage of settings used directly by the signal evaluator.

## Deployment and first scheduled run

Verified 2.24.0 after restart; restored the previously enabled practice entry state
through broker reconciliation. 447 Python tests (isolated from private .env),
48 dashboard scenarios and JavaScript syntax passed.

The first scheduled attribution report covered 21 primary closed bot trades in
nine groups and two comparisons; both comparisons had insufficient samples.

The first completed active-settings cost report used 2000 bars from 2026-09-29 11:04:00+00:00 through 2026-09-30 20:28:00+00:00.

| Spread / slippage (pips) | Completed simulated trades | Net pips |
| --- | ---: | ---: |
| 1.2 / 0.1 | 65 | -102.91 |
| 1.6 / 0.2 | 64 | -123.22 |
| 1.8 / 0.2 | 62 | -137.50 |
| 2.5 / 0.5 | 0 | 0.00 |
| 3.0 / 1.0 | 0 | 0.00 |

These are exploratory equal-weight pips, excluding forced ending exits, not account
returns or evidence of improvement. Fees remain an explicitly unknown zero-fee
reference until supplied; historical calendar coverage is not certified. Higher
cost scenarios were rejected primarily by spread-to-stop and spread-cap checks.
The registered generation 0004 remains unchanged.
