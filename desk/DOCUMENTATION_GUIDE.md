# Documentation and trading journey

Start at [the desk index](INDEX.md). Existing filenames are kept stable so code,
links, and operator workflows continue to work.

- **Operating rules:** OPERATING, SCALPING, MISTAKES and MT4 describe the intended behavior. Deterministic Python enforces trading rules; Markdown is not executable configuration.
- **Current book:** the playbook, growth, history, learning log and news summaries are generated views. Historical research does not authorize live strategy promotion.
- **Research and operations:** dated audits, source reviews, integration guides and deployment notes remain separately linked.
- **Individual journals:** [journal/INDEX.md](journal/INDEX.md) links every available EUR/USD database journal. Each contains entry thesis, outcome, recorded price P/L, what went right/wrong, lesson and improvement to investigate. Human trades and venue copies are labeled separately.

## What the bot actually accesses

At every signal evaluation, `read_documentation` reads the configured operating
and learning documents and records their SHA-256 fingerprints and read time in
the decision evidence. Missing files are reported explicitly. It reads references;
it does not semantically interpret arbitrary Markdown or convert prose into orders.
The existing lesson/growth gates consume structured trade-journal data from SQLite.
This distinction prevents a speculative note from silently changing trading rules.

The scheduler exports committed database journals and rebuilds the index every
60 seconds, starting immediately when scheduling begins. `/api/health` exposes
export status, counts and the latest document-access receipt. `DOCUMENT_ACCESS.json`
is the last successful export's read receipt; individual decisions also retain
what they read. A failed export leaves prior documents intact and retries on the
next interval. Open positions receive an entry page; recorded exits enrich it.

## Preservation and interpretation

The database remains the source of truth. `journal/trade-N.md` is the current
rendered version; `journal/revisions/trade-N-SHA256.md` preserves prior content.
Unchanged content creates no duplicate revision. The exporter updates files
atomically. Do not edit generated pages; put operator annotations in a separate
manual document so refreshes cannot overwrite them.

Post-mortems are deterministic interpretations of recorded facts. Their language
can express hypotheses, not proven causes. Missing fields remain “Not recorded.”
Price P/L excludes separately reported financing; no all-cost return is invented.
Research-ledger recoveries are not silently inserted as current-version trades.
The journal can therefore only describe trades available in the journal database.

Test coverage includes wins/losses/scratches, ownership labels, revision retention,
deduplication, index links and detection of changed/missing reference files.

Daily activity reports now live at [journal/daily/INDEX.md](journal/daily/INDEX.md).
Each minute's export refreshes today and yesterday and preserves older daily files.
They explain inactivity as well as recorded outcomes and do not invent lessons on
no-trade days. Strategy configurations may change: consult the current named policy
and [active-practice profile](AGGRESSIVE_PRACTICE_PROFILE.md) when comparing results.
