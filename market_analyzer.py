import numpy as np
import pandas as pd
import yfinance as yf
import ta

from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier


def fetch_market_data(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Download OHLCV data from Yahoo Finance."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    df.dropna(inplace=True)
    return df


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute and attach all technical indicators to the dataframe."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # Trend indicators
    df["ema_9"] = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    df["ema_21"] = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    df["ema_50"] = ta.trend.EMAIndicator(close, window=50).ema_indicator()

    macd_obj = ta.trend.MACD(close)
    df["macd"] = macd_obj.macd()
    df["macd_diff"] = macd_obj.macd_diff()

    df["adx"] = ta.trend.ADXIndicator(high, low, close).adx()

    # Momentum indicators
    df["rsi"] = ta.momentum.RSIIndicator(close).rsi()
    df["stoch_k"] = ta.momentum.StochasticOscillator(high, low, close).stoch()
    df["williams_r"] = ta.momentum.WilliamsRIndicator(high, low, close).williams_r()

    # Volatility indicators
    df["atr"] = ta.volatility.AverageTrueRange(high, low, close).average_true_range()
    bb = ta.volatility.BollingerBands(close)
    df["bb_width"] = bb.bollinger_wband()

    # Volume indicators
    df["vwap"] = ta.volume.VolumeWeightedAveragePrice(high, low, close, volume).volume_weighted_average_price()
    df["obv"] = ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume()

    # Returns
    df["returns_1d"] = close.pct_change(1)
    df["returns_5d"] = close.pct_change(5)

    # Volume ratio (current vs 20-day average)
    df["vol_ratio"] = volume / volume.rolling(20).mean()

    df.dropna(inplace=True)
    return df


def build_prediction_model(df: pd.DataFrame) -> dict:
    """
    Train an XGBoost classifier with TimeSeriesSplit CV.

    Returns:
        direction    - 'LONG' or 'SHORT'
        confidence   - float percentage
        cv_accuracy  - float percentage (mean of CV folds)
        features     - dict of latest feature values
    """
    feature_cols = [
        "ema_9", "ema_21", "ema_50",
        "macd", "macd_diff", "adx",
        "rsi", "stoch_k", "williams_r",
        "atr", "bb_width",
        "vwap", "obv",
        "returns_1d", "returns_5d", "vol_ratio",
    ]

    # Target: 1 if next‑day return is positive, else 0
    df = df.copy()
    df["target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)
    df.dropna(subset=feature_cols + ["target"], inplace=True)

    X = df[feature_cols].values
    y = df["target"].values

    model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="logloss",
        verbosity=0,
    )

    tscv = TimeSeriesSplit(n_splits=5)
    cv_scores = []
    for train_idx, val_idx in tscv.split(X):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        model.fit(X_train, y_train)
        acc = (model.predict(X_val) == y_val).mean()
        cv_scores.append(acc)

    # Refit on all data for final prediction
    model.fit(X, y)

    latest_features = df[feature_cols].iloc[-1].to_dict()
    X_latest = np.array([list(latest_features.values())])
    proba = model.predict_proba(X_latest)[0]
    long_prob = float(proba[1])

    direction = "LONG" if long_prob >= 0.5 else "SHORT"
    confidence = long_prob * 100 if direction == "LONG" else (1 - long_prob) * 100

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "cv_accuracy": round(float(np.mean(cv_scores)) * 100, 2),
        "features": {k: round(float(v), 4) for k, v in latest_features.items()},
    }


def full_analysis(symbol: str) -> dict:
    """
    Fetch data, compute indicators, run ML model, return combined dict.

    Returns:
        symbol, price, prediction (dict), indicators (dict)
    """
    df = fetch_market_data(symbol)
    df = add_technical_indicators(df)
    prediction = build_prediction_model(df)

    latest = df.iloc[-1]
    ema_trend = (
        "BULLISH" if latest["ema_9"] > latest["ema_21"] > latest["ema_50"]
        else "BEARISH" if latest["ema_9"] < latest["ema_21"] < latest["ema_50"]
        else "MIXED"
    )

    indicators = {
        "rsi": round(float(latest["rsi"]), 2),
        "macd": round(float(latest["macd_diff"]), 4),
        "adx": round(float(latest["adx"]), 2),
        "atr": round(float(latest["atr"]), 4),
        "ema_trend": ema_trend,
    }

    return {
        "symbol": symbol,
        "price": round(float(latest["Close"]), 4),
        "prediction": prediction,
        "indicators": indicators,
    }
