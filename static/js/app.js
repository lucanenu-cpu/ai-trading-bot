/* =====================================================================
   AI Trading Bot — Client JS (v3)
   ===================================================================== */

(function () {
  "use strict";

  // ------------------------------------------------------------------
  // DOM refs
  // ------------------------------------------------------------------
  const symbolInput    = document.getElementById("symbol-input");
  const analyzeBtn     = document.getElementById("analyze-btn");
  const recommendBtn   = document.getElementById("recommend-btn");
  const errorMsg       = document.getElementById("error-msg");
  const loading        = document.getElementById("loading");
  const results        = document.getElementById("results");
  const watchlistChips = document.getElementById("watchlist-chips");
  const resRec         = document.getElementById("res-recommendation");

  // Search mode: "symbol" or "ask"
  let searchMode = "symbol";

  // ------------------------------------------------------------------
  // Tab switching
  // ------------------------------------------------------------------
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const pane = document.getElementById("tab-" + btn.dataset.tab);
      if (pane) {
        pane.classList.add("active");
        if (btn.dataset.tab === "dashboard") loadDashboard();
        if (btn.dataset.tab === "settings") loadCurrentConfig();
      }
    });
  });

  // ------------------------------------------------------------------
  // Mode toggle (Symbol / Ask AI)
  // ------------------------------------------------------------------
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      searchMode = btn.dataset.mode;
      if (searchMode === "ask") {
        symbolInput.placeholder = "Ask — e.g. \u201cShould I buy Tesla?\u201d or \u201cbitcoin\u201d";
        analyzeBtn.textContent = "🧠 Ask";
      } else {
        symbolInput.placeholder = "Symbol — e.g. AAPL, BTC-USD, SPY";
        analyzeBtn.textContent = "⚡ Analyze";
      }
    });
  });

  // ------------------------------------------------------------------
  // Load watchlist chips
  // ------------------------------------------------------------------
  fetch("/watchlist")
    .then((r) => r.json())
    .then((data) => {
      if (!data.success) return;
      data.watchlist.forEach((sym) => {
        const chip = document.createElement("button");
        chip.className = "chip";
        chip.textContent = sym;
        chip.addEventListener("click", () => {
          symbolInput.value = sym;
          searchMode = "symbol";
          document.querySelectorAll(".mode-btn").forEach((b) =>
            b.classList.toggle("active", b.dataset.mode === "symbol")
          );
          runAnalysis(sym);
        });
        watchlistChips.appendChild(chip);
      });
    })
    .catch(() => {});

  // ------------------------------------------------------------------
  // Button listeners
  // ------------------------------------------------------------------
  analyzeBtn.addEventListener("click", () => {
    const q = symbolInput.value.trim();
    if (!q) return showError("Please enter a symbol or question.");
    if (searchMode === "ask") {
      runAutoAnalysis(q);
    } else {
      runAnalysis(q.toUpperCase());
    }
  });

  symbolInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeBtn.click();
  });

  recommendBtn.addEventListener("click", () => {
    const sym = symbolInput.value.trim().toUpperCase();
    if (!sym) return showError("Please enter a symbol.");
    runAIRecommendation(sym);
  });

  // ------------------------------------------------------------------
  // Analysis — calls /api/recommendation/<symbol>
  // ------------------------------------------------------------------
  function runAnalysis(symbol) {
    showLoading();
    hideError();
    resRec.classList.add("hidden");
    resRec.textContent = "";

    fetch(`/api/recommendation/${encodeURIComponent(symbol)}`)
      .then(checkStatus)
      .then((data) => {
        renderSignal(data);
        showResults();
      })
      .catch((err) => {
        showError(err.message || "Analysis failed. Please try again.");
        hideLoading();
      });
  }

  // ------------------------------------------------------------------
  // Auto-analysis — calls /api/ask (natural language)
  // ------------------------------------------------------------------
  function runAutoAnalysis(query) {
    showLoading();
    hideError();
    resRec.classList.add("hidden");
    resRec.textContent = "";

    fetch("/api/ask?" + new URLSearchParams({ q: query }))
      .then(checkStatus)
      .then((data) => {
        // /api/ask embeds the resolved symbol
        if (data.resolved && data.resolved.symbol) {
          symbolInput.value = data.resolved.description
            ? `${data.resolved.symbol} — ${data.resolved.description}`
            : data.resolved.symbol;
        }
        renderSignal(data);
        showResults();
      })
      .catch((err) => {
        showError(err.message || "Auto-analysis failed. Please try again.");
        hideLoading();
      });
  }

  // ------------------------------------------------------------------
  // AI deep-dive — calls /recommend/<symbol>
  // ------------------------------------------------------------------
  function runAIRecommendation(symbol) {
    recommendBtn.disabled = true;
    recommendBtn.textContent = "⏳ Asking AI…";
    hideError();

    fetch(`/recommend/${encodeURIComponent(symbol)}`)
      .then(checkStatus)
      .then((data) => {
        resRec.textContent = data.recommendation;
        resRec.classList.remove("hidden");
      })
      .catch((err) => {
        showError(err.message || "AI recommendation failed.");
      })
      .finally(() => {
        recommendBtn.disabled = false;
        recommendBtn.textContent = "Get AI Recommendation";
      });
  }

  // ------------------------------------------------------------------
  // Render unified signal (Analyze tab)
  // ------------------------------------------------------------------
  function renderSignal(data) {
    const action   = (data.action || "HOLD").toUpperCase();
    const score    = data.score  || 0;
    const risk     = data.risk   || {};
    const reasons  = data.reasons || [];
    const ind      = data.indicators || {};
    const resolved = data.resolved || {};
    const tv       = data.tradingview || {};

    // Prefer TradingView's close price when available so the number shown matches
    // exactly what the embedded TradingView chart displays. Fall back to the
    // yfinance-based price from the scoring pipeline otherwise.
    const price = (tv && typeof tv.close === "number" && tv.close > 0)
      ? tv.close
      : (data.price || 0);

    // ── Symbol & Price ──
    const displaySymbol = resolved.symbol || data.symbol || "—";
    setText("res-symbol", displaySymbol);
    setText("res-price", formatPrice(price));
    const now = new Date();
    setText("res-updated", `Updated: ${now.toLocaleTimeString()}`);

    // Exchange / description line (e.g. "NASDAQ · Apple Inc. · stock")
    const exchangeEl = document.getElementById("res-exchange");
    if (exchangeEl) {
      const parts = [];
      if (resolved.exchange) parts.push(resolved.exchange);
      if (resolved.description) parts.push(resolved.description);
      if (resolved.type) parts.push(resolved.type);
      exchangeEl.textContent = parts.join(" · ");
    }

    // ── Action badge ──
    const actionEl = document.getElementById("res-action");
    actionEl.textContent = action;
    actionEl.className   = "action-badge " + actionClass(action);

    const subLabel = score >= 80 ? "Strong signal" : score >= 65 ? "Moderate signal" : "Weak / caution";
    setText("res-action-sub", `Score: ${score}/100 · ${subLabel}`);

    // TradingView consensus badge (under the action badge)
    const consEl = document.getElementById("res-tv-consensus");
    if (consEl) {
      if (tv && tv.recommendation && tv.recommendation !== "UNKNOWN") {
        const tvLabel = String(tv.recommendation).replace("_", " ");
        const tvScore = typeof tv.score === "number" ? tv.score : 0;
        consEl.textContent = `📡 TradingView: ${tvLabel} (${tvScore >= 0 ? "+" : ""}${tvScore.toFixed(2)})`;
        consEl.className = "tv-consensus " + tvConsensusClass(tv.recommendation);
      } else {
        consEl.textContent = "";
        consEl.className = "tv-consensus";
      }
    }

    // ── Allocation ──
    const allocUsd = risk.allocation_usd != null ? risk.allocation_usd : 0;
    const allocPct = risk.allocation_pct != null ? risk.allocation_pct : 0;
    setText("res-alloc-usd", action === "HOLD" ? "$0.00" : formatPrice(allocUsd));
    setText("res-alloc-pct", action === "HOLD" ? "No position" : `${allocPct.toFixed(1)}% of balance`);

    // ── Trade levels ──
    const entry = risk.entry  != null ? risk.entry  : price;
    const sl    = risk.stop_loss   != null ? risk.stop_loss   : 0;
    const tp    = risk.take_profit != null ? risk.take_profit : 0;
    const slPct = risk.stop_loss_pct   != null ? risk.stop_loss_pct   : 0;
    const tpPct = risk.take_profit_pct != null ? risk.take_profit_pct : 0;

    setText("res-entry", formatPrice(entry));
    setText("res-sl", action === "HOLD" ? "—" : formatPrice(sl));
    setText("res-sl-pct", action === "HOLD" ? "" : `-${slPct.toFixed(1)}%`);
    setText("res-tp", action === "HOLD" ? "—" : formatPrice(tp));
    setText("res-tp-pct", action === "HOLD" ? "" : `+${tpPct.toFixed(1)}%`);

    // ── Score gauge ──
    const scoreEl = document.getElementById("res-score");
    scoreEl.textContent = score;
    scoreEl.style.color = scoreColor(score);
    const arcLen = 172.79;
    const offset = arcLen - (score / 100) * arcLen;
    const arc = document.getElementById("gauge-arc");
    if (arc) {
      arc.setAttribute("stroke-dashoffset", offset.toFixed(2));
      arc.setAttribute("stroke", scoreColor(score));
    }

    // ── Score details ──
    setText("res-confidence", `${(data.confidence || 0).toFixed(0)}%`);

    const emaEl = document.getElementById("res-ema-trend");
    const ema   = ind.ema_trend || "—";
    emaEl.textContent = ema;
    emaEl.className   = "score-stat-value " + (ema === "BULLISH" ? "bull" : ema === "BEARISH" ? "bear" : "neutral");

    const rsiEl = document.getElementById("res-rsi");
    const rsi   = ind.rsi != null ? ind.rsi : "—";
    rsiEl.textContent = rsi !== "—" ? rsi.toFixed(1) : "—";
    if (rsi !== "—") {
      rsiEl.className = "score-stat-value " + (rsi >= 70 ? "bear" : rsi <= 30 ? "bull" : "neutral");
    }

    const newsEl = document.getElementById("res-news-impact");
    const ni     = data.news_impact || "—";
    newsEl.textContent = ni;
    newsEl.className   = "score-stat-value " + (ni === "HIGH" ? "bear" : ni === "MEDIUM" ? "neutral" : "bull");

    // ── Reasons ──
    const reasonsList = document.getElementById("res-reasons");
    reasonsList.innerHTML = "";
    if (reasons.length === 0) {
      const li = document.createElement("li");
      li.textContent = "No specific signals triggered.";
      reasonsList.appendChild(li);
    } else {
      reasons.forEach((r) => {
        const li = document.createElement("li");
        li.textContent = r;
        reasonsList.appendChild(li);
      });
    }

    // ── Embedded TradingView chart ──
    const tfSelect = document.getElementById("timeframe-select");
    const tfLabel = tfSelect ? tfSelect.options[tfSelect.selectedIndex].text : "1h";
    const chartNote = document.getElementById("chart-note");
    if (chartNote) chartNote.textContent = `Live chart · ${tfLabel} timeframe — data matches the numbers shown above.`;
    renderTradingViewChart(resolved, data.symbol);

    // Update header status after a signal load
    refreshHeaderStatus();
  }

  // ------------------------------------------------------------------
  // Embed the TradingView Advanced Chart widget.
  // Builds "EXCHANGE:SYMBOL" when we have one (from resolved), otherwise
  // falls back to the raw ticker — TradingView will auto-resolve.
  // ------------------------------------------------------------------
  function renderTradingViewChart(resolved, rawSymbol) {
    const container = document.getElementById("tv-chart-container");
    if (!container) return;

    const sym = (resolved && resolved.symbol) ? resolved.symbol : (rawSymbol || "").toUpperCase();
    const exch = resolved && resolved.exchange ? resolved.exchange.toUpperCase() : "";
    const type = resolved && resolved.type ? resolved.type : "";

    if (!sym) {
      container.innerHTML = '<div class="chart-empty">No chart available.</div>';
      return;
    }

    // Read the user-selected timeframe from the dropdown.
    const tfSelect = document.getElementById("timeframe-select");
    const interval = tfSelect ? tfSelect.value : "60";

    // Build the TradingView ticker: prefer EXCHANGE:SYMBOL when we know the
    // exchange; for crypto fall back to a sensible default.
    let tvSymbol;
    if (exch) {
      tvSymbol = `${exch}:${sym}`;
    } else if (type === "crypto") {
      // Strip any hyphen and assume Binance (very common; TV will fall back
      // gracefully if Binance doesn't list it).
      tvSymbol = `BINANCE:${sym.replace(/-/g, "")}`;
    } else {
      tvSymbol = sym;
    }

    // Recreate container to fully reset any previous widget.
    container.innerHTML = "";
    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    widgetDiv.style.height = "100%";
    widgetDiv.style.width = "100%";
    container.appendChild(widgetDiv);

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: interval,
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      toolbar_bg: "#0d1117",
      enable_publishing: false,
      allow_symbol_change: true,
      hide_side_toolbar: false,
      withdateranges: true,
      studies: [
        "STD;EMA%Cross",
        "STD;RSI",
        "STD;MACD",
      ],
      support_host: "https://www.tradingview.com",
    });
    container.appendChild(script);
  }

  function tvConsensusClass(rec) {
    switch ((rec || "").toUpperCase()) {
      case "STRONG_BUY":  return "cons-strong-buy";
      case "BUY":         return "cons-buy";
      case "STRONG_SELL": return "cons-strong-sell";
      case "SELL":        return "cons-sell";
      default:            return "cons-neutral";
    }
  }

  // ------------------------------------------------------------------
  // Dashboard tab
  // ------------------------------------------------------------------
  let dashAutoRefresh = null;

  function loadDashboard() {
    fetch("/api/bot-status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) return;
        renderDashboard(data);
      })
      .catch(() => {});
  }

  document.getElementById("dash-refresh-btn").addEventListener("click", loadDashboard);

  function renderDashboard(data) {
    const limits = data.limits || {};

    // KPI
    setText("d-status", data.status === "running" ? "🟢 Running" : "🔴 Stopped");
    setText("d-trades", `${data.trades_today} / ${limits.max_trades_per_day || "—"}`);
    setText("d-positions", `${(data.open_positions || []).length} / ${limits.max_open_positions || "—"}`);
    setText("d-ai-calls", `${data.ai_calls_remaining} / ${data.ai_calls_max || "—"}`);
    const pnl = data.realized_pnl_today || 0;
    const pnlEl = document.getElementById("d-pnl");
    pnlEl.textContent = (pnl >= 0 ? "+" : "") + "$" + Math.abs(pnl).toFixed(2);
    pnlEl.style.color = pnl >= 0 ? "var(--green)" : "var(--red)";

    // Open positions
    const posList = document.getElementById("d-open-positions-list");
    posList.innerHTML = "";
    const positions = data.open_positions || [];
    if (positions.length === 0) {
      posList.innerHTML = '<span class="text-muted">No open positions</span>';
    } else {
      positions.forEach((sym) => {
        const tag = document.createElement("span");
        tag.className = "position-tag";
        tag.textContent = sym;
        posList.appendChild(tag);
      });
    }

    // Risk limits
    const rlGrid = document.getElementById("d-risk-limits");
    rlGrid.innerHTML = "";
    const rlItems = [
      ["Max Trades/Day", limits.max_trades_per_day],
      ["Max Positions", limits.max_open_positions],
      ["Max Daily Loss", limits.max_daily_loss_pct != null ? limits.max_daily_loss_pct + "%" : "—"],
      ["Balance", limits.account_balance_usd != null ? "$" + limits.account_balance_usd : "—"],
      ["Risk/Trade", limits.risk_per_trade_pct != null ? limits.risk_per_trade_pct + "%" : "—"],
      ["Min Score", limits.min_signal_score],
      ["SL Default", limits.default_stop_loss_pct != null ? limits.default_stop_loss_pct + "%" : "—"],
      ["TP Default", limits.default_take_profit_pct != null ? limits.default_take_profit_pct + "%" : "—"],
      ["Cooldown", limits.trade_cooldown_secs != null ? limits.trade_cooldown_secs + "s" : "—"],
      ["Chop ADX", limits.chop_adx_threshold],
      ["ATR Mult", limits.atr_sl_multiplier],
      ["AI Enabled", data.ai_enabled ? "Yes" : "No"],
    ];
    rlItems.forEach(([k, v]) => {
      const div = document.createElement("div");
      div.className = "rl-item";
      div.innerHTML = `<span class="rl-key">${k}</span><span class="rl-val">${v ?? "—"}</span>`;
      rlGrid.appendChild(div);
    });

    // Recent trades table
    const tbody = document.getElementById("d-trades-tbody");
    tbody.innerHTML = "";
    const trades = data.recent_trades || [];
    if (trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-muted text-center">No recent trades</td></tr>';
    } else {
      [...trades].reverse().forEach((t) => {
        const tr = document.createElement("tr");
        const action = (t.action || "—").toUpperCase();
        const ts = t.timestamp ? new Date(t.timestamp).toLocaleString() : "—";
        tr.innerHTML = `
          <td>${t.symbol || "—"}</td>
          <td class="action-${action.toLowerCase()}">${action}</td>
          <td>${t.price != null ? formatPrice(t.price) : "—"}</td>
          <td>${t.score != null ? t.score.toFixed(0) : "—"}</td>
          <td>${t.stop_loss != null ? formatPrice(t.stop_loss) : "—"}</td>
          <td>${t.take_profit != null ? formatPrice(t.take_profit) : "—"}</td>
          <td>${t.allocation_usd != null ? "$" + t.allocation_usd.toFixed(2) : "—"}</td>
          <td class="text-muted">${ts}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    // Sync header status too
    updateHeaderStatus(data);
  }

  // ------------------------------------------------------------------
  // Header live status
  // ------------------------------------------------------------------
  function refreshHeaderStatus() {
    fetch("/api/bot-status")
      .then((r) => r.json())
      .then((data) => { if (data.success) updateHeaderStatus(data); })
      .catch(() => {});
  }

  function updateHeaderStatus(data) {
    const dot   = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
    const ai    = document.getElementById("status-ai-calls");
    const tr    = document.getElementById("status-trades");
    const limits = data.limits || {};

    if (data.status === "running") {
      dot.className = "status-dot running";
      label.textContent = "Running";
    } else {
      dot.className = "status-dot stopped";
      label.textContent = "Stopped";
    }
    ai.textContent = `AI ${data.ai_calls_remaining}/${data.ai_calls_max || "—"}`;
    tr.textContent = `Trades ${data.trades_today}/${limits.max_trades_per_day || "—"}`;
  }

  // Poll header status every 60 s
  refreshHeaderStatus();
  setInterval(refreshHeaderStatus, 60_000);

  // ------------------------------------------------------------------
  // Settings tab
  // ------------------------------------------------------------------
  function loadCurrentConfig() {
    fetch("/api/bot-status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.success) return;
        const lim = data.limits || {};
        // Pre-fill form inputs
        setInput("s-balance",  lim.account_balance_usd);
        setInput("s-risk",     lim.risk_per_trade_pct);
        setInput("s-sl",       lim.default_stop_loss_pct);
        setInput("s-tp",       lim.default_take_profit_pct);
        setInput("s-min-score",lim.min_signal_score);
        setInput("s-chop-adx", lim.chop_adx_threshold);
        setInput("s-atr-mult", lim.atr_sl_multiplier);
        setInput("s-cooldown", lim.trade_cooldown_secs);

        // Update current config display panel
        const grid = document.getElementById("s-current-config");
        grid.innerHTML = "";
        const items = [
          ["Account Balance", lim.account_balance_usd != null ? "$" + lim.account_balance_usd : "—"],
          ["Risk/Trade", lim.risk_per_trade_pct != null ? lim.risk_per_trade_pct + "%" : "—"],
          ["Stop-Loss", lim.default_stop_loss_pct != null ? lim.default_stop_loss_pct + "%" : "—"],
          ["Take-Profit", lim.default_take_profit_pct != null ? lim.default_take_profit_pct + "%" : "—"],
          ["ATR SL Mult", lim.atr_sl_multiplier ?? "—"],
          ["Min Score", lim.min_signal_score ?? "—"],
          ["Chop ADX", lim.chop_adx_threshold ?? "—"],
          ["Cooldown", lim.trade_cooldown_secs != null ? lim.trade_cooldown_secs + "s" : "—"],
          ["Max Trades/Day", lim.max_trades_per_day ?? "—"],
          ["Max Positions", lim.max_open_positions ?? "—"],
          ["Max Daily Loss", lim.max_daily_loss_pct != null ? lim.max_daily_loss_pct + "%" : "—"],
          ["AI Calls/Hour", lim.max_ai_calls_per_hour ?? "—"],
        ];
        items.forEach(([k, v]) => {
          const div = document.createElement("div");
          div.className = "rl-item";
          div.innerHTML = `<span class="rl-key">${k}</span><span class="rl-val">${v}</span>`;
          grid.appendChild(div);
        });
      })
      .catch(() => {});
  }

  document.getElementById("settings-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const feedback = document.getElementById("settings-feedback");

    // Collect only filled-in fields
    const fields = [
      { id: "s-balance",   key: "account_balance_usd" },
      { id: "s-risk",      key: "risk_per_trade_pct" },
      { id: "s-sl",        key: "default_stop_loss_pct" },
      { id: "s-tp",        key: "default_take_profit_pct" },
      { id: "s-min-score", key: "min_signal_score" },
      { id: "s-chop-adx",  key: "chop_adx_threshold" },
      { id: "s-atr-mult",  key: "atr_sl_multiplier" },
      { id: "s-cooldown",  key: "trade_cooldown_secs" },
    ];
    const body = {};
    fields.forEach(({ id, key }) => {
      const val = document.getElementById(id).value.trim();
      if (val !== "") body[key] = Number(val);
    });

    if (Object.keys(body).length === 0) {
      showSettingsFeedback("No changes to save.", "err");
      return;
    }

    const btn = document.getElementById("save-settings-btn");
    btn.disabled = true;
    btn.textContent = "Saving…";

    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.success) {
          const keys = Object.keys(data.updated || {}).join(", ");
          showSettingsFeedback(`✅ Saved: ${keys}`, "ok");
          loadCurrentConfig();
          refreshHeaderStatus();
        } else {
          const errs = (data.errors || [data.error || "Unknown error"]).join("; ");
          showSettingsFeedback(`❌ ${errs}`, "err");
        }
      })
      .catch(() => showSettingsFeedback("❌ Save failed — check connection.", "err"))
      .finally(() => {
        btn.disabled = false;
        btn.textContent = "💾 Save Settings";
      });
  });

  function showSettingsFeedback(msg, type) {
    const el = document.getElementById("settings-feedback");
    el.textContent = msg;
    el.className = "settings-feedback " + type;
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 5000);
  }

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------
  function formatPrice(price) {
    const n = Number(price);
    if (isNaN(n)) return "—";
    if (n >= 100) return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return "$" + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }

  function scoreColor(score) {
    if (score >= 65) return "#3fb950";
    if (score >= 45) return "#d29922";
    return "#f85149";
  }

  function actionClass(action) {
    const a = action.toLowerCase();
    if (a === "buy")  return "buy";
    if (a === "sell") return "sell";
    if (a.includes("strong buy"))  return "strong-buy";
    if (a.includes("strong sell")) return "strong-sell";
    return "hold";
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setInput(id, value) {
    const el = document.getElementById(id);
    if (el && value != null) el.value = value;
  }

  function checkStatus(response) {
    return response.json().then((data) => {
      if (!data.success) throw new Error(data.error || "Unknown error");
      return data;
    });
  }

  function showError(msg) {
    errorMsg.textContent = msg;
    errorMsg.classList.remove("hidden");
  }

  function hideError() {
    errorMsg.classList.add("hidden");
  }

  function showLoading() {
    loading.classList.remove("hidden");
    results.classList.add("hidden");
  }

  function hideLoading() {
    loading.classList.add("hidden");
  }

  function showResults() {
    hideLoading();
    results.classList.remove("hidden");
  }
})();

