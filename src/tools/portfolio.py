"""포트폴리오 관리 도구

data/portfolio.md 의 보유 종목 테이블을 읽어 현재가·환율을 조회하고
평가금액·손익·비중을 계산한다.

테이블 컬럼: 종목 | 수량 | 매입가 | 통화 | 매입시환율
 - 통화: USD 또는 KRW
 - 매입시환율: USD 종목만 (매입 시점 원/달러). KRW 종목은 '-' 또는 공란
 - 손익은 현지통화 기준(순수 자산수익)과 원화 기준(환손익 포함) 둘 다 산출
"""

import os

import yfinance as yf

# data/portfolio.md 기본 경로 (이 파일: src/tools/portfolio.py → repo 루트로 2단계 상위)
_DEFAULT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "portfolio.md"
)

# 컬럼 헤더 별칭 → 표준 키
_HEADER_MAP = {
    "종목": "ticker", "티커": "ticker", "ticker": "ticker",
    "수량": "quantity", "주수": "quantity", "qty": "quantity",
    "매입가": "buy_price", "진입가": "buy_price", "평단": "buy_price",
    "통화": "currency", "ccy": "currency",
    "매입시환율": "buy_fx", "환율": "buy_fx", "매입환율": "buy_fx",
}


def _to_float(s):
    """쉼표/통화기호 제거 후 float. 빈값/'-'/'N/A'는 None."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("$", "").replace("₩", "")
    if t in ("", "-", "—", "N/A", "n/a"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _norm_currency(s):
    t = str(s).strip().upper()
    if t in ("USD", "$", "달러", "USD($)"):
        return "USD"
    if t in ("KRW", "원", "₩", "WON"):
        return "KRW"
    return t or "KRW"


def load_holdings(path: str = None) -> list:
    """portfolio.md 의 첫 번째 마크다운 테이블을 파싱해 보유 종목 리스트 반환."""
    path = path or _DEFAULT_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"포트폴리오 파일 없음: {path}")

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    # 첫 번째 연속된 '|' 블록을 테이블로 인식
    table = []
    in_table = False
    for line in lines:
        if line.lstrip().startswith("|"):
            table.append(line.strip())
            in_table = True
        elif in_table:
            break  # 테이블 종료

    if len(table) < 3:
        raise ValueError("보유 종목 테이블을 찾지 못했습니다 (헤더+구분선+데이터 행 필요).")

    def split_row(row):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        return cells

    headers = [_HEADER_MAP.get(h, h) for h in split_row(table[0])]
    holdings = []
    for row in table[2:]:  # table[1] = 구분선(---)
        cells = split_row(row)
        if not any(cells):
            continue
        rec = dict(zip(headers, cells))
        ticker = (rec.get("ticker") or "").strip()
        if not ticker:
            continue
        currency = _norm_currency(rec.get("currency"))
        holdings.append({
            "ticker": ticker,
            "quantity": _to_float(rec.get("quantity")) or 0.0,
            "buy_price": _to_float(rec.get("buy_price")) or 0.0,
            "currency": currency,
            "buy_fx": _to_float(rec.get("buy_fx")),
        })
    return holdings


# 파일이 없을 때 새로 만들 포트폴리오 골격 (예시 행 없음 — 깨끗한 시작)
_PORTFOLIO_SCAFFOLD = """# 내 포트폴리오 (보유 종목)

`python3 src/tools/cli.py portfolio` 로 현재가·환율을 조회해 평가/손익/비중을 계산합니다.
행 추가/삭제는 `portfolio add` / `portfolio remove` 또는 직접 편집.

| 종목 | 수량 | 매입가 | 통화 | 매입시환율 |
|------|------|--------|------|-----------|
"""


def _suggest_currency(ticker: str, listed_ccy: str = None) -> str:
    """티커로 통화 추정. 한국(.KS/.KQ)=KRW, 그 외는 상장통화 또는 USD."""
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "KRW"
    return (listed_ccy or "USD").upper()


def _num(v) -> str:
    """숫자를 표 셀 문자열로. 정수면 정수, 아니면 불필요한 0 제거."""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


def quote(ticker: str) -> dict:
    """매수 입력을 돕기 위한 간단 종목 정보(이름·현재가·통화·섹터·52주 범위·시총)."""
    ticker = ticker.strip()
    tk = yf.Ticker(ticker)
    info = {}
    try:
        info = tk.get_info() or {}
    except Exception:
        pass
    price, listed_ccy = _fetch_price(ticker)
    ccy = info.get("currency") or listed_ccy
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "current_price": round(price, 2) if price else None,
        "currency": ccy.upper() if ccy else None,
        "suggested_currency": _suggest_currency(ticker, ccy),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "quote_type": info.get("quoteType"),
        "hint": "수량 | 매입가 | 통화(USD/KRW) | 매입시환율(USD만, 매입 시점 원/달러)을 입력하세요.",
    }


def _read_first_table(path: str):
    """portfolio.md 의 첫 마크다운 테이블 위치를 찾는다.
    반환: (lines, start, end) — start=헤더행 인덱스, end=테이블 다음 인덱스(exclusive)."""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            start = i
            break
    if start is None:
        raise ValueError("보유 종목 테이블을 찾지 못했습니다.")
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    return lines, start, end


def _split_row(row: str):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _render_row(headers_raw, rec: dict) -> str:
    """헤더 컬럼 순서에 맞춰 한 행을 렌더링."""
    cells = []
    for h in headers_raw:
        key = _HEADER_MAP.get(h.strip(), h.strip())
        if key == "ticker":
            cells.append(str(rec["ticker"]))
        elif key == "quantity":
            cells.append(_num(rec["quantity"]))
        elif key == "buy_price":
            cells.append(_num(rec["buy_price"]))
        elif key == "currency":
            cells.append(rec["currency"])
        elif key == "buy_fx":
            fx = rec.get("buy_fx")
            cells.append(_num(fx) if fx not in (None, "", "-") else "-")
        else:
            cells.append("")
    return "| " + " | ".join(cells) + " |\n"


def _load_records(path: str):
    """현재 테이블의 행들을 (lines, start, end, headers_raw, records) 로 로드."""
    lines, start, end = _read_first_table(path)
    headers_raw = _split_row(lines[start])
    headers = [_HEADER_MAP.get(h, h) for h in headers_raw]
    records = []
    for row in lines[start + 2:end]:  # start+1 = 구분선
        cells = _split_row(row)
        if not any(cells):
            continue
        rec = dict(zip(headers, cells))
        if (rec.get("ticker") or "").strip():
            records.append(rec)
    return lines, start, end, headers_raw, records


def _write_table(path: str, lines, start, end, headers_raw, records):
    """헤더+구분선은 보존하고 데이터 행만 재작성하여 파일 저장."""
    new_rows = [_render_row(headers_raw, _std_rec(r)) for r in records]
    new_lines = lines[:start + 2] + new_rows + lines[end:]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _std_rec(r: dict) -> dict:
    """원시 행 dict → 렌더용 표준 dict."""
    return {
        "ticker": (r.get("ticker") or "").strip(),
        "quantity": _to_float(r.get("quantity")) or 0,
        "buy_price": _to_float(r.get("buy_price")) or 0,
        "currency": _norm_currency(r.get("currency")),
        "buy_fx": r.get("buy_fx"),
    }


def add_holding(ticker, quantity, buy_price, currency=None, buy_fx=None, path=None) -> dict:
    """보유 종목 추가/수정(매수). 같은 티커가 있으면 덮어쓴다. 파일 없으면 생성."""
    path = path or _DEFAULT_PATH
    ticker = str(ticker).strip()
    currency = _norm_currency(currency) if currency else _suggest_currency(ticker)
    warnings = []
    if currency == "USD" and buy_fx in (None, "", "-"):
        warnings.append("USD 종목인데 매입시환율 누락 → 원화 손익 계산이 부정확합니다.")

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(_PORTFOLIO_SCAFFOLD)

    lines, start, end, headers_raw, records = _load_records(path)
    new_rec = {
        "ticker": ticker, "quantity": quantity, "buy_price": buy_price,
        "currency": currency, "buy_fx": buy_fx,
    }
    action = "added"
    for i, r in enumerate(records):
        if (r.get("ticker") or "").strip().upper() == ticker.upper():
            records[i] = new_rec
            action = "updated"
            break
    else:
        records.append(new_rec)
    _write_table(path, lines, start, end, headers_raw, records)
    return {"action": action, "ticker": ticker, "quantity": _num(quantity),
            "buy_price": _num(buy_price), "currency": currency,
            "buy_fx": (_num(buy_fx) if buy_fx not in (None, "", "-") else "-"),
            "count": len(records), "warnings": warnings}


def remove_holding(ticker, path=None) -> dict:
    """보유 종목 삭제(매도). 티커 일치 행을 제거."""
    path = path or _DEFAULT_PATH
    ticker = str(ticker).strip()
    if not os.path.exists(path):
        return {"error": f"포트폴리오 파일 없음: {path}"}
    lines, start, end, headers_raw, records = _load_records(path)
    kept = [r for r in records if (r.get("ticker") or "").strip().upper() != ticker.upper()]
    removed = len(records) - len(kept)
    if removed == 0:
        return {"action": "not_found", "ticker": ticker,
                "message": f"{ticker} 보유 종목에 없음", "count": len(records)}
    _write_table(path, lines, start, end, headers_raw, kept)
    return {"action": "removed", "ticker": ticker, "removed": removed, "count": len(kept)}


def _fetch_price(ticker: str):
    """현재가와 상장통화 반환. 실패 시 (None, None)."""
    try:
        tk = yf.Ticker(ticker)
        price, listed_ccy = None, None
        try:
            fi = tk.fast_info
            price = fi.get("last_price") or fi.get("lastPrice")
            listed_ccy = fi.get("currency")
        except Exception:
            pass
        if price is None:
            hist = tk.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].dropna().iloc[-1])
        return (float(price) if price else None,
                listed_ccy.upper() if listed_ccy else None)
    except Exception:
        return (None, None)


def _fetch_usdkrw():
    """현재 원/달러 환율. 실패 시 None."""
    price, _ = _fetch_price("USDKRW=X")
    return price


def analyze_portfolio(path: str = None, fx_override: float = None) -> dict:
    """보유 종목을 평가하여 종목별 손익·비중과 합계를 계산."""
    holdings = load_holdings(path)
    if not holdings:
        return {"error": "보유 종목이 없습니다.", "holdings": [], "totals": {}}

    needs_fx = any(h["currency"] == "USD" for h in holdings)
    usdkrw = fx_override or (_fetch_usdkrw() if needs_fx else None)

    rows, warnings = [], []
    total_cost_krw = total_value_krw = 0.0

    for h in holdings:
        price, listed_ccy = _fetch_price(h["ticker"])
        qty, buy = h["quantity"], h["buy_price"]
        ccy = h["currency"]

        # 통화별 원화 환산 환율 결정
        if ccy == "USD":
            cur_fx = usdkrw
            buy_fx = h["buy_fx"] or usdkrw  # 매입환율 없으면 현재환율로 대체(경고)
            if h["buy_fx"] is None:
                warnings.append(f"{h['ticker']}: 매입시환율 누락 → 현재환율로 대체(원화 손익 부정확)")
        else:  # KRW
            cur_fx = buy_fx = 1.0

        if listed_ccy and ccy and listed_ccy != ccy:
            warnings.append(f"{h['ticker']}: 입력통화({ccy}) ≠ 상장통화({listed_ccy})")

        cost_native = qty * buy
        cost_krw = cost_native * buy_fx

        if price is None:
            warnings.append(f"{h['ticker']}: 현재가 조회 실패")
            rows.append({
                **h, "current_price": None, "value_native": None,
                "value_krw": None, "pnl_native": None, "pnl_pct_native": None,
                "pnl_krw": None, "pnl_pct_krw": None, "weight_pct": None,
                "cost_krw": round(cost_krw, 0),
            })
            total_cost_krw += cost_krw
            continue

        value_native = qty * price
        value_krw = value_native * (cur_fx if ccy == "USD" else 1.0)
        pnl_native = value_native - cost_native
        pnl_krw = value_krw - cost_krw

        rows.append({
            "ticker": h["ticker"],
            "quantity": qty,
            "buy_price": buy,
            "currency": ccy,
            "buy_fx": h["buy_fx"],
            "current_price": round(price, 2),
            "current_fx": round(cur_fx, 2) if ccy == "USD" else None,
            "cost_krw": round(cost_krw, 0),
            "value_native": round(value_native, 2),
            "value_krw": round(value_krw, 0),
            "pnl_native": round(pnl_native, 2),
            "pnl_pct_native": round(pnl_native / cost_native * 100, 2) if cost_native else None,
            "pnl_krw": round(pnl_krw, 0),
            "pnl_pct_krw": round(pnl_krw / cost_krw * 100, 2) if cost_krw else None,
            "weight_pct": None,  # 합계 후 채움
        })
        total_cost_krw += cost_krw
        total_value_krw += value_krw

    # 비중 계산
    for r in rows:
        if r.get("value_krw"):
            r["weight_pct"] = round(r["value_krw"] / total_value_krw * 100, 2) if total_value_krw else None

    total_pnl_krw = total_value_krw - total_cost_krw
    return {
        "usdkrw": round(usdkrw, 2) if usdkrw else None,
        "holdings": rows,
        "totals": {
            "cost_krw": round(total_cost_krw, 0),
            "value_krw": round(total_value_krw, 0),
            "pnl_krw": round(total_pnl_krw, 0),
            "pnl_pct": round(total_pnl_krw / total_cost_krw * 100, 2) if total_cost_krw else None,
        },
        "warnings": warnings,
    }


def _fmt(n, dec=0):
    if n is None:
        return "N/A"
    if dec == 0:
        return f"{n:,.0f}"
    return f"{n:,.{dec}f}"


def _sign(n, dec=0, pct=False):
    if n is None:
        return "N/A"
    s = "+" if n >= 0 else ""
    suf = "%" if pct else ""
    return f"{s}{_fmt(n, dec)}{suf}"


def render_table(result: dict) -> str:
    """analyze_portfolio 결과를 사람이 읽는 텍스트 테이블로 렌더링."""
    if result.get("error"):
        return f"오류: {result['error']}"

    rows = result["holdings"]
    t = result["totals"]
    out = []
    fx = result.get("usdkrw")
    out.append("=" * 96)
    hdr = f"📊 내 포트폴리오  (원/달러 {_fmt(fx, 2) if fx else 'N/A'})"
    out.append(hdr)
    out.append("=" * 96)

    cols = (f"{'종목':<11}{'수량':>7}{'매입가':>11}{'현재가':>11}"
            f"{'평가(KRW)':>15}{'손익(KRW)':>15}{'손익%':>9}{'비중':>7}")
    out.append(cols)
    out.append("-" * 96)

    for r in rows:
        line = (
            f"{r['ticker']:<11}"
            f"{_fmt(r.get('quantity'), 0):>7}"
            f"{_fmt(r.get('buy_price'), 2):>11}"
            f"{_fmt(r.get('current_price'), 2):>11}"
            f"{_fmt(r.get('value_krw'), 0):>15}"
            f"{_sign(r.get('pnl_krw'), 0):>15}"
            f"{_sign(r.get('pnl_pct_krw'), 1, pct=True):>9}"
            f"{(_fmt(r.get('weight_pct'), 1) + '%') if r.get('weight_pct') is not None else 'N/A':>7}"
        )
        out.append(line)

    out.append("-" * 96)
    total_line = (
        f"{'합계':<11}{'':>7}{'':>11}{'':>11}"
        f"{_fmt(t.get('value_krw'), 0):>15}"
        f"{_sign(t.get('pnl_krw'), 0):>15}"
        f"{_sign(t.get('pnl_pct'), 1, pct=True):>9}"
        f"{'100%':>7}"
    )
    out.append(total_line)
    out.append("=" * 96)
    out.append(f"투자원금(KRW): {_fmt(t.get('cost_krw'))}    평가액(KRW): {_fmt(t.get('value_krw'))}")

    # 종목별 현지통화 수익률(환손익 분리) 보조 표기
    usd_rows = [r for r in rows if r.get("currency") == "USD" and r.get("pnl_pct_native") is not None]
    if usd_rows:
        out.append("-" * 96)
        out.append("현지통화 기준 수익률(환율 효과 제외):")
        for r in usd_rows:
            out.append(f"  {r['ticker']:<11} {_sign(r['pnl_pct_native'], 1, pct=True)}  "
                       f"(원화 {_sign(r.get('pnl_pct_krw'), 1, pct=True)})")

    if result.get("warnings"):
        out.append("-" * 96)
        out.append("⚠️  경고:")
        for w in result["warnings"]:
            out.append(f"  - {w}")

    return "\n".join(out)
