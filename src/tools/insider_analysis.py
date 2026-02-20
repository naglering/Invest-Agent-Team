"""내부자 거래 + 기관 보유 + 공매도 분석 도구

yfinance의 insider transactions, institutional holders, short interest 데이터 활용.
"""

import math

import yfinance as yf


def _safe_round(value, digits=2):
    if value is None:
        return None
    try:
        fval = float(value)
        if math.isnan(fval) or math.isinf(fval):
            return None
        return round(fval, digits)
    except (TypeError, ValueError):
        return None


def analyze_insider(ticker_symbol: str) -> dict:
    """내부자 거래, 기관 보유, 공매도 데이터를 분석한다."""
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    if not info:
        raise ValueError(f"티커 '{ticker_symbol}'에 대한 데이터를 찾을 수 없습니다.")

    company_name = info.get("longName") or info.get("shortName", "N/A")

    # --- 내부자 거래 ---
    insider_transactions = []
    buy_count = 0
    sell_count = 0
    try:
        insider_df = ticker.get_insider_transactions()
        if insider_df is not None and not insider_df.empty:
            for _, row in insider_df.head(20).iterrows():
                shares_val = row.get("Shares", row.get("shares"))
                try:
                    shares_int = int(shares_val) if shares_val is not None and not (isinstance(shares_val, float) and math.isnan(shares_val)) else 0
                except (TypeError, ValueError):
                    shares_int = 0
                trans = {
                    "insider": str(row.get("Insider", row.get("insider", "N/A"))),
                    "relation": str(row.get("Relation", row.get("relation", "N/A"))),
                    "date": str(row.get("Start Date", row.get("startDate", row.get("date", "N/A")))),
                    "transaction": str(row.get("Transaction", row.get("transaction", "N/A"))),
                    "shares": shares_int,
                    "value": _safe_round(row.get("Value", row.get("value"))),
                }
                insider_transactions.append(trans)

                trans_type = trans["transaction"].lower()
                if "buy" in trans_type or "purchase" in trans_type or "매수" in trans_type:
                    buy_count += 1
                elif "sell" in trans_type or "sale" in trans_type or "매도" in trans_type:
                    sell_count += 1
    except Exception:
        pass

    insider_sentiment = (
        "매수 우위" if buy_count > sell_count
        else "매도 우위" if sell_count > buy_count
        else "중립" if buy_count + sell_count > 0
        else "데이터 없음"
    )

    # --- 기관 보유자 ---
    institutional_holders = []
    try:
        inst_df = ticker.get_institutional_holders()
        if inst_df is not None and not inst_df.empty:
            for _, row in inst_df.head(10).iterrows():
                inst_shares = row.get("Shares", row.get("shares"))
                try:
                    inst_shares_int = int(inst_shares) if inst_shares is not None and not (isinstance(inst_shares, float) and math.isnan(inst_shares)) else 0
                except (TypeError, ValueError):
                    inst_shares_int = 0
                holder = {
                    "holder": str(row.get("Holder", row.get("holder", "N/A"))),
                    "shares": inst_shares_int,
                    "date_reported": str(row.get("Date Reported", row.get("dateReported", "N/A"))),
                    "pct_out": _safe_round(row.get("% Out", row.get("pctHeld"))),
                    "value": _safe_round(row.get("Value", row.get("value"))),
                }
                institutional_holders.append(holder)
    except Exception:
        pass

    # --- 보유 비율 ---
    held_by_insiders = info.get("heldPercentInsiders")
    held_by_institutions = info.get("heldPercentInstitutions")
    ownership = {
        "insider_pct": _safe_round(held_by_insiders * 100 if held_by_insiders and held_by_insiders < 1 else held_by_insiders),
        "institutional_pct": _safe_round(held_by_institutions * 100 if held_by_institutions and held_by_institutions < 1 else held_by_institutions),
    }

    # --- 공매도 ---
    short_ratio = info.get("shortRatio")
    short_pct_float = info.get("shortPercentOfFloat")
    shares_short = info.get("sharesShort")
    shares_short_prior = info.get("sharesShortPriorMonth")
    short_pct_shares_out = info.get("shortPercentOfSharesOutstanding", info.get("sharesPercentSharesOut"))

    short_change = None
    if shares_short and shares_short_prior and shares_short_prior > 0:
        short_change = _safe_round((shares_short - shares_short_prior) / shares_short_prior * 100)

    short_interest = {
        "short_ratio": _safe_round(short_ratio),
        "short_pct_float": _safe_round(short_pct_float * 100 if short_pct_float and short_pct_float < 1 else short_pct_float),
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior,
        "short_change_pct": short_change,
        "interpretation": (
            "높은 공매도 (숏스퀴즈 가능성)" if short_pct_float and (short_pct_float > 0.1 or (short_pct_float > 10))
            else "보통 수준의 공매도" if short_pct_float and (short_pct_float > 0.03 or (short_pct_float > 3))
            else "낮은 공매도" if short_pct_float is not None
            else "데이터 없음"
        ),
        "short_ratio_interpretation": (
            "커버에 5일 이상 (높음)" if short_ratio and short_ratio > 5
            else "커버에 2~5일 (보통)" if short_ratio and short_ratio > 2
            else "커버에 2일 이내 (낮음)" if short_ratio is not None
            else "N/A"
        ),
    }

    return {
        "ticker": ticker_symbol,
        "company_name": company_name,
        "insider_transactions": {
            "recent_transactions": insider_transactions,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "sentiment": insider_sentiment,
        },
        "institutional_holders": {
            "top_holders": institutional_holders,
        },
        "ownership": ownership,
        "short_interest": short_interest,
    }
