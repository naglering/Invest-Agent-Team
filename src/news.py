"""뉴스 수집 모듈 - yfinance 뉴스 + 기사 본문 스크래핑"""

import logging
import re
from datetime import datetime, timedelta, timezone

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

# 금융 감성 키워드
_POSITIVE_KEYWORDS = [
    "surge", "soar", "rally", "beat", "outperform", "upgrade", "bullish", "record",
    "growth", "profit", "revenue up", "expansion", "breakthrough", "innovation",
    "dividend", "buyback", "strong demand", "exceeds", "above expectations", "partnership",
    "상승", "급등", "호재", "흑자", "성장", "실적 개선", "매출 증가", "신고가",
    "수주", "계약", "배당", "자사주", "혁신", "돌파", "호실적", "컨센서스 상회",
    "목표가 상향", "투자의견 상향", "매수", "비중확대",
]

_NEGATIVE_KEYWORDS = [
    "crash", "plunge", "decline", "miss", "underperform", "downgrade", "bearish",
    "loss", "deficit", "layoff", "recall", "investigation", "lawsuit", "debt",
    "bankruptcy", "warning", "below expectations", "risk", "sell-off", "concern",
    "하락", "급락", "악재", "적자", "감소", "실적 부진", "매출 감소", "저점",
    "소송", "조사", "리콜", "부채", "경고", "하회", "손실", "구조조정",
    "목표가 하향", "투자의견 하향", "매도", "비중축소",
]

# 'risk factors' 같은 상용구로 스크래핑 본문(3,000자)에 거의 항상 등장하는
# 부정 키워드 — 체계적 부정 편향을 막기 위해 **제목에서만** 매칭한다.
_NEGATIVE_TITLE_ONLY = {"risk", "debt", "concern"}

# 업종별 경쟁사 맵 (뉴스에서 경쟁사 언급 추출용)
_COMPETITOR_MAP = {
    "TSLA": ["GM", "Ford", "Toyota", "Rivian", "BYD", "NIO", "Lucid", "Volkswagen"],
    "AAPL": ["Samsung", "Google", "Microsoft", "Huawei", "Xiaomi"],
    "NVDA": ["AMD", "Intel", "Qualcomm", "Broadcom", "ARM"],
    "MSFT": ["Google", "Amazon", "Apple", "Salesforce", "Oracle"],
    "AMZN": ["Walmart", "Alibaba", "Shopify", "eBay", "Target"],
    "GOOGL": ["Microsoft", "Meta", "Apple", "Amazon", "OpenAI"],
    "META": ["Google", "TikTok", "Snap", "Twitter", "Pinterest"],
}


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
    # 시각 기준은 UTC로 통일 (pubDate가 UTC라 로컬 naive now와 비교 시 최대 9시간 어긋남)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=days)
    end_date = now_utc.strftime("%Y-%m-%d")
    start_date = cutoff.strftime("%Y-%m-%d")

    raw_news = ticker.news or []

    news_items = []
    seen_keys = set()        # canonicalUrl 기준 중복 제거 (신디케이트 재발행 중복 가중 방지)
    skipped_undated = 0      # 발행일 미확인으로 제외한 기사 수
    for item in raw_news:
        content = item.get("content", {})

        # 발행일 파싱 — 실패/부재 기사는 기간 필터를 우회시키지 않고 제외
        pub_dt = None
        pub_date_str = content.get("pubDate", "")
        if pub_date_str:
            try:
                pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pub_dt = None
        if pub_dt is None:
            skipped_undated += 1
            continue
        if pub_dt < cutoff:
            continue
        date_str = pub_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")

        title = content.get("title", "")
        summary = content.get("summary", content.get("description", ""))
        url = content.get("canonicalUrl", {}).get("url", "") if isinstance(content.get("canonicalUrl"), dict) else ""
        source = content.get("provider", {}).get("displayName", "") if isinstance(content.get("provider"), dict) else ""

        # 동일 기사 중복 제거 (URL 우선, 없으면 제목+출처)
        dedupe_key = url or (title.strip().lower(), source)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

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

    # --- 키워드 감성 스코어링 ---
    for item in news_items:
        title_text = item.get("title", "").lower()
        text = (item.get("title", "") + " " + item.get("body", "")).lower()
        pos_count = sum(1 for kw in _POSITIVE_KEYWORDS if kw.lower() in text)
        # 상용구성 부정 키워드(risk/debt/concern)는 제목에서만 매칭 (본문 상용구 편향 방지)
        neg_count = sum(
            1 for kw in _NEGATIVE_KEYWORDS
            if kw.lower() in (title_text if kw.lower() in _NEGATIVE_TITLE_ONLY else text)
        )
        total_kw = pos_count + neg_count
        if total_kw > 0:
            item["sentiment_score"] = round((pos_count - neg_count) / total_kw, 2)
        else:
            item["sentiment_score"] = 0.0
        item["positive_keywords"] = pos_count
        item["negative_keywords"] = neg_count

    # 평균은 감성 키워드가 실제 매칭된 기사만으로 계산 — 0점 기사 희석으로
    # 강한 호재/악재 흐름이 '중립'으로 수렴하는 보수 편향 방지
    scored_items = [
        item for item in news_items
        if item["positive_keywords"] + item["negative_keywords"] > 0
    ]
    avg_sentiment = round(
        sum(item["sentiment_score"] for item in scored_items) / len(scored_items), 3
    ) if scored_items else 0.0

    sentiment_label = (
        "중립 (감성 키워드 매칭 기사 없음)" if not scored_items
        else "긍정적" if avg_sentiment > 0.2
        else "부정적" if avg_sentiment < -0.2
        else "중립"
    )

    # --- 경쟁사 언급 추출 ---
    ticker_upper = ticker_symbol.upper()
    competitors = _COMPETITOR_MAP.get(ticker_upper, [])
    competitor_mentions = {}
    if competitors:
        all_text = " ".join(
            (item.get("title", "") + " " + item.get("body", ""))
            for item in news_items
        ).lower()
        for comp in competitors:
            # \b 단어 경계 매칭 — 'ARM'이 harm/farm/warming, 'Ford'가 afford에 매칭되는 과대 집계 방지
            count = len(re.findall(r"\b" + re.escape(comp.lower()) + r"\b", all_text))
            if count > 0:
                competitor_mentions[comp] = count

    return {
        "analysis_period": {
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
        },
        "total_news_count": len(news_items),
        "skipped_undated_count": skipped_undated,  # 발행일 미확인으로 기간 검증 불가 → 제외된 기사 수
        "news_items": news_items,
        "sentiment": {
            "average_score": avg_sentiment,
            "label": sentiment_label,
            "scored_count": len(scored_items),
        },
        "competitor_mentions": competitor_mentions,
    }
