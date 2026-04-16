/* =====================================================================
   AI Trading Bot Dashboard — Client JS
   ===================================================================== */

(function () {
  "use strict";

  const symbolInput = document.getElementById("symbol-input");
  const analyzeBtn = document.getElementById("analyze-btn");
  const recommendBtn = document.getElementById("recommend-btn");
  const errorMsg = document.getElementById("error-msg");
  const loading = document.getElementById("loading");
  const results = document.getElementById("results");
  const recommendationCard = document.getElementById("recommendation-card");
  const watchlistChips = document.getElementById("watchlist-chips");

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
          runSmartScore(sym);
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
    runSmartScore(sym);
  });

  recommendBtn.addEventListener("click", () => {
    const sym = symbolInput.value.trim().toUpperCase();
    if (!sym) return showError("Please enter a symbol.");
    runRecommendation(sym);
  });

  symbolInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeBtn.click();
  });

  // ------------------------------------------------------------------
  // Smart Score flow  (/api/score/<symbol>  — no OpenAI needed)
  // ------------------------------------------------------------------
  function runSmartScore(symbol) {
    showLoading();
    hideError();
    recommendationCard.classList.add("hidden");

    fetch(`/api/score/${encodeURIComponent(symbol)}`)
      .then(checkStatus)
      .then((data) => {
        renderScore(data);
        showResults();
      })
      .catch((err) => {
        showError(err.message || "Analysis failed.");
        hideLoading();
      });
  }

  // ------------------------------------------------------------------
  // Recommendation flow  (/recommend/<symbol>  — needs OpenAI)
  // ------------------------------------------------------------------
  function runRecommendation(symbol) {
    showLoading();
    hideError();
    recommendationCard.classList.add("hidden");

    // First get smart score to populate cards, then get AI recommendation
    fetch(`/api/score/${encodeURIComponent(symbol)}`)
      .then(checkStatus)
      .then((data) => {
        renderScore(data);
        showResults();
        return fetch(`/recommend/${encodeURIComponent(symbol)}`);
      })
      .then(checkStatus)
      .then((data) => {
        document.getElementById("res-recommendation").textContent =
          data.recommendation;
        recommendationCard.classList.remove("hidden");
        hideLoading();
      })
      .catch((err) => {
        showError(err.message || "Recommendation failed.");
        hideLoading();
      });
  }

  // ------------------------------------------------------------------
  // Render smart score data
  // ------------------------------------------------------------------
  function renderScore(data) {
    const pred = data.prediction;
    const ind  = data.indicators;

    // Hero — symbol, price, timestamp
    setText("res-symbol", data.symbol);
    setText("res-price", formatPrice(data.price));
    const now = new Date();
    setText("res-updated", `Last updated: ${now.toLocaleTimeString()}`);

    // Smart Score gauge
    const score = data.smart_score;
    const scoreEl = document.getElementById("res-score");
    scoreEl.textContent = score;
    // Arc: full circumference ≈ 172.79 (for the half-circle path)
    const arcLen = 172.79;
    const offset = arcLen - (score / 100) * arcLen;
    const arc = document.getElementById("gauge-arc");
    if (arc) {
      arc.setAttribute("stroke-dashoffset", offset.toFixed(2));
      arc.setAttribute("stroke", scoreColor(score));
    }
    scoreEl.style.color = scoreColor(score);

    // Action badge
    const actionEl = document.getElementById("res-action");
    const actionText = data.action || "HOLD 🟡";
    actionEl.textContent = actionText;
    actionEl.className = "action-badge " + actionClass(actionText);

    // Signals list
    const signalsEl = document.getElementById("res-signals");
    signalsEl.innerHTML = "";
    (data.signals || []).forEach((sig) => {
      const div = document.createElement("div");
      div.className = "signal-item";
      div.textContent = sig;
      signalsEl.appendChild(div);
    });

    // Market / Prediction
    const dirEl = document.getElementById("res-direction");
    dirEl.textContent = pred.direction;
    dirEl.className = `stat-value ${pred.direction === "LONG" ? "bull" : "bear"}`;
    setText("res-confidence", `${pred.confidence}%`);
    setText("res-accuracy", `${pred.cv_accuracy}%`);

    // Indicators
    colorRsi("res-rsi", ind.rsi);
    setColored("res-macd", ind.macd, ind.macd >= 0 ? "bull" : "bear");
    setText("res-adx", ind.adx);
    setText("res-atr", ind.atr);
    setColored(
      "res-ema-trend",
      ind.ema_trend,
      ind.ema_trend === "BULLISH" ? "bull" : ind.ema_trend === "BEARISH" ? "bear" : "neutral"
    );

    // News
    const impact = data.news_impact;
    const impactEl = document.getElementById("res-impact");
    impactEl.textContent = impact;
    impactEl.className = `stat-value ${
      impact === "HIGH" ? "bear" : impact === "MEDIUM" ? "neutral" : "bull"
    }`;
    setText("res-impact-score", Number(data.news_score).toFixed(2));
    setText("res-articles", data.article_count != null ? data.article_count : "—");
    setText("res-hi-events", data.high_impact_count != null ? data.high_impact_count : "—");
  }

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------
  function formatPrice(price) {
    return "$" + Number(price).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function scoreColor(score) {
    if (score >= 60) return "#3fb950";   // green
    if (score >= 45) return "#d29922";   // yellow
    return "#f85149";                    // red
  }

  function actionClass(action) {
    const a = action.toLowerCase();
    if (a.includes("strong buy"))  return "strong-buy";
    if (a.includes("buy"))         return "buy";
    if (a.includes("strong sell")) return "strong-sell";
    if (a.includes("sell"))        return "sell";
    return "hold";
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setColored(id, value, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.className = `stat-value ${cls}`;
  }

  function colorRsi(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.className = `stat-value ${
      value >= 70 ? "bear" : value <= 30 ? "bull" : "neutral"
    }`;
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
