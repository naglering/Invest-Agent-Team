"""메모 관리 도구 - Memo Writer 에이전트용

투자 메모 작성, 조회, 검색 기능 제공.
메모 저장 위치: data/memos/YYYY-MM-DD_TICKER.md
"""

import os
import re
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MEMOS_DIR = os.path.join(DATA_DIR, "memos")


def _ensure_dir():
    os.makedirs(MEMOS_DIR, exist_ok=True)


def _memo_filename(ticker: str, date: str = None) -> str:
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return f"{date}_{ticker.upper()}.md"


def _memo_path(ticker: str, date: str = None) -> str:
    return os.path.join(MEMOS_DIR, _memo_filename(ticker, date))


MEMO_TEMPLATE = """# 투자 메모: {ticker} ({company_name})

**작성일**: {date}
**분석가**: {analyst}
**확신도**: {conviction}

---

## 투자 논거 (Thesis)

{thesis}

## 재무 요약

{financial_summary}

## 밸류에이션 분석 요약

{valuation_summary}

## 기술적 분석 요약

{technical_summary}

## 리스크 요인

{risk_factors}

## 투자 결정

### 현재 보유자
- **권고**: {decision_holder}

### 신규 투자자
- **권고**: {decision_new}

- **목표가**: {target_price}
- **손절가**: {stop_loss}

## 포지션 사이징

{position_sizing}

## 시나리오 분석

{scenario_analysis}

## 후속 조치

{follow_up}

---

*이 메모는 투자 참고 자료이며, 투자 권유가 아닙니다.*
"""


def write_memo(ticker: str, data: dict) -> dict:
    """
    투자 메모를 작성하여 파일로 저장한다.

    Args:
        ticker: 종목 티커
        data: 메모 데이터 (dict). 키:
            - company_name, analyst, conviction, thesis,
            - financial_summary, technical_summary, risk_factors,
            - decision, target_price, stop_loss, follow_up

    Returns:
        dict: 저장된 파일 경로 및 메타데이터
    """
    _ensure_dir()
    date = datetime.now().strftime("%Y-%m-%d")

    # decision 하위 호환: 기존 단일 decision 필드도 지원
    decision_holder = data.get("decision_holder", data.get("decision", "N/A"))
    decision_new = data.get("decision_new", data.get("decision", "N/A"))

    content = MEMO_TEMPLATE.format(
        ticker=ticker.upper(),
        company_name=data.get("company_name", "N/A"),
        date=date,
        analyst=data.get("analyst", "Investment Agent Team"),
        conviction=data.get("conviction", "N/A"),
        thesis=data.get("thesis", "N/A"),
        financial_summary=data.get("financial_summary", "N/A"),
        valuation_summary=data.get("valuation_summary", "N/A"),
        technical_summary=data.get("technical_summary", "N/A"),
        risk_factors=data.get("risk_factors", "N/A"),
        decision_holder=decision_holder,
        decision_new=decision_new,
        target_price=data.get("target_price", "N/A"),
        stop_loss=data.get("stop_loss", "N/A"),
        position_sizing=data.get("position_sizing", "N/A"),
        scenario_analysis=data.get("scenario_analysis", "N/A"),
        follow_up=data.get("follow_up", "N/A"),
    )

    filepath = _memo_path(ticker, date)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return {
        "status": "success",
        "file_path": filepath,
        "filename": _memo_filename(ticker, date),
        "ticker": ticker.upper(),
        "date": date,
    }


def read_memo(ticker: str) -> dict:
    """
    특정 티커의 가장 최신 메모를 읽는다.

    Args:
        ticker: 종목 티커

    Returns:
        dict: 메모 내용 및 메타데이터
    """
    _ensure_dir()
    ticker = ticker.upper()

    # 해당 티커의 메모 파일 찾기 (최신순)
    matching = []
    for fname in os.listdir(MEMOS_DIR):
        if fname.endswith(f"_{ticker}.md"):
            matching.append(fname)

    if not matching:
        return {"error": f"티커 '{ticker}'에 대한 메모가 없습니다.", "ticker": ticker}

    matching.sort(reverse=True)  # 최신 날짜 우선
    latest = matching[0]
    filepath = os.path.join(MEMOS_DIR, latest)

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    return {
        "ticker": ticker,
        "filename": latest,
        "file_path": filepath,
        "content": content,
        "all_memos": matching,
    }


def list_memos() -> dict:
    """
    저장된 모든 메모 목록을 반환한다.

    Returns:
        dict: 메모 파일 목록 및 메타데이터
    """
    _ensure_dir()

    memos = []
    for fname in sorted(os.listdir(MEMOS_DIR), reverse=True):
        if fname.endswith(".md") and fname != "README.md":
            # YYYY-MM-DD_TICKER.md 형식 파싱
            match = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)\.md", fname)
            if match:
                memos.append({
                    "filename": fname,
                    "date": match.group(1),
                    "ticker": match.group(2),
                })

    return {
        "total_count": len(memos),
        "memos": memos,
        "directory": MEMOS_DIR,
    }


def search_memos(query: str) -> dict:
    """
    메모 내용에서 키워드를 검색한다.

    Args:
        query: 검색어

    Returns:
        dict: 매칭된 메모 목록
    """
    _ensure_dir()
    query_lower = query.lower()
    results = []

    for fname in sorted(os.listdir(MEMOS_DIR), reverse=True):
        if not fname.endswith(".md") or fname == "README.md":
            continue

        filepath = os.path.join(MEMOS_DIR, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if query_lower in content.lower():
            # 매칭 라인 추출 (최대 3줄)
            matching_lines = [
                line.strip() for line in content.split("\n")
                if query_lower in line.lower() and line.strip()
            ][:3]

            match = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)\.md", fname)
            results.append({
                "filename": fname,
                "date": match.group(1) if match else "",
                "ticker": match.group(2) if match else "",
                "matching_lines": matching_lines,
            })

    return {
        "query": query,
        "total_results": len(results),
        "results": results,
    }
