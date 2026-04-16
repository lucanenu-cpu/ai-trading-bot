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

  recommendBtn.addEventListener("click", () => {
    const sym = symbolInput.value.trim().toUpperCase();
    if (!sym) return showError("Please enter a symbol.");
    runRecommendation(sym);
  });

  symbolInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") analyzeBtn.click();
  });

  // ------------------------------------------------------------------
  // Analysis flow
  // ------------------------------------------------------------------
  function runAnalysis(symbol) {
    showLoading();
    hideError();
    recommendationCard.classList.add("hidden");

    fetch(`/analyze/${encodeURIComponent(symbol)}`)
      .then(checkStatus)
      .then((data) => {
        renderAnalysis(data);
        showResults();
      })
      .catch((err) => {
        showError(err.message || "Analysis failed.");
        hideLoading();
      });
  }

  function runRecommendation(symbol) {
    showLoading();
    hideError();
    recommendationCard.classList.add("hidden");

    // Run analysis first to populate cards, then recommendation
    fetch(`/analyze/${encodeURIComponent(symbol)}`)
      .then(checkStatus)
      .then((data) => {
        renderAnalysis(data);
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
  // Render helpers
  // ------------------------------------------------------------------
  function renderAnalysis(data) {
    const market = data.market;
    const news = data.news;
    const pred = market.prediction;
    const ind = market.indicators;

    setText("res-symbol", data.symbol);
    setText("res-price", `$${market.price}`);

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
    const impactEl = document.getElementById("res-impact");
    impactEl.textContent = news.overall_impact;
    impactEl.className = `stat-value ${
      news.overall_impact === "HIGH"
        ? "bear"
        : news.overall_impact === "MEDIUM"
        ? "neutral"
        : "bull"
    }`;
    setText("res-impact-score", news.impact_score);
    setText("res-articles", news.article_count);
    setText("res-hi-events", news.high_impact_count);
  }

  // ------------------------------------------------------------------
  // Utilities
  // ------------------------------------------------------------------
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
