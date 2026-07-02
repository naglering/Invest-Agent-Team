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


def _last_bar_status(index) -> str:
    """마지막 봉이 당일(미완성 가능) 봉인지 판정.

    장중 실행이면 마지막 봉의 거래량이 부분 누적이라 완성일 평균과 비교하면
    과소평가된다 — partial이면 거래량 비교는 직전 완성봉 기준으로 수행한다.
    """
    try:
        last = index[-1]
        now = pd.Timestamp.now(tz=getattr(last, "tzinfo", None))
        return "partial" if last.date() == now.date() else "complete"
    except Exception:
        return "unknown"


def analyze_technical(ticker_symbol: str, period: str = "1y") -> dict:
    """
    주어진 티커의 기술적 분석을 수행한다.

    Args:
        ticker_symbol: 주식 티커 심볼
        period: 데이터 조회 기간 (기본 1년 — SMA200·장기 골든크로스·52주 레벨 산출에 필요)

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

    # --- RSI (14일, Signal 7일) - SMA 기반 + Wilder 기반 둘 다 계산 ---
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # SMA 기반 RSI (한국 증권사 표준)
    avg_gain_sma = gain.rolling(window=14).mean()
    avg_loss_sma = loss.rolling(window=14).mean()
    rs_sma = avg_gain_sma / avg_loss_sma
    rsi_sma_series = 100 - (100 / (1 + rs_sma))
    rsi_sma_value = _safe_round(rsi_sma_series.iloc[-1])
    rsi_sma_signal_line = _safe_round(rsi_sma_series.rolling(window=7).mean().iloc[-1])

    # Wilder's Smoothing RSI (글로벌 표준)
    rsi_wilder_indicator = ta.momentum.RSIIndicator(close=close, window=14)
    rsi_wilder_series = rsi_wilder_indicator.rsi()
    rsi_wilder_value = _safe_round(rsi_wilder_series.iloc[-1])
    rsi_wilder_signal_line = _safe_round(rsi_wilder_series.rolling(window=7).mean().iloc[-1])

    # 시그널 판정은 SMA 기반 기준
    rsi_signal = _signal(rsi_sma_value, 30, 70)
    signals.append(rsi_signal)

    # RSI-Signal 크로스오버 감지 (SMA 기반)
    rsi_sma_sig = rsi_sma_series.rolling(window=7).mean()
    rsi_crossover = "없음"
    if len(rsi_sma_series.dropna()) >= 2 and len(rsi_sma_sig.dropna()) >= 2:
        prev_diff = float(rsi_sma_series.dropna().iloc[-2]) - float(rsi_sma_sig.dropna().iloc[-2])
        curr_diff = float(rsi_sma_series.dropna().iloc[-1]) - float(rsi_sma_sig.dropna().iloc[-1])
        if prev_diff < 0 and curr_diff >= 0:
            rsi_crossover = "골든크로스 (RSI가 Signal 상향 돌파)"
        elif prev_diff > 0 and curr_diff <= 0:
            rsi_crossover = "데드크로스 (RSI가 Signal 하향 돌파)"

    rsi = {
        "sma": {
            "value": rsi_sma_value,
            "signal_line": rsi_sma_signal_line,
        },
        "wilder": {
            "value": rsi_wilder_value,
            "signal_line": rsi_wilder_signal_line,
        },
        "crossover": rsi_crossover,
        "signal": rsi_signal,
        "interpretation": (
            "과매도 구간 (반등 가능성)" if rsi_sma_value and rsi_sma_value < 30
            else "과매수 구간 (조정 가능성)" if rsi_sma_value and rsi_sma_value > 70
            else "중립 구간"
        ),
    }

    # --- MACD ---
    macd_indicator = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    macd_line = _safe_round(macd_indicator.macd().iloc[-1])
    signal_line = _safe_round(macd_indicator.macd_signal().iloc[-1])
    # 부호 판정은 원시값 기준 (저가주는 2자리 반올림 시 0.0이 되어 항상 '중립'이 되는 결함 방지)
    _hist_raw = macd_indicator.macd_diff().iloc[-1]
    _hist_raw = None if pd.isna(_hist_raw) else float(_hist_raw)
    histogram = _safe_round(_hist_raw)  # 표시용만 반올림

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

    macd_signal = "매수" if _hist_raw is not None and _hist_raw > 0 else "매도" if _hist_raw is not None and _hist_raw < 0 else "중립"
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

    # --- 거래량 분석 (volume) ---
    # 마지막 봉이 당일 미완성이면 부분 거래량이라 완성일 평균 대비 과소평가 — 직전 완성봉 기준으로 비교
    volume_series = df["Volume"]
    bar_status = _last_bar_status(df.index)
    if bar_status == "partial" and len(volume_series) >= 2:
        eff_vol = volume_series.iloc[:-1]
        volume_today_partial = int(volume_series.iloc[-1])  # 당일 누적(부분) 거래량 — 비교 미사용, 참고용
    else:
        eff_vol = volume_series
        volume_today_partial = None
    vol_10d = _safe_round(float(eff_vol.tail(10).mean()))
    vol_50d = _safe_round(float(eff_vol.tail(50).mean())) if len(eff_vol) >= 50 else None
    vol_ratio = _safe_round(float(eff_vol.iloc[-1]) / vol_10d) if vol_10d and vol_10d > 0 else None
    latest_volume = int(eff_vol.iloc[-1])

    # OBV (On Balance Volume)
    obv_indicator = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume_series)
    obv_series = obv_indicator.on_balance_volume()
    obv_current = _safe_round(float(obv_series.iloc[-1]))
    obv_prev_5d = _safe_round(float(obv_series.iloc[-6])) if len(obv_series) >= 6 else None
    obv_trend = "상승" if obv_current and obv_prev_5d and obv_current > obv_prev_5d else "하락" if obv_current and obv_prev_5d else "N/A"

    # 가격-거래량 정합성 판단 — OBV 추세는 '총 거래량 증감'이 아니라 상승일/하락일 거래량 우위를 뜻함
    price_change_5d = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100 if len(close) >= 6 else None
    if price_change_5d is not None and obv_trend != "N/A":
        if price_change_5d > 0 and obv_trend == "상승":
            volume_confirmation = "정합 (가격 상승 + OBV 상승(매수 거래량 우위) = 강세 확인)"
        elif price_change_5d < 0 and obv_trend == "하락":
            volume_confirmation = "정합 (가격 하락 + OBV 하락(매도 거래량 우위) = 약세 확인)"
        elif price_change_5d > 0 and obv_trend == "하락":
            volume_confirmation = "괴리 (가격 상승 + OBV 하락(매도 거래량 우위) = 상승 약화 경고)"
        else:
            volume_confirmation = "괴리 (가격 하락 + OBV 상승(매수 거래량 우위) = 매집 가능성)"
    else:
        volume_confirmation = "판단 불가"

    vol_signal = "중립"
    if vol_ratio and vol_ratio > 1.5 and price_change_5d and price_change_5d > 0:
        vol_signal = "매수"
    elif vol_ratio and vol_ratio > 1.5 and price_change_5d and price_change_5d < 0:
        vol_signal = "매도"
    signals.append(vol_signal)

    volume = {
        "latest_volume": latest_volume,  # bar_status=partial이면 직전 완성봉 거래량
        "bar_status": bar_status,  # partial=마지막 봉이 당일 미완성 → 거래량 비교는 직전 완성봉 기준
        "volume_today_partial": volume_today_partial,  # 당일 누적(부분) 거래량 (완성봉이면 null)
        "avg_10d": vol_10d,
        "avg_50d": vol_50d,
        "volume_ratio": vol_ratio,
        "obv": obv_current,
        "obv_trend": obv_trend,  # OBV 상승=매수 거래량 우위 (총 거래량 증가 아님)
        "price_volume_confirmation": volume_confirmation,
        "signal": vol_signal,
    }

    # --- 피보나치 되돌림 (fibonacci) ---
    # 레벨은 관측 범위(range) 기준으로 계산하되, '52주' 라벨은 실제 1년치(~240봉 이상) 데이터일 때만 부여
    range_high = float(high.max())
    range_low = float(low.min())
    is_52w_range = len(close) >= 240
    fib_range = range_high - range_low
    fib_levels = {}
    if fib_range > 0:
        for level in [0.236, 0.382, 0.5, 0.618, 0.786]:
            fib_levels[f"{level*100:.1f}%"] = _safe_round(range_high - fib_range * level)

    # 가장 가까운 지지/저항 식별
    nearest_support = None
    nearest_resistance = None
    for label, price_level in sorted(fib_levels.items(), key=lambda x: x[1], reverse=True):
        if price_level and price_level < current_price:
            if nearest_support is None or price_level > nearest_support["price"]:
                nearest_support = {"level": label, "price": price_level}
        elif price_level and price_level > current_price:
            if nearest_resistance is None or price_level < nearest_resistance["price"]:
                nearest_resistance = {"level": label, "price": price_level}

    fibonacci = {
        "high_52w": _safe_round(range_high) if is_52w_range else None,  # 1년치 미만 데이터면 N/A (오라벨 방지)
        "low_52w": _safe_round(range_low) if is_52w_range else None,
        "range_high": _safe_round(range_high),  # 실제 관측 범위 고점 (range_bars 참조)
        "range_low": _safe_round(range_low),
        "range_bars": int(len(close)),  # 관측 봉 수 — 240 미만이면 52주 범위가 아님
        "levels": fib_levels,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
    }

    # --- ADX (Average Directional Index) ---
    adx_indicator = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
    adx_value = _safe_round(float(adx_indicator.adx().iloc[-1]))
    plus_di = _safe_round(float(adx_indicator.adx_pos().iloc[-1]))
    minus_di = _safe_round(float(adx_indicator.adx_neg().iloc[-1]))

    adx_trend_strength = (
        "매우 강한 추세" if adx_value and adx_value > 50
        else "강한 추세" if adx_value and adx_value > 25
        else "약한 추세" if adx_value and adx_value > 20
        else "추세 없음 (횡보)" if adx_value is not None
        else "계산 불가"
    )
    adx_direction = (
        "상승 추세" if plus_di and minus_di and plus_di > minus_di
        else "하락 추세" if plus_di and minus_di
        else "N/A"
    )

    adx_signal = "중립"
    if adx_value and adx_value > 25 and plus_di and minus_di:
        adx_signal = "매수" if plus_di > minus_di else "매도"
    signals.append(adx_signal)

    adx = {
        "adx": adx_value,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "trend_strength": adx_trend_strength,
        "trend_direction": adx_direction,
        "signal": adx_signal,
    }

    # --- 스토캐스틱 (Stochastic Oscillator) ---
    stoch_indicator = ta.momentum.StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    stoch_k = _safe_round(float(stoch_indicator.stoch().iloc[-1]))
    stoch_d = _safe_round(float(stoch_indicator.stoch_signal().iloc[-1]))

    stoch_crossover = "없음"
    stoch_series = stoch_indicator.stoch()
    stoch_sig_series = stoch_indicator.stoch_signal()
    if len(stoch_series.dropna()) >= 2 and len(stoch_sig_series.dropna()) >= 2:
        prev_diff = float(stoch_series.dropna().iloc[-2]) - float(stoch_sig_series.dropna().iloc[-2])
        curr_diff = float(stoch_series.dropna().iloc[-1]) - float(stoch_sig_series.dropna().iloc[-1])
        if prev_diff < 0 and curr_diff >= 0:
            stoch_crossover = "골든크로스 (%K가 %D 상향 돌파)"
        elif prev_diff > 0 and curr_diff <= 0:
            stoch_crossover = "데드크로스 (%K가 %D 하향 돌파)"

    stoch_signal = _signal(stoch_k, 20, 80)
    signals.append(stoch_signal)

    stochastic = {
        "k": stoch_k,
        "d": stoch_d,
        "crossover": stoch_crossover,
        "signal": stoch_signal,
        "interpretation": (
            "과매도 구간 (반등 가능성)" if stoch_k and stoch_k < 20
            else "과매수 구간 (조정 가능성)" if stoch_k and stoch_k > 80
            else "중립 구간"
        ),
    }

    # --- 주간 시그널 (weekly_signals) ---
    weekly_signals = {}
    try:
        weekly_df = ticker.history(period="1y", interval="1wk")
        if not weekly_df.empty and len(weekly_df) >= 14:
            w_close = weekly_df["Close"]
            w_rsi = ta.momentum.RSIIndicator(close=w_close, window=14).rsi()
            w_rsi_val = _safe_round(float(w_rsi.iloc[-1]))

            w_macd = ta.trend.MACD(close=w_close, window_slow=26, window_fast=12, window_sign=9)
            # 부호 판정은 원시값 기준, 표시만 반올림 (일간과 동일 — 저가주 중립 고착 방지)
            _w_hist_raw = w_macd.macd_diff().iloc[-1]
            _w_hist_raw = None if pd.isna(_w_hist_raw) else float(_w_hist_raw)
            w_macd_hist = _safe_round(_w_hist_raw)

            w_sma_20 = _safe_round(float(ta.trend.SMAIndicator(close=w_close, window=20).sma_indicator().iloc[-1])) if len(w_close) >= 20 else None

            weekly_signals = {
                "rsi": w_rsi_val,
                "rsi_signal": _signal(w_rsi_val, 30, 70),
                "macd_histogram": w_macd_hist,
                "macd_signal": "매수" if _w_hist_raw is not None and _w_hist_raw > 0 else "매도" if _w_hist_raw is not None and _w_hist_raw < 0 else "중립",
                "sma_20": w_sma_20,
                "price_vs_sma20": _safe_round((float(w_close.iloc[-1]) / w_sma_20 - 1) * 100) if w_sma_20 else None,
            }
    except Exception:
        pass

    # --- 추세 확인 (정배열 + ADX 강추세 + 상승방향) ---
    # sma_200 미산출(200봉 미만)이면 '통과'가 아니라 '미확인' 처리 — 200일선 붕괴 종목이
    # 추세 확인되어 과매수 매도신호가 매수로 재해석되는 것을 방지
    trend_confirmed = bool(
        sma_20 and sma_50 and current_price > sma_20 > sma_50
        and sma_200 is not None and sma_50 > sma_200
        and adx_value and adx_value > 25
        and plus_di and minus_di and plus_di > minus_di
    )

    # --- 종합 시그널 (추세 확인 시 과매수=강세 재해석) ---
    # 모멘텀 주도주는 강세장에서 RSI 70+·%B>1·스토캐스틱 80+를 수주간 유지하며 상승(밴드워킹).
    # 추세가 확인되면 이 '과매수 매도' 표를 매도로 세지 않는다(추세 추종 관점). 과매도 매수는 유지.
    adj = {
        "rsi": rsi_signal,
        "macd": macd_signal,
        "bollinger_bands": bb_signal,
        "moving_averages": ma_signal,
        "volume": vol_signal,
        "adx": adx_signal,
        "stochastic": stoch_signal,
    }
    reinterpreted = []
    if trend_confirmed:
        if rsi_signal == "매도" and rsi_sma_value and rsi_sma_value >= 70:
            adj["rsi"] = "매수"; reinterpreted.append("RSI 과매수→추세강세")
        if bb_signal == "매도" and bb_pband is not None and bb_pband >= 1.0:
            adj["bollinger_bands"] = "매수"; reinterpreted.append("볼린저 상단돌파(밴드워킹)→강세")
        if stoch_signal == "매도" and stoch_k and stoch_k >= 80:
            adj["stochastic"] = "중립"; reinterpreted.append("스토캐스틱 과매수→추세장 중립화")

    score_map = {"매수": 1, "중립": 0, "매도": -1}
    raw_score = sum(score_map.get(s, 0) for s in signals)
    total_score = sum(score_map.get(s, 0) for s in adj.values())
    max_score = len(adj)

    if total_score >= 3:
        overall_signal = "매수"
    elif total_score <= -3:
        overall_signal = "매도"
    else:
        overall_signal = "중립"

    summary = {
        "current_price": _safe_round(current_price),
        "trend_confirmed": trend_confirmed,
        "signals": adj,
        "raw_signals": {
            "rsi": rsi_signal, "macd": macd_signal, "bollinger_bands": bb_signal,
            "moving_averages": ma_signal, "volume": vol_signal, "adx": adx_signal, "stochastic": stoch_signal,
        },
        "reinterpreted": reinterpreted,
        "score": total_score,
        "raw_score": raw_score,
        "max_score": max_score,
        "overall_signal": overall_signal,
        "note": (
            "추세 확인(정배열+ADX>25+상승) 시 과매수 매도신호를 강세로 재해석. raw_score는 재해석 전 점수." if trend_confirmed
            else "SMA200 미산출(데이터 200봉 미만) — trend_confirmed는 통과가 아닌 미확인(False) 처리." if sma_200 is None
            else None
        ),
    }

    return {
        "rsi": rsi,
        "macd": macd,
        "bollinger_bands": bollinger_bands,
        "moving_averages": moving_averages,
        "volume": volume,
        "fibonacci": fibonacci,
        "adx": adx,
        "stochastic": stochastic,
        "weekly_signals": weekly_signals,
        "summary": summary,
    }
