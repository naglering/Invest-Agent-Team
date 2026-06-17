"""섹터·테마 로테이션 스캐너 — '지금 자금이 어디로 몰리는가'를 랭킹.

메가트렌드 테마 ETF + 전통 GICS 섹터 ETF의 모멘텀(1/3/6M 수익률, SPY 대비 상대강도,
50/200일선 위치)을 점수화해 랭킹한다. 사용자가 섹터를 지목하기 전에 시스템이 먼저
"뜨거운 섹터"를 발굴하도록 하는 능동 엔진.
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


def _scan_one(name, etf, category, spy_3m, period):
    try:
        df = yf.Ticker(etf).history(period=period)
        if df.empty or len(df) < 30:
            return None
        close = df["Close"]
        cur = float(close.iloc[-1])
        r1, r3, r6 = _ret_pct(close, 21), _ret_pct(close, 63), _ret_pct(close, 126)
        sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
        sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
        above_50 = bool(sma50 and cur > sma50)
        above_200 = bool(sma200 and cur > sma200) if sma200 else None
        rs_spy = round(r3 - spy_3m, 2) if (r3 is not None and spy_3m is not None) else None

        # 점수: 3M 수익(40) + SPY 대비 RS(40) + 50일선(10) + 200일선(10)
        score = 0.0
        if r3 is not None:
            score += max(0.0, min(r3 / 25.0, 1.0)) * 40
        if rs_spy is not None:
            score += max(0.0, min((rs_spy + 10) / 25.0, 1.0)) * 40
        if above_50:
            score += 10
        if above_200:
            score += 10
        score = round(score, 1)

        # 판정: 🟢 3M RS>+5 & 50일선 상회 / 🔴 3M RS<-5 or 200일선 하회
        if rs_spy is not None and rs_spy > 5 and above_50:
            rating = "🟢 자금유입"
        elif (rs_spy is not None and rs_spy < -5) or (above_200 is False):
            rating = "🔴 자금이탈"
        else:
            rating = "🟡 중립"

        return {
            "name": name,
            "etf": etf,
            "category": category,
            "return_1m_pct": r1,
            "return_3m_pct": r3,
            "return_6m_pct": r6,
            "rs_vs_spy_3m_pct": rs_spy,
            "above_50ma": above_50,
            "above_200ma": above_200,
            "momentum_score": score,
            "rating": rating,
        }
    except Exception as e:
        return {"name": name, "etf": etf, "category": category, "error": str(e)}


def scan_sectors(period: str = "1y", include_traditional: bool = True) -> dict:
    """테마/섹터 모멘텀을 스캔해 랭킹한다."""
    try:
        spy = yf.Ticker("SPY").history(period=period)["Close"]
        spy_3m = _ret_pct(spy, 63)
    except Exception:
        spy_3m = None

    rows = []
    for theme, cfg in THEME_ETF_MAP.items():
        etf = cfg["etfs"][0] if cfg.get("etfs") else None
        if etf:
            r = _scan_one(theme, etf, "메가트렌드", spy_3m, period)
            if r:
                rows.append(r)
    if include_traditional:
        for sector, etf in SECTOR_ETF_MAP.items():
            r = _scan_one(sector, etf, "전통섹터", spy_3m, period)
            if r:
                rows.append(r)

    ranked = sorted(
        [r for r in rows if "momentum_score" in r],
        key=lambda x: x["momentum_score"],
        reverse=True,
    )
    errors = [r for r in rows if "error" in r]

    return {
        "spy_3m_return_pct": spy_3m,
        "ranking_method": "momentum_score = 3M수익(40) + SPY대비 RS(40) + 50일선(10) + 200일선(10)",
        "rating_rule": "🟢 자금유입: 3M RS>+5%p & 50일선 상회 / 🔴 자금이탈: 3M RS<-5%p 또는 200일선 하회 / 나머지 🟡",
        "ranking": ranked,
        "top_megatrend": [r for r in ranked if r["category"] == "메가트렌드"][:5],
        "errors": errors,
    }
