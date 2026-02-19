"""기술적 분석 모듈 - ta 라이브러리 기반 기술적 지표 계산 및 시그널 판정"""

import yfinance as yf
import ta
import pandas as pd


def _signal(value, buy_threshold, sell_threshold):
    """값 기반 매수/매도/중립 시그널 판정"""
    if value is None:
        return "중립"
    if value <= buy_threshold:
        return "매수"
    elif value >= sell_threshold:
        return "매도"
    return "중립"


def _safe_round(value, digits=2):
    if value is None or pd.isna(value):
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def analyze_technical(ticker_symbol: str, period: str = "6mo") -> dict:
    """
    주어진 티커의 기술적 분석을 수행한다.

    Args:
        ticker_symbol: 주식 티커 심볼
        period: 데이터 조회 기간 (기본 6개월)

    Returns:
        dict: RSI, MACD, 볼린저밴드, 이동평균선, 종합 시그널 포함
    """
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period)

    if df.empty:
        raise ValueError(f"티커 '{ticker_symbol}'의 가격 데이터를 가져올 수 없습니다.")

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    current_price = float(close.iloc[-1])

    signals = []

    # --- RSI (14일) ---
    rsi_indicator = ta.momentum.RSIIndicator(close=close, window=14)
    rsi_value = _safe_round(rsi_indicator.rsi().iloc[-1])

    rsi_signal = _signal(rsi_value, 30, 70)
    signals.append(rsi_signal)

    rsi = {
        "value": rsi_value,
        "signal": rsi_signal,
        "interpretation": (
            "과매도 구간 (반등 가능성)" if rsi_value and rsi_value < 30
            else "과매수 구간 (조정 가능성)" if rsi_value and rsi_value > 70
            else "중립 구간"
        ),
    }

    # --- MACD ---
    macd_indicator = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line = _safe_round(macd_indicator.macd().iloc[-1])
    signal_line = _safe_round(macd_indicator.macd_signal().iloc[-1])
    histogram = _safe_round(macd_indicator.macd_diff().iloc[-1])

    # 크로스오버 감지
    macd_series = macd_indicator.macd()
    signal_series = macd_indicator.macd_signal()
    crossover = "없음"
    if len(macd_series) >= 2 and len(signal_series) >= 2:
        prev_diff = float(macd_series.iloc[-2]) - float(signal_series.iloc[-2])
        curr_diff = float(macd_series.iloc[-1]) - float(signal_series.iloc[-1])
        if prev_diff < 0 and curr_diff >= 0:
            crossover = "골든크로스 (매수 시그널)"
        elif prev_diff > 0 and curr_diff <= 0:
            crossover = "데드크로스 (매도 시그널)"

    macd_signal = "매수" if histogram and histogram > 0 else "매도" if histogram and histogram < 0 else "중립"
    signals.append(macd_signal)

    macd = {
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": histogram,
        "crossover": crossover,
        "signal": macd_signal,
    }

    # --- 볼린저 밴드 ---
    bb_indicator = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    bb_upper = _safe_round(bb_indicator.bollinger_hband().iloc[-1])
    bb_middle = _safe_round(bb_indicator.bollinger_mavg().iloc[-1])
    bb_lower = _safe_round(bb_indicator.bollinger_lband().iloc[-1])
    bb_pband = _safe_round(bb_indicator.bollinger_pband().iloc[-1])  # %B
    bb_wband = _safe_round(bb_indicator.bollinger_wband().iloc[-1])  # 밴드폭

    bb_signal = _signal(bb_pband, 0.0, 1.0)
    signals.append(bb_signal)

    bollinger_bands = {
        "upper_band": bb_upper,
        "middle_band": bb_middle,
        "lower_band": bb_lower,
        "percent_b": bb_pband,
        "bandwidth": bb_wband,
        "signal": bb_signal,
        "interpretation": (
            "하단 밴드 이탈 (과매도)" if bb_pband is not None and bb_pband < 0
            else "상단 밴드 이탈 (과매수)" if bb_pband is not None and bb_pband > 1
            else "밴드 내 정상 범위"
        ),
    }

    # --- 이동평균선 ---
    sma_20 = _safe_round(ta.trend.SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
    sma_50 = _safe_round(ta.trend.SMAIndicator(close=close, window=50).sma_indicator().iloc[-1]) if len(close) >= 50 else None
    sma_200 = _safe_round(ta.trend.SMAIndicator(close=close, window=200).sma_indicator().iloc[-1]) if len(close) >= 200 else None
    ema_12 = _safe_round(ta.trend.EMAIndicator(close=close, window=12).ema_indicator().iloc[-1])
    ema_26 = _safe_round(ta.trend.EMAIndicator(close=close, window=26).ema_indicator().iloc[-1])

    # 골든크로스/데드크로스 감지 (SMA 50 vs SMA 200)
    ma_crossover = "N/A (데이터 부족)"
    if sma_50 is not None and sma_200 is not None:
        sma50_series = ta.trend.SMAIndicator(close=close, window=50).sma_indicator()
        sma200_series = ta.trend.SMAIndicator(close=close, window=200).sma_indicator()
        if len(sma50_series.dropna()) >= 2 and len(sma200_series.dropna()) >= 2:
            prev_diff = float(sma50_series.dropna().iloc[-2]) - float(sma200_series.dropna().iloc[-2])
            curr_diff = float(sma50_series.dropna().iloc[-1]) - float(sma200_series.dropna().iloc[-1])
            if prev_diff < 0 and curr_diff >= 0:
                ma_crossover = "골든크로스 (장기 매수 시그널)"
            elif prev_diff > 0 and curr_diff <= 0:
                ma_crossover = "데드크로스 (장기 매도 시그널)"
            else:
                ma_crossover = "크로스 없음"

    # 이동평균 배열 시그널
    ma_signal = "중립"
    if sma_20 and sma_50:
        if current_price > sma_20 > sma_50:
            ma_signal = "매수"
        elif current_price < sma_20 < sma_50:
            ma_signal = "매도"
    signals.append(ma_signal)

    moving_averages = {
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "price_vs_sma20": _safe_round((current_price / sma_20 - 1) * 100) if sma_20 else None,
        "price_vs_sma50": _safe_round((current_price / sma_50 - 1) * 100) if sma_50 else None,
        "price_vs_sma200": _safe_round((current_price / sma_200 - 1) * 100) if sma_200 else None,
        "ma_crossover": ma_crossover,
        "signal": ma_signal,
    }

    # --- 종합 시그널 ---
    score_map = {"매수": 1, "중립": 0, "매도": -1}
    total_score = sum(score_map.get(s, 0) for s in signals)
    max_score = len(signals)

    if total_score >= 2:
        overall_signal = "매수"
    elif total_score <= -2:
        overall_signal = "매도"
    else:
        overall_signal = "중립"

    summary = {
        "current_price": _safe_round(current_price),
        "signals": {
            "rsi": rsi_signal,
            "macd": macd_signal,
            "bollinger_bands": bb_signal,
            "moving_averages": ma_signal,
        },
        "score": total_score,
        "max_score": max_score,
        "overall_signal": overall_signal,
    }

    return {
        "rsi": rsi,
        "macd": macd,
        "bollinger_bands": bollinger_bands,
        "moving_averages": moving_averages,
        "summary": summary,
    }
