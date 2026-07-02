"""메모 예측 vs 실현 추적 도구 — 성과 피드백 루프의 측정 축 (#14 후반부)

data/histories/YYYY-MM-DD_TICKER/summary.md(레거시 flat 포함)를 관대하게 파싱해
작성일·티커·권고(매수/관망/회피)·목표가·손절가·시나리오 확률·확신도를 추출하고,
yfinance 이후 가격으로 1/3/6M 수익률과 손절/목표 터치 여부를 계산한다.

집계(위원회가 conviction·사이징 규율을 보정할 실측 데이터):
- 권고별 승률·평균 수익률·평균 실현 R (손절 선터치 시 -1R 클램프 — 규율 준수 가정)
- Bull/Base/Bear 선언 확률 vs 실현 빈도 (캘리브레이션 갭)
- conviction 구간별(low/mid/high) 성과
- data/trades.jsonl 체결 레저가 있으면 실현 손익·평균 R-multiple도 집계

메모 포맷 편차에 관대: 신형 템플릿(**권고**: 라인)·구형 테이블(| 비보유자 | ... |)·
인라인 시나리오(Bull(25%): $1,400) 등 다중 정규식을 순차 시도하고,
파싱/가격조회 실패 항목은 unparsed / price_errors 리스트로 노출한다(조용한 누락 방지).
"""

import json
import os
import re
from datetime import datetime

import yfinance as yf

try:
    from tools.memo_manager import _iter_records
except ImportError:
    from memo_manager import _iter_records

DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
TRADES_PATH = os.path.join(DATA_DIR, "trades.jsonl")

# 관측 지평(거래일 봉 수). 크립토(-USD)는 캘린더 일봉이라 별도 환산.
_HORIZONS_EQUITY = {"1m": 21, "3m": 63, "6m": 126}
_HORIZONS_CRYPTO = {"1m": 30, "3m": 91, "6m": 182}

_HEADING_RE = re.compile(r"^(#{1,6})\s*(.+?)\s*$", re.MULTILINE)

# 가격 토큰: $1,206.5 / 85,000원 / 560K (천 단위). 범위는 첫 매칭 토큰 사용.
_PRICE_TOKEN = re.compile(
    r"\$\s*([\d,]+(?:\.\d+)?)"
    r"|([\d,]+(?:\.\d+)?)\s*원"
    r"|([\d,]+(?:\.\d+)?)\s*[Kk]\b"
)


# ─────────────────────────────────────────────────────────────────────────────
# 파싱 헬퍼 (메모 포맷 편차에 관대 — 다중 패턴 순차 시도)
# ─────────────────────────────────────────────────────────────────────────────

def _first_price(text):
    """텍스트에서 첫 가격 토큰을 숫자로. 없으면 None."""
    for m in _PRICE_TOKEN.finditer(text or ""):
        if m.group(1):
            return float(m.group(1).replace(",", ""))
        if m.group(2):
            return float(m.group(2).replace(",", ""))
        if m.group(3):
            return float(m.group(3).replace(",", "")) * 1000.0
    return None


def _section(text, keyword):
    """keyword를 포함한 마크다운 헤딩부터 같은 레벨 이하 다음 헤딩 전까지."""
    if not text:
        return None
    for m in _HEADING_RE.finditer(text):
        if keyword in m.group(2):
            level = len(m.group(1))
            start = m.end()
            for m2 in _HEADING_RE.finditer(text, start):
                if len(m2.group(1)) <= level:
                    return text[start:m2.start()]
            return text[start:]
    return None


def _labeled_value(text, *labels):
    """'- **라벨**: 값' 또는 '라벨: 값' 라인의 값 부분(콜론 뒤 첫 내용)을 추출."""
    if not text:
        return None
    for label in labels:
        m = re.search(rf"\*\*{re.escape(label)}[^\n:：]*\*\*\s*[:：]\s*(.+)", text)
        if m:
            return m.group(1).strip()
    for label in labels:  # 볼드 없는 변형
        m = re.search(rf"^[ \t>*+-]*{re.escape(label)}[^\n:：]{{0,24}}[:：]\s*(.+)$",
                      text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


def _head_clause(raw):
    """권고문의 첫 절('비중 유지. ...'의 '비중 유지')만 떼서 키워드 오염을 줄인다."""
    return re.split(r"[.。—–]", raw or "")[0]


def _norm_new_rec(raw):
    """신규 투자자 권고 정규화: 회피 > 관망 > 매수 > 매도 (혼합 표현은 보수적으로)."""
    if not raw:
        return None
    head = _head_clause(raw)
    low = head.lower()
    if "회피" in head or "avoid" in low:
        return "회피"
    if "관망" in head or "wait" in low or "watch" in low:
        return "관망"
    if "매수" in head or "buy" in low:
        return "매수"
    if "매도" in head or "sell" in low:
        return "매도"
    return None


def _norm_holder_rec(raw):
    """보유자 권고 정규화: 청산/축소/확대/유지."""
    if not raw:
        return None
    head = _head_clause(raw)
    low = head.lower()
    if "전량" in head or "청산" in head:
        return "청산"
    if "축소" in head or "trim" in low:
        return "축소"
    if "확대" in head or "피라미딩" in head or "add" in low:
        return "확대"
    if "유지" in head or "hold" in low:
        return "유지"
    return None


def _extract_recommendations(text):
    """(신규 권고 raw, 신규 정규화, 보유자 정규화) 추출."""
    dec = _section(text, "투자 결정") or text
    # 신규 투자자
    sub = _section(dec, "신규 투자자")
    raw_new = _labeled_value(sub, "권고") if sub else None
    if raw_new is None:  # 구형 이중추천 테이블: | **비보유자** | 관망 (Wait) | 75% |
        m = re.search(r"\|\s*\*{0,2}\s*(?:비보유자|신규\s*투자자|신규)\s*\*{0,2}\s*\|\s*([^|\n]+)\|", dec)
        if m:
            raw_new = m.group(1).strip()
    if raw_new is None:  # 최구형: - **결정**: 관망
        raw_new = _labeled_value(dec, "결정")
    # 현재 보유자
    hold_sec = _section(dec, "현재 보유자")
    raw_hold = _labeled_value(hold_sec, "권고") if hold_sec else None
    if raw_hold is None:
        m = re.search(r"\|\s*\*{0,2}\s*(?:현재\s*)?보유자\s*\*{0,2}\s*\|\s*([^|\n]+)\|", dec)
        if m:
            raw_hold = m.group(1).strip()
    return raw_new, _norm_new_rec(raw_new), _norm_holder_rec(raw_hold)


def _target_from_text(raw):
    """목표가 라인에서 대표값 추출 — 'Base' 라벨 우선, 없으면 첫 가격 토큰."""
    if not raw or raw.strip().upper().startswith("N/A"):
        return None
    bidx = raw.find("Base")
    if bidx >= 0:
        p = _first_price(raw[bidx:])
        if p is not None:
            return p
    return _first_price(raw)


def _extract_target(text):
    dec = _section(text, "투자 결정")
    for scope in (dec, text):
        raw = _labeled_value(scope, "목표가") if scope else None
        if raw is not None:
            t = _target_from_text(raw)
            if t is not None:
                return t
    return None


def _extract_stop(text):
    """(손절가 숫자, 트레일링 규칙 문자열) — 숫자 미검출 시 원문을 규칙으로 보존."""
    dec = _section(text, "투자 결정")
    rule = None
    for scope in (dec, text):
        if not scope:
            continue
        raw = _labeled_value(scope, "초기 손절가", "손절가", "손절")
        if raw is None:
            continue
        if raw.strip().upper().startswith("N/A"):
            return None, None
        p = _first_price(raw)
        if p is not None:
            return p, None
        rule = rule or raw[:60]
    return None, rule


_SCEN_WORDS = {"bull": ("Bull",), "base": ("Base",), "bear": ("Bear",)}


def _extract_scenarios(text):
    """Bull/Base/Bear별 {prob_pct, target}. 시나리오 섹션 우선, 없으면 전문 탐색.

    지원 패턴: 'Bull(확률 25%): 목표가 $900-1,250' / 'Bull(25%): $1,400(+31.7%)' /
    '### Bull Case (확률: 20%)' + '| 목표가 | **$220** |' / '| **Bull** | 20% | $100,000~ |'
    """
    scope = _section(text, "시나리오") or text
    out = {}
    for key, words in _SCEN_WORDS.items():
        for w in words:
            m = re.search(rf"{w}[^%\n]{{0,30}}?(\d{{1,3}}(?:\.\d+)?)\s*%", scope, re.IGNORECASE)
            if not m:
                continue
            prob = float(m.group(1))
            if not (0 < prob <= 100):
                continue
            window = scope[m.end(): m.end() + 300]
            # 다음 시나리오 단어가 나오면 거기서 창을 자른다(타 시나리오 목표가 오염 방지)
            cuts = [window.find(ow) for ows in _SCEN_WORDS.values() for ow in ows
                    if ow != w and window.find(ow) >= 0]
            if cuts:
                window = window[:min(cuts)]
            tm = re.search(r"목표가[^\n|]*", window)
            target = _first_price(tm.group(0)) if tm else None
            if target is None:
                target = _first_price(window)
            out[key] = {"prob_pct": prob, "target": target}
            break
    return out


def _extract_conviction(text):
    """헤더 확신도 라벨 + 본문의 배수(0.5~2.0) → low/mid/high 버킷."""
    m = re.search(r"\*\*확신도\*\*\s*[:：]\s*(.+)", text)
    label = m.group(1).strip()[:40] if m else None
    m2 = re.search(r"확신도\s*[:：]?\s*([0-2]\.\d+)", text)
    mult = float(m2.group(1)) if m2 else None
    bucket = None
    if mult is not None:
        bucket = "low" if mult < 0.9 else "mid" if mult <= 1.2 else "high"
    elif label and not label.upper().startswith("N/A"):
        low = label.lower()
        if "중상" in label:
            bucket = "high"
        elif "중하" in label or "중-저" in label or "medium-low" in low:
            bucket = "low"
        elif "상" in label[:3] or "high" in low:
            bucket = "high"
        elif "하" in label[:3] or "저" in label[:3] or "low" in low:
            bucket = "low"
        elif "중" in label[:3] or "medium" in low or "mid" in low:
            bucket = "mid"
    return {"label": label, "multiplier": mult, "bucket": bucket}


def _parse_summary(text):
    """summary.md 전문 → 예측 필드 dict (+ unparsed_fields)."""
    raw_new, rec_new, rec_hold = _extract_recommendations(text)
    target = _extract_target(text)
    stop, stop_rule = _extract_stop(text)
    scenarios = _extract_scenarios(text)
    conviction = _extract_conviction(text)
    unparsed_fields = [name for name, ok in (
        ("recommendation", rec_new is not None),
        ("target", target is not None),
        ("stop", stop is not None or stop_rule is not None),
        ("scenarios", bool(scenarios)),
    ) if not ok]
    return {
        "recommendation": rec_new,
        "recommendation_raw": (_head_clause(raw_new)[:80] if raw_new else None),
        "holder_recommendation": rec_hold,
        "target": target,
        "stop": stop,
        "stop_rule": stop_rule,
        "scenarios": scenarios,
        "conviction": conviction,
        "unparsed_fields": unparsed_fields,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 가격 평가 (티커별 1회 조회 — 레이트리밋 최소화)
# ─────────────────────────────────────────────────────────────────────────────

def _price_history(ticker, start_iso):
    """가격 조회 (df, 실제 사용 심볼). 접미사 없는 6자리 한국 티커는 .KS → .KQ 순 폴백."""
    candidates = [ticker]
    if re.fullmatch(r"\d{6}", ticker):
        candidates = [f"{ticker}.KS", f"{ticker}.KQ"]
    last_err = None
    for sym in candidates:
        try:
            df = yf.Ticker(sym).history(start=start_iso, auto_adjust=False)
            if df is not None and not df.empty:
                return df, sym
        except Exception as e:  # 다음 후보 시도
            last_err = e
    if last_err is not None:
        raise last_err
    raise ValueError("가격 데이터 없음")


def _evaluate_ticker(ticker, recs):
    """같은 티커의 메모들에 이후 수익률/손절·목표 터치를 채운다. 실패 시 예외."""
    start = min(r["_date_obj"] for r in recs)
    df, used_symbol = _price_history(ticker, start.isoformat())
    if used_symbol != ticker:
        for r in recs:
            r["notes"].append(f"가격 심볼 '{used_symbol}'로 폴백 조회 (한국 티커 접미사 보정)")
    dates = [d.date() for d in df.index]
    close, high, low = df["Close"], df["High"], df["Low"]
    horizons = _HORIZONS_CRYPTO if ticker.upper().endswith("-USD") else _HORIZONS_EQUITY

    for r in recs:
        md = r["_date_obj"]
        i = next((k for k, d in enumerate(dates) if d >= md), None)
        if i is None:
            r["notes"].append("메모일 이후 가격 없음")
            continue
        if (dates[i] - md).days > 10:
            r["notes"].append(f"기준가가 메모일 {(dates[i] - md).days}일 후 봉({dates[i]})")
        base = float(close.iloc[i])
        r["base_price"] = round(base, 4)
        r["base_date"] = str(dates[i])
        r["days_observed"] = len(df) - 1 - i

        # 1/3/6M 수익률 (미도래 지평은 None)
        rets = {}
        for name, bars in horizons.items():
            j = i + bars
            rets[name] = round((float(close.iloc[j]) / base - 1) * 100, 2) if j < len(df) else None
        r["returns_pct"] = rets

        # 손절/목표 터치 — 6M 지평 내 저가/고가 기준
        end = min(i + horizons["6m"], len(df) - 1)
        stop_idx = target_idx = None
        stop, target = r.get("stop"), r.get("target")
        if stop is not None and stop >= base:
            r["notes"].append("손절가가 기준가 이상 — R 계산 제외")
            stop = None
        if stop is not None:
            stop_idx = next((k for k in range(i, end + 1) if float(low.iloc[k]) <= stop), None)
            r["stop_hit"] = stop_idx is not None
            r["stop_hit_date"] = str(dates[stop_idx]) if stop_idx is not None else None
        if target is not None and target > base:
            target_idx = next((k for k in range(i, end + 1) if float(high.iloc[k]) >= target), None)
            r["target_hit"] = target_idx is not None
            r["target_hit_date"] = str(dates[target_idx]) if target_idx is not None else None
        if stop_idx is not None and (target_idx is None or stop_idx <= target_idx):
            r["first_event"] = "stop"
        elif target_idx is not None:
            r["first_event"] = "target"
        else:
            r["first_event"] = "none"

        # 실현 R (3M): 손절 선터치면 -1R 클램프(규율 준수 가정), 아니면 (P3M-P0)/리스크
        if stop is not None:
            risk = base - stop
            if stop_idx is not None and stop_idx <= i + horizons["3m"]:
                r["realized_r_3m"] = -1.0
            elif rets["3m"] is not None:
                r["realized_r_3m"] = round((float(close.iloc[i + horizons["3m"]]) - base) / risk, 2)

        # 시나리오 실현 판정 — 가용한 가장 긴 지평의 가격 vs Bull/Bear 목표가
        sc = r.get("scenarios") or {}
        bull_t = (sc.get("bull") or {}).get("target")
        bear_t = (sc.get("bear") or {}).get("target")
        if bull_t and bear_t and all((sc.get(k) or {}).get("prob_pct") is not None
                                     for k in ("bull", "base", "bear")):
            for name in ("6m", "3m", "1m"):
                j = i + horizons[name]
                if j < len(df):
                    p = float(close.iloc[j])
                    outcome = "bull" if p >= bull_t else "bear" if p <= bear_t else "base"
                    r["scenario_realized"] = {"horizon": name, "price": round(p, 4),
                                              "outcome": outcome}
                    break


# ─────────────────────────────────────────────────────────────────────────────
# 집계
# ─────────────────────────────────────────────────────────────────────────────

def _agg_group(records):
    out = {"count": len(records),
           "evaluated": sum(1 for r in records if r.get("base_price") is not None)}
    for h in ("1m", "3m", "6m"):
        rets = [r["returns_pct"][h] for r in records
                if r.get("returns_pct") and r["returns_pct"].get(h) is not None]
        if rets:
            out[f"n_{h}"] = len(rets)
            out[f"avg_ret_{h}_pct"] = round(sum(rets) / len(rets), 2)
            out[f"win_rate_{h}_pct"] = round(sum(1 for x in rets if x > 0) / len(rets) * 100, 1)
    rs = [r["realized_r_3m"] for r in records if r.get("realized_r_3m") is not None]
    if rs:
        out["n_r"] = len(rs)
        out["avg_realized_r_3m"] = round(sum(rs) / len(rs), 2)
    stops = [r for r in records if r.get("stop") is not None and r.get("base_price") is not None]
    if stops:
        out["n_stop"] = len(stops)
        out["stop_hit_rate_pct"] = round(
            sum(1 for r in stops if r.get("stop_hit")) / len(stops) * 100, 1)
    return out


def _calibration(records):
    rows = [r for r in records if r.get("scenario_realized")]
    if not rows:
        return {"n": 0, "note": "시나리오 확률+목표가와 실현 가격을 모두 가진 메모 없음"}
    out = {"n": len(rows),
           "horizon_mix": {h: sum(1 for r in rows if r["scenario_realized"]["horizon"] == h)
                           for h in ("6m", "3m", "1m")
                           if any(r["scenario_realized"]["horizon"] == h for r in rows)}}
    for key in ("bull", "base", "bear"):
        probs = [r["scenarios"][key]["prob_pct"] for r in rows]
        realized = sum(1 for r in rows if r["scenario_realized"]["outcome"] == key)
        declared = round(sum(probs) / len(probs), 1)
        freq = round(realized / len(rows) * 100, 1)
        out[key] = {"declared_avg_prob_pct": declared, "realized_freq_pct": freq,
                    "gap_pp": round(freq - declared, 1), "realized_count": realized}
    return out


def _aggregate_trades():
    """data/trades.jsonl 체결 레저 집계(있으면). 통화 혼합 방지를 위해 ccy별 합산."""
    if not os.path.exists(TRADES_PATH):
        return {"available": False,
                "note": "data/trades.jsonl 없음 — portfolio add/sell 레저가 쌓이면 실현 손익을 집계합니다."}
    buys = sells = skipped = wins = losses = 0
    pnl_by_ccy, r_multiples = {}, []
    with open(TRADES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                skipped += 1
                continue
            action = str(rec.get("action", "")).lower()
            if action == "buy":
                buys += 1
            elif action == "sell":
                sells += 1
                pnl = rec.get("realized_pnl")
                if isinstance(pnl, (int, float)):
                    ccy = rec.get("ccy") or "?"
                    pnl_by_ccy[ccy] = round(pnl_by_ccy.get(ccy, 0.0) + pnl, 2)
                    if pnl > 0:
                        wins += 1
                    elif pnl < 0:
                        losses += 1
                rm = rec.get("r_multiple")
                if isinstance(rm, (int, float)):
                    r_multiples.append(rm)
    out = {"available": True, "buys": buys, "sells": sells,
           "realized_pnl_by_ccy": pnl_by_ccy, "skipped_lines": skipped}
    if wins + losses > 0:
        out["sell_win_rate_pct"] = round(wins / (wins + losses) * 100, 1)
        out["sell_wins"] = wins
        out["sell_losses"] = losses
    if r_multiples:
        out["avg_r_multiple"] = round(sum(r_multiples) / len(r_multiples), 2)
        out["n_r_multiple"] = len(r_multiples)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────

def track(ticker: str = None) -> dict:
    """histories 메모의 예측을 실현 가격과 대조해 채점한다.

    Args:
        ticker: 지정 시 해당 티커 메모만 (예: 'TSLA')
    Returns:
        dict: 메모별 레코드 + 권고/캘리브레이션/확신도 집계 + trades.jsonl 요약
    """
    errors, soft_warnings, unparsed, records = [], [], [], []
    tfilter = ticker.upper().strip() if ticker else None

    memos_total = 0
    for meta in _iter_records():
        if not meta.get("date"):
            continue  # EXAMPLE 등 날짜 없는 디렉토리 제외
        raw_ticker = meta["ticker"]
        # 버전 suffix 디렉토리(IREN_VALUATION 등)는 앞부분을 평가 티커로 사용
        eval_ticker = raw_ticker.split("_")[0] if "_" in raw_ticker else raw_ticker
        if tfilter and eval_ticker != tfilter and raw_ticker != tfilter:
            continue
        memos_total += 1

        if meta["kind"] == "dir":
            spath = os.path.join(meta["path"], "summary.md")
            if not meta.get("has_summary") or not os.path.exists(spath):
                unparsed.append({"name": meta["name"],
                                 "reason": "summary.md 없음 (보고서 전용 — 시장/테마 리뷰 추정)"})
                continue
        else:
            spath = meta["path"]
        try:
            text = open(spath, encoding="utf-8").read()
        except OSError as e:
            unparsed.append({"name": meta["name"], "reason": f"읽기 실패: {e}"})
            continue

        parsed = _parse_summary(text)
        # 권고·목표가·손절·시나리오가 전부 미검출이면 단일 종목 메모가 아니라고 본다
        if len(parsed["unparsed_fields"]) == 4:
            unparsed.append({"name": meta["name"],
                             "reason": "권고/목표가/손절/시나리오 전부 미검출 — 종목 메모 아님 추정"})
            continue

        rec = {"name": meta["name"], "date": meta["date"], "ticker": eval_ticker,
               "_date_obj": datetime.strptime(meta["date"], "%Y-%m-%d").date(),
               "base_price": None, "notes": []}
        if eval_ticker != raw_ticker:
            rec["notes"].append(f"디렉토리 티커 '{raw_ticker}' → '{eval_ticker}'로 평가")
        rec.update(parsed)
        records.append(rec)

    # 티커별 1회 가격 조회로 평가
    price_errors = []
    by_ticker = {}
    for r in records:
        by_ticker.setdefault(r["ticker"], []).append(r)
    for t, recs in sorted(by_ticker.items()):
        try:
            _evaluate_ticker(t, recs)
        except Exception as e:
            price_errors.append({"ticker": t, "memos": len(recs), "error": str(e)[:120]})

    records.sort(key=lambda r: (r["date"], r["ticker"]))
    for r in records:
        r.pop("_date_obj", None)
        if not r["notes"]:
            r.pop("notes")

    evaluated = [r for r in records if r.get("base_price") is not None]

    # 집계: 권고별 / 캘리브레이션 / 확신도 구간별
    by_rec = {}
    for r in records:
        key = r.get("recommendation") or "미분류"
        by_rec.setdefault(key, []).append(r)
    by_conv = {}
    for r in records:
        b = (r.get("conviction") or {}).get("bucket")
        if b:
            by_conv.setdefault(b, []).append(r)

    aggregates = {
        "by_recommendation": {k: _agg_group(v) for k, v in sorted(by_rec.items())},
        "scenario_calibration": _calibration(evaluated),
        "by_conviction": {k: _agg_group(by_conv[k]) for k in ("low", "mid", "high")
                          if k in by_conv},
    }

    if price_errors:
        soft_warnings.append(
            f"{len(price_errors)}개 티커 가격 조회 실패 — 해당 메모는 집계에서 제외 (price_errors 참조)")
    if unparsed:
        soft_warnings.append(f"{len(unparsed)}개 메모 파싱 제외 (unparsed 참조)")
    not_matured = sum(1 for r in evaluated
                      if r.get("returns_pct") and all(v is None for v in r["returns_pct"].values()))
    if not_matured:
        soft_warnings.append(f"{not_matured}개 메모는 1M 지평 미도래 — 수익률 전부 null")

    buy = aggregates["by_recommendation"].get("매수", {})
    interpretation = None
    if buy.get("n_3m"):
        interpretation = (f"매수 권고 3M 승률 {buy['win_rate_3m_pct']}% "
                          f"(n={buy['n_3m']}, 평균 {buy['avg_ret_3m_pct']:+.1f}%)"
                          + (f", 평균 실현 R {buy['avg_realized_r_3m']:+.2f}"
                             if buy.get("avg_realized_r_3m") is not None else ""))

    data_status = ("empty" if not records
                   else "partial" if (price_errors or unparsed) else "ok")

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "ticker_filter": tfilter,
        "universe": {"memos_total": memos_total, "parsed": len(records),
                     "evaluated": len(evaluated), "tickers": len(by_ticker)},
        "aggregates": aggregates,
        "records": records,
        "trades_ledger": _aggregate_trades(),
        "unparsed": unparsed,
        "price_errors": price_errors,
        "interpretation": interpretation,
        "method": {
            "horizons": "주식 21/63/126 거래일 봉, 크립토(-USD) 30/91/182 캘린더 봉",
            "price_basis": "yfinance auto_adjust=False 종가 (분할 반영·배당 미반영 명목가)",
            "base_price": "메모일 당일 이후 첫 종가",
            "win": "지평 수익률 > 0 (관망/회피의 승률·수익률은 '피한 기회'의 기회비용으로 해석)",
            "realized_r_3m": "손절 3M 내 선터치 시 -1R 클램프(규율 준수 가정), 아니면 (P3M-P0)/(P0-손절가)",
            "scenario_realized": "가용 최장 지평 종가 ≥ Bull목표 → bull, ≤ Bear목표 → bear, 사이 → base "
                                 "(범위 목표가는 첫 토큰 = Bull 하한이라 bull 판정이 다소 후함)",
            "target_stop_hit": "6M 지평 내 고가/저가 터치 기준",
        },
        "data_status": data_status,
        "errors": errors,
        "soft_warnings": soft_warnings,
    }
