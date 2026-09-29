# Contextual loss review — September 29

The operator requested that losing trades be investigated instead of imposing broad
strategy exclusions. `PRACTICE_CONTEXTUAL_LOSS_REVIEW=true` makes outcome-count-only
exact, family and side bans advisory in practice. Both lesson_gate and growth_gate
honor this setting, including existing learned rules. Historical rules and trades
remain intact. Live environments retain their previous restrictions.

Current quote, price drift, spread/stop, stop geometry, calendar, duplicate-entry,
position and sizing checks still run. Short post-loss and re-entry cooldowns remain.
The independent no-daily-halt override remains enabled. Risk is not increased.

New close journals capture a structured review: recorded P/L and exit label,
loss relative to original USD entry risk, recorded slippage, and quoted entry
spread relative to original stop distance. Missing evidence is explicitly unknown.
Tests to investigate execution, market context and ordinary variance are separated
from facts; no loss receives a fabricated causal explanation.

Before eligible new entries, the most recent three same-side primary OANDA losses
are attached as evidence to the decision context. These are contextual references,
not claims that the trades are identical. Fresh conditions are evaluated by existing
entry checks. A negative outcome alone neither bans the setup nor trains a new
predictive model. The autonomous research process continues independent validation.

Generated per-trade documents and the hourly compiled knowledge base include these
reviews for older losses too. Old journal prose is preserved as historical advice;
it does not override this current execution policy. No historical loss is erased.

The two latest primary losses measured about 1.02R and 1.03R, with recorded entry
slippage of 1.3/1.4 pips and spread/stop ratios of 25.0%/23.1%. These measurements do
not prove causation. Their local close labels are broker_closed; finer attribution
requires broker transaction evidence and comparable market-path observations.
