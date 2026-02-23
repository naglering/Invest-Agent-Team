"""동종업계 피어 비교 분석 도구

업종별 피어 매핑 기반 멀티플 비교 및 순위 산출.
"""

import yfinance as yf


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
    "Communication Equipment": ["CSCO", "ANET", "MSI", "JNPR", "ERIC"],
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
    """업종 기반 피어 티커 목록 반환 (자기 자신 제외)"""
    ticker_upper = ticker.upper()
    for ind, peers in INDUSTRY_PEERS.items():
        if ind.lower() == industry.lower():
            return [p for p in peers if p != ticker_upper]
        # 부분 매칭
        if industry.lower() in ind.lower() or ind.lower() in industry.lower():
            return [p for p in peers if p != ticker_upper]
    # 매칭 실패 시 빈 리스트
    return []


def _extract_metrics(info: dict) -> dict:
    return {
        "pe_ratio": _safe_round(info.get("trailingPE")),
        "forward_pe": _safe_round(info.get("forwardPE")),
        "pb_ratio": _safe_round(info.get("priceToBook")),
        "ps_ratio": _safe_round(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": _safe_round(info.get("enterpriseToEbitda")),
        "operating_margin_pct": _safe_round(
            info.get("operatingMargins", 0) * 100 if info.get("operatingMargins") and abs(info.get("operatingMargins", 0)) < 10 else info.get("operatingMargins")
        ),
        "roe_pct": _safe_round(
            info.get("returnOnEquity", 0) * 100 if info.get("returnOnEquity") and abs(info.get("returnOnEquity", 0)) < 10 else info.get("returnOnEquity")
        ),
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

    if custom_peers:
        peer_tickers = [p for p in custom_peers if p.upper() != ticker_symbol.upper()][:max_peers]
    else:
        peer_tickers = _get_peer_tickers(industry, ticker_symbol)[:max_peers]

    if not peer_tickers:
        return {
            "ticker": ticker_symbol,
            "company_name": company_name,
            "industry": industry,
            "sector": sector,
            "target_metrics": target_metrics,
            "peers": [],
            "sector_averages": {},
            "ranking": {},
            "note": f"업종 '{industry}'에 대한 피어 매핑이 없습니다.",
        }

    # 피어 데이터 수집
    peers_data = []
    all_metrics = [target_metrics]  # 타겟 포함

    for pt in peer_tickers:
        try:
            peer_info = yf.Ticker(pt).info or {}
            if not peer_info or peer_info.get("currentPrice") is None and peer_info.get("regularMarketPrice") is None:
                continue
            metrics = _extract_metrics(peer_info)
            peers_data.append({
                "ticker": pt,
                "company_name": peer_info.get("longName") or peer_info.get("shortName", pt),
                "metrics": metrics,
            })
            all_metrics.append(metrics)
        except Exception:
            continue

    # 섹터 평균/중앙값 계산
    metric_keys = ["pe_ratio", "forward_pe", "pb_ratio", "ps_ratio", "ev_to_ebitda", "operating_margin_pct", "roe_pct"]
    sector_averages = {}
    for key in metric_keys:
        values = [m[key] for m in all_metrics if m[key] is not None]
        if values:
            import numpy as np
            sector_averages[key] = {
                "mean": _safe_round(float(np.mean(values))),
                "median": _safe_round(float(np.median(values))),
                "min": _safe_round(min(values)),
                "max": _safe_round(max(values)),
            }

    # 타겟 순위 및 프리미엄/할인 계산
    ranking = {}
    for key in metric_keys:
        target_val = target_metrics.get(key)
        if target_val is None:
            ranking[key] = {"rank": "N/A", "premium_pct": None}
            continue

        values = sorted(
            [m[key] for m in all_metrics if m[key] is not None],
            reverse=(key in ["operating_margin_pct", "roe_pct"]),  # 높을수록 좋은 지표
        )
        if target_val in values:
            rank = values.index(target_val) + 1
        else:
            rank = "N/A"

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

    return {
        "ticker": ticker_symbol,
        "company_name": company_name,
        "industry": industry,
        "sector": sector,
        "target_metrics": target_metrics,
        "peers": peers_data,
        "sector_averages": sector_averages,
        "ranking": ranking,
    }
