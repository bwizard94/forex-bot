const ACTION_BUTTONS = {
  "/api/slack/connect": "save-slack", "/api/sheets/connect": "save-sheets",
  "/api/sheets/sync": "sync-sheets", "/api/mt4/connect": "save-mt4",
  "/api/history": "run-history", "/api/growth": "run-growth",
  "/api/intel": "run-intel", "/api/news/scan": "run-news-scan",
  "/api/cycle": "run-cycle", "/api/trading": "toggle-trading",
  "/api/briefing/morning": "run-morning", "/api/briefing/recap": "run-recap",
};

function showAction(message, error = false, buttonId = null) {
  const ids = ["action-status", ...(buttonId ? [`${buttonId}-result`] : [])];
  for (const id of ids) {
    const status = document.getElementById(id);
    if (!status) continue;
    status.hidden = false;
    status.textContent = `${error ? "Failed: " : ""}${message}`;
    status.dataset.error = String(error);
  }
}

function actionConfirmation(url, payload) {
  if (url === "/api/slack/connect") return payload.ready
    ? `Connected to ${payload.channel || "Slack"}. ${payload.replayed || 0} queued updates sent.`
    : "Connection checked, but Slack is not ready. Check the connection status above.";
  if (url === "/api/sheets/connect" || url === "/api/sheets/sync") {
    if (payload.started) return "Sync started in the background. Upload is not yet confirmed; watch Google Sheets status above.";
    if (payload.last && payload.last.ok && payload.spreadsheet_url)
      return "Last Sheets sync succeeded. No new sync started; check the workbook and status above.";
    return `No new Sheets sync started. ${(payload.last && payload.last.reason) || "It may already be running or disabled; check the status above."}`;
  }
  if (url === "/api/history") return payload.started
    ? "Rescan started in the background. Results will appear in History when finished."
    : "No new rescan started. A scan may already be running; check History status.";
  if (url === "/api/mt4/connect") return `MT4 setup saved. Mode: ${payload.mode || "unconfirmed"}; check connection status above.`;
  if (url === "/api/trading") return payload.trading_enabled ? "New trade entries enabled." : "New trade entries paused.";
  const names = {"/api/cycle":"Cycle", "/api/growth":"Growth study", "/api/intel":"Intel update",
    "/api/news/scan":"News scan", "/api/briefing/morning":"Morning briefing", "/api/briefing/recap":"Recap"};
  return `${names[url] || "Request"} completed. Results refreshed below.`;
}

async function actionFetch(url, options = {}) {
  const buttonId = (options.method || "GET") !== "GET" ? ACTION_BUTTONS[url] : null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const payload = await response.clone().json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      const detail = payload.error || payload.detail || `Request failed (HTTP ${response.status}).`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if ((options.method || "GET") !== "GET") {
      showAction(actionConfirmation(url, payload), false, buttonId);
    }
    return response;
  } catch (err) {
    const message = err.name === "AbortError"
      ? "The request timed out. It may still be running; check its status before retrying."
      : err.message || "Unable to reach the bot. Check the background service.";
    showAction(message, true, buttonId);
    throw new Error(message);
  } finally {
    clearTimeout(timeout);
  }
}

const fmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const px = (symbol, value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const digits = String(symbol || "").includes("JPY") ? 3 : 5;
  return Number(value).toFixed(digits);
};

const signed = (value) => {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  const cls = n > 0 ? "up" : n < 0 ? "down" : "";
  return `<span class="${cls}">${fmt.format(n)}</span>`;
};

const actionClass = (action) => {
  if (action === "BUY") return "buy";
  if (action === "SELL") return "sell";
  return "hold";
};

const iso = (value) => {
  if (!value) return "—";
  return String(value).replace("T", " ").replace("+00:00", "").slice(0, 19);
};

const num = (value, digits = 5) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
};

const SHEETS = {
  bars: {
    title: "OHLCV bars",
    hint: "Minute-by-minute market data stored for backtesting",
    filters: ["symbol", "timeframe"],
    columns: [
      ["ts", "Time", "time"],
      ["symbol", "Pair", "text"],
      ["timeframe", "TF", "text"],
      ["open", "Open", "px"],
      ["high", "High", "px"],
      ["low", "Low", "px"],
      ["close", "Close", "px"],
      ["volume", "Vol", "raw"],
      ["source", "Source", "text"],
    ],
  },
  indicators: {
    title: "Indicators",
    hint: "EMA 9/21, RSI, MACD, Stochastic, ADX, CCI, ATR, Bollinger, Supertrend, VWAP, WaveTrend",
    filters: ["symbol", "timeframe"],
    columns: [
      ["ts", "Time", "time"],
      ["symbol", "Pair", "text"],
      ["timeframe", "TF", "text"],
      ["ema_fast", "EMA9", "px"],
      ["ema_slow", "EMA21", "px"],
      ["rsi", "RSI", "num1"],
      ["macd", "MACD", "num5"],
      ["macd_hist", "MACD hist", "num5"],
      ["stoch_k", "Stoch %K", "num1"],
      ["stoch_d", "Stoch %D", "num1"],
      ["adx", "ADX", "num1"],
      ["cci", "CCI", "num1"],
      ["vwap", "VWAP", "px"],
      ["supertrend", "Supertrend", "px"],
      ["wt1", "WaveTrend", "num1"],
      ["ewmac", "EWMAC", "num2"],
      ["tma", "TMA", "px"],
      ["atr", "ATR", "px"],
      ["bb_upper", "BB up", "px"],
      ["bb_mid", "BB mid", "px"],
      ["bb_lower", "BB low", "px"],
    ],
  },
  signals: {
    title: "Signals",
    hint: "Every BUY, SELL, and HOLD with setup type, fingerprint, and oscillator snapshot",
    filters: ["symbol", "action", "skipped", "source"],
    columns: [
      ["ts", "Time", "time"],
      ["symbol", "Pair", "text"],
      ["timeframe", "TF", "text"],
      ["action", "Action", "tag"],
      ["signal_type", "Setup", "text"],
      ["fingerprint", "Fingerprint", "wrap"],
      ["htf_bias", "H1", "text"],
      ["price", "Price", "px"],
      ["rsi", "RSI", "num1"],
      ["macd", "MACD", "num5"],
      ["stoch_k", "Stoch", "num1"],
      ["adx", "ADX", "num1"],
      ["cci", "CCI", "num1"],
      ["strength", "Str", "raw"],
      ["skipped", "Skip", "bool"],
      ["skip_reason", "Skip reason", "wrap"],
      ["reason", "Why", "wrap"],
      ["source", "Source", "text"],
    ],
  },
  setups: {
    title: "Setup memory",
    hint: "Named signal types scored on ForexSB / extra-dataset history so the desk can skip losers",
    filters: ["symbol", "side"],
    columns: [
      ["last_studied", "Studied", "time"],
      ["symbol", "Pair", "text"],
      ["signal_type", "Setup", "text"],
      ["side", "Side", "tag"],
      ["session", "Session", "text"],
      ["samples", "N", "raw"],
      ["wins", "Wins", "raw"],
      ["losses", "Losses", "raw"],
      ["expectancy_pips", "E pips", "num1"],
      ["win_rate", "Win", "pct"],
      ["avg_strength", "Avg str", "num1"],
    ],
  },
  trades: {
    title: "Trades",
    hint: "Demo fills, slippage, stops, targets, exits, and realized P/L",
    filters: ["symbol", "side", "status"],
    columns: [
      ["id", "Id", "raw"],
      ["broker_trade_id", "Broker #", "raw"],
      ["opened_at", "Opened", "time"],
      ["closed_at", "Closed", "time"],
      ["symbol", "Pair", "text"],
      ["side", "Side", "tag"],
      ["units", "Units", "raw"],
      ["fill_price", "Fill", "px"],
      ["slippage_pips", "Slip", "num1"],
      ["stop_loss", "SL", "px"],
      ["take_profit_1", "TP1", "px"],
      ["take_profit_2", "TP2", "px"],
      ["exit_price", "Exit", "px"],
      ["realized_pl", "P/L", "money"],
      ["status", "Status", "text"],
      ["source", "Whose", "text"],
      ["venue", "Venue", "text"],
      ["close_reason", "Exit why", "text"],
    ],
  },
  snapshots: {
    title: "Account snapshots",
    hint: "NAV, margin, and drawdown captured on each cycle",
    filters: [],
    columns: [
      ["ts", "Time", "time"],
      ["balance", "Balance", "money"],
      ["nav", "NAV", "money"],
      ["unrealized_pl", "Unrealized", "money"],
      ["realized_pl", "Realized", "money"],
      ["margin_used", "Margin used", "money"],
      ["open_trade_count", "Open", "raw"],
      ["drawdown_pct", "DD", "pct"],
    ],
  },
  daily: {
    title: "Daily P/L",
    hint: "Session start balance, trades opened/closed, halt flags",
    filters: [],
    columns: [
      ["day", "Day", "text"],
      ["starting_balance", "Start", "money"],
      ["realized_pl", "Realized", "money"],
      ["trades_opened", "Opened", "raw"],
      ["trades_closed", "Closed", "raw"],
      ["halted", "Halted", "bool"],
      ["halt_reason", "Halt reason", "wrap"],
    ],
  },
  alerts: {
    title: "Alerts",
    hint: "Slack Block Kit payloads, stored even when Slack is disconnected",
    filters: ["kind"],
    columns: [
      ["ts", "Time", "time"],
      ["kind", "Kind", "text"],
      ["title", "Title", "wrap"],
      ["delivered", "Sent", "bool"],
      ["error", "Error", "wrap"],
    ],
  },
  cycles: {
    title: "Pipeline cycles",
    hint: "Fetch → analyze → execute runs",
    filters: [],
    columns: [
      ["id", "Id", "raw"],
      ["started_at", "Started", "time"],
      ["finished_at", "Finished", "time"],
      ["status", "Status", "text"],
      ["symbols_processed", "Pairs", "raw"],
      ["signals_emitted", "Signals", "raw"],
      ["orders_placed", "Orders", "raw"],
      ["error", "Error", "wrap"],
    ],
  },
  journal: {
    title: "Trade journal",
    hint: "Why each buy/sell happened, and the post-mortem on every close",
    filters: ["symbol", "side", "outcome"],
    columns: [
      ["updated_at", "When", "time"],
      ["trade_id", "Trade", "raw"],
      ["symbol", "Pair", "text"],
      ["side", "Side", "tag"],
      ["outcome", "Outcome", "tag"],
      ["realized_pl", "P/L", "money"],
      ["close_reason", "Exit", "text"],
      ["fingerprint", "Fingerprint", "wrap"],
      ["entry_thesis", "Why it traded", "wrap"],
      ["what_went_wrong", "What went wrong", "wrap"],
      ["how_to_avoid", "How to avoid", "wrap"],
      ["mistakes", "Mistake tags", "wrap"],
      ["what_went_right", "What went right", "wrap"],
    ],
  },
  lessons: {
    title: "Lessons",
    hint: "Fingerprints that now demand a stronger score or are skipped after repeat losses",
    filters: ["symbol", "side", "rule"],
    columns: [
      ["updated_at", "Updated", "time"],
      ["fingerprint", "Fingerprint", "wrap"],
      ["symbol", "Pair", "text"],
      ["side", "Side", "tag"],
      ["action", "Rule", "text"],
      ["min_strength", "Min str", "raw"],
      ["skip_until", "Skip until", "time"],
      ["loss_count", "Losses", "raw"],
      ["win_count", "Wins", "raw"],
      ["net_pl", "Net P/L", "money"],
      ["lesson", "Lesson", "wrap"],
    ],
  },
};

const state = {
  tab: "overview",
  page: 1,
  symbols: [],
};

function setClock() {
  document.getElementById("clock").textContent = new Date().toISOString().slice(11, 19) + " UTC";
}

function cell(column, row) {
  const [key, , kind] = column;
  const value = row[key];
  if (kind === "time") return iso(value);
  if (kind === "px") return px(row.symbol, value);
  if (kind === "money") return signed(value);
  if (kind === "num1") return num(value, 1);
  if (kind === "num2") return num(value, 2);
  if (kind === "num5") return num(value, 5);
  if (kind === "pct") return value == null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
  if (kind === "bool") return value ? "yes" : "no";
  if (kind === "tag") return `<span class="tag ${actionClass(String(value))}">${value ?? "—"}</span>`;
  if (kind === "wrap") {
    if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
    return value ? String(value) : "—";
  }
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function renderOverview(payload) {
  const orderCapBox = document.getElementById("order-value-cap");
  if (orderCapBox) orderCapBox.textContent = payload.order_value_cap_fraction == null
    ? "" : `Order value ceiling: ${(100*payload.order_value_cap_fraction).toFixed(0)}% of account balance per order (not stop-loss risk).`;
  const samplingBox = document.getElementById("sampling-policy");
  if (samplingBox && payload.sampling_policy) {
    const p = payload.sampling_policy;
    samplingBox.textContent = p.enabled
      ? `Practice sampling: ${p.status} · spread/stop limit ${(100*p.cost_stop_fraction).toFixed(0)}% · risk cap ${(100*p.risk_cap).toFixed(1)}% · trial ends ${p.expires_at || "not set"}. Other entry and loss limits remain active.`
      : "Baseline trading policy.";
  }

  const learningBox = document.getElementById("strategy-learning");
  if (learningBox) {
    const lab = payload.strategy_learning || {};
    const researchOnly = payload.bot?.strategy_research_only;
    const candidates = (lab.candidates || []).map(c => `${c.name}: ${c.status}`).join(" · ");
    learningBox.textContent = `${researchOnly ? "Research only — new orders disabled. " : ""}Strategy evidence: ${lab.status || "not evaluated"}. ${candidates} Last check: ${lab.evaluated_at || "not yet"}. No validated profitable strategy. ${lab.note || ""} ${lab.autonomous_research ? `Autonomous research generation ${lab.generation}. ${lab.next_action}` : ""}`;
  }

  const healthBox = document.getElementById("decision-health");
  if (healthBox && payload.decision_health) {
    const h = payload.decision_health;
    const blockers = (h.blockers || []).map(b => `${b.reason}: ${b.count}`).join(" · ");
    healthBox.textContent = `${h.directional_setups} directional setups · ${h.holds} holds · ${h.blocked_setups} blocked. ${blockers || "No blocked setups recorded."} ${h.note}`;
  }

  const bot = payload.bot || {};
  if (samplingBox && bot.entry_hours) samplingBox.textContent += ` Entry hours: ${bot.entry_hours}.`;
  if (samplingBox && bot.daily_loss_halt_enabled === false) {
    samplingBox.textContent += " Daily loss halt: disabled for practice. Other entry and risk limits still apply.";
  }
  const account = payload.account;
  document.getElementById("env-pill").textContent = (bot.environment || "practice").toUpperCase();
  document.getElementById("tf-pill").textContent = bot.specialist
    ? `${bot.specialist} · ${bot.signal_timeframe || "M5"}`
    : bot.signal_timeframe || "M5";
  document.getElementById("account-line").textContent = bot.account_id
    ? `account ${bot.account_id} · slack ${
        bot.slack_ready ? bot.slack_channel || "#forex" : "offline → connect token below"
      } · ref ${
        bot.feeds && bot.feeds.reference_as_of ? "CF " + bot.feeds.reference_as_of.slice(0, 16) : "CF pending"
      }${bot.history_studying ? " · history restudy running off-clock" : ""}`
    : "discovering account…";
  const slackStatus = document.getElementById("slack-status");
  if (slackStatus) {
    slackStatus.textContent = bot.slack_ready
      ? `live · ${bot.slack_channel || "#forex"}`
      : "offline — nothing has been posted to #forex yet";
  }
  const slackSetup = document.getElementById("slack-setup");
  if (slackSetup) slackSetup.classList.toggle("connected", Boolean(bot.slack_ready));

  const sheets = payload.sheets || {};
  const sheetsStatus = document.getElementById("sheets-status");
  if (sheetsStatus) {
    const last = sheets.last;
    if (sheets.spreadsheet_url && last && last.ok) {
      sheetsStatus.textContent = `live · ${last.reason || "pushed"}`;
    } else if (sheets.spreadsheet_url) {
      sheetsStatus.textContent = sheets.configured
        ? "workbook saved · waiting for next push"
        : "ID saved · paste a Composio API key to push";
    } else if (sheets.configured) {
      sheetsStatus.textContent = "key saved · workbook will be created on the next push";
    } else if (last && last.reason) {
      sheetsStatus.textContent = last.reason;
    } else {
      sheetsStatus.textContent = "offline — packed locally until Google Sheets is connected";
    }
  }
  const sheetsSetup = document.getElementById("sheets-setup");
  if (sheetsSetup) {
    sheetsSetup.classList.toggle("connected", Boolean(sheets.spreadsheet_url || sheets.configured));
  }

  const mt4 = payload.mt4 || bot.mt4 || {};
  const mt4Status = document.getElementById("mt4-status");
  if (mt4Status) {
    if (mt4.mode === "metaapi") {
      mt4Status.textContent = `MetaApi · ${mt4.login || ""} @ ${mt4.server || ""}`;
    } else if (mt4.mode === "bridge") {
      mt4Status.textContent = `EA live · ${mt4.login || ""} @ ${mt4.server || ""}`;
    } else if (mt4.mode === "ledger") {
      mt4Status.textContent = `ledger · ${mt4.login || ""} @ ${mt4.server || ""} (not on MetaQuotes yet)`;
    } else if (mt4.credentials) {
      mt4Status.textContent = mt4.detail || "credentials saved";
    } else {
      mt4Status.textContent = "offline — paste demo login, password, and server";
    }
  }
  const mt4Setup = document.getElementById("mt4-setup");
  if (mt4Setup) {
    mt4Setup.classList.toggle("connected", Boolean(mt4.credentials) && mt4.mode && mt4.mode !== "off" && mt4.mode !== "disconnected");
  }
  const mt4Login = document.getElementById("mt4-login");
  if (mt4Login && mt4.login && !mt4Login.value) mt4Login.value = mt4.login;
  const mt4Server = document.getElementById("mt4-server");
  if (mt4Server && mt4.server && !mt4Server.value) mt4Server.value = mt4.server;
  const linkWrap = document.getElementById("sheets-link-wrap");
  const link = document.getElementById("sheets-link");
  if (linkWrap && link) {
    if (sheets.spreadsheet_url) {
      linkWrap.hidden = false;
      link.href = sheets.spreadsheet_url;
    } else {
      linkWrap.hidden = true;
    }
  }

  const tape = document.getElementById("tape");
  if (tape) {
    if (!payload.tape || !payload.tape.length) {
      tape.classList.add("empty-state");
      tape.textContent = "No tape yet — a read is written on every cycle and pulsed to Slack.";
    } else {
      tape.classList.remove("empty-state");
      tape.innerHTML = payload.tape
        .slice(0, 8)
        .map((note) => {
          const posted = note.posted ? " · posted to Slack" : " · stored locally";
          return `<article class="signal journal-card">
            <header>
              <span class="tag ${actionClass(note.action)}">${note.action} ${note.symbol}</span>
              <span>${iso(note.ts)}${posted}</span>
            </header>
            <div class="journal-body">${note.body || note.reason || ""}</div>
          </article>`;
        })
        .join("");
    }
  }
  const toggle = document.getElementById("toggle-trading");
  toggle.textContent = bot.trading_enabled ? "Pause trading" : "Resume trading";
  toggle.dataset.enabled = bot.trading_enabled ? "1" : "0";
  if (account) {
    document.getElementById("kpi-nav").textContent = fmt.format(account.nav);
    document.getElementById("kpi-balance").textContent = fmt.format(account.balance);
    document.getElementById("kpi-upl").innerHTML = signed(account.unrealized_pl);
    document.getElementById("kpi-dd").textContent = `${(account.drawdown_pct * 100).toFixed(2)}%`;
    document.getElementById("kpi-open").textContent = String(account.open_trade_count);
  }
  const cycle = payload.pipeline;
  document.getElementById("kpi-cycle").textContent = cycle
    ? `${cycle.status} · ${cycle.symbols_processed || 0} pairs`
    : "idle";

  const quotesBody = document.getElementById("quotes-body");
  if (!payload.quotes || !payload.quotes.length) {
    quotesBody.innerHTML = `<tr><td colspan="8" class="empty">Waiting for the first quote tick…</td></tr>`;
  } else {
    quotesBody.innerHTML = payload.quotes
      .map((q) => {
        const book = q.tradeable === false ? "closed" : q.tradeable ? "open" : "—";
        const div = q.divergence_pips;
        let divCls = "";
        if (typeof div === "number") {
          const abs = Math.abs(div);
          divCls = abs >= 25 ? "down" : abs >= 10 ? "" : "up";
        }
        const divCell =
          typeof div === "number" ? `<span class="${divCls}">${div >= 0 ? "+" : ""}${div.toFixed(1)}</span>` : "—";
        return `<tr>
          <td>${q.symbol}<div class="hint">${q.source || ""}</div></td>
          <td>${px(q.symbol, q.bid)}</td>
          <td>${px(q.symbol, q.ask)}</td>
          <td>${px(q.symbol, q.mid)}</td>
          <td>${px(q.symbol, q.reference_mid)}</td>
          <td>${divCell}</td>
          <td>${q.spread == null ? "—" : Number(q.spread).toFixed(5)}</td>
          <td>${book}</td>
        </tr>`;
      })
      .join("");
  }

  const positions = document.getElementById("positions");
  if (!payload.positions || !payload.positions.length) {
    positions.classList.add("empty-state");
    positions.textContent = "No open demo positions.";
  } else {
    positions.classList.remove("empty-state");
    positions.innerHTML = payload.positions
      .map(
        (p) => `<article class="card">
          <header>
            <strong class="${actionClass(p.side)}">${p.side} ${p.symbol}</strong>
            <button class="linkish" data-close="${p.id}">Close</button>
          </header>
          <div>${p.source === "human" ? "Operator" : "Desk"} · ${(p.venue || "oanda").toUpperCase()} · Fill ${px(p.symbol, p.fill_price)} · ${p.remaining_units} / ${p.units} units · #${p.broker_trade_id || p.id}</div>
          <div class="levels">
            <div>SL<b>${px(p.symbol, p.stop_loss)}</b></div>
            <div>TP1<b>${px(p.symbol, p.take_profit_1)}</b></div>
            <div>TP2<b>${px(p.symbol, p.take_profit_2)}</b></div>
            <div>P/L<b>${fmt.format(p.realized_pl || 0)}</b></div>
          </div>
        </article>`
      )
      .join("");
    positions.querySelectorAll("[data-close]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`/api/trades/${btn.dataset.close}/close`, { method: "POST" });
        refreshOverview();
      });
    });
  }

  const signals = document.getElementById("signals");
  if (!payload.signals || !payload.signals.length) {
    signals.classList.add("empty-state");
    signals.textContent = "No signals yet.";
  } else {
    signals.classList.remove("empty-state");
    signals.innerHTML = payload.signals
      .slice(0, 8)
      .map((s) => {
        const skip = s.skipped ? ` · skipped: ${s.skip_reason}` : "";
        return `<article class="signal">
          <header>
            <span class="tag ${actionClass(s.action)}">${s.action} ${s.symbol}</span>
            <span>${iso(s.ts).slice(11, 19)} · ${s.timeframe} · ${s.strength}</span>
          </header>
          <div>${s.reason || ""}${skip}</div>
        </article>`;
      })
      .join("");
  }

  const tradesBody = document.getElementById("trades-body");
  if (!payload.trades || !payload.trades.length) {
    tradesBody.innerHTML = `<tr><td colspan="9" class="empty">No demo orders yet.</td></tr>`;
  } else {
    tradesBody.innerHTML = payload.trades
      .slice(0, 12)
      .map(
        (t) => `<tr>
          <td>${t.broker_trade_id || t.id}</td>
          <td>${t.symbol}</td>
          <td class="${actionClass(t.side)}">${t.side}</td>
          <td>${px(t.symbol, t.fill_price)}</td>
          <td>${t.units}</td>
          <td>${fmt.format(t.realized_pl || 0)}</td>
          <td>${t.source === "human" ? "you" : "desk"}</td>
          <td>${(t.venue || "oanda").toUpperCase()}</td>
          <td>${t.status}</td>
        </tr>`
      )
      .join("");
  }

  const skipRules = document.getElementById("skip-rules");
  if (skipRules) {
    const active = (payload.lessons || []).filter(
      (r) => r.action === "skip" || r.action === "require_high_strength" || r.action === "prefer"
    );
    if (!active.length) {
      skipRules.classList.add("empty-state");
      skipRules.textContent = "No skip rules yet — they appear after repeat losses on the same family of setups.";
    } else {
      skipRules.classList.remove("empty-state");
      skipRules.innerHTML = active
        .slice(0, 8)
        .map((r) => {
          const until = r.skip_until ? ` until ${iso(r.skip_until)}` : "";
          const need = r.min_strength ? ` · min strength ${r.min_strength}` : "";
          return `<article class="signal journal-card">
            <header>
              <span class="tag ${r.action === "skip" ? "sell" : r.action === "prefer" ? "buy" : "hold"}">${r.action}</span>
              <span>${r.symbol} ${r.side} · ${r.loss_count} loss(es) · ${fmt.format(r.net_pl || 0)}${until}${need}</span>
            </header>
            <div class="journal-body">${r.fingerprint}\n${r.lesson || ""}</div>
          </article>`;
        })
        .join("");
    }
  }

  const growthBox = document.getElementById("growth-overview");
  if (growthBox) {
    const g = payload.growth;
    if (!g) {
      growthBox.classList.add("empty-state");
      growthBox.textContent = "No growth study yet — it restudies on startup and after every fill.";
    } else {
      growthBox.classList.remove("empty-state");
      const buckets = (g.buckets || [])
        .filter((b) => b.scope === "book" && b.samples)
        .map(
          (b) =>
            `<article class="signal journal-card">
              <header>
                <span class="tag ${b.net_pl >= 0 ? "buy" : "sell"}">${b.key}</span>
                <span>${b.wins}W/${b.losses}L/${b.scratches || 0} scratches · recorded P/L ${fmt.format(b.net_pl || 0)}</span>
              </header>
              <div class="journal-body">Mean R: ${b.mean_r == null ? "unknown" : Number(b.mean_r).toFixed(2)} · initial-risk coverage ${b.r_samples || 0}/${b.samples} · ${b.evidence_status === "insufficient_evidence" ? "insufficient evidence" : "unvalidated"}. ${b.lesson || ""}</div>
            </article>`
        )
        .join("");
      growthBox.innerHTML = `<article class="signal journal-card">
          <header>
            <span class="tag hold">focus</span>
            <span>configured stop floor ${Number(g.recommended_min_stop_pips || 0).toFixed(1)} pips · learning is observational</span>
          </header>
          <div class="journal-body">${g.next_focus || ""}</div>
        </article>${buckets}`;
    }
  }

  const historyBox = document.getElementById("history-overview");
  if (historyBox) {
    const h = payload.history;
    if (!h) {
      historyBox.classList.add("empty-state");
      historyBox.textContent = "No extra datasets studied yet — drop EUR/USD CSV/JSON/Parquet in extra datasets/ and restudy.";
    } else {
      historyBox.classList.remove("empty-state");
      const files = (h.files || [])
        .map(
          (f) =>
            `<article class="signal journal-card">
              <header>
                <span class="tag hold">${f.kind || "file"}</span>
                <span>${f.rows || 0} rows${f.timeframe ? " · " + f.timeframe : ""}</span>
              </header>
              <div class="journal-body">${f.path}${f.start && f.end ? " · " + f.start + " → " + f.end : ""} ${f.note || ""}</div>
            </article>`
        )
        .join("");
      const setup = h.preferred_signal_type ? ` · setup ${h.preferred_signal_type}` : "";
      historyBox.innerHTML = `<article class="signal journal-card">
          <header>
            <span class="tag ${h.preferred_side === "BUY" ? "buy" : h.preferred_side === "SELL" ? "sell" : "hold"}">${h.preferred_side || "waiting"}</span>
            <span>${h.eurusd_bars || 0} EUR/USD bars · ${h.replay_trades || 0} replay trades · ${h.preferred_session || "no session yet"}${setup}</span>
          </header>
          <div class="journal-body">${h.next_focus || h.note || ""}</div>
        </article>${files}`;
    }
  }

  const journals = document.getElementById("journals");
  if (journals) {
    if (!payload.journals || !payload.journals.length) {
      journals.classList.add("empty-state");
      journals.textContent = "No reflections yet — they appear on the next demo fill.";
    } else {
      journals.classList.remove("empty-state");
      journals.innerHTML = payload.journals
        .slice(0, 8)
        .map((j) => {
          const outcome = j.outcome || "open";
          const body =
            outcome === "loss"
              ? `${j.what_went_wrong || ""}\n\nHow to avoid: ${j.how_to_avoid || ""}`
              : outcome === "open"
                ? j.entry_thesis || ""
                : j.what_went_right || j.entry_thesis || "";
          const why =
            j.side === "BUY" ? "Why it bought" : j.side === "SELL" ? "Why it sold" : "Thesis";
          return `<article class="signal journal-card">
            <header>
              <span class="tag ${actionClass(j.side)}">${j.side} ${j.symbol}</span>
              <span class="${outcome === "loss" ? "down" : outcome === "win" ? "up" : ""}">${outcome} · ${fmt.format(j.realized_pl || 0)}</span>
            </header>
            <div class="hint">${why} · ${j.fingerprint || ""}${j.mistakes && j.mistakes.length ? " · " + j.mistakes.join(", ") : ""}</div>
            <div class="journal-body">${(j.entry_thesis || "").slice(0, 420)}</div>
            ${body && outcome !== "open" ? `<div class="journal-body">${String(body).slice(0, 520)}</div>` : ""}
          </article>`;
        })
        .join("");
    }
  }

  renderDeskNotes(payload.desk_notes || []);
  renderIntel(payload.intel);
}

function renderIntel(intel) {
  const el = document.getElementById("intel");
  if (!el) return;
  if (!intel) {
    el.classList.add("empty-state");
    el.textContent = "No intel yet — the desk writes it on startup and every 20 minutes.";
    return;
  }
  el.classList.remove("empty-state");
  const price = intel.price || {};
  const drivers = (intel.drivers || []).slice(0, 5).map((d) => `<li>${d}</li>`).join("");
  const macro = (intel.macro || [])
    .filter((m) => m.last != null)
    .map((m) => {
      const chg = m.change_pct == null ? "" : ` (${m.change_pct >= 0 ? "+" : ""}${Number(m.change_pct).toFixed(2)}%)`;
      return `${m.name} ${Number(m.last).toFixed(3)}${chg}`;
    })
    .join(" · ");
  el.innerHTML = `<article class="signal journal-card">
    <header>
      <span class="tag ${price.verdict === "disagree" ? "sell" : price.verdict === "consistent" ? "buy" : "hold"}">${price.verdict || "watch"}</span>
      <span>${intel.sentiment_label || "news"} · H1 ${intel.h1_bias || "n/a"} · D1 ${intel.d1_bias || "n/a"}</span>
    </header>
    <div class="journal-body">${intel.stance || ""}</div>
    <div class="hint">OANDA ${price.oanda_mid != null ? Number(price.oanda_mid).toFixed(5) : "—"} · CF ${price.cf_mid != null ? Number(price.cf_mid).toFixed(5) : "—"} · TE ${price.te_mid != null ? Number(price.te_mid).toFixed(5) : "—"} · FXS ${price.fxs_mid != null ? Number(price.fxs_mid).toFixed(5) : "—"} · BC ${price.bc_mid != null ? Number(price.bc_mid).toFixed(5) : "—"} · INV ${price.inv_mid != null ? Number(price.inv_mid).toFixed(5) : "—"} · TV ${price.tv_mid != null ? Number(price.tv_mid).toFixed(5) : "—"} · Δ ${price.oanda_vs_cf_pips != null ? Number(price.oanda_vs_cf_pips).toFixed(1) + " pips" : "n/a"} · spread ${price.spread_pips != null ? Number(price.spread_pips).toFixed(1) : "—"}</div>
    ${macro ? `<div class="hint">${macro}</div>` : ""}
    ${drivers ? `<h4>What can move EUR/USD</h4><ul class="briefing-list">${drivers}</ul>` : ""}
  </article>`;
}

async function refreshPlaybook() {
  const md = document.getElementById("playbook-md");
  const log = document.getElementById("learning-log");
  const te = document.getElementById("te-guide");
  const fxs = document.getElementById("fxs-guide");
  const bc = document.getElementById("bc-guide");
  const inv = document.getElementById("inv-guide");
  const tv = document.getElementById("tv-guide");
  const ops = document.getElementById("ops-guide");
  const scalp = document.getElementById("scalp-guide");
  const mistakes = document.getElementById("mistakes-guide");
  if (!md) return;
  try {
    const res = await actionFetch("/api/playbook");
    const payload = await res.json();
    md.textContent = payload.playbook || "Playbook is empty — run intel.";
    if (log) log.textContent = payload.learning_log || "No learning log yet.";
    if (te) te.textContent = payload.tradingeconomics || "No Trading Economics notes yet.";
    if (fxs) fxs.textContent = payload.fxstreet || "No FXStreet notes yet.";
    if (bc) bc.textContent = payload.barchart || "No Barchart notes yet.";
    if (inv) inv.textContent = payload.investing || "No Investing.com notes yet.";
    const ff = document.getElementById("ff-guide");
    if (ff) ff.textContent = payload.forexfactory || "No Forex Factory notes yet.";
    const mt4Guide = document.getElementById("mt4-guide");
    if (mt4Guide) mt4Guide.textContent = payload.mt4 || "No MT4 notes yet.";
    if (tv) tv.textContent = payload.tradingview || "No TradingView notes yet.";
    if (ops) ops.textContent = payload.operating || "No operating notes yet.";
    if (scalp) scalp.textContent = payload.scalping || "No scalp notes yet.";
    if (mistakes) mistakes.textContent = payload.mistakes || "No mistake book yet.";
    const sheetsGuide = document.getElementById("sheets-guide");
    if (sheetsGuide) sheetsGuide.textContent = payload.sheets || "No Sheets notes yet.";
    const newsGuide = document.getElementById("news-guide");
    if (newsGuide) newsGuide.textContent = payload.news || "No news notes yet.";
    const newsPat = document.getElementById("news-patterns-guide");
    if (newsPat) newsPat.textContent = payload.news_patterns || "No scored news patterns yet.";
  } catch (err) {
    md.textContent = "Could not load desk/EURUSD_PLAYBOOK.md";
  }
}

async function refreshNews() {
  const body = document.getElementById("news-patterns-body");
  const itemsEl = document.getElementById("news-items");
  const md = document.getElementById("news-patterns-md");
  const meta = document.getElementById("news-meta");
  try {
    const res = await actionFetch("/api/news");
    const payload = await res.json();
    if (meta && payload.bot && payload.bot.news_scan) {
      meta.textContent =
        `${payload.bot.news_scan} harvest from Forex Factory, NewsNow, Google News, Yahoo/ECB/Fed, and intel hubs. ` +
        `Each story is classified, a EUR/USD lean is stored with the spot mid, then the 1-hour M5 close is checked.`;
    }
    const patterns = payload.patterns || [];
    if (body) {
      if (!patterns.length) {
        body.innerHTML = `<tr><td class="empty" colspan="8">No scored categories yet — run a scan.</td></tr>`;
      } else {
        body.innerHTML = patterns
          .map((row) => {
            const hit = row.hit_rate == null ? "—" : `${Math.round(100 * row.hit_rate)}%`;
            const avg = row.avg_abs_1h_pips == null ? "—" : row.avg_abs_1h_pips;
            return `<tr>
              <td>${row.category}</td>
              <td>${row.samples}</td>
              <td>${row.correct}</td>
              <td>${row.wrong}</td>
              <td>${row.unclear}</td>
              <td>${row.pending}</td>
              <td>${hit}</td>
              <td>${avg}</td>
            </tr>`;
          })
          .join("");
      }
    }
    const items = payload.items || [];
    if (itemsEl) {
      if (!items.length) {
        itemsEl.classList.add("empty-state");
        itemsEl.textContent = "No headlines stored yet.";
      } else {
        itemsEl.classList.remove("empty-state");
        itemsEl.innerHTML = items
          .slice(0, 24)
          .map((item) => {
            const move = item.move_1h_pips == null ? "pending" : `${item.move_1h_pips >= 0 ? "+" : ""}${item.move_1h_pips} pips 1h`;
            const side = item.predicted === "bullish" ? "BUY" : item.predicted === "bearish" ? "SELL" : "HOLD";
            const href = item.url
              ? `<a href="${item.url}" target="_blank" rel="noopener">${item.title}</a>`
              : item.title;
            return `<article class="signal journal-card">
              <header>
                <span class="tag ${actionClass(side)}">${item.category} · ${item.predicted}</span>
                <span>${item.verdict || "pending"} · ${move}</span>
              </header>
              <div class="journal-body">${href}<div class="hint">${item.source || ""} · ${item.ts || ""}</div></div>
            </article>`;
          })
          .join("");
      }
    }
    if (md) md.textContent = payload.patterns_markdown || payload.guide || "No pattern book yet.";
  } catch (err) {
    if (itemsEl) {
      itemsEl.classList.add("empty-state");
      itemsEl.textContent = "Could not load the news book.";
    }
  }
}

async function refreshGrowth() {
  const md = document.getElementById("growth-md");
  const body = document.getElementById("growth-body");
  const histMd = document.getElementById("growth-history-md");
  if (!md) return;
  try {
    const res = await actionFetch("/api/growth");
    const payload = await res.json();
    md.textContent = payload.markdown || "Growth ledger is empty — restudy after a fill.";
    const hist = (payload.study && payload.study.history) || {};
    if (histMd) {
      histMd.textContent =
        payload.history_markdown ||
        (hist && (hist.next_focus || hist.note)) ||
        "No extra datasets studied yet.";
    }
    const buckets = (payload.study && payload.study.buckets) || [];
    const rows = buckets.filter((b) => b.samples);
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="6" class="empty">No closed EUR/USD desk fills scored yet.</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map(
        (b) => `<tr>
          <td>${b.key}</td>
          <td>${b.scope}</td>
          <td>${b.wins}/${b.losses}</td>
          <td>${fmt.format(b.expectancy || 0)}</td>
          <td>${fmt.format(b.net_pl || 0)}</td>
          <td>${b.lesson || ""}</td>
        </tr>`
      )
      .join("");
  } catch (err) {
    md.textContent = "Could not load desk/GROWTH.md";
  }
}

async function refreshHistory() {
  const md = document.getElementById("history-md");
  const body = document.getElementById("history-files");
  const setupsBody = document.getElementById("history-setups");
  if (!md) return;
  try {
    const res = await actionFetch("/api/history");
    const payload = await res.json();
    md.textContent = payload.studying
      ? (payload.markdown || "Historical study is running in the background so live quotes stay on the clock.")
      : payload.markdown || "No extra datasets studied yet.";
    const files = (payload.study && payload.study.files) || [];
    const setups = (payload.study && payload.study.setups) || [];
    if (body) {
      if (!files.length) {
        body.innerHTML = `<tr><td colspan="6" class="empty">${(payload.study && payload.study.note) || "No extra datasets loaded yet."}</td></tr>`;
      } else {
        body.innerHTML = files
          .map(
            (f) => `<tr>
              <td>${f.path}</td>
              <td>${f.kind}</td>
              <td>${f.rows}</td>
              <td>${f.timeframe || "—"}</td>
              <td>${f.start && f.end ? f.start + " → " + f.end : "—"}</td>
              <td>${f.note || ""}</td>
            </tr>`
          )
          .join("");
      }
    }
    if (setupsBody) {
      if (!setups.length) {
        setupsBody.innerHTML = `<tr><td colspan="6" class="empty">No named setups scored yet.</td></tr>`;
      } else {
        setupsBody.innerHTML = setups
          .slice(0, 24)
          .map(
            (s) => `<tr>
              <td>${s.signal_type || "mixed"}</td>
              <td>${s.side || "—"}</td>
              <td>${s.session || "—"}</td>
              <td>${s.wins || 0}/${s.losses || 0}</td>
              <td>${Number(s.expectancy_pips || 0).toFixed(1)} pips</td>
              <td>${((Number(s.win_rate) || 0) * 100).toFixed(0)}%</td>
            </tr>`
          )
          .join("");
      }
    }
  } catch (err) {
    md.textContent = "Could not load desk/HISTORY.md";
  }
}

function noteKindLabel(note) {
  if (note.kind === "morning") return note.sentiment ? `Morning · ${note.sentiment}` : "Morning briefing";
  const verdict = (note.verdict || "recap").toUpperCase();
  return `Night recap · ${verdict}`;
}

function noteClass(note) {
  if (note.kind === "morning") return "morning";
  if (note.verdict === "positive") return "up";
  if (note.verdict === "negative") return "down";
  return "hold";
}

function briefingCard(note, emptyText) {
  if (!note) {
    return `<p class="empty">${emptyText}</p>`;
  }
  const sections = [];
  if (note.kind === "morning") {
    if (note.why) sections.push(`<h4>Sentiment</h4><div class="journal-body">${note.why}</div>`);
    const events = (note.news && note.news.events) || [];
    const headlines = (note.news && note.news.headlines) || [];
    if (events.length) {
      sections.push(
        `<h4>News that can move EUR/USD</h4><ul class="briefing-list">${events
          .slice(0, 8)
          .map((ev) => {
            const when = ev.ts ? iso(ev.ts).slice(11, 16) + " UTC" : "untimed";
            return `<li>${when} ${ev.country || ""} ${ev.impact || ""} — ${ev.title}</li>`;
          })
          .join("")}</ul>`
      );
    }
    if (headlines.length) {
      sections.push(
        `<h4>Headlines</h4><ul class="briefing-list">${headlines
          .slice(0, 6)
          .map((h) => `<li>${h.title}${h.source ? ` (${h.source})` : ""}</li>`)
          .join("")}</ul>`
      );
    }
    if (note.looking_for) sections.push(`<h4>What I am looking for</h4><div class="journal-body">${note.looking_for}</div>`);
    if (note.goals) sections.push(`<h4>Goals for the day</h4><div class="journal-body">${note.goals}</div>`);
  } else {
    if (note.why) sections.push(`<h4>Why it was ${note.verdict || "the day"}</h4><div class="journal-body">${note.why}</div>`);
    if (note.what_went_right) sections.push(`<h4>What went right</h4><div class="journal-body">${note.what_went_right}</div>`);
    if (note.what_went_wrong) sections.push(`<h4>What went wrong</h4><div class="journal-body">${note.what_went_wrong}</div>`);
    if (note.learned) sections.push(`<h4>What I learned</h4><div class="journal-body">${note.learned}</div>`);
    if (note.realized_pl != null) {
      sections.push(`<div class="hint">Realized P/L ${fmt.format(note.realized_pl || 0)}</div>`);
    }
  }
  return `<header>
      <strong class="${noteClass(note)}">${noteKindLabel(note)}</strong>
      <span>${note.day || ""}</span>
    </header>
    ${sections.join("")}`;
}

function renderDeskNotes(notes) {
  const today = new Date().toISOString().slice(0, 10);
  const morning = notes.find((n) => n.kind === "morning" && n.day === today);
  const recap = notes.find((n) => n.kind === "recap" && n.day === today);
  const overview = document.getElementById("desk-notes");
  if (overview) {
    const latest = notes.slice(0, 4);
    if (!latest.length) {
      overview.classList.add("empty-state");
      overview.textContent = "No briefing yet — it writes at 08:00 UTC on trading days, or tap Briefings to run one now.";
    } else {
      overview.classList.remove("empty-state");
      overview.innerHTML = latest
        .map((n) => {
          const excerpt =
            n.kind === "morning"
              ? n.why || n.looking_for || n.body || ""
              : n.why || n.learned || n.body || "";
          return `<article class="signal journal-card">
            <header>
              <span class="tag ${noteClass(n)}">${noteKindLabel(n)}</span>
              <span>${n.day || ""}</span>
            </header>
            <div class="journal-body">${String(excerpt).slice(0, 520)}</div>
          </article>`;
        })
        .join("");
    }
  }

  const morningCard = document.getElementById("card-morning");
  const recapCard = document.getElementById("card-recap");
  if (morningCard) {
    morningCard.className = "briefing-card" + (morning ? "" : " empty-state");
    morningCard.innerHTML = briefingCard(morning, "No morning briefing yet for today.");
  }
  if (recapCard) {
    recapCard.className = "briefing-card" + (recap ? "" : " empty-state");
    recapCard.innerHTML = briefingCard(recap, "No night recap yet for today.");
  }
  const history = document.getElementById("briefing-history");
  if (history) {
    const older = notes.filter((n) => n.day !== today);
    if (!older.length) {
      history.classList.add("empty-state");
      history.textContent = "Earlier weekday notes will stack here.";
    } else {
      history.classList.remove("empty-state");
      history.innerHTML = older
        .map((n) => {
          const excerpt = n.kind === "morning" ? n.why || n.goals || "" : n.why || n.learned || "";
          return `<article class="signal journal-card">
            <header>
              <span class="tag ${noteClass(n)}">${noteKindLabel(n)}</span>
              <span>${n.day || ""}</span>
            </header>
            <div class="journal-body">${String(excerpt).slice(0, 420)}</div>
          </article>`;
        })
        .join("");
    }
  }
  const meta = document.getElementById("briefing-meta");
  if (meta) {
    const am = morning ? "today's 08:00 note is on file" : "08:00 briefing still pending";
    const pm = recap ? "today's 23:30 recap is on file" : "23:30 recap still pending";
    meta.textContent = `${am} · ${pm}`;
  }
}

function renderSummary(summary) {
  const counts = summary.counts || {};
  document.getElementById("count-bars").textContent = (counts.bars ?? 0).toLocaleString();
  document.getElementById("count-signals").textContent = (counts.signals ?? 0).toLocaleString();
  document.getElementById("count-sides").textContent = `${counts.buy_signals ?? 0} / ${counts.sell_signals ?? 0}`;
  document.getElementById("count-trades").textContent = `${counts.open_trades ?? 0} open · ${counts.closed_trades ?? 0} closed`;
  document.getElementById("count-pl").innerHTML = signed(summary.realized_pl || 0);
  document.getElementById("count-skipped").textContent = (counts.skipped_signals ?? 0).toLocaleString();
  const journalEl = document.getElementById("count-journal");
  if (journalEl) {
    journalEl.textContent = `${counts.journals ?? 0} · ${counts.journal_losses ?? 0} losses`;
  }
  const lessonEl = document.getElementById("count-lessons");
  if (lessonEl) {
    lessonEl.textContent = (counts.active_lessons ?? 0).toLocaleString();
  }
  const briefingEl = document.getElementById("count-briefings");
  if (briefingEl) {
    briefingEl.textContent = `${counts.morning_notes ?? 0} · ${counts.recap_notes ?? 0}`;
  }
  if (summary.symbols && summary.symbols.length) {
    state.symbols = summary.symbols;
    const select = document.getElementById("filter-symbol");
    const current = select.value;
    select.innerHTML =
      `<option value="ALL">All</option>` +
      summary.symbols.map((symbol) => `<option value="${symbol}">${symbol}</option>`).join("");
    if ([...select.options].some((opt) => opt.value === current)) select.value = current;
  }
}

function currentFilters() {
  const spec = SHEETS[state.tab];
  if (!spec) return {};
  const params = {};
  spec.filters.forEach((name) => {
    const el = document.getElementById(`filter-${name}`);
    if (el && el.value && el.value !== "ALL") params[name] = el.value;
  });
  return params;
}

function queryString(extra = {}) {
  const params = new URLSearchParams({ ...currentFilters(), ...extra });
  [...params.entries()].forEach(([key, value]) => {
    if (!value || value === "ALL") params.delete(key);
  });
  return params.toString();
}

function toggleFilters() {
  const spec = SHEETS[state.tab];
  const names = ["symbol", "timeframe", "action", "skipped", "source", "side", "status", "kind", "outcome", "rule"];
  names.forEach((name) => {
    const wrap = document.getElementById(`filter-${name}-wrap`) || document.getElementById(`filter-${name}`)?.parentElement;
    if (!wrap || wrap.tagName === "SELECT") return;
    wrap.hidden = !(spec && spec.filters.includes(name));
  });
  const symbolWrap = document.getElementById("filter-symbol").parentElement;
  symbolWrap.hidden = !(spec && spec.filters.includes("symbol"));
}

function renderSheet(payload) {
  const spec = SHEETS[state.tab];
  if (!spec) return;
  document.getElementById("sheet-title").textContent = spec.title;
  const total = payload.total || 0;
  const page = payload.page || 1;
  const size = payload.page_size || 100;
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  document.getElementById("sheet-meta").textContent = spec.hint + ` · ${from}–${to} of ${total.toLocaleString()}`;
  document.getElementById("sheet-head").innerHTML = spec.columns.map((col) => `<th>${col[1]}</th>`).join("");
  const rows = payload.rows || [];
  const body = document.getElementById("sheet-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td class="empty" colspan="${spec.columns.length}">No rows for these filters.</td></tr>`;
  } else {
    body.innerHTML = rows
      .map((row) => {
        const tds = spec.columns
          .map((col) => {
            const cls = col[2] === "wrap" ? "wrap" : col[0] === "side" || col[0] === "action" ? actionClass(row[col[0]]) : "";
            return `<td class="${cls}">${cell(col, row)}</td>`;
          })
          .join("");
        return `<tr>${tds}</tr>`;
      })
      .join("");
  }
  document.getElementById("sheet-prev").disabled = page <= 1;
  document.getElementById("sheet-next").disabled = to >= total;
  const qs = queryString();
  document.getElementById("sheet-export").href = `/api/tables/${state.tab}/csv${qs ? "?" + qs : ""}`;
}

async function refreshOverview() {
  try {
    const [stateRes, summaryRes] = await Promise.all([fetch("/api/state"), fetch("/api/hub/summary")]);
    if (stateRes.ok) renderOverview(await stateRes.json());
    if (summaryRes.ok) renderSummary(await summaryRes.json());
  } catch (err) {
    console.warn(err);
  }
}

async function refreshSheet() {
  if (!SHEETS[state.tab]) return;
  const params = queryString({ page: String(state.page), page_size: "100" });
  try {
    const res = await fetch(`/api/tables/${state.tab}?${params}`);
    if (!res.ok) throw new Error("table " + res.status);
    renderSheet(await res.json());
  } catch (err) {
    console.warn(err);
    document.getElementById("sheet-body").innerHTML = `<tr><td class="empty">Could not load this sheet.</td></tr>`;
  }
}

function showTab(tab) {
  state.tab = tab;
  state.page = 1;
  document.querySelectorAll(".tab").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  document.getElementById("view-overview").classList.toggle("active", tab === "overview");
  const briefings = document.getElementById("view-briefings");
  if (briefings) briefings.classList.toggle("active", tab === "briefings");
  const chartView = document.getElementById("view-chart");
  if (chartView) chartView.classList.toggle("active", tab === "chart");
  const playbookView = document.getElementById("view-playbook");
  if (playbookView) playbookView.classList.toggle("active", tab === "playbook");
  const growthView = document.getElementById("view-growth");
  if (growthView) growthView.classList.toggle("active", tab === "growth");
  const historyView = document.getElementById("view-history");
  if (historyView) historyView.classList.toggle("active", tab === "history");
  const newsView = document.getElementById("view-news");
  if (newsView) newsView.classList.toggle("active", tab === "news");
  const special = tab === "overview" || tab === "briefings" || tab === "chart" || tab === "playbook" || tab === "growth" || tab === "history" || tab === "news";
  document.getElementById("view-sheet").classList.toggle("active", !special);
  if (tab === "overview" || tab === "briefings") {
    refreshOverview();
    if (tab === "overview" && typeof refreshDeskChart === "function") refreshDeskChart();
    return;
  }
  if (tab === "playbook") {
    refreshPlaybook();
    return;
  }
  if (tab === "growth") {
    refreshGrowth();
    return;
  }
  if (tab === "history") {
    refreshHistory();
    return;
  }
  if (tab === "news") {
    refreshNews();
    return;
  }
  if (tab === "chart") {
    requestAnimationFrame(() => {
      if (typeof refreshDeskChart === "function") refreshDeskChart();
    });
    return;
  }
  toggleFilters();
  refreshSheet();
}

document.getElementById("tabs").addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-tab]");
  if (!btn) return;
  showTab(btn.dataset.tab);
});

["symbol", "timeframe", "action", "skipped", "source", "side", "status", "kind", "outcome", "rule"].forEach((name) => {
  document.getElementById(`filter-${name}`).addEventListener("change", () => {
    state.page = 1;
    refreshSheet();
  });
});

document.getElementById("sheet-prev").addEventListener("click", () => {
  state.page = Math.max(1, state.page - 1);
  refreshSheet();
});
document.getElementById("sheet-next").addEventListener("click", () => {
  state.page += 1;
  refreshSheet();
});

document.getElementById("toggle-trading").addEventListener("click", async (ev) => {
  const button = ev.currentTarget;
  const enabled = button.dataset.enabled === "1";
  button.disabled = true;
  showAction("Working…", false, button.id);
  try {
    await actionFetch("/api/trading", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled }),
    });
    await refreshOverview();
  } catch (err) {
    showAction(err.message || String(err), true, button.id);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("run-cycle").addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
  button.disabled = true;
    showAction("Working…", false, button.id);
  try {
    await actionFetch("/api/cycle", { method: "POST" });
    await refreshOverview();
    if (state.tab !== "overview" && state.tab !== "briefings" && state.tab !== "chart" && state.tab !== "playbook") await refreshSheet();
    if (typeof refreshDeskChart === "function") await refreshDeskChart();
  } catch (err) {
    showAction(err.message || String(err), true, button.id);
  } finally {
    button.disabled = false;
  }
});

const runIntel = document.getElementById("run-intel");
if (runIntel) {
  runIntel.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    try {
      await actionFetch("/api/intel", { method: "POST" });
      await refreshPlaybook();
      await refreshOverview();
    } catch (err) {
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

const runGrowth = document.getElementById("run-growth");
if (runGrowth) {
  runGrowth.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    try {
      await actionFetch("/api/growth", { method: "POST" });
      await refreshGrowth();
      await refreshOverview();
    } catch (err) {
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

const runHistory = document.getElementById("run-history");
if (runHistory) {
  runHistory.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    try {
      await actionFetch("/api/history", { method: "POST" });
      await refreshHistory();
      await refreshOverview();
    } catch (err) {
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

const saveSheets = document.getElementById("save-sheets");
if (saveSheets) {
  saveSheets.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    const status = document.getElementById("sheets-status");
    try {
      const res = await actionFetch("/api/sheets/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          composio_api_key: document.getElementById("sheets-key").value,
          spreadsheet_id: document.getElementById("sheets-id").value,
        }),
      });
      const payload = await res.json();
      if (status) {
        status.textContent = payload.ok
          ? payload.spreadsheet_url
            ? `connected · ${payload.last && payload.last.reason ? payload.last.reason : "sync started"}`
            : payload.last && payload.last.reason
              ? payload.last.reason
              : "sync started — waiting on Google Sheets"
          : payload.error || payload.detail || "Sheets still offline";
      }
      document.getElementById("sheets-key").value = "";
      await refreshOverview();
    } catch (err) {
      if (status) status.textContent = String(err);
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

const syncSheets = document.getElementById("sync-sheets");
if (syncSheets) {
  syncSheets.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    const status = document.getElementById("sheets-status");
    try {
      const res = await actionFetch("/api/sheets/sync", { method: "POST" });
      const payload = await res.json();
      if (status) {
        status.textContent = payload.started
          ? "sync started"
          : (payload.last && payload.last.reason) || "sync already running or disabled";
      }
      await refreshOverview();
    } catch (err) {
      if (status) status.textContent = String(err);
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

const saveMt4 = document.getElementById("save-mt4");
if (saveMt4) {
  saveMt4.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    const status = document.getElementById("mt4-status");
    try {
      const res = await actionFetch("/api/mt4/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          login: document.getElementById("mt4-login").value,
          password: document.getElementById("mt4-password").value,
          server: document.getElementById("mt4-server").value,
          metaapi_token: document.getElementById("mt4-metaapi").value,
        }),
      });
      const payload = await res.json();
      if (status) {
        status.textContent = payload.ok
          ? `${payload.mode || "connected"} · ${payload.login || ""} @ ${payload.server || ""}`
          : payload.error || payload.detail || "MT4 still offline";
      }
      const wrap = document.getElementById("mt4-secret-wrap");
      const secretEl = document.getElementById("mt4-secret");
      if (payload.bridge_secret && wrap && secretEl) {
        wrap.hidden = false;
        secretEl.textContent = payload.bridge_secret;
      }
      document.getElementById("mt4-password").value = "";
      document.getElementById("mt4-metaapi").value = "";
      await refreshOverview();
    } catch (err) {
      if (status) status.textContent = String(err);
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

const saveSlack = document.getElementById("save-slack");
if (saveSlack) {
  saveSlack.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    const status = document.getElementById("slack-status");
    try {
      const res = await actionFetch("/api/slack/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_token: document.getElementById("slack-token").value,
          webhook_url: document.getElementById("slack-webhook").value,
          channel: document.getElementById("slack-channel").value || "forex",
        }),
      });
      const payload = await res.json();
      if (status) {
        status.textContent = payload.ok
          ? `connected · ${payload.channel || "#forex"} · replayed ${payload.replayed || 0}`
          : payload.error || payload.detail || "Slack still offline";
      }
      document.getElementById("slack-token").value = "";
      await refreshOverview();
    } catch (err) {
      if (status) status.textContent = String(err);
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

async function runDeskNote(path, button) {
  button.disabled = true;
    showAction("Working…", false, button.id);
  try {
    const res = await actionFetch(path, { method: "POST" });
    if (!res.ok) throw new Error("briefing " + res.status);
    await refreshOverview();
  } catch (err) {
    showAction(err.message || String(err), true, button.id);
  } finally {
    button.disabled = false;
  }
}

const runMorning = document.getElementById("run-morning");
if (runMorning) {
  runMorning.addEventListener("click", (ev) => runDeskNote("/api/briefing/morning", ev.currentTarget));
}
const runRecap = document.getElementById("run-recap");
if (runRecap) {
  runRecap.addEventListener("click", (ev) => runDeskNote("/api/briefing/recap", ev.currentTarget));
}
const runNewsScan = document.getElementById("run-news-scan");
if (runNewsScan) {
  runNewsScan.addEventListener("click", async (ev) => {
    const button = ev.currentTarget;
    button.disabled = true;
    showAction("Working…", false, button.id);
    try {
      await actionFetch("/api/news/scan", { method: "POST" });
      await refreshNews();
      await refreshOverview();
    } catch (err) {
      showAction(err.message || String(err), true, button.id);
    } finally {
      button.disabled = false;
    }
  });
}

setClock();
setInterval(setClock, 1000);
refreshOverview();
setInterval(() => {
  refreshOverview();
  if (state.tab === "chart" && typeof refreshDeskChart === "function") refreshDeskChart();
  else if (state.tab === "news") refreshNews();
  else if (state.tab !== "overview" && state.tab !== "briefings" && state.tab !== "chart") refreshSheet();
}, 4000);
if (typeof refreshDeskChart === "function") refreshDeskChart();
