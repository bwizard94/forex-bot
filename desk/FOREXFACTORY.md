# Forex Factory — primary news discovery source

Updated 30 September 2026 by operator request.
Primary: [Forex Factory news](https://www.forexfactory.com/news).
Secondary manual reference: [EUR/USD market hub](https://www.forexfactory.com/market/eurusd).

## Automated workflow

The general news harvester attempts Forex Factory first, filters its headlines
for EUR/USD and macro relevance, then collects the existing official and
supplementary feeds. Deduplication and result limits preserve this source priority.
The intel snapshot uses the same news endpoint and attaches the separate
High/Medium EUR/USD calendar feed. Existing schedules and execution controls
are unchanged. Relevant USD cross headlines may supply dollar context.

Source: src/data/forexfactory.py and src/data/news.py.
The parser retains Forex Factory story URLs, rejects challenge pages even when
they contain apparent news links, and never treats a number on the general news
page as a EUR/USD quote. Pair-page quote extraction is only permitted when the
caller explicitly identifies the EUR/USD hub.

HTTP blocks, timeouts and empty results are logged. Other feeds remain available;
calendar retrieval is attempted separately. A successful web-browser visit does
not prove unattended HTTP access works. Do not bypass a site's access challenge.

## Evidence and freshness

Forex Factory aggregates multiple publishers and community discussion. Primary
here means first source checked, not guaranteed factual correctness.
Inspect the original report behind a story; use the Fed, ECB and relevant
statistical agency for release verification. Distinguish factual release,
attributed interpretation and community opinion.

The automated parser currently stores headline text, source label and Forex Factory
URL. It does not yet extract verified publication times or original publisher
URLs. Unknown publication time remains unknown; retrieval time must not be used
to claim a story is breaking news. Slug-derived titles can be incomplete.

A headline alone does not establish direction, entry quality or profitability.
Use news as context within the configured strategy and event controls. Research
ideas and unresolved limitations are recorded in
[the September 30 review](RESEARCH_NEWS_2026-09-30.md).

## Availability diagnostics (2.22.1)

The News dashboard and /api/health expose primary-source state separately from
service health, plus the last completed harvest's source counts and fallback use.
Missing checks are pending; old checks become stale after 40 minutes. This tracks
fetch availability, not the age or truth of a headline. Both headline and intel
requests share a five-minute cache/retry interval, including blocked attempts.
No challenge solver, cookie harvesting or access-control workaround is used.

The direct page returned HTTP 403 during deployment preparation; the historical
RSS hostname could not be reached. Forex Factory remains the preferred source,
with the existing supplementary feeds providing operational news coverage.
