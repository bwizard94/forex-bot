# 2.25.2 — lighter status polling and documentation writes

Detailed replay reason maps were included in every health/state response. Status
now carries the ten most frequent reasons in each category, distinct counts and
omitted observation totals. Full report files remain unchanged and linked.
Unchanged status files use a bounded 32-entry cache keyed by file identity, size,
mtime and ctime; callers receive independent copies and freshness is recomputed.
Missing status and malformed status are reported separately. Hourly experiment
reports become stale after two hours, rather than the cost job's seven hours.

Unchanged documentation indexes no longer create temporary files or replace
existing files. Changed content still uses atomic replacement. Journal revisions
and knowledge compilation are retained.

Measured locally against the current reports: status payload dropped from 323,273
on-disk JSON bytes to 11,093 response JSON bytes (96.6 percent). Formatting differs,
so this measures practical payload size, not compression alone. A 100-read warm
cache benchmark averaged 0.247 ms per read. This is status-path performance, not
an execution-latency or profitability claim.

Validation: 459 Python tests and 48 dashboard checks. Trading rules, risk settings
and registered experiment sources are unchanged.
