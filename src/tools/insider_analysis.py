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


# routine(비방향성) 내부자 거래로 분류할 키워드.
# 옵션행사(M), grant/award(A), 세금납부용 처분(F), 증여(gift), 10b5-1 사전약정 등.
_ROUTINE_KEYWORDS = (
    "exercise",   # 옵션 행사 (Form4 'M')
    "option",
    "award",      # grant/award (Form4 'A')
    "grant",
    "gift",
    "tax",        # 세금 납부용 처분 (Form4 'F')
    "withhold",
    "10b5-1",     # 사전약정 매매 플랜
    "10b5",
    "rule 10b5",
    "vest",       # RSU vesting
    "conversion",
)


def _classify_insider_transaction(transaction_text: str) -> str:
    """SEC Form4 성격을 추정해 내부자 거래를 분류한다.

    반환값:
      - "open_market_buy"  : open-market 매수 (Form4 'P')
      - "open_market_sell" : open-market 매도 (Form4 'S')
      - "routine"          : 옵션행사/grant/award/세금/증여/10b5-1 등 비방향성 거래
      - "unknown"          : 분류 불가
    """
    text = (transaction_text or "").lower()

    # routine 키워드가 있으면 방향성 sentiment에서 제외
    if any(kw in text for kw in _ROUTINE_KEYWORDS):
        return "routine"

    # open-market 매수
    if "buy" in text or "purchase" in text or "매수" in text:
        return "open_market_buy"

    # open-market 매도 ('sale'/'sold'/'sell'만 있고 routine 키워드는 없는 경우)
    if "sale" in text or "sold" in text or "sell" in text or "매도" in text or "disposition" in text:
        return "open_market_sell"

    return "unknown"


def analyze_insider(ticker_symbol: str) -> dict:
    """내부자 거래, 기관 보유, 공매도 데이터를 분석한다."""
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    if not info:
        raise ValueError(f"티커 '{ticker_symbol}'에 대한 데이터를 찾을 수 없습니다.")

    company_name = info.get("longName") or info.get("shortName", "N/A")

    # 어떤 조회가 성공/실패했는지 추적 (빈 결과를 '중립'으로 오판하지 않도록)
    data_status = {}
    errors = []

    # --- 내부자 거래 ---
    insider_transactions = []
    buy_count = 0          # open-market 매수 (Form4 'P')
    sell_count = 0         # open-market 매도 (Form4 'S')
    routine_count = 0      # 옵션행사(M)/grant·award(A)/세금(F)/10b5-1 등 비방향성 거래
    try:
        insider_df = ticker.get_insider_transactions()
        if insider_df is not None and not insider_df.empty:
            for _, row in insider_df.head(20).iterrows():
                shares_val = row.get("Shares", row.get("shares"))
                try:
                    shares_int = int(shares_val) if shares_val is not None and not (isinstance(shares_val, float) and math.isnan(shares_val)) else 0
                except (TypeError, ValueError):
                    shares_int = 0
                trans_text = str(row.get("Transaction", row.get("transaction", "N/A")))
                classification = _classify_insider_transaction(trans_text)
                trans = {
                    "insider": str(row.get("Insider", row.get("insider", "N/A"))),
                    "relation": str(row.get("Relation", row.get("relation", "N/A"))),
                    "date": str(row.get("Start Date", row.get("startDate", row.get("date", "N/A")))),
                    "transaction": trans_text,
                    "shares": shares_int,
                    "value": _safe_round(row.get("Value", row.get("value"))),
                    "classification": classification,  # open_market_buy / open_market_sell / routine / unknown
                }
                insider_transactions.append(trans)

                if classification == "open_market_buy":
                    buy_count += 1
                elif classification == "open_market_sell":
                    sell_count += 1
                elif classification == "routine":
                    routine_count += 1
            data_status["insider"] = "ok"
        else:
            data_status["insider"] = "empty"
    except Exception as e:
        data_status["insider"] = "error"
        errors.append(f"insider_transactions: {type(e).__name__}: {e}")

    # sentiment는 routine(RSU vesting·옵션행사·세금·10b5-1)을 제외한
    # open-market 순매수/순매도로만 판정 — 고성장주 RSU 매도 오판 방지
    if data_status.get("insider") == "error":
        insider_sentiment = "데이터 없음 (조회 실패)"
    elif buy_count > sell_count:
        insider_sentiment = "매수 우위"
    elif sell_count > buy_count:
        insider_sentiment = "매도 우위"
    elif buy_count + sell_count > 0:
        insider_sentiment = "중립"
    elif routine_count > 0:
        insider_sentiment = "중립 (routine 거래만 존재)"
    else:
        insider_sentiment = "데이터 없음"

    classification_note = (
        "sentiment는 open-market 매수(P)/매도(S)만 반영하며, "
        "옵션행사(M)·grant/award(A)·세금납부(F)·10b5-1 등 routine 거래는 제외됨."
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
            data_status["institutional"] = "ok"
        else:
            data_status["institutional"] = "empty"
    except Exception as e:
        data_status["institutional"] = "error"
        errors.append(f"institutional_holders: {type(e).__name__}: {e}")

    # --- 보유 비율 ---
    held_by_insiders = info.get("heldPercentInsiders")
    held_by_institutions = info.get("heldPercentInstitutions")
    ownership = {
        "insider_pct": _safe_round(held_by_insiders * 100 if held_by_insiders and held_by_insiders < 1 else held_by_insiders),
        "institutional_pct": _safe_round(held_by_institutions * 100 if held_by_institutions and held_by_institutions < 1 else held_by_institutions),
    }

    # --- 공매도 ---
    short_ratio = info.get("shortRatio")
    short_pct_float = info.get("shortPercentOfFloat")  # yfinance는 분수(0~1)로 반환
    shares_short = info.get("sharesShort")
    shares_short_prior = info.get("sharesShortPriorMonth")
    short_pct_shares_out = info.get("shortPercentOfSharesOutstanding", info.get("sharesPercentSharesOut"))

    short_change = None
    if shares_short and shares_short_prior and shares_short_prior > 0:
        short_change = _safe_round((shares_short - shares_short_prior) / shares_short_prior * 100)

    # short_pct_float는 분수(0~1)이므로 % 단위로 정규화. (>10 같은 dead-code 분기 제거)
    short_pct_float_pct = _safe_round(short_pct_float * 100) if short_pct_float is not None else None

    # 공매도 데이터 존재 여부 판정 (전부 None이면 미제공으로 표기)
    if short_pct_float is None and short_ratio is None and shares_short is None:
        data_status["short_interest"] = "empty"
    else:
        data_status["short_interest"] = "ok"

    # --- 숏스퀴즈 점수(0~100) ---
    # 높은 short %float + 높은 days-to-cover(short_ratio) + 공매도 증가(short_change) → 높음.
    # TODO(momentum 결합): 가격 데이터는 이 파일에 없으므로 가격 상승과의 결합은 생략.
    #   실제 스퀴즈 트리거 판단 시 momentum/technical 도구의 가격 추세와 함께 해석 권장.
    squeeze_score = None
    if data_status["short_interest"] == "ok":
        score = 0.0
        # (1) short % float: 0%→0, 20%+→50점 (절반 비중)
        if short_pct_float_pct is not None:
            score += min(short_pct_float_pct / 20.0, 1.0) * 50.0
        # (2) days-to-cover(short_ratio): 0일→0, 10일+→30점
        if short_ratio is not None:
            score += min(short_ratio / 10.0, 1.0) * 30.0
        # (3) 공매도 증가율: 0%→0, +50%+→20점 (감소 시 0)
        if short_change is not None and short_change > 0:
            score += min(short_change / 50.0, 1.0) * 20.0
        squeeze_score = _safe_round(score, 1)

    # squeeze_score 해석 (방향성 신호 — 정적 리스크가 아닌 스퀴즈 연료 관점)
    squeeze_signals = []
    if short_change is not None and short_change > 0:
        squeeze_signals.append("숏 증가(역풍 또는 스퀴즈 연료 축적)")
    elif short_change is not None and short_change < 0:
        squeeze_signals.append("숏 감소(공매도 청산 진행)")
    if short_ratio is not None and short_ratio > 5:
        squeeze_signals.append("커버 어려움 → 스퀴즈 연료")
    if short_pct_float_pct is not None and short_pct_float_pct > 10:
        squeeze_signals.append("높은 short %float → 스퀴즈 잠재력")

    if data_status["short_interest"] != "ok":
        squeeze_interpretation = "데이터 없음"
    elif squeeze_score is not None and squeeze_score >= 60:
        squeeze_interpretation = "스퀴즈 연료 높음 (가격 모멘텀과 결합 시 폭발 가능)"
    elif squeeze_score is not None and squeeze_score >= 30:
        squeeze_interpretation = "스퀴즈 연료 보통"
    else:
        squeeze_interpretation = "스퀴즈 연료 낮음"

    short_interest = {
        "short_ratio": _safe_round(short_ratio),
        "short_pct_float": short_pct_float_pct,
        "shares_short": shares_short,
        "shares_short_prior_month": shares_short_prior,
        "short_change_pct": short_change,
        "interpretation": (
            "높은 공매도 (숏스퀴즈 가능성)" if short_pct_float_pct is not None and short_pct_float_pct > 10
            else "보통 수준의 공매도" if short_pct_float_pct is not None and short_pct_float_pct > 3
            else "낮은 공매도" if short_pct_float_pct is not None
            else "데이터 없음"
        ),
        "short_ratio_interpretation": (
            "커버에 5일 이상 (높음)" if short_ratio and short_ratio > 5
            else "커버에 2~5일 (보통)" if short_ratio and short_ratio > 2
            else "커버에 2일 이내 (낮음)" if short_ratio is not None
            else "N/A"
        ),
        "squeeze_score": squeeze_score,
        "squeeze_signals": squeeze_signals,
        "squeeze_interpretation": squeeze_interpretation,
    }

    return {
        "ticker": ticker_symbol,
        "company_name": company_name,
        "insider_transactions": {
            "recent_transactions": insider_transactions,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "open_market_buy_count": buy_count,
            "open_market_sell_count": sell_count,
            "routine_count": routine_count,
            "sentiment": insider_sentiment,
            "classification_note": classification_note,
        },
        "institutional_holders": {
            "top_holders": institutional_holders,
        },
        "ownership": ownership,
        "short_interest": short_interest,
        "data_status": data_status,
        "errors": errors,
    }
