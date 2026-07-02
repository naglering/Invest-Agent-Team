"""동종업계 피어 비교 분석 도구

업종별 피어 매핑 기반 멀티플 비교 및 순위 산출.
"""

import bisect

import yfinance as yf

try:
    from tools.theme_etf_map import THEME_ETF_MAP, themes_for_ticker, theme_members
except ImportError:
    from theme_etf_map import THEME_ETF_MAP, themes_for_ticker, theme_members


INDUSTRY_PEERS = {
    "Auto Manufacturers": ["TSLA", "TM", "GM", "F", "RIVN", "HMC", "STLA"],
    "Consumer Electronics": ["AAPL", "SONY", "HPQ", "DELL", "LOGI"],
    "Semiconductors": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TSM", "MU"],
    "Software - Infrastructure": ["MSFT", "ORCL", "CRM", "NOW", "ADBE", "INTU"],
    "Software - Application": ["CRM", "ADBE", "INTU", "WDAY", "SNOW", "TEAM"],
    "Internet Content & Information": ["GOOGL", "META", "SNAP", "PINS", "BIDU"],
    "Internet Retail": ["AMZN", "BABA", "JD", "PDD", "MELI", "SE"],
    "Specialty Retail": ["HD", "LOW", "TJX", "ROST", "BBY"],
    "Drug Manufacturers - General": ["JNJ", "PFE", "MRK", "LLY", "ABBV", "NVO"],
    "Biotechnology": ["AMGN", "GILD", "BIIB", "REGN", "VRTX", "MRNA"],
    "Banks - Diversified": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
    "Aerospace & Defense": ["BA", "LMT", "RTX", "NOC", "GD", "HII"],
    "Oil & Gas Integrated": ["XOM", "CVX", "SHEL", "TTE", "BP", "COP"],
    "Restaurants": ["MCD", "SBUX", "CMG", "YUM", "DRI", "QSR"],
    "Entertainment": ["DIS", "NFLX", "CMCSA", "WBD", "PARA"],
    "Communication Equipment": ["CSCO", "ANET", "MSI", "ERIC"],  # JNPR은 HPE 인수 상폐로 제거
    "Telecom Services": ["T", "VZ", "TMUS", "AMX"],
    "Utilities - Regulated Electric": ["NEE", "DUK", "SO", "D", "AEP"],
    "REIT - Diversified": ["PLD", "AMT", "EQIX", "SPG", "O"],
    "Household & Personal Products": ["PG", "UL", "CL", "KMB", "EL"],
}


def _safe_round(value, digits=2):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _get_peer_tickers(industry: str, ticker: str) -> list:
    """업종 기반 피어 티커 목록 반환 (자기 자신 제외).

    정확 매칭을 우선하고, 없을 때만 방어적으로 부분 매칭(양방향 포함)을 사용한다.
    빈 industry 문자열은 모든 키와 substring 매칭되어 오매칭을 유발하므로 제외.
    """
    ticker_upper = ticker.upper()
    industry_l = (industry or "").strip().lower()
    if not industry_l:
        return []

    # 1순위: 정확 매칭
    for ind, peers in INDUSTRY_PEERS.items():
        if ind.lower() == industry_l:
            return [p for p in peers if p != ticker_upper]

    # 2순위: 방어적 부분 매칭 (양방향 substring)
    for ind, peers in INDUSTRY_PEERS.items():
        ind_l = ind.lower()
        if industry_l in ind_l or ind_l in industry_l:
            return [p for p in peers if p != ticker_upper]

    # 매칭 실패 시 빈 리스트
    return []


def _get_theme_peer_tickers(ticker: str) -> tuple:
    """메가트렌드 테마 폴백 피어.

    INDUSTRY_PEERS 매칭이 실패했을 때, 타겟이 속한 테마의 멤버십
    (ETF holdings ∪ reps − exclude)에서 타겟 자신을 제외하고 피어로 사용한다.
    큐레이션 reps를 앞에 두고(클린·대표성) ETF holdings로 보강한다.

    Returns:
        (peer_tickers, theme_name). 매칭 테마가 없으면 ([], None).
    """
    ticker_upper = ticker.upper().strip()
    themes = themes_for_ticker(ticker_upper)
    if not themes:
        return [], None
    theme = themes[0]
    cfg = THEME_ETF_MAP.get(theme, {})
    reps = [r.upper() for r in cfg.get("reps", [])]
    extra = sorted(theme_members(theme) - set(reps))  # holdings 보강분
    ordered = reps + extra
    peers = [p for p in ordered if p != ticker_upper]
    return peers, theme


def _extract_metrics(info: dict) -> dict:
    # yfinance info의 operatingMargins/returnOnEquity는 항상 소수 형태(0.15=15%) → 조건 없는 ×100
    # (abs<10 휴리스틱은 초고ROE·초고성장 케이스를 100배 축소해 제거)
    om_raw = info.get("operatingMargins")
    roe_raw = info.get("returnOnEquity")
    return {
        "pe_ratio": _safe_round(info.get("trailingPE")),
        "forward_pe": _safe_round(info.get("forwardPE")),
        "pb_ratio": _safe_round(info.get("priceToBook")),
        "ps_ratio": _safe_round(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": _safe_round(info.get("enterpriseToEbitda")),
        "operating_margin_pct": _safe_round(om_raw * 100) if om_raw is not None else None,
        "roe_pct": _safe_round(roe_raw * 100) if roe_raw is not None else None,
        "market_cap": info.get("marketCap"),
    }


def compare_peers(ticker_symbol: str, max_peers: int = 5, custom_peers: list = None) -> dict:
    """동종업계 피어 비교 분석을 수행한다.

    Args:
        custom_peers: 커스텀 피어 티커 목록. 제공되면 하드코딩 맵 대신 사용.
    """
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    if not info:
        raise ValueError(f"티커 '{ticker_symbol}'에 대한 데이터를 찾을 수 없습니다.")

    industry = info.get("industry", "")
    sector = info.get("sector", "")
    company_name = info.get("longName") or info.get("shortName", "N/A")

    target_metrics = _extract_metrics(info)

    theme_name = None
    peer_source = "custom"
    if custom_peers:
        peer_tickers = [p for p in custom_peers if p.upper() != ticker_symbol.upper()][:max_peers]
    else:
        peer_tickers = _get_peer_tickers(industry, ticker_symbol)
        if peer_tickers:
            peer_source = "industry"
        else:
            # INDUSTRY_PEERS 매칭 실패 → 메가트렌드 테마 폴백
            theme_peers, theme_name = _get_theme_peer_tickers(ticker_symbol)
            if theme_peers:
                peer_tickers = theme_peers
                peer_source = "theme"
        peer_tickers = peer_tickers[:max_peers]

    if not peer_tickers:
        return {
            "ticker": ticker_symbol,
            "company_name": company_name,
            "industry": industry,
            "sector": sector,
            "target_metrics": target_metrics,
            "peers": [],
            "failed_peers": [],
            "sector_averages": {},
            "excluded_negative": {},
            "ranking": {},
            "note": f"업종 '{industry}'에 대한 피어 매핑이 없으며, 메가트렌드 테마에도 해당되지 않습니다.",
        }

    # 피어 데이터 수집 — 조회 실패(상폐·오티커)는 failed_peers로 노출해 조용한 표본 축소 방지
    peers_data = []
    failed_peers = []
    all_metrics = [target_metrics]  # 타겟 포함 (유효 지표 카운트용 — 벤치마크 통계는 peers-only)

    for pt in peer_tickers:
        try:
            peer_info = yf.Ticker(pt).info or {}
            if not peer_info or peer_info.get("currentPrice") is None and peer_info.get("regularMarketPrice") is None:
                failed_peers.append(pt)
                continue
            metrics = _extract_metrics(peer_info)
            peers_data.append({
                "ticker": pt,
                "company_name": peer_info.get("longName") or peer_info.get("shortName", pt),
                "metrics": metrics,
            })
            all_metrics.append(metrics)
        except Exception:
            failed_peers.append(pt)
            continue

    # 섹터 평균/중앙값 계산 — 벤치마크는 peers-only(타겟 포함 시 자기참조로 프리미엄이 0 방향 희석),
    # lower-is-better 멀티플은 값>0만 포함(음수 멀티플의 '가장 싸다=1위'·평균 파괴 방지)
    metric_keys = ["pe_ratio", "forward_pe", "pb_ratio", "ps_ratio", "ev_to_ebitda", "operating_margin_pct", "roe_pct"]
    lower_is_better_keys = {"pe_ratio", "forward_pe", "pb_ratio", "ps_ratio", "ev_to_ebitda"}
    sector_averages = {}
    excluded_negative = {}
    peer_values_by_key = {}
    for key in metric_keys:
        vals = []
        for p in peers_data:
            v = p["metrics"].get(key)
            if v is None:
                continue
            if key in lower_is_better_keys and v <= 0:
                excluded_negative.setdefault(key, []).append(p["ticker"])
                continue
            vals.append(v)
        peer_values_by_key[key] = vals
        if vals:
            import numpy as np
            sector_averages[key] = {
                "mean": _safe_round(float(np.mean(vals))),
                "median": _safe_round(float(np.median(vals))),
                "min": _safe_round(min(vals)),
                "max": _safe_round(max(vals)),
            }

    # 타겟 순위 및 프리미엄/할인 계산 (랭킹 풀엔 타겟 포함, 벤치마크 분모는 peers-only 중앙값)
    ranking = {}
    for key in metric_keys:
        target_val = target_metrics.get(key)
        if target_val is None:
            ranking[key] = {"rank": "N/A", "premium_pct": None}
            continue

        higher_is_better = key in ["operating_margin_pct", "roe_pct"]
        if not higher_is_better and target_val <= 0:
            # 타겟 자신의 음수 멀티플(적자·음수자본 등)도 랭킹·프리미엄에서 제외
            excluded_negative.setdefault(key, []).append(ticker_symbol.upper())
            ranking[key] = {
                "rank": "N/A",
                "premium_pct": None,
                "interpretation": "음수 멀티플 (적자/음수자본 등) — '가장 싸다' 오독 방지 위해 랭킹·통계 제외",
            }
            continue

        raw_values = peer_values_by_key[key] + [target_val]
        values = sorted(raw_values, reverse=higher_is_better)  # 1위가 앞쪽

        # bisect로 순위 계산 — float == 멤버십 대신 정렬 위치로 산출(동률·부동소수 안전).
        # higher_is_better가 아니면 낮을수록 1위(오름차순 정렬 후 target보다 작은 값 개수+1),
        # higher_is_better면 높을수록 1위(내림차순 정렬에서는 부호를 뒤집어 동일 논리 적용).
        if higher_is_better:
            keyed = sorted(-v for v in raw_values)
            rank = bisect.bisect_left(keyed, -target_val) + 1
        else:
            keyed = sorted(raw_values)
            rank = bisect.bisect_left(keyed, target_val) + 1

        avg = sector_averages.get(key, {}).get("median")
        premium = _safe_round((target_val / avg - 1) * 100) if avg and avg != 0 else None

        ranking[key] = {
            "rank": f"{rank}/{len(values)}" if isinstance(rank, int) else rank,
            "premium_pct": premium,
            "interpretation": (
                f"섹터 대비 {abs(premium)}% 프리미엄" if premium and premium > 5
                else f"섹터 대비 {abs(premium)}% 할인" if premium and premium < -5
                else "섹터 평균 수준" if premium is not None
                else "N/A"
            ),
        }

    result = {
        "ticker": ticker_symbol,
        "company_name": company_name,
        "industry": industry,
        "sector": sector,
        "target_metrics": target_metrics,
        "peers": peers_data,
        "failed_peers": failed_peers,
        "sector_averages": sector_averages,
        "benchmark_basis": "peers-only (타겟 제외; lower-is-better 멀티플은 값>0만 포함)",
        "excluded_negative": excluded_negative,
        "ranking": ranking,
    }
    if failed_peers:
        result["peer_fetch_warning"] = (
            f"피어 {len(peer_tickers)}개 중 {len(failed_peers)}개 조회 실패(상폐·오티커 가능): "
            f"{', '.join(failed_peers)} — 표본 축소로 벤치마크 신뢰도 저하"
        )

    # 메가트렌드 테마 폴백을 사용한 경우 — 적자 종목이 많아 PER이 무의미할 수 있으므로
    # P/S·EV/Sales 중심 해석 note와 P/S 기준 순위를 함께 제공한다.
    if peer_source == "theme":
        ps_count = sum(1 for m in all_metrics if m.get("ps_ratio") is not None)
        pe_count = sum(1 for m in all_metrics if m.get("pe_ratio") is not None)
        ps_rank = ranking.get("ps_ratio", {}).get("rank")
        result["peer_source"] = "megatrend_theme"
        result["theme"] = theme_name
        result["ps_rank"] = ps_rank  # P/S 기준 순위(낮을수록 1위)
        result["note"] = (
            f"업종 '{industry}' 피어 매핑이 없어 메가트렌드 테마 '{theme_name}' 대표종목을 "
            f"피어로 사용했습니다. 이 테마는 적자/고성장 종목이 많아 PER 비교가 무의미할 수 "
            f"있으니 P/S·EV/Sales 중심으로 해석하세요. "
            f"(P/S 유효 {ps_count}/{len(all_metrics)}개, PER 유효 {pe_count}/{len(all_metrics)}개; "
            f"P/S 순위 {ps_rank})"
        )
    else:
        result["peer_source"] = peer_source

    return result
