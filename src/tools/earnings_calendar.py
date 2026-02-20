"""실적발표 일정 도구 - 예정된 실적 발표일, 컨센서스 EPS/매출 조회

yfinance의 calendar 및 info 데이터를 활용한다.
"""

from datetime import datetime, date

import yfinance as yf


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
    calendar = {}
    try:
        calendar = ticker.calendar or {}
    except Exception:
        pass

    today = date.today()

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
            dt = datetime.fromtimestamp(ts_start)
            earnings_date_str = dt.strftime("%Y-%m-%d")
            days_until_earnings = (dt.date() - today).days
        elif ts_end:
            dt = datetime.fromtimestamp(ts_end)
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
        call_dt = datetime.fromtimestamp(call_ts)
        earnings_call = call_dt.strftime("%Y-%m-%d %H:%M")

    # --- 실적 서프라이즈 이력 (earnings_history) ---
    earnings_history = []
    beat_count = 0
    total_history = 0
    try:
        earnings_dates_df = ticker.earnings_dates
        if earnings_dates_df is not None and not earnings_dates_df.empty:
            for idx, row in earnings_dates_df.head(8).iterrows():
                estimate = row.get("EPS Estimate")
                actual = row.get("Reported EPS")
                surprise_pct = row.get("Surprise(%)")

                record = {
                    "date": str(idx.date()) if hasattr(idx, 'date') else str(idx),
                    "eps_estimate": float(estimate) if estimate is not None and str(estimate) != "nan" else None,
                    "eps_actual": float(actual) if actual is not None and str(actual) != "nan" else None,
                    "surprise_pct": float(surprise_pct) if surprise_pct is not None and str(surprise_pct) != "nan" else None,
                }
                earnings_history.append(record)
                if record["eps_estimate"] is not None and record["eps_actual"] is not None:
                    total_history += 1
                    if record["eps_actual"] >= record["eps_estimate"]:
                        beat_count += 1
    except Exception:
        pass

    beat_rate = round(beat_count / total_history * 100, 1) if total_history > 0 else None

    # --- 추정치 변동 추세 (estimate_revisions) ---
    estimate_revisions = {}
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
    except Exception:
        pass

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
        except Exception:
            pass

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
            "earnings_growth_pct": round(earnings_growth * 100, 2) if earnings_growth and abs(earnings_growth) < 10 else earnings_growth,
            "quarterly_earnings_growth_pct": round(quarterly_growth * 100, 2) if quarterly_growth and abs(quarterly_growth) < 10 else quarterly_growth,
        },
        "earnings_history": {
            "records": earnings_history,
            "beat_rate_pct": beat_rate,
            "beat_count": beat_count,
            "total_count": total_history,
        },
        "estimate_revisions": estimate_revisions,
        "analyst_count": analyst_count,
        "dividend_schedule": {
            "next_dividend_date": dividend_date.isoformat() if isinstance(dividend_date, date) else str(dividend_date) if dividend_date else None,
            "ex_dividend_date": ex_dividend_date.isoformat() if isinstance(ex_dividend_date, date) else str(ex_dividend_date) if ex_dividend_date else None,
            "annual_dividend_rate": dividend_rate,
            "dividend_yield_pct": round(dividend_yield, 2) if dividend_yield else None,
        },
    }
