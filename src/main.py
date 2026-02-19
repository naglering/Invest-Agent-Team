"""주식 분석 오케스트레이터 - 재무 + 기술적 분석 통합 JSON 출력"""

import sys
import json
import logging
import warnings
from datetime import datetime

# yfinance의 HTTP 에러 로그 및 경고 억제
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module="yfinance")

from fundamental import analyze_fundamentals
from technical import analyze_technical
from news import collect_news


def analyze(ticker_symbol: str) -> dict:
    """재무 분석과 기술적 분석을 통합하여 결과를 반환한다."""
    result = {
        "ticker": ticker_symbol,
        "analyzed_at": datetime.now().isoformat(),
        "fundamental": None,
        "technical": None,
        "news": None,
        "errors": [],
    }

    # 재무 분석
    try:
        result["fundamental"] = analyze_fundamentals(ticker_symbol)
    except Exception as e:
        result["errors"].append({"module": "fundamental", "error": str(e)})

    # 기술적 분석
    try:
        result["technical"] = analyze_technical(ticker_symbol)
    except Exception as e:
        result["errors"].append({"module": "technical", "error": str(e)})

    # 뉴스 수집
    try:
        result["news"] = collect_news(ticker_symbol)
    except Exception as e:
        result["errors"].append({"module": "news", "error": str(e)})

    if result["fundamental"] is None and result["technical"] is None:
        raise ValueError(
            f"'{ticker_symbol}'에 대한 분석 데이터를 가져올 수 없습니다. "
            f"티커 심볼을 확인해주세요. (미국: AAPL, 한국: 005930.KS)"
        )

    return result


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "사용법: python src/main.py <TICKER>  (예: AAPL, 005930.KS)"}))
        sys.exit(1)

    ticker_symbol = sys.argv[1].strip().upper()

    try:
        result = analyze(ticker_symbol)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except ValueError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"예상치 못한 오류: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
