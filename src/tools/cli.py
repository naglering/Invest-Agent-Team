"""통합 CLI - 모든 에이전트의 도구 진입점

사용법:
    python src/tools/cli.py fundamental <TICKER>
    python src/tools/cli.py technical <TICKER>
    python src/tools/cli.py news <TICKER>
    python src/tools/cli.py news-search "<QUERY>"
    python src/tools/cli.py earnings <TICKER>
    python src/tools/cli.py risk <TICKER>
    python src/tools/cli.py mandate-check <TICKER>
    python src/tools/cli.py valuation <TICKER>
    python src/tools/cli.py peers <TICKER>
    python src/tools/cli.py insider <TICKER>
    python src/tools/cli.py memo list
    python src/tools/cli.py memo read <TICKER>
    python src/tools/cli.py memo search "<QUERY>"
    python src/tools/cli.py memo write <TICKER>  (stdin으로 JSON 입력)
"""

import sys
import os
import json
import logging
import warnings

# yfinance 로그/경고 억제
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module="yfinance")

# src/ 디렉토리를 path에 추가 (기존 모듈 import용)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def cmd_fundamental(ticker: str) -> dict:
    from fundamental import analyze_fundamentals
    return analyze_fundamentals(ticker)


def cmd_technical(ticker: str) -> dict:
    from technical import analyze_technical
    return analyze_technical(ticker)


def cmd_news(ticker: str) -> dict:
    from news import collect_news
    return collect_news(ticker)


def cmd_news_search(query: str) -> dict:
    from tools.news_search import search
    return search(query)


def cmd_earnings(ticker: str) -> dict:
    from tools.earnings_calendar import get_earnings
    return get_earnings(ticker)


def cmd_risk(ticker: str) -> dict:
    from tools.risk_analyzer import analyze_risk
    return analyze_risk(ticker)


def cmd_mandate_check(ticker: str) -> dict:
    from tools.risk_analyzer import check_mandate
    return check_mandate(ticker)


def cmd_valuation(ticker: str) -> dict:
    from tools.valuation import analyze_valuation
    return analyze_valuation(ticker)


def cmd_peers(ticker: str) -> dict:
    from tools.peer_comparison import compare_peers
    return compare_peers(ticker)


def cmd_insider(ticker: str) -> dict:
    from tools.insider_analysis import analyze_insider
    return analyze_insider(ticker)


def cmd_memo(subcommand: str, args: list) -> dict:
    from tools.memo_manager import list_memos, read_memo, search_memos, write_memo

    if subcommand == "list":
        return list_memos()
    elif subcommand == "read":
        if not args:
            return {"error": "사용법: memo read <TICKER>"}
        return read_memo(args[0])
    elif subcommand == "search":
        if not args:
            return {"error": "사용법: memo search <QUERY>"}
        return search_memos(" ".join(args))
    elif subcommand == "write":
        if not args:
            return {"error": "사용법: memo write <TICKER> (stdin으로 JSON 입력)"}
        data = json.load(sys.stdin)
        return write_memo(args[0], data)
    else:
        return {"error": f"알 수 없는 memo 서브커맨드: {subcommand}"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "사용법: python src/tools/cli.py <command> [args]"}, ensure_ascii=False))
        sys.exit(1)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    try:
        if command == "fundamental":
            if not args:
                raise ValueError("사용법: fundamental <TICKER>")
            result = cmd_fundamental(args[0].upper())

        elif command == "technical":
            if not args:
                raise ValueError("사용법: technical <TICKER>")
            result = cmd_technical(args[0].upper())

        elif command == "news":
            if not args:
                raise ValueError("사용법: news <TICKER>")
            result = cmd_news(args[0].upper())

        elif command == "news-search":
            if not args:
                raise ValueError("사용법: news-search <QUERY>")
            result = cmd_news_search(" ".join(args))

        elif command == "earnings":
            if not args:
                raise ValueError("사용법: earnings <TICKER>")
            result = cmd_earnings(args[0].upper())

        elif command == "risk":
            if not args:
                raise ValueError("사용법: risk <TICKER>")
            result = cmd_risk(args[0].upper())

        elif command == "mandate-check":
            if not args:
                raise ValueError("사용법: mandate-check <TICKER>")
            result = cmd_mandate_check(args[0].upper())

        elif command == "valuation":
            if not args:
                raise ValueError("사용법: valuation <TICKER>")
            result = cmd_valuation(args[0].upper())

        elif command == "peers":
            if not args:
                raise ValueError("사용법: peers <TICKER>")
            result = cmd_peers(args[0].upper())

        elif command == "insider":
            if not args:
                raise ValueError("사용법: insider <TICKER>")
            result = cmd_insider(args[0].upper())

        elif command == "memo":
            if not args:
                raise ValueError("사용법: memo <list|read|search|write> [args]")
            result = cmd_memo(args[0].lower(), args[1:])

        else:
            result = {"error": f"알 수 없는 명령: {command}"}

        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
