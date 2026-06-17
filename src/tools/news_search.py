"""뉴스 검색 도구 - Market Analyst 에이전트용

yfinance 기반 뉴스 검색. 키워드/티커로 관련 종목의 뉴스를 수집한다.
메가트렌드 투자에서 '서사(narrative) 강도'의 1순위 입력인 뉴스 빈도
(news velocity)를 측정한다.
"""

import re
import yfinance as yf
from datetime import datetime, timedelta

# 흔한 거래소 접미사 (티커 후보 판별용)
_EXCHANGE_SUFFIXES = (
    "KS", "KQ", "T", "HK", "SS", "SZ", "L", "TO", "V", "AX",
    "DE", "PA", "MI", "MC", "AS", "BR", "SW", "ST", "HE", "OL",
    "CO", "VI", "SI", "TW", "NS", "BO", "SA", "MX", "BA",
)

# 티커가 아닌, 짧은 대문자 테마/일반 키워드 (오인 방지)
_THEME_STOPWORDS = {
    "AI", "ML", "SMR", "GLD", "EV", "IT", "US", "USA", "EU", "UK",
    "CEO", "CFO", "GDP", "FED", "CPI", "PPI", "ETF", "IPO", "M&A",
    "ESG", "API", "GPU", "CPU", "VR", "AR", "5G", "6G", "IOT", "SAAS",
    "EPS", "PER", "PBR", "ROE", "ROI", "FCF", "DCF", "TAM", "Q1",
    "Q2", "Q3", "Q4", "FY", "YOY", "QOQ", "USD", "KRW", "EUR", "JPY",
    "OPEC", "NATO", "WTI", "VIX", "SP500", "NASDAQ", "DOW",
}


def _looks_like_ticker(token: str) -> bool:
    """토큰이 티커 심볼일 가능성이 있는지 휴리스틱으로 판정한다.

    - (a) 거래소 접미사(.KS 등)가 붙어 있으면 명백한 티커로 간주.
    - (b) 접미사 없는 토큰은 대문자 영숫자이면서 테마/일반 키워드가
          아니고 길이 휴리스틱(보통 3~5자)을 만족해야 티커로 본다.
    """
    up = token.upper()
    if not re.match(r"^[A-Z0-9]+(\.[A-Z]+)?$", up):
        return False

    # (a) 명백한 거래소 접미사가 있으면 티커로 확정
    if "." in up:
        suffix = up.split(".")[-1]
        if suffix in _EXCHANGE_SUFFIXES:
            return True
        # 알 수 없는 접미사라도 점이 붙어 있으면 티커 형태로 취급
        return True

    # (b) 접미사 없는 토큰: 테마/일반 키워드는 배제
    if up in _THEME_STOPWORDS:
        return False
    # 숫자만으로 이루어진 토큰은 티커가 아님 (연도/금액 등)
    if up.isdigit():
        return False
    # 길이 휴리스틱: 1~2자(AI 등 너무 짧음)·6자 초과는 티커로 보지 않음
    if len(up) < 3 or len(up) > 5:
        return False
    return True


def _parse_pub_time(item: dict, content: dict):
    """기사 항목에서 발행 시각을 datetime(naive, UTC 기준)으로 파싱한다.

    가능한 필드: providerPublishTime(epoch), content.pubDate(ISO),
    content.displayTime(ISO) 등. 실패 시 None 반환(조용히 죽지 않음).
    """
    # 1) epoch 초 (구 yfinance 스키마)
    epoch = item.get("providerPublishTime")
    if isinstance(epoch, (int, float)) and epoch > 0:
        try:
            return datetime.utcfromtimestamp(epoch)
        except (ValueError, OverflowError, OSError):
            pass

    # 2) ISO 문자열 후보들
    for key in ("pubDate", "displayTime"):
        val = content.get(key)
        if isinstance(val, str) and val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.replace(tzinfo=None)
            except (ValueError, TypeError):
                continue
    return None


def _compute_news_velocity(pub_times, days: int) -> dict:
    """발행 시각 리스트로 뉴스 빈도(news velocity)를 계산한다.

    Returns:
        dict: 윈도 내 총 기사 수, 일평균 기사 수, 최근 3일 vs 이전 비교 추세.
              시각 파싱이 전혀 안 되면 값들을 None 처리.
    """
    parsed = [t for t in pub_times if t is not None]
    velocity = {
        "window_days": days,
        "articles_with_timestamp": len(parsed),
        "total_articles": len(pub_times),
        "articles_per_day": None,
        "recent_3d_count": None,
        "prior_period_count": None,
        "prior_per_day": None,
        "velocity_trend": None,
    }

    if not parsed:
        return velocity

    now = datetime.utcnow()
    recent_cut = now - timedelta(days=3)

    recent_3d = sum(1 for t in parsed if t >= recent_cut)
    prior = len(parsed) - recent_3d
    prior_days = max(days - 3, 1)

    velocity["articles_per_day"] = round(len(parsed) / max(days, 1), 2)
    velocity["recent_3d_count"] = recent_3d
    velocity["prior_period_count"] = prior
    velocity["prior_per_day"] = round(prior / prior_days, 2)

    recent_per_day = recent_3d / 3.0
    prior_per_day = prior / prior_days

    # 추세 판정: 최근 3일 일평균을 이전 기간 일평균과 비교
    if prior_per_day == 0:
        velocity["velocity_trend"] = "급증" if recent_3d > 0 else "감소"
    else:
        ratio = recent_per_day / prior_per_day
        if ratio >= 1.5:
            velocity["velocity_trend"] = "급증"
        elif ratio <= 0.5:
            velocity["velocity_trend"] = "감소"
        else:
            velocity["velocity_trend"] = "보통"

    return velocity


def search(query: str, days: int = 14) -> dict:
    """
    yfinance를 통해 뉴스를 검색한다.

    쿼리에서 티커 심볼을 추출하여 해당 종목의 뉴스를 수집하고,
    쿼리 키워드로 필터링한다. 티커가 식별되지 않는 순수 테마/키워드
    쿼리도 폴백 경로를 통해 동작하도록 보장한다.

    Args:
        query: 검색 쿼리 (티커 심볼 포함 가능)
        days: 검색 기간 (기본 14일)

    Returns:
        dict: 검색 결과 목록 (news_velocity, status, errors 포함)
    """
    errors = []
    tokens = query.split()

    # 변경 2: 휴리스틱 기반 티커 후보 추출 (짧은 테마 키워드 오인 방지)
    ticker_candidates = [t for t in tokens if _looks_like_ticker(t)]

    # 키워드: 티커로 식별되지 않은 모든 토큰 (테마 키워드 포함)
    ticker_set = {c.upper() for c in ticker_candidates}
    keywords = [t.lower() for t in tokens if t.upper() not in ticker_set]

    cutoff = datetime.utcnow() - timedelta(days=days)
    all_results = []
    pub_times = []  # news velocity 계산용 (윈도 내 기사 발행 시각)

    # 검색 대상 티커 결정
    tickers_to_search = list(ticker_candidates)
    keyword_fallback = False

    # 변경 2(폴백): 티커가 식별 안 되면 키워드 자체로 뉴스 검색을 시도한다.
    # yfinance .news는 심볼 기반이므로, 키워드 토큰들을 후보 심볼로 사용하되
    # 거기서 나온 기사를 키워드 필터로 좁혀 키워드만으로도 결과가 비지 않게 한다.
    if not tickers_to_search and keywords:
        keyword_fallback = True
        tickers_to_search = [t for t in tokens]  # 원본 토큰을 심볼 후보로 시도

    for symbol in tickers_to_search:
        try:
            ticker = yf.Ticker(symbol.upper())
            raw_news = ticker.news or []
        except Exception as e:
            errors.append(f"{symbol}: {type(e).__name__}: {e}")
            continue

        for item in raw_news:
            try:
                content = item.get("content", {}) or {}
                pub_dt = _parse_pub_time(item, content)

                if pub_dt is not None:
                    if pub_dt < cutoff:
                        continue
                    date_str = pub_dt.strftime("%Y-%m-%d %H:%M")
                else:
                    # 시각 파싱 실패: 조용히 죽지 않고 원본 문자열 보존
                    date_str = content.get("pubDate", "") or ""

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
                    "_pub_dt": pub_dt,  # 내부용 (반환 전 제거)
                })
            except Exception as e:
                errors.append(f"{symbol} item parse: {type(e).__name__}: {e}")
                continue

    # 키워드 필터링 (티커가 아닌 단어들)
    if keywords and all_results:
        filtered = []
        for r in all_results:
            text = (r["title"] + " " + r["summary"]).lower()
            if any(kw in text for kw in keywords):
                filtered.append(r)
        # 키워드 폴백 경로에서는 반드시 필터를 적용 (테마 정확도 확보).
        # 티커 기반 경로에서는 매칭이 있을 때만 좁힌다(기존 동작 유지).
        if filtered:
            all_results = filtered
        elif keyword_fallback:
            all_results = filtered  # 폴백인데 매칭 없으면 빈 결과가 맞음

    # news velocity 계산 (필터링 후 최종 기사 기준)
    pub_times = [r["_pub_dt"] for r in all_results]
    news_velocity = _compute_news_velocity(pub_times, days)

    # 내부용 필드 제거 (JSON 직렬화 안전)
    for r in all_results:
        r.pop("_pub_dt", None)

    status = "ok"
    if errors and not all_results:
        status = "error"
    elif errors:
        status = "partial"

    return {
        "query": query,
        "tickers_searched": [t.upper() for t in tickers_to_search],
        "keyword_fallback": keyword_fallback,
        "keywords": keywords,
        "total_results": len(all_results),
        "results": all_results,
        "news_velocity": news_velocity,
        "status": status,
        "errors": errors,
    }
