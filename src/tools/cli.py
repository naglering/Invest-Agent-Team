"""통합 CLI - 모든 에이전트의 도구 진입점

사용법:
    python src/tools/cli.py fundamental <TICKER>
    python src/tools/cli.py technical <TICKER>
    python src/tools/cli.py news <TICKER>
    python src/tools/cli.py news-search "<QUERY>"
    python src/tools/cli.py earnings <TICKER>
    python src/tools/cli.py risk <TICKER> [--mandate default|megatrend] [--conviction 0.5~2.0] [--entry-mode breakout|accumulate|full] [--stop-loss-pct N]
    python src/tools/cli.py mandate-check <TICKER> [--mandate default|megatrend]
    python src/tools/cli.py valuation <TICKER>
    python src/tools/cli.py peers <TICKER>
    python src/tools/cli.py insider <TICKER>
    python src/tools/cli.py momentum <TICKER>           (상대강도·신고가 돌파·거래량)
    python src/tools/cli.py sectors                     (테마·섹터 자금흐름 랭킹 — 발굴)
    python src/tools/cli.py memo list
    python src/tools/cli.py memo read <TICKER>
    python src/tools/cli.py memo search "<QUERY>"
    python src/tools/cli.py memo write <TICKER>  (stdin으로 JSON 입력)
    python src/tools/cli.py portfolio                  (data/portfolio.md 평가 — 테이블)
    python src/tools/cli.py portfolio --json           (JSON 출력)
    python src/tools/cli.py portfolio --file <PATH>    (다른 포트폴리오 파일)
    python src/tools/cli.py portfolio --fx <RATE>      (원/달러 환율 수동 지정)
    python src/tools/cli.py portfolio init [--force]   (portfolio/theses/positions 템플릿 생성)
    python src/tools/cli.py setup [--force]            (data/mandates/*.json 정본 생성)
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


def cmd_risk(ticker: str, mandate: str = None, conviction: float = None,
             entry_mode: str = "accumulate", stop_loss_pct: float = None) -> dict:
    from tools.risk_analyzer import analyze_risk
    return analyze_risk(ticker, mandate_profile=mandate, conviction=conviction,
                        entry_mode=entry_mode, stop_loss_pct=stop_loss_pct)


def cmd_mandate_check(ticker: str, mandate: str = None) -> dict:
    from tools.risk_analyzer import check_mandate
    return check_mandate(ticker, mandate_profile=mandate)


def cmd_momentum(ticker: str) -> dict:
    from tools.momentum import analyze_momentum
    return analyze_momentum(ticker)


def cmd_sectors() -> dict:
    from tools.sector_scan import scan_sectors
    return scan_sectors()


def _parse_opt(args: list, name: str):
    """--name value 형태 옵션 파싱(없으면 None)."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None


def cmd_valuation(ticker: str) -> dict:
    from tools.valuation import analyze_valuation
    return analyze_valuation(ticker)


def cmd_peers(ticker: str, custom_peers: list = None) -> dict:
    from tools.peer_comparison import compare_peers
    return compare_peers(ticker, custom_peers=custom_peers)


def cmd_insider(ticker: str) -> dict:
    from tools.insider_analysis import analyze_insider
    return analyze_insider(ticker)


def cmd_setup(args: list) -> dict:
    """data/mandates/{default,megatrend}.json 정본 생성."""
    from tools.setup_tool import setup_mandates
    return setup_mandates(force="--force" in args)


def cmd_portfolio(args: list):
    """포트폴리오 평가. 기본은 텍스트 테이블 출력, --json 시 dict 반환.

    `portfolio init` 서브커맨드는 개인 데이터 템플릿을 생성한다.
    반환값: dict(--json/init 모드) 또는 None(테이블을 직접 출력한 경우).
    """
    if args and args[0] == "init":
        from tools.setup_tool import setup_portfolio
        return setup_portfolio(force="--force" in args)

    from tools.portfolio import analyze_portfolio, render_table

    as_json = "--json" in args
    path = None
    fx = None
    for i, a in enumerate(args):
        if a == "--file" and i + 1 < len(args):
            path = args[i + 1]
        elif a == "--fx" and i + 1 < len(args):
            fx = float(args[i + 1])

    result = analyze_portfolio(path=path, fx_override=fx)
    if as_json:
        return result
    print(render_table(result))
    return None


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
                raise ValueError("사용법: risk <TICKER> [--mandate ...] [--conviction ...] [--entry-mode ...] [--stop-loss-pct ...]")
            conv = _parse_opt(args, "--conviction")
            slp = _parse_opt(args, "--stop-loss-pct")
            result = cmd_risk(
                args[0].upper(),
                mandate=_parse_opt(args, "--mandate"),
                conviction=float(conv) if conv else None,
                entry_mode=_parse_opt(args, "--entry-mode") or "accumulate",
                stop_loss_pct=float(slp) if slp else None,
            )

        elif command == "mandate-check":
            if not args:
                raise ValueError("사용법: mandate-check <TICKER> [--mandate default|megatrend]")
            result = cmd_mandate_check(args[0].upper(), mandate=_parse_opt(args, "--mandate"))

        elif command == "momentum":
            if not args:
                raise ValueError("사용법: momentum <TICKER>")
            result = cmd_momentum(args[0].upper())

        elif command == "sectors":
            result = cmd_sectors()

        elif command == "valuation":
            if not args:
                raise ValueError("사용법: valuation <TICKER>")
            result = cmd_valuation(args[0].upper())

        elif command == "peers":
            if not args:
                raise ValueError("사용법: peers <TICKER> [--peers T1,T2,T3]")
            ticker_arg = args[0].upper()
            custom_peers = None
            for i, a in enumerate(args[1:], 1):
                if a == "--peers" and i + 1 < len(args):
                    custom_peers = [p.strip().upper() for p in args[i + 1].split(",") if p.strip()]
                    break
            result = cmd_peers(ticker_arg, custom_peers=custom_peers)

        elif command == "insider":
            if not args:
                raise ValueError("사용법: insider <TICKER>")
            result = cmd_insider(args[0].upper())

        elif command == "memo":
            if not args:
                raise ValueError("사용법: memo <list|read|search|write> [args]")
            result = cmd_memo(args[0].lower(), args[1:])

        elif command == "portfolio":
            result = cmd_portfolio(args)  # 테이블 직접 출력 시 None 반환

        elif command == "setup":
            result = cmd_setup(args)

        else:
            result = {"error": f"알 수 없는 명령: {command}"}

        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
