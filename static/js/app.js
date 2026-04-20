/* =====================================================================
   AI Trading Bot — Client JS (v2)
   ===================================================================== */

(function () {
  "use strict";

  const symbolInput   = document.getElementById("symbol-input");
  const analyzeBtn    = document.getElementById("analyze-btn");
  const recommendBtn  = document.getElementById("recommend-btn");
  const errorMsg      = document.getElementById("error-msg");
  const loading       = document.getElementById("loading");
  const results       = document.getElementById("results");
  const watchlistChips= document.getElementById("watchlist-chips");
  const resRec        = document.getElementById("res-recommendation");

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
    const sym = symbolInput.value.trim().toUpperCase();
    if (!sym) return showError("Please enter a symbol.");
    runAnalysis(sym);
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
  // Main analysis flow — calls /api/recommendation/<symbol>
  // which returns BUY/SELL/HOLD + allocation + SL/TP + reasons
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
  // Render unified signal
  // ------------------------------------------------------------------
  function renderSignal(data) {
    const action   = (data.action || "HOLD").toUpperCase();
    const score    = data.score  || 0;
    const price    = data.price  || 0;
    const risk     = data.risk   || {};
    const reasons  = data.reasons || [];
    const ind      = data.indicators || {};

    // ── Symbol & Price ──
    setText("res-symbol", data.symbol || "—");
    setText("res-price", formatPrice(price));
    const now = new Date();
    setText("res-updated", `Updated: ${now.toLocaleTimeString()}`);

    // ── Action badge ──
    const actionEl = document.getElementById("res-action");
    actionEl.textContent = action;
    actionEl.className   = "action-badge " + actionClass(action);

    // Action sub-label
    const subLabel = score >= 80 ? "Strong signal" : score >= 65 ? "Moderate signal" : "Weak / caution";
    setText("res-action-sub", `Score: ${score}/100 · ${subLabel}`);

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

