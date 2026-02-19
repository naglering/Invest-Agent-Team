"""뉴스 수집 모듈 - yfinance 뉴스 + 기사 본문 스크래핑"""

import logging
from datetime import datetime, timedelta

import requests
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
_BODY_MAX_CHARS = 3000
_REQUEST_TIMEOUT = 5


def _scrape_body(url: str) -> str | None:
    """기사 URL에서 본문 텍스트를 추출한다."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Yahoo Finance 기사 구조 우선, 일반 <article> 폴백
        container = (
            soup.find("div", class_="caas-body")
            or soup.find("article")
            or soup.find("div", class_="article-body")
        )
        if not container:
            return None

        paragraphs = container.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
        return text[:_BODY_MAX_CHARS] if text else None
    except Exception:
        return None


def collect_news(ticker_symbol: str, days: int = 14) -> dict:
    """최근 뉴스를 수집하여 구조화된 dict로 반환한다."""
    ticker = yf.Ticker(ticker_symbol)
    cutoff = datetime.now() - timedelta(days=days)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = cutoff.strftime("%Y-%m-%d")

    raw_news = ticker.news or []

    news_items = []
    for item in raw_news:
        content = item.get("content", {})

        # 발행일 파싱
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
        url = content.get("canonicalUrl", {}).get("url", "") if isinstance(content.get("canonicalUrl"), dict) else ""
        source = content.get("provider", {}).get("displayName", "") if isinstance(content.get("provider"), dict) else ""

        # 본문 스크래핑 시도
        body = _scrape_body(url) if url else None
        if not body:
            body = summary or ""

        news_items.append({
            "date": date_str,
            "title": title,
            "summary": summary,
            "body": body,
            "source": source,
            "url": url,
        })

    return {
        "analysis_period": {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
        },
        "total_news_count": len(news_items),
        "news_items": news_items,
    }
