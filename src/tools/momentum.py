"""모멘텀/상대강도 분석 도구 — 메가트렌드 추세추종의 핵심 입력.

절대수익률(1/3/6/12M), 벤치마크 대비 상대강도(RS), 52주 신고가 근접도/돌파,
거래량 급증, 200일선 상회 비율을 산출하고 momentum_score(0~100)로 합성한다.

"되돌림에서 사라"가 아니라 "강한 종목이 더 강해진다(신고가 돌파)"를 측정한다.
"""

import pandas as pd
import yfinance as yf


def _ret_pct(series, days):
    if series is None or len(series) <= days:
        return None
    base = float(series.iloc[-1 - days])
    if base == 0:
        return None
    return round((float(series.iloc[-1]) / base - 1) * 100, 2)


def _last_bar_status(index) -> str:
    """마지막 봉이 당일(미완성 가능) 봉인지 판정.

    장중 실행(미국 주식 KST 밤, 한국 주식 KST 낮, 크립토 24/7 UTC)이면 마지막 봉의
    거래량이 부분 누적이라 완성일 평균과 비교하면 과소평가된다 — partial이면
    거래량·돌파 판정은 직전 완성봉 기준으로 수행한다.
    """
    try:
        last = index[-1]
        now = pd.Timestamp.now(tz=getattr(last, "tzinfo", None))
        return "partial" if last.date() == now.date() else "complete"
    except Exception:
        return "unknown"


def analyze_momentum(ticker_symbol: str, benchmarks=("SPY", "QQQ"), period: str = "1y") -> dict:
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period)
    if df.empty or len(df) < 30:
        raise ValueError(f"티커 '{ticker_symbol}'의 가격 데이터가 부족합니다(모멘텀 분석 최소 30거래일).")

    close = df["Close"]
    vol = df["Volume"]
    cur = float(close.iloc[-1])
    errors = []

    # 마지막 봉이 당일 미완성이면 거래량·돌파 판정은 직전 완성봉 기준 (실행 시각 비결정성 제거)
    bar_status = _last_bar_status(df.index)
    if bar_status == "partial" and len(close) >= 2:
        eff_close, eff_vol = close.iloc[:-1], vol.iloc[:-1]
    else:
        eff_close, eff_vol = close, vol

    data_span_days = int(len(close))  # 가용 거래일(봉) 수 — 신규 상장 식별용
    span_calendar_days = int((close.index[-1] - close.index[0]).days)

    returns = {
        "1m": _ret_pct(close, 21),
        "3m": _ret_pct(close, 63),
        "6m": _ret_pct(close, 126),
        # 12M 오라벨 방지: 데이터가 1년치(252봉 또는 달력 ~350일) 미만이면 짧은 기간 수익률을 12M로 표기하지 않음
        "12m": _ret_pct(close, min(252, len(close) - 1)) if (len(close) - 1 >= 252 or span_calendar_days >= 350) else None,
    }

    # 52주 고점/저점 위치
    high_52w = float(close.max())
    low_52w = float(close.min())
    pct_from_high = round((cur / high_52w - 1) * 100, 2) if high_52w else None
    pct_from_low = round((cur / low_52w - 1) * 100, 2) if low_52w else None

    # 거래량 급증 (완성봉 기준: 마지막 완성봉 vs 20일 평균)
    vol_20 = float(eff_vol.tail(20).mean()) if len(eff_vol) >= 20 else None
    vol_surge = round(float(eff_vol.iloc[-1]) / vol_20, 2) if vol_20 and vol_20 > 0 else None

    # 신고가 돌파 확인: 종가가 직전 고점 경신 AND 당일 양방향 AND 거래량 동반 (완성봉 기준)
    # — 고점 부근 대량 매도일(분산일)을 돌파로 오판하지 않도록 방향·경신을 함께 확인
    eff_cur = float(eff_close.iloc[-1])
    prior_high = float(eff_close.iloc[:-1].max()) if len(eff_close) >= 2 else None
    new_high = bool(prior_high is not None and eff_cur >= prior_high)
    up_day = bool(len(eff_close) >= 2 and eff_cur > float(eff_close.iloc[-2]))
    breakout_buy = bool(new_high and up_day and vol_surge and vol_surge >= 1.3)
    # 고점 -3% 이내 '근접'만 한 경우 (돌파 미확인) — 별도 관찰 신호
    breakout_watch = bool(not breakout_buy and pct_from_high is not None and pct_from_high >= -3)

    # 200일선 상회 비율 + 현재 상회 여부
    pct_days_above_200 = None
    above_200_now = None
    if len(close) >= 200:
        sma200 = close.rolling(200).mean().dropna()
        if len(sma200) > 0:
            aligned = close.loc[sma200.index]
            pct_days_above_200 = round(float((aligned > sma200).mean()) * 100, 1)
            above_200_now = bool(cur > float(sma200.iloc[-1]))

    # 상대강도(RS): 3개월 초과수익(%p) vs 벤치마크 — 실패는 errors에 기록 (조용한 강등 방지)
    stock_3m = returns["3m"]
    relative_strength = {}
    for b in benchmarks:
        try:
            bclose = yf.Ticker(b).history(period=period)["Close"]
            b3m = _ret_pct(bclose, 63)
            if b3m is None:
                errors.append(f"벤치마크 {b}: 3M 수익률 산출 불가(빈 데이터 또는 기간 부족)")
            elif stock_3m is not None:
                relative_strength[b] = {
                    "excess_return_3m_pct": round(stock_3m - b3m, 2),
                    "outperforming": stock_3m > b3m,
                }
        except Exception as e:
            errors.append(f"벤치마크 {b}: {type(e).__name__}: {e}")
    spy_rs = relative_strength.get("SPY", {}).get("excess_return_3m_pct")
    rs_available = spy_rs is not None  # False면 RS 컴포넌트는 score에서 제외(재정규화)

    # 숏 포지셔닝: 유통주식 대비 공매도 비율(%) — 돌파의 스퀴즈 연료/과밀 확인용 (실패 시 null)
    short_pct_float = None
    try:
        spf = (ticker.info or {}).get("shortPercentOfFloat")
        if spf is not None:
            short_pct_float = round(float(spf) * 100, 2)  # yfinance는 분수(0~1)로 반환
    except Exception as e:
        errors.append(f"short_pct_float: {type(e).__name__}: {e}")

    # --- momentum_score (0~100 합성) ---
    # 결측 컴포넌트(벤치마크 실패·신규 상장 데이터 부족)는 0점 처리하지 않고
    # 가용 컴포넌트 만점 기준으로 재정규화 — 신규 주도주가 구조적으로 '약함' 판정되는 것을 방지
    score = 0.0
    available_max = 0.0
    # 3개월 절대수익 (최대 25점): +30% 이상이면 만점
    if stock_3m is not None:
        available_max += 25
        score += max(0.0, min(stock_3m / 30.0, 1.0)) * 25
    # SPY 대비 상대강도 (최대 25점): +20%p 초과수익이면 만점
    if spy_rs is not None:
        available_max += 25
        score += max(0.0, min(spy_rs / 20.0, 1.0)) * 25
    # 52주 고점 근접 (최대 25점): 고점이면 만점, -25% 이하면 0
    if pct_from_high is not None:
        available_max += 25
        score += max(0.0, min((pct_from_high + 25) / 25.0, 1.0)) * 25
    # 200일선 상회 (10점) — 200봉 미만이면 미가용(제외)
    if above_200_now is not None:
        available_max += 10
        if above_200_now:
            score += 10
    # 돌파 셋업 (15점) — 거래량 비교 가능할 때만 가용
    if vol_surge is not None:
        available_max += 15
        if breakout_buy:
            score += 15
    momentum_score = round(score / available_max * 100, 1) if available_max > 0 else None

    ms = momentum_score if momentum_score is not None else 0.0
    rating = "⚪ 판정불가" if momentum_score is None else "🟢 강함" if ms >= 70 else "🟡 보통" if ms >= 40 else "🔴 약함"

    return {
        "ticker": ticker_symbol,
        "current_price": round(cur, 2),
        "bar_status": bar_status,  # partial=당일 미완성 봉 → 거래량·돌파 판정은 직전 완성봉 기준
        "data_span_days": data_span_days,
        "returns_pct": returns,
        "high_52w": round(high_52w, 2),
        "low_52w": round(low_52w, 2),
        "pct_from_52w_high": pct_from_high,
        "pct_from_52w_low": pct_from_low,
        "volume_surge_x": vol_surge,
        "breakout_buy_setup": breakout_buy,
        "breakout_watch": breakout_watch,  # 고점 -3% 이내 근접 (돌파 미확인 — 확인 대기)
        "pct_days_above_200ma": pct_days_above_200,
        "above_200ma_now": above_200_now,
        "relative_strength": relative_strength,
        "rs_available": rs_available,
        "short_pct_float": short_pct_float,  # 유통주식 대비 공매도 % (실패/미제공 시 null)
        "momentum_score": momentum_score,
        "score_available_max": round(available_max, 1),  # 100 미만이면 결측 컴포넌트 제외 후 재정규화된 점수
        "score_renormalized": available_max < 100,
        "rating": rating,
        "interpretation": (
            "신고가 돌파 확인(종가 경신 + 양봉 + 거래량 동반) — 추세추종 진입/피라미딩 적합" if breakout_buy
            else "52주 고점 -3% 이내 근접 — 돌파(신고가 경신+거래량) 확인 후 진입" if breakout_watch
            else "강한 상대강도, 추세 유효" if ms >= 70
            else "모멘텀 보통 — 돌파 확인 후 진입" if ms >= 40
            else "모멘텀 약함 — 추세 회복 전 관망"
        ),
        "errors": errors,
    }
