"""뉴스 검색 도구 - Market Analyst 에이전트용

yfinance 기반 뉴스 검색. 키워드로 관련 종목의 뉴스를 수집한다.
"""

import yfinance as yf
from datetime import datetime, timedelta


def search(query: str, days: int = 14) -> dict:
    """
    yfinance를 통해 뉴스를 검색한다.

    쿼리에서 티커 심볼을 추출하여 해당 종목의 뉴스를 수집하고,
    쿼리 키워드로 필터링한다.

    Args:
        query: 검색 쿼리 (티커 심볼 포함 가능)
        days: 검색 기간 (기본 14일)

    Returns:
        dict: 검색 결과 목록
    """
    # 쿼리에서 티커 후보 추출 (대문자 영문 + 숫자/점 조합)
    import re
    tokens = query.split()
    ticker_candidates = [t for t in tokens if re.match(r'^[A-Z0-9]+(\.[A-Z]+)?$', t.upper())]

    cutoff = datetime.now() - timedelta(days=days)
    all_results = []

    # 티커 후보가 있으면 해당 종목 뉴스 수집
    tickers_to_search = ticker_candidates if ticker_candidates else []

    for symbol in tickers_to_search:
        try:
            ticker = yf.Ticker(symbol.upper())
            raw_news = ticker.news or []

            for item in raw_news:
                content = item.get("content", {})
                pub_date_str = content.get("pubDate", "")

                if pub_date_str:
                    try:
                        pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                        if pub_dt.replace(tzinfo=None) < cutoff:
                            continue
                        date_str = pub_dt.strftime("%Y-%m-%d %H:%M")
                    except (ValueError, TypeError):
                        date_str = pub_date_str
                else:
                    date_str = ""

                title = content.get("title", "")
                summary = content.get("summary", content.get("description", ""))
                url = ""
                if isinstance(content.get("canonicalUrl"), dict):
                    url = content["canonicalUrl"].get("url", "")
                source = ""
                if isinstance(content.get("provider"), dict):
                    source = content["provider"].get("displayName", "")

                all_results.append({
                    "ticker": symbol.upper(),
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "source": source,
                    "published_date": date_str,
                })
        except Exception:
            continue

    # 키워드 필터링 (티커가 아닌 단어들)
    keywords = [t.lower() for t in tokens if t.upper() not in [c.upper() for c in ticker_candidates]]
    if keywords and all_results:
        filtered = []
        for r in all_results:
            text = (r["title"] + " " + r["summary"]).lower()
            if any(kw in text for kw in keywords):
                filtered.append(r)
        # 키워드 매칭이 있으면 필터링된 결과, 없으면 전체 반환
        if filtered:
            all_results = filtered

    return {
        "query": query,
        "tickers_searched": [t.upper() for t in tickers_to_search],
        "total_results": len(all_results),
        "results": all_results,
    }
