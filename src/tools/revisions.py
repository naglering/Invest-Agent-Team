"""테마 EPS 리비전 랭킹 도구 — 가격과 독립적인 확인 신호 (#18a)

theme_etf_map.theme_members(테마)로 유니버스(ETF holdings ∪ reps − exclude)를 구성하고,
각 티커의 yfinance eps_trend(현재/7일 전/30일 전 컨센서스 EPS)를 자체 파싱해
7d/30d 추정 변화율을 계산, 리비전 상향 순으로 랭킹한다.

가격 모멘텀은 가장 붐비는 팩터다 — 애널리스트 추정 상향(리비전)은 돌파·자금흐름
신호의 진위를 가려주는 **가격 외** 확인 신호. sector_scan(상대모멘텀)·momentum과
교차 사용한다. eps_trend 파싱은 earnings_calendar와 독립 구현(스키마: index 0q/+1q/0y/+1y,
columns current/7daysAgo/30daysAgo/60daysAgo/90daysAgo).
"""

from datetime import datetime

import yfinance as yf

try:
    from tools.theme_etf_map import THEME_ETF_MAP, theme_members
except ImportError:
    from theme_etf_map import THEME_ETF_MAP, theme_members

# 대표 기간 우선순위: 당해 회계연도(0y)가 리비전 신호의 표준, 없으면 차기연도→분기
_BASIS_PRIORITY = ("0y", "+1y", "0q", "+1q")
# 보합 판정 밴드 — |30d 변화| < 0.5%는 노이즈로 본다
_FLAT_BAND_PCT = 0.5


def _num(val):
    """pandas 셀 값을 float로 (NaN/None → None)."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN 방어


def _chg_pct(cur, prev):
    """(현재-과거)/|과거| % — 적자 추정이 0으로 좁혀지는 상향도 양수로 잡힌다."""
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def _resolve_theme(query: str):
    """테마명 관대 매칭: 정확 일치 → 대소문자 무시 부분 일치(양방향). 다중/무매칭 시 None."""
    themes = list(THEME_ETF_MAP.keys())
    if query in themes:
        return query, None
    q = (query or "").strip().lower()
    if not q:
        return None, "테마명이 비어 있음"
    hits = [t for t in themes if q in t.lower() or t.lower() in q]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, f"테마명 '{query}'가 모호함 (후보: {', '.join(hits)})"
    return None, f"테마 '{query}' 없음"


def _fetch_periods(symbol: str):
    """티커의 eps_trend를 기간별 리비전 dict로. 커버리지 없으면 None, 조회 실패 시 예외 전파."""
    df = yf.Ticker(symbol).eps_trend
    if df is None or len(df) == 0:
        return None
    # 방어: 행/열 방향이 뒤집힌 스키마 변경에 대비 (기대: index=기간, columns=시점)
    if "current" not in df.columns and "current" in df.index:
        df = df.T
    periods = {}
    for per in _BASIS_PRIORITY:
        if per not in df.index:
            continue
        row = df.loc[per]
        cur = _num(row.get("current"))
        d7 = _num(row.get("7daysAgo"))
        d30 = _num(row.get("30daysAgo"))
        if cur is None and d7 is None and d30 is None:
            continue
        periods[per] = {
            "eps_current": cur,
            "eps_7d_ago": d7,
            "eps_30d_ago": d30,
            "rev_7d_pct": _chg_pct(cur, d7),
            "rev_30d_pct": _chg_pct(cur, d30),
        }
    return periods or None


def _rate(rev_30d, rev_7d):
    """대표 30d(없으면 7d) 변화율로 상향/보합/하향 판정."""
    val = rev_30d if rev_30d is not None else rev_7d
    if val is None:
        return None
    if val > _FLAT_BAND_PCT:
        return "🟢 상향"
    if val < -_FLAT_BAND_PCT:
        return "🔴 하향"
    return "🟡 보합"


def _build_row(sym, periods):
    """기간별 리비전 dict → 랭킹 행 (대표 basis 선택 + 판정)."""
    basis = next(p for p in _BASIS_PRIORITY if p in periods)
    b = periods[basis]
    cur, prev30 = b["eps_current"], b["eps_30d_ago"]
    return {
        "ticker": sym,
        "basis": basis,  # 대표 기간 (0y=당해 회계연도 우선)
        "eps_current": cur,
        "eps_30d_ago": prev30,
        "rev_7d_pct": b["rev_7d_pct"],
        "rev_30d_pct": b["rev_30d_pct"],
        "sign_flip": (
            "적자→흑자 전환 추정" if (prev30 is not None and cur is not None
                                      and prev30 < 0 <= cur)
            else "흑자→적자 전환 추정" if (prev30 is not None and cur is not None
                                           and cur < 0 <= prev30)
            else None
        ),
        "rating": _rate(b["rev_30d_pct"], b["rev_7d_pct"]),
        "periods": periods,
    }


def rank_revisions(theme: str) -> dict:
    """테마 유니버스의 EPS 추정 리비전(7d/30d)을 집계해 상향 순으로 랭킹한다.

    Args:
        theme: THEME_ETF_MAP 테마명 (부분 일치 허용 — 예: 'AI', '우주', '방산')
    Returns:
        dict: ranked(리비전 상향 순) + breadth 집계 + no_coverage/failed
    """
    errors, soft_warnings = [], []

    resolved, why = _resolve_theme(theme)
    if resolved is None:
        return {
            "theme_query": theme,
            "error": why,
            "available_themes": list(THEME_ETF_MAP.keys()),
            "data_status": "error",
            "errors": [why],
            "soft_warnings": [],
        }

    universe = sorted(theme_members(resolved))
    if not universe:
        errors.append(f"테마 '{resolved}' 멤버십이 비어 있음 (ETF holdings 캐시·reps 확인)")

    rows, no_coverage, failed = [], [], []
    for sym in universe:
        try:
            periods = _fetch_periods(sym)
        except Exception as e:
            failed.append({"ticker": sym, "error": f"{type(e).__name__}: {e}"[:120]})
            continue
        if not periods:
            # ETF·애널리스트 미커버 소형주·일부 해외 상장은 eps_trend가 비어 있음 — 정상 경로
            no_coverage.append(sym)
            continue
        rows.append(_build_row(sym, periods))

    # 조회 실패분 1회 재시도 (일시적 레이트리밋 방어)
    if failed:
        still_failed = []
        for item in failed:
            sym = item["ticker"]
            try:
                periods = _fetch_periods(sym)
            except Exception:
                still_failed.append(item)
                continue
            if not periods:
                no_coverage.append(sym)
                continue
            rows.append(_build_row(sym, periods))
        failed = still_failed

    # 랭킹: 30d 변화율 내림차순 (30d 결측이면 7d로 대체, 둘 다 결측이면 최하단)
    def _key(r):
        v = r["rev_30d_pct"] if r["rev_30d_pct"] is not None else r["rev_7d_pct"]
        return (v is not None, v if v is not None else 0.0)

    rows.sort(key=_key, reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # 집계 — breadth(상향 비중)가 테마 레벨의 확인 신호
    vals = [r["rev_30d_pct"] for r in rows if r["rev_30d_pct"] is not None]
    aggregate = {"n_ranked": len(rows), "n_with_30d": len(vals)}
    if vals:
        up = sum(1 for v in vals if v > _FLAT_BAND_PCT)
        down = sum(1 for v in vals if v < -_FLAT_BAND_PCT)
        flat = len(vals) - up - down
        svals = sorted(vals)
        mid = len(svals) // 2
        median = svals[mid] if len(svals) % 2 else (svals[mid - 1] + svals[mid]) / 2
        aggregate.update({
            "up_30d": up, "down_30d": down, "flat_30d": flat,
            "breadth_30d_pct": round(up / len(vals) * 100, 1),
            "avg_rev_30d_pct": round(sum(vals) / len(vals), 2),
            "median_rev_30d_pct": round(median, 2),
        })

    interpretation = None
    if vals:
        top = rows[0]
        interpretation = (
            f"'{resolved}' 리비전 breadth {aggregate['breadth_30d_pct']}% "
            f"(30d 상향 {aggregate['up_30d']}·보합 {aggregate['flat_30d']}·하향 {aggregate['down_30d']}, "
            f"중앙값 {aggregate['median_rev_30d_pct']:+.2f}%) — "
            f"1위 {top['ticker']} ({top['rev_30d_pct']:+.2f}%, {top['basis']})"
        )

    if failed:
        soft_warnings.append(
            f"{len(failed)}개 티커 eps_trend 조회 실패(재시도 1회 포함) — 랭킹에서 제외 (failed 참조)")
    if no_coverage:
        soft_warnings.append(
            f"{len(no_coverage)}개 심볼은 애널리스트 추정 없음(ETF·미커버) — no_coverage 참조")

    data_status = ("empty" if not rows else "partial" if failed else "ok")

    return {
        "theme": resolved,
        "theme_query": theme,
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "universe_size": len(universe),
        "universe": universe,
        "ranked": rows,
        "aggregate": aggregate,
        "no_coverage": sorted(no_coverage),
        "failed": failed,
        "interpretation": interpretation,
        "method": {
            "source": "yfinance eps_trend (컨센서스 EPS: current vs 7/30daysAgo)",
            "formula": "rev_pct = (current − N일전) / |N일전| × 100 — 절대값 분모라 적자 추정 상향도 양수",
            "basis": "대표 기간 우선순위 0y(당해 회계연도) → +1y → 0q → +1q (티커별 basis 필드에 명시)",
            "ranking": "rev_30d_pct 내림차순 (결측 시 rev_7d_pct 대체, 둘 다 결측이면 최하단)",
            "rating": f"🟢 상향 > +{_FLAT_BAND_PCT}% / 🔴 하향 < -{_FLAT_BAND_PCT}% / 🟡 보합 (30d 기준, 결측 시 7d)",
            "usage": "가격 외 확인 신호 — sector_scan 상대모멘텀 🟢와 리비전 breadth가 동시에 강할 때 진입 신뢰도 상승. "
                     "sign_flip(적자↔흑자 전환 추정)은 변화율이 과장되므로 EPS 절대값 병행 확인",
        },
        "data_status": data_status,
        "errors": errors,
        "soft_warnings": soft_warnings,
    }
