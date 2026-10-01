# 2.25.1 — individual trade review and complete position observation

Reviewed every broker-returned closed bot trade against historical executable-side
M1 candles and linked matching execution journals by broker trade ID. Legacy bot
trades missing from the current execution ledger remain separate research records;
no risk snapshots or trading history were fabricated. Private per-trade evidence
is in the generated TRADE_REVIEW_2026-10-01.md and ignored research snapshots.

Corrections:
- Continue sampled excursions through partial exits, preserving original entry risk.
- Use the final executable quote checked before submission for cost attribution,
  falling back to the earlier decision quote only when final evidence is absent.
- Include every local closed primary bot trade in recurring individual assessments,
  including winners as comparisons. Report opposing signal-candle bodies and
  observed favorable excursions as facts; causal explanations remain hypotheses.
- Publish those assessments in the hourly diagnostic document and knowledge base.

Historical paths distinguish observed profit giveback from entries with little or
no observed favorable movement. Neither pattern alone validates new execution
rules. Fully held candles omit boundary minutes and cannot establish alternative
fill ordering. Existing prospective experiments and risk settings are unchanged.
No strategy-wide loss ban or automatic strategy promotion was added.

Validation: 457 Python tests and 48 dashboard regression scenarios passed.
