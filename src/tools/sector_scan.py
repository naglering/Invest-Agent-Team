"""섹터·테마 로테이션 스캐너 — '지금 상대모멘텀이 어디로 몰리는가'를 랭킹.

메가트렌드 테마 ETF + 전통 GICS 섹터 ETF의 모멘텀(1/3/6M 수익률, SPY 대비 상대강도,
50/200일선 위치)을 점수화해 랭킹한다. 사용자가 섹터를 지목하기 전에 시스템이 먼저
"뜨거운 섹터"를 발굴하도록 하는 능동 엔진.

주의: 모든 신호는 **가격 기반 프록시**다 — 실제 ETF 자금유출입(fund flow)이 아니다.
실제 flow 판단은 가격 외 증거(ETF sharesOutstanding 변화, fund flow 기사 등)로 보강할 것.
"""

import yfinance as yf

try:
    from tools.theme_etf_map import SECTOR_ETF_MAP, THEME_ETF_MAP
except ImportError:
    from theme_etf_map import SECTOR_ETF_MAP, THEME_ETF_MAP


def _ret_pct(series, days):
    if series is None or len(series) <= days:
        return None
    base = float(series.iloc[-1 - days])
    if base == 0:
        return None
    return round((float(series.iloc[-1]) / base - 1) * 100, 2)


def _scan_one(name, etf, category, spy_3m, spy_1m, period):
    try:
        df = yf.Ticker(etf).history(period=period)
        if df.empty or len(df) < 30:
            # 신규 상장 테마 ETF가 조용히 누락되지 않도록 errors에 노출
            return {"name": name, "etf": etf, "category": category,
                    "error": f"insufficient history ({len(df)} bars < 30)"}
        close = df["Close"]
        cur = float(close.iloc[-1])
        r1, r3, r6 = _ret_pct(close, 21), _ret_pct(close, 63), _ret_pct(close, 126)
        sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
        sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
        above_50 = bool(cur > sma50) if sma50 else None
        above_200 = bool(cur > sma200) if sma200 else None
        rs_spy = round(r3 - spy_3m, 2) if (r3 is not None and spy_3m is not None) else None
        rs_spy_1m = round(r1 - spy_1m, 2) if (r1 is not None and spy_1m is not None) else None

        # 점수: 3M수익(30) + SPY 3M RS(35) + SPY 1M RS(15) + 50일선(10) + 200일선(10)
        # 1M RS를 반영해 완만한 롤오버 테마(3M 강세이나 최근 꺾임)의 상위 고착을 방지.
        # 결측 컴포넌트(신규 ETF·벤치마크 실패)는 0점이 아니라 제외 후 가용 만점 기준 재정규화.
        score = 0.0
        available_max = 0.0
        if r3 is not None:
            available_max += 30
            score += max(0.0, min(r3 / 25.0, 1.0)) * 30
        if rs_spy is not None:
            available_max += 35
            score += max(0.0, min((rs_spy + 10) / 25.0, 1.0)) * 35
        if rs_spy_1m is not None:
            available_max += 15
            score += max(0.0, min((rs_spy_1m + 5) / 12.5, 1.0)) * 15
        if above_50 is not None:
            available_max += 10
            if above_50:
                score += 10
        if above_200 is not None:
            available_max += 10
            if above_200:
                score += 10
        score = round(score / available_max * 100, 1) if available_max > 0 else None

        # 판정 (가격 프록시 — 실제 ETF 자금유출입 아님):
        # 🟢 3M RS>+5 & 50일선 상회 — 단, 1M RS 음수(최근 롤오버)면 🟡로 강등
        if rs_spy is not None and rs_spy > 5 and above_50:
            if rs_spy_1m is not None and rs_spy_1m < 0:
                rating = "🟡 중립 (3M 강세이나 1M RS 음전 — 롤오버 주의)"
            else:
                rating = "🟢 상대모멘텀 유입(가격 프록시)"
        elif (rs_spy is not None and rs_spy < -5) or (above_200 is False):
            rating = "🔴 상대모멘텀 이탈(가격 프록시)"
        else:
            rating = "🟡 중립"

        return {
            "name": name,
            "etf": etf,
            "category": category,
            "data_span_days": int(len(close)),
            "return_1m_pct": r1,
            "return_3m_pct": r3,
            "return_6m_pct": r6,
            "rs_vs_spy_3m_pct": rs_spy,
            "rs_vs_spy_1m_pct": rs_spy_1m,
            "above_50ma": above_50,
            "above_200ma": above_200,
            "momentum_score": score,
            "score_available_max": round(available_max, 1),  # 100 미만이면 결측 컴포넌트 제외 후 재정규화
            "rating": rating,
        }
    except Exception as e:
        return {"name": name, "etf": etf, "category": category, "error": str(e)}


def scan_sectors(period: str = "1y", include_traditional: bool = True) -> dict:
    """테마/섹터 모멘텀을 스캔해 랭킹한다."""
    errors = []
    try:
        spy = yf.Ticker("SPY").history(period=period)["Close"]
        spy_3m = _ret_pct(spy, 63)
        spy_1m = _ret_pct(spy, 21)
        if spy_3m is None:
            errors.append({"name": "SPY(벤치마크)", "etf": "SPY",
                           "error": "3M 수익률 산출 불가(빈 데이터/기간 부족) — 전 테마 RS·🟢 판정 무효"})
    except Exception as e:
        spy_3m = None
        spy_1m = None
        # 벤치마크 실패를 조용히 삼키지 않는다 — RS 40~50점 소실로 랭킹·breadth 판정이 변질됨
        errors.append({"name": "SPY(벤치마크)", "etf": "SPY",
                       "error": f"{type(e).__name__}: {e} — 전 테마 RS·🟢 판정 무효"})

    rows = []
    for theme, cfg in THEME_ETF_MAP.items():
        etf = cfg["etfs"][0] if cfg.get("etfs") else None
        if etf:
            r = _scan_one(theme, etf, "메가트렌드", spy_3m, spy_1m, period)
            if r:
                rows.append(r)
    if include_traditional:
        for sector, etf in SECTOR_ETF_MAP.items():
            r = _scan_one(sector, etf, "전통섹터", spy_3m, spy_1m, period)
            if r:
                rows.append(r)

    ranked = sorted(
        [r for r in rows if r.get("momentum_score") is not None],
        key=lambda x: x["momentum_score"],
        reverse=True,
    )
    errors += [r for r in rows if "error" in r]

    return {
        "spy_3m_return_pct": spy_3m,
        "spy_1m_return_pct": spy_1m,
        "benchmark_available": spy_3m is not None,  # False면 RS·🟢 판정 불가 — breadth 판정 보류
        "ranking_method": "momentum_score = 3M수익(30) + SPY 3M RS(35) + SPY 1M RS(15) + 50일선(10) + 200일선(10) — 결측 컴포넌트는 제외 후 가용 만점 기준 0~100 재정규화(score_available_max 참조)",
        "rating_rule": "가격 기반 프록시 — 실제 ETF 자금유출입(fund flow) 아님. 🟢 상대모멘텀 유입: 3M RS>+5%p & 50일선 상회 & 1M RS≥0 (1M RS 음수면 🟡 강등) / 🔴 상대모멘텀 이탈: 3M RS<-5%p 또는 200일선 하회 / 나머지 🟡",
        "ranking": ranked,
        "top_megatrend": [r for r in ranked if r["category"] == "메가트렌드"][:5],
        "errors": errors,
    }
