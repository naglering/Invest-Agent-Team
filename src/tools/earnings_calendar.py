"""실적발표 일정 도구 - 예정된 실적 발표일, 컨센서스 EPS/매출 조회

yfinance의 calendar 및 info 데이터를 활용한다.
"""

import bisect
from datetime import datetime, date, timezone

import yfinance as yf


def _yoy_pct(g):
    """yfinance growth(소수, 0.5=50%)를 % 정수로. None만 제외하고 0.0도 정상 처리.

    yfinance의 earningsGrowth/earningsQuarterlyGrowth는 모두 YoY(전년동기 대비) 기준.
    """
    return round(g * 100, 2) if g is not None else None


def get_earnings(ticker_symbol: str) -> dict:
    """
    주어진 티커의 실적발표 일정 및 컨센서스 추정치를 조회한다.

    Args:
        ticker_symbol: 주식 티커 심볼

    Returns:
        dict: 실적발표 일정, 컨센서스 EPS/매출, 배당 일정
    """
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    # 어떤 조회가 성공/실패했는지 추적 — '이력 없음'과 '조회 실패'를 구분
    # (insider_analysis.py와 동일한 data_status/errors 규약)
    data_status = {}
    errors = []

    calendar = {}
    try:
        calendar = ticker.calendar or {}
        data_status["calendar"] = "ok" if calendar else "empty"
    except Exception as e:
        data_status["calendar"] = "error"
        errors.append(f"calendar: {type(e).__name__}: {e}")

    today = datetime.now(timezone.utc).date()

    # --- 실적발표 일정 ---
    earnings_dates = calendar.get("Earnings Date", [])
    upcoming_earnings = None
    earnings_date_str = None
    days_until_earnings = None

    if earnings_dates:
        # 가장 가까운 미래 날짜 선택
        for ed in earnings_dates:
            if isinstance(ed, date):
                if ed >= today:
                    upcoming_earnings = ed
                    break
        if upcoming_earnings is None and earnings_dates:
            # 모두 과거면 가장 최근 것
            upcoming_earnings = earnings_dates[-1] if isinstance(earnings_dates[-1], date) else None

        if upcoming_earnings:
            earnings_date_str = upcoming_earnings.isoformat()
            days_until_earnings = (upcoming_earnings - today).days

    # info에서 타임스탬프 기반 보완
    if not upcoming_earnings:
        ts_start = info.get("earningsTimestampStart")
        ts_end = info.get("earningsTimestampEnd")
        if ts_start:
            dt = datetime.fromtimestamp(ts_start, tz=timezone.utc)
            earnings_date_str = dt.strftime("%Y-%m-%d")
            days_until_earnings = (dt.date() - today).days
        elif ts_end:
            dt = datetime.fromtimestamp(ts_end, tz=timezone.utc)
            earnings_date_str = dt.strftime("%Y-%m-%d")
            days_until_earnings = (dt.date() - today).days

    is_estimate = info.get("isEarningsDateEstimate", True)

    # --- 컨센서스 추정치 ---
    eps_estimate = calendar.get("Earnings Average")
    eps_high = calendar.get("Earnings High")
    eps_low = calendar.get("Earnings Low")
    revenue_estimate = calendar.get("Revenue Average")
    revenue_high = calendar.get("Revenue High")
    revenue_low = calendar.get("Revenue Low")

    # --- 최근 실적 (info에서) ---
    trailing_eps = info.get("trailingEps")
    forward_eps = info.get("forwardEps")
    earnings_growth = info.get("earningsGrowth")
    quarterly_growth = info.get("earningsQuarterlyGrowth")

    # --- 배당 일정 ---
    dividend_date = calendar.get("Dividend Date")
    ex_dividend_date = calendar.get("Ex-Dividend Date")
    dividend_rate = info.get("dividendRate")
    dividend_yield = info.get("dividendYield")

    # --- 실적발표 콜 ---
    call_ts = info.get("earningsCallTimestampStart")
    earnings_call = None
    if call_ts:
        call_dt = datetime.fromtimestamp(call_ts, tz=timezone.utc)
        earnings_call = call_dt.strftime("%Y-%m-%d %H:%M UTC")

    # --- 실적 서프라이즈 이력 (earnings_history) ---
    earnings_history = []
    ann_timestamps = []  # 발표 후 가격 반응 계산용 (earnings_history와 정렬 동일)
    beat_count = 0   # actual > estimate (일치 meet는 별도 집계)
    meet_count = 0   # actual == estimate
    miss_count = 0   # actual < estimate
    total_history = 0
    try:
        earnings_dates_df = ticker.earnings_dates
        if earnings_dates_df is not None and not earnings_dates_df.empty:
            # 미래 예정 분기(Reported EPS=NaN)를 표본에서 제외한 뒤 실제 발표 8분기만 사용
            reported_df = earnings_dates_df
            if "Reported EPS" in earnings_dates_df.columns:
                reported_df = earnings_dates_df[earnings_dates_df["Reported EPS"].notna()]
            for idx, row in reported_df.head(8).iterrows():
                estimate = row.get("EPS Estimate")
                actual = row.get("Reported EPS")
                surprise_pct = row.get("Surprise(%)")

                record = {
                    "date": str(idx.date()) if hasattr(idx, 'date') else str(idx),
                    "eps_estimate": float(estimate) if estimate is not None and str(estimate) != "nan" else None,
                    "eps_actual": float(actual) if actual is not None and str(actual) != "nan" else None,
                    "surprise_pct": float(surprise_pct) if surprise_pct is not None and str(surprise_pct) != "nan" else None,
                    "result": None,        # beat / meet / miss
                    "gap_t1_pct": None,    # 발표 반응일 종가의 직전 종가 대비 갭(%)
                    "drift_t5_pct": None,  # 반응일 종가 이후 5거래일 드리프트(%)
                }
                if record["eps_estimate"] is not None and record["eps_actual"] is not None:
                    total_history += 1
                    if record["eps_actual"] > record["eps_estimate"]:
                        beat_count += 1
                        record["result"] = "beat"
                    elif record["eps_actual"] == record["eps_estimate"]:
                        meet_count += 1
                        record["result"] = "meet"
                    else:
                        miss_count += 1
                        record["result"] = "miss"
                earnings_history.append(record)
                ann_timestamps.append(idx)
            data_status["earnings_history"] = "ok" if earnings_history else "empty"
        else:
            data_status["earnings_history"] = "empty"
    except Exception as e:
        data_status["earnings_history"] = "error"
        errors.append(f"earnings_dates: {type(e).__name__}: {e}")

    beat_rate = round(beat_count / total_history * 100, 1) if total_history > 0 else None

    # --- 발표 후 가격 반응 (T+1 갭 / T+5 드리프트 / beat-and-fade) ---
    # 'beat 여부'가 아니라 '시장이 beat에 어떻게 반응했나'가 모멘텀 신호:
    # beat인데 T+1 하락(beat-and-fade)은 기대 소진 = 출구 신호.
    beat_and_fade_count = None
    if earnings_history:
        try:
            hist = ticker.history(period="3y", auto_adjust=True)
            if hist is not None and not hist.empty:
                trade_dates = [ts.date() for ts in hist.index]
                closes = hist["Close"].tolist()
                for record, ann_ts in zip(earnings_history, ann_timestamps):
                    try:
                        ann_date = ann_ts.date() if hasattr(ann_ts, "date") else None
                        if ann_date is None:
                            continue
                        # 발표 시각이 정오 이후(AMC)면 반응일은 익거래일, 이전(BMO)이면 당일
                        amc = getattr(ann_ts, "hour", 0) >= 12
                        if amc:
                            r_idx = bisect.bisect_right(trade_dates, ann_date)
                        else:
                            r_idx = bisect.bisect_left(trade_dates, ann_date)
                        if 1 <= r_idx < len(trade_dates) and closes[r_idx - 1]:
                            record["gap_t1_pct"] = round(
                                (closes[r_idx] / closes[r_idx - 1] - 1) * 100, 2)
                            d_idx = r_idx + 5
                            if d_idx < len(trade_dates) and closes[r_idx]:
                                record["drift_t5_pct"] = round(
                                    (closes[d_idx] / closes[r_idx] - 1) * 100, 2)
                    except Exception:
                        continue  # 개별 분기 실패는 null 유지
                beat_and_fade_count = sum(
                    1 for r in earnings_history
                    if r["result"] == "beat" and r["gap_t1_pct"] is not None and r["gap_t1_pct"] < 0
                )
                computed = sum(1 for r in earnings_history if r["gap_t1_pct"] is not None)
                data_status["price_reaction"] = (
                    "ok" if computed == len(earnings_history)
                    else "partial" if computed > 0 else "empty"
                )
            else:
                data_status["price_reaction"] = "empty"
        except Exception as e:
            data_status["price_reaction"] = "error"
            errors.append(f"price_reaction: {type(e).__name__}: {e}")

    # --- 추정치 변동 추세 (estimate_revisions) ---
    estimate_revisions = {}
    revisions_failed = False
    try:
        eps_trend = getattr(ticker, "eps_trend", None)
        if eps_trend is not None and not eps_trend.empty:
            for col in eps_trend.columns:
                col_data = {}
                for idx_name in eps_trend.index:
                    val = eps_trend.loc[idx_name, col]
                    if val is not None and str(val) != "nan":
                        col_data[str(idx_name)] = float(val)
                if col_data:
                    estimate_revisions[str(col)] = col_data
    except Exception as e:
        revisions_failed = True
        errors.append(f"eps_trend: {type(e).__name__}: {e}")

    if not estimate_revisions:
        try:
            eps_revisions = getattr(ticker, "eps_revisions", None)
            if eps_revisions is not None and not eps_revisions.empty:
                for col in eps_revisions.columns:
                    col_data = {}
                    for idx_name in eps_revisions.index:
                        val = eps_revisions.loc[idx_name, col]
                        if val is not None and str(val) != "nan":
                            col_data[str(idx_name)] = float(val)
                    if col_data:
                        estimate_revisions[str(col)] = col_data
        except Exception as e:
            revisions_failed = True
            errors.append(f"eps_revisions: {type(e).__name__}: {e}")

    data_status["estimate_revisions"] = (
        "ok" if estimate_revisions
        else "error" if revisions_failed
        else "empty"
    )

    analyst_count = info.get("numberOfAnalystOpinions")

    return {
        "ticker": ticker_symbol,
        "company_name": info.get("longName") or info.get("shortName", "N/A"),
        "earnings_schedule": {
            "next_earnings_date": earnings_date_str,
            "days_until_earnings": days_until_earnings,
            "is_estimate": is_estimate,
            "earnings_call_time": earnings_call,
            "status": (
                "임박" if days_until_earnings is not None and 0 <= days_until_earnings <= 7
                else "2주 이내" if days_until_earnings is not None and 7 < days_until_earnings <= 14
                else "1개월 이내" if days_until_earnings is not None and 14 < days_until_earnings <= 30
                else "1개월 이상" if days_until_earnings is not None and days_until_earnings > 30
                else "발표 완료" if days_until_earnings is not None and days_until_earnings < 0
                else "미정"
            ),
        },
        "consensus": {
            "eps_estimate": eps_estimate,
            "eps_high": eps_high,
            "eps_low": eps_low,
            "revenue_estimate": revenue_estimate,
            "revenue_high": revenue_high,
            "revenue_low": revenue_low,
        },
        "recent_performance": {
            "trailing_eps": trailing_eps,
            "forward_eps": forward_eps,
            "earnings_growth_yoy_pct": _yoy_pct(earnings_growth),
            "quarterly_earnings_growth_yoy_pct": _yoy_pct(quarterly_growth),
            # 하위호환용 구 키 (동일 값, YoY 의미) — 신규 코드는 *_yoy_pct 사용
            "earnings_growth_pct": _yoy_pct(earnings_growth),
            "quarterly_earnings_growth_pct": _yoy_pct(quarterly_growth),
            "growth_basis_note": (
                "성장률은 모두 YoY(전년동기 대비) 기준. "
                "QoQ는 earnings_history.records의 연속 분기 eps_actual로 직접 계산할 것."
            ),
        },
        "earnings_history": {
            "records": earnings_history,
            "beat_rate_pct": beat_rate,  # actual > estimate만 beat (meet 제외)
            "beat_count": beat_count,
            "meet_count": meet_count,
            "miss_count": miss_count,
            "total_count": total_history,
            "beat_and_fade_count": beat_and_fade_count,
            "reaction_note": (
                "gap_t1_pct=발표 반응일 종가의 직전 종가 대비 갭(%), "
                "drift_t5_pct=반응일 종가 이후 5거래일 수익률(%). "
                "beat_and_fade=EPS beat인데 T+1 갭 음수(기대 소진 = 출구 신호). "
                "가격 조회 실패 시 null."
            ),
        },
        "estimate_revisions": estimate_revisions,
        "analyst_count": analyst_count,
        "dividend_schedule": {
            "next_dividend_date": dividend_date.isoformat() if isinstance(dividend_date, date) else str(dividend_date) if dividend_date else None,
            "ex_dividend_date": ex_dividend_date.isoformat() if isinstance(ex_dividend_date, date) else str(ex_dividend_date) if ex_dividend_date else None,
            "annual_dividend_rate": dividend_rate,
            "dividend_yield_pct": round(dividend_yield, 2) if dividend_yield else None,
        },
        "data_status": data_status,
        "errors": errors,
    }
