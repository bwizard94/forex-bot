/* EUR/USD OANDA chart with specialist markup (lightweight-charts + drawing overlay). */

const CHART_THEME = {
  layout: {
    background: { color: "#0c1110" },
    textColor: "#8aa094",
    fontFamily: "IBM Plex Mono, ui-monospace, monospace",
  },
  grid: {
    vertLines: { color: "rgba(214, 186, 122, 0.08)" },
    horzLines: { color: "rgba(214, 186, 122, 0.08)" },
  },
  rightPriceScale: { borderColor: "rgba(214, 186, 122, 0.2)" },
  timeScale: {
    borderColor: "rgba(214, 186, 122, 0.2)",
    timeVisible: true,
    secondsVisible: false,
  },
  crosshair: {
    vertLine: { color: "rgba(214, 186, 122, 0.4)", labelBackgroundColor: "#141c1a" },
    horzLine: { color: "rgba(214, 186, 122, 0.4)", labelBackgroundColor: "#141c1a" },
  },
};

const deskCharts = {};

const DEFAULT_LAYERS = {
  indicators: true,
  text: true,
  trend: true,
  drawing: true,
  icons: true,
  patterns: true,
};

function lineStyle(name) {
  const L = window.LightweightCharts && window.LightweightCharts.LineStyle;
  if (!L) return 0;
  if (name === "dotted") return L.Dotted;
  if (name === "dashed") return L.Dashed;
  return L.Solid;
}

function ensureOverlay(handle, el) {
  if (handle.overlay) return handle.overlay;
  const canvas = document.createElement("canvas");
  canvas.className = "chart-draw-layer";
  canvas.setAttribute("aria-hidden", "true");
  el.appendChild(canvas);
  handle.overlay = canvas;
  handle.drawings = [];
  const redraw = () => paintDrawings(handle);
  handle.chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
  try {
    handle.chart.timeScale().subscribeVisibleTimeRangeChange(redraw);
  } catch (err) {
    /* older lightweight-charts */
  }
  return canvas;
}

function toXY(handle, time, price) {
  const x = handle.chart.timeScale().timeToCoordinate(time);
  const y = handle.candles.priceToCoordinate(price);
  if (x == null || y == null) return null;
  return { x, y };
}

function extendRay(a, b, width) {
  if (!a || !b) return b;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (Math.abs(dx) < 0.001) return { x: width, y: b.y };
  const t = (width - a.x) / dx;
  return { x: width, y: a.y + dy * t };
}

function paintDrawings(handle) {
  const canvas = handle.overlay;
  if (!canvas) return;
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const layers = (handle.layers || DEFAULT_LAYERS);
  const drawings = handle.drawings || [];
  drawings.forEach((item) => {
    if (!layers[item.layer]) return;
    const pts = (item.points || [])
      .map((p) => toXY(handle, p.time, p.price))
      .filter(Boolean);
    ctx.save();
    ctx.strokeStyle = item.color || "#d6ba7a";
    ctx.fillStyle = item.fill || item.color || "#d6ba7a";
    ctx.lineWidth = item.width || 1;
    if (item.style === "dashed") ctx.setLineDash([7, 5]);
    else if (item.style === "dotted") ctx.setLineDash([2, 4]);
    else ctx.setLineDash([]);

    if (item.tool === "zone" && pts.length >= 2) {
      const x1 = Math.min(pts[0].x, pts[1].x);
      const x2 = Math.max(pts[0].x, pts[1].x);
      const y1 = Math.min(pts[0].y, pts[1].y);
      const y2 = Math.max(pts[0].y, pts[1].y);
      ctx.fillRect(x1, y1, Math.max(2, x2 - x1), Math.max(2, y2 - y1));
      ctx.strokeRect(x1, y1, Math.max(2, x2 - x1), Math.max(2, y2 - y1));
      if (item.label) {
        ctx.setLineDash([]);
        ctx.font = "11px IBM Plex Mono, ui-monospace, monospace";
        ctx.fillStyle = item.color || "#d6ba7a";
        ctx.fillText(item.label, x1 + 4, y1 + 12);
      }
    } else if ((item.tool === "trendline" || item.tool === "channel" || item.tool === "fib" || item.tool === "ray") && pts.length >= 2) {
      let end = pts[1];
      if (item.extend === "right") end = extendRay(pts[0], pts[1], width - 8);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();
      if (item.label) {
        ctx.setLineDash([]);
        ctx.font = "10px IBM Plex Mono, ui-monospace, monospace";
        ctx.fillStyle = item.color || "#d6ba7a";
        ctx.fillText(item.label, end.x - 92, end.y - 4);
      }
    } else if (item.tool === "pattern" && pts.length >= 1) {
      const p = pts[0];
      const q = pts[1] || { x: p.x + 18, y: p.y + 28 };
      ctx.fillRect(p.x - 10, Math.min(p.y, q.y), 20, Math.abs(q.y - p.y) || 20);
      ctx.setLineDash([]);
      ctx.font = "10px IBM Plex Mono, ui-monospace, monospace";
      ctx.fillStyle = item.color || "#d6ba7a";
      if (item.label) ctx.fillText(item.label, p.x - 8, Math.min(p.y, q.y) - 4);
    } else if ((item.tool === "text" || item.tool === "icon") && pts.length >= 1) {
      const p = pts[0];
      ctx.setLineDash([]);
      ctx.font = item.tool === "icon" ? "13px IBM Plex Mono, ui-monospace, monospace" : "11px IBM Plex Mono, ui-monospace, monospace";
      ctx.fillStyle = item.color || "#e8efe9";
      const glyph = (item.icon ? item.icon + " " : "") + (item.label || "");
      ctx.fillText(glyph, p.x + 6, p.y - 6);
    }
    ctx.restore();
  });
}

function ensureChart(containerId, { height, volume }) {
  if (deskCharts[containerId]) return deskCharts[containerId];
  const el = document.getElementById(containerId);
  if (!el || !window.LightweightCharts) return null;
  const chart = LightweightCharts.createChart(el, {
    ...CHART_THEME,
    height: height || el.clientHeight || 420,
    width: el.clientWidth || el.parentElement.clientWidth,
  });
  const candles = chart.addCandlestickSeries({
    upColor: "#3ee0b0",
    downColor: "#ff6b73",
    borderVisible: false,
    wickUpColor: "#3ee0b0",
    wickDownColor: "#ff6b73",
  });
  const emaFast = chart.addLineSeries({ color: "#d6ba7a", lineWidth: 2, title: "EMA9" });
  const emaSlow = chart.addLineSeries({ color: "#8aa094", lineWidth: 2, title: "EMA21" });
  const bbUpper = chart.addLineSeries({
    color: "rgba(62, 224, 176, 0.45)",
    lineWidth: 1,
    lineStyle: lineStyle("dotted"),
    title: "BB up",
  });
  const bbMid = chart.addLineSeries({
    color: "rgba(214, 186, 122, 0.45)",
    lineWidth: 1,
    lineStyle: lineStyle("dotted"),
    title: "BB mid",
  });
  const bbLower = chart.addLineSeries({
    color: "rgba(255, 107, 115, 0.45)",
    lineWidth: 1,
    lineStyle: lineStyle("dotted"),
    title: "BB low",
  });
  const vwap = chart.addLineSeries({ color: "#7ec8e3", lineWidth: 2, title: "VWAP" });
  const supertrend = chart.addLineSeries({
    color: "#c084fc",
    lineWidth: 2,
    lineStyle: lineStyle("dashed"),
    title: "Supertrend",
  });
  let vol = null;
  let macd = null;
  let rsi = null;
  if (volume) {
    vol = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.88, bottom: 0 },
    });
    macd = chart.addHistogramSeries({
      priceScaleId: "macd",
      priceFormat: { type: "price", precision: 5, minMove: 0.00001 },
    });
    chart.priceScale("macd").applyOptions({
      scaleMargins: { top: 0.76, bottom: 0.14 },
    });
    rsi = chart.addLineSeries({
      color: "#d6ba7a",
      lineWidth: 1,
      priceScaleId: "rsi",
      title: "RSI",
    });
    chart.priceScale("rsi").applyOptions({
      scaleMargins: { top: 0.9, bottom: 0 },
    });
  }
  const handle = {
    chart,
    candles,
    emaFast,
    emaSlow,
    bbUpper,
    bbMid,
    bbLower,
    vwap,
    supertrend,
    vol,
    macd,
    rsi,
    priceLines: [],
    layers: { ...DEFAULT_LAYERS },
  };
  deskCharts[containerId] = handle;
  ensureOverlay(handle, el);
  const ro = new ResizeObserver(() => {
    handle.chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || height || 420 });
    paintDrawings(handle);
  });
  ro.observe(el);
  return handle;
}

function paintChart(containerId, payload, options = {}) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const handle = ensureChart(containerId, options);
  if (!handle || !payload || !payload.candles || !payload.candles.length) return;
  const height = el.clientHeight || options.height || 420;
  const width = el.clientWidth || el.parentElement.clientWidth;
  if (width > 40) {
    handle.chart.applyOptions({ width, height });
  }
  handle.layers = { ...DEFAULT_LAYERS, ...(chartState.layers || {}) };
  handle.candles.setData(payload.candles);
  const ov = payload.overlays || {};
  const showInd = handle.layers.indicators !== false;
  handle.emaFast.setData(showInd ? ov.ema_fast || [] : []);
  handle.emaSlow.setData(showInd ? ov.ema_slow || [] : []);
  handle.bbUpper.setData(showInd ? ov.bb_upper || [] : []);
  handle.bbMid.setData(showInd ? ov.bb_mid || [] : []);
  handle.bbLower.setData(showInd ? ov.bb_lower || [] : []);
  if (handle.vwap) handle.vwap.setData(showInd ? ov.vwap || [] : []);
  if (handle.supertrend) handle.supertrend.setData(showInd ? ov.supertrend || [] : []);
  if (handle.vol) handle.vol.setData(showInd ? payload.volume || [] : []);
  if (handle.macd) {
    const hist = showInd
      ? (ov.macd_hist || []).map((pt) => ({
          time: pt.time,
          value: pt.value,
          color: pt.value >= 0 ? "rgba(62,224,176,0.55)" : "rgba(255,107,115,0.55)",
        }))
      : [];
    handle.macd.setData(hist);
  }
  if (handle.rsi) handle.rsi.setData(showInd ? ov.rsi || [] : []);
  const showIcons = handle.layers.icons !== false;
  if (typeof handle.candles.setMarkers === "function") {
    handle.candles.setMarkers(showIcons ? payload.markers || [] : []);
  }
  handle.priceLines.forEach((line) => {
    try {
      handle.candles.removePriceLine(line);
    } catch (err) {
      /* ignore */
    }
  });
  handle.priceLines = [];
  if (showInd) {
    (payload.price_lines || []).slice(0, 18).forEach((line) => {
      handle.priceLines.push(
        handle.candles.createPriceLine({
          price: line.price,
          color: line.color,
          lineWidth: 1,
          lineStyle: lineStyle(line.style),
          axisLabelVisible: true,
          title: line.title,
        })
      );
    });
  }
  handle.drawings = payload.drawings || [];
  handle.chart.timeScale().fitContent();
  requestAnimationFrame(() => paintDrawings(handle));
}

function renderChartBlotter(payload) {
  const meta = document.getElementById("chart-meta");
  if (meta) meta.textContent = payload.note || payload.thesis || "";
  const legend = document.getElementById("chart-legend");
  if (legend) {
    const last = payload.last || {};
    const bias = payload.bias || {};
    const chips = [
      `H1 ${bias.h1 || "—"}`,
      `D1 ${bias.d1 || "—"}`,
      payload.pattern && payload.pattern.name ? payload.pattern.name : null,
      last.rsi != null ? `RSI ${Number(last.rsi).toFixed(1)}` : null,
      last.stoch_k != null ? `Stoch ${Number(last.stoch_k).toFixed(0)}` : null,
      last.adx != null ? `ADX ${Number(last.adx).toFixed(0)}` : null,
      last.cci != null ? `CCI ${Number(last.cci).toFixed(0)}` : null,
      last.macd_hist != null ? `MACD ${Number(last.macd_hist).toFixed(5)}` : null,
      last.atr != null ? `ATR ${Number(last.atr).toFixed(5)}` : null,
      payload.spot != null ? `Spot ${Number(payload.spot).toFixed(5)}` : null,
      (payload.source || "oanda").toUpperCase(),
    ].filter(Boolean);
    legend.innerHTML = chips.map((chip) => `<span class="pill">${chip}</span>`).join("");
  }
  const tools = document.getElementById("chart-tools-used");
  if (tools) {
    const used = payload.tools_used || [];
    tools.innerHTML = used.length
      ? used.map((row) => `<li>${row}</li>`).join("")
      : "<li>Waiting on OANDA candles.</li>";
  }
  const marks = document.getElementById("chart-marks");
  if (!marks) return;
  const rows = payload.legend || [];
  if (!rows.length) {
    marks.classList.add("empty-state");
    marks.textContent = "No marks yet — they appear with OANDA candles.";
    return;
  }
  marks.classList.remove("empty-state");
  marks.innerHTML = rows
    .slice()
    .reverse()
    .map((row) => {
      const when = row.ts ? String(row.ts).replace("T", " ").slice(11, 19) : "";
      return `<article class="signal">
        <header>
          <span class="tag" style="color:${row.color || "#d6ba7a"}">${row.kind}</span>
          <span>${when}</span>
        </header>
        <div>${row.title || ""}</div>
        ${row.detail ? `<div class="hint">${String(row.detail).slice(0, 220)}</div>` : ""}
      </article>`;
    })
    .join("");
}

const chartState = { tf: "M5", last: null, layers: { ...DEFAULT_LAYERS } };

function applyLayerButtons() {
  document.querySelectorAll("#chart-tools [data-layer]").forEach((btn) => {
    const on = chartState.layers[btn.dataset.layer] !== false;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

async function refreshDeskChart() {
  try {
    const res = await fetch(`/api/chart?timeframe=${encodeURIComponent(chartState.tf)}&limit=240`);
    if (!res.ok) throw new Error("chart " + res.status);
    const payload = await res.json();
    chartState.last = payload;
    paintChart("desk-chart", payload, { height: 520, volume: true });
    paintChart("overview-chart", payload, { height: 280, volume: false });
    renderChartBlotter(payload);
  } catch (err) {
    console.warn(err);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const tfs = document.getElementById("chart-tfs");
  if (tfs) {
    tfs.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-tf]");
      if (!btn) return;
      chartState.tf = btn.dataset.tf;
      tfs.querySelectorAll(".tf-btn").forEach((el) => el.classList.toggle("active", el === btn));
      refreshDeskChart();
    });
  }
  const tools = document.getElementById("chart-tools");
  if (tools) {
    tools.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-layer]");
      if (!btn) return;
      const layer = btn.dataset.layer;
      chartState.layers[layer] = chartState.layers[layer] === false;
      applyLayerButtons();
      if (chartState.last) {
        paintChart("desk-chart", chartState.last, { height: 520, volume: true });
        paintChart("overview-chart", chartState.last, { height: 280, volume: false });
      }
    });
    applyLayerButtons();
  }
});
