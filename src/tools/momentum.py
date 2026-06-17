"""모멘텀/상대강도 분석 도구 — 메가트렌드 추세추종의 핵심 입력.

절대수익률(1/3/6/12M), 벤치마크 대비 상대강도(RS), 52주 신고가 근접도/돌파,
거래량 급증, 200일선 상회 비율을 산출하고 momentum_score(0~100)로 합성한다.

"되돌림에서 사라"가 아니라 "강한 종목이 더 강해진다(신고가 돌파)"를 측정한다.
"""

import yfinance as yf


def _ret_pct(series, days):
    if series is None or len(series) <= days:
        return None
    base = float(series.iloc[-1 - days])
    if base == 0:
        return None
    return round((float(series.iloc[-1]) / base - 1) * 100, 2)


def analyze_momentum(ticker_symbol: str, benchmarks=("SPY", "QQQ"), period: str = "1y") -> dict:
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period)
    if df.empty or len(df) < 30:
        raise ValueError(f"티커 '{ticker_symbol}'의 가격 데이터가 부족합니다(모멘텀 분석 최소 30거래일).")

    close = df["Close"]
    vol = df["Volume"]
    cur = float(close.iloc[-1])

    returns = {
        "1m": _ret_pct(close, 21),
        "3m": _ret_pct(close, 63),
        "6m": _ret_pct(close, 126),
        "12m": _ret_pct(close, min(252, len(close) - 1)),  # 1y 데이터(~250봉)면 거의 전구간 수익
    }

    # 52주 고점/저점 위치
    high_52w = float(close.max())
    low_52w = float(close.min())
    pct_from_high = round((cur / high_52w - 1) * 100, 2) if high_52w else None
    pct_from_low = round((cur / low_52w - 1) * 100, 2) if low_52w else None

    # 거래량 급증 (최근 vs 20일 평균)
    vol_20 = float(vol.tail(20).mean()) if len(vol) >= 20 else None
    vol_surge = round(float(vol.iloc[-1]) / vol_20, 2) if vol_20 and vol_20 > 0 else None

    # 신고가 돌파 셋업: 52주 고점 -3% 이내 + 거래량 동반
    breakout_buy = bool(pct_from_high is not None and pct_from_high >= -3 and vol_surge and vol_surge >= 1.3)

    # 200일선 상회 비율 + 현재 상회 여부
    pct_days_above_200 = None
    above_200_now = None
    if len(close) >= 200:
        sma200 = close.rolling(200).mean().dropna()
        if len(sma200) > 0:
            aligned = close.loc[sma200.index]
            pct_days_above_200 = round(float((aligned > sma200).mean()) * 100, 1)
            above_200_now = bool(cur > float(sma200.iloc[-1]))

    # 상대강도(RS): 3개월 초과수익(%p) vs 벤치마크
    stock_3m = returns["3m"]
    relative_strength = {}
    for b in benchmarks:
        try:
            bclose = yf.Ticker(b).history(period=period)["Close"]
            b3m = _ret_pct(bclose, 63)
            if stock_3m is not None and b3m is not None:
                relative_strength[b] = {
                    "excess_return_3m_pct": round(stock_3m - b3m, 2),
                    "outperforming": stock_3m > b3m,
                }
        except Exception:
            pass

    # --- momentum_score (0~100 합성) ---
    score = 0.0
    # 3개월 절대수익 (최대 25점): +30% 이상이면 만점
    if stock_3m is not None:
        score += max(0.0, min(stock_3m / 30.0, 1.0)) * 25
    # SPY 대비 상대강도 (최대 25점): +20%p 초과수익이면 만점
    spy_rs = relative_strength.get("SPY", {}).get("excess_return_3m_pct")
    if spy_rs is not None:
        score += max(0.0, min(spy_rs / 20.0, 1.0)) * 25
    # 52주 고점 근접 (최대 25점): 고점이면 만점, -25% 이하면 0
    if pct_from_high is not None:
        score += max(0.0, min((pct_from_high + 25) / 25.0, 1.0)) * 25
    # 200일선 상회 (10점) + 돌파 셋업 (15점)
    if above_200_now:
        score += 10
    if breakout_buy:
        score += 15
    momentum_score = round(score, 1)

    rating = "🟢 강함" if momentum_score >= 70 else "🟡 보통" if momentum_score >= 40 else "🔴 약함"

    return {
        "ticker": ticker_symbol,
        "current_price": round(cur, 2),
        "returns_pct": returns,
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "pct_from_52w_high": pct_from_high,
        "pct_from_52w_low": pct_from_low,
        "volume_surge_x": vol_surge,
        "breakout_buy_setup": breakout_buy,
        "pct_days_above_200ma": pct_days_above_200,
        "above_200ma_now": above_200_now,
        "relative_strength": relative_strength,
        "momentum_score": momentum_score,
        "rating": rating,
        "interpretation": (
            "신고가 돌파 + 거래량 동반 — 추세추종 진입/피라미딩 적합" if breakout_buy
            else "강한 상대강도, 추세 유효" if momentum_score >= 70
            else "모멘텀 보통 — 돌파 확인 후 진입" if momentum_score >= 40
            else "모멘텀 약함 — 추세 회복 전 관망"
        ),
    }
