"""포트폴리오 관리 도구

data/portfolio.md 의 보유 종목 테이블을 읽어 현재가·환율을 조회하고
평가금액·손익·비중을 계산한다.

테이블 컬럼(정본 8컬럼): 종목 | 수량 | 평단 | 통화 | 매입환율 | 손절가 | 목표가 | 진입일
 - 통화: USD/KRW 권장. 그 외(EUR 등)는 평가 시 <CCY>KRW=X 환율을 자동 조회해 환산
 - 매입환율: 비KRW 종목만 (매입 시점 원화 환율). KRW 종목은 '-' 또는 공란
 - 손절가: 매입 통화 기준 숫자 또는 트레일링 규칙 문자열(예: MA20, 직전고점-15%)
 - 목표가: 매입 통화 기준 숫자
 - 손익은 현지통화 기준(순수 자산수익)과 원화 기준(환손익 포함) 둘 다 산출
 - 구 5컬럼(종목|수량|매입가|통화|매입시환율) 파일도 파싱 허용 — 누락 컬럼은 None
 - 매수/매도 체결은 data/trades.jsonl 원장에 1행 1 JSON으로 기록(성과 피드백 루프 원천)
"""

import json
import os
import re
import statistics
from datetime import date

import yfinance as yf

# data/portfolio.md 기본 경로 (이 파일: src/tools/portfolio.py → repo 루트로 2단계 상위)
_DEFAULT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "portfolio.md"
)

# 체결 레저(매수/매도 원장) 기본 경로 — 1행 1 JSON append
_TRADES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "trades.jsonl"
)

# 컬럼 헤더 별칭 → 표준 키
_HEADER_MAP = {
    "종목": "ticker", "티커": "ticker", "ticker": "ticker",
    "수량": "quantity", "주수": "quantity", "qty": "quantity",
    "매입가": "buy_price", "진입가": "buy_price", "평단": "buy_price",
    "통화": "currency", "ccy": "currency",
    "매입시환율": "buy_fx", "환율": "buy_fx", "매입환율": "buy_fx",
    "손절가": "stop", "손절": "stop", "stop": "stop",
    "목표가": "target", "목표": "target", "target": "target",
    "진입일": "entry_date", "매수일": "entry_date", "entry": "entry_date",
}

# 정본 8컬럼 헤더 — 구 5컬럼 파일에 손절가/목표가/진입일을 쓸 때 이 스키마로 승격
_CANON_HEADERS = ["종목", "수량", "평단", "통화", "매입환율", "손절가", "목표가", "진입일"]

# 손절선 '근접' 판정 문턱(%) — 현재가가 손절선 위 이 비율 이내면 근접
_NEAR_PCT = 3.0


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


def _stop_value(s):
    """손절가 셀 → float(고정가) 또는 트레일링 규칙 문자열(MA20/직전고점-15% 등).
    빈값/'-'는 None."""
    if s is None:
        return None
    t = str(s).strip()
    if t in ("", "-", "—", "N/A", "n/a"):
        return None
    v = _to_float(t)
    return v if v is not None else t


def _clean_str(s):
    """표 셀 문자열 정리 — 빈값/'-'는 None."""
    if s is None:
        return None
    t = str(s).strip()
    return None if t in ("", "-", "—", "N/A", "n/a") else t


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
            # 구 5컬럼 파일이면 아래는 전부 None
            "stop": _stop_value(rec.get("stop")),
            "target": _to_float(rec.get("target")),
            "entry_date": _clean_str(rec.get("entry_date")),
        })
    return holdings


# 파일이 없을 때 새로 만들 포트폴리오 골격 (예시 행 없음 — 깨끗한 시작)
_PORTFOLIO_SCAFFOLD = """# 내 포트폴리오 (보유 종목)

`python3 src/tools/cli.py portfolio` 로 현재가·환율을 조회해 평가/손익/비중을 계산합니다.
행 추가/삭제는 `portfolio add` / `portfolio sell` / `portfolio remove` 또는 직접 편집.
손절가는 숫자 또는 트레일링 규칙(MA20, 직전고점-15%) — `portfolio check` 로 위반 여부 점검.

| 종목 | 수량 | 평단 | 통화 | 매입환율 | 손절가 | 목표가 | 진입일 |
|------|------|------|------|----------|--------|--------|--------|
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
    price, listed_ccy, _session = _fetch_price(ticker)
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


def _cell(v) -> str:
    """숫자/규칙 문자열/빈값을 표 셀 문자열로."""
    if v in (None, "", "-"):
        return "-"
    f = _to_float(v)
    return _num(f) if f is not None else str(v)


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
            # _cell은 쉼표 포함 셀('1,380')도 _to_float로 정규화 — _num 직접 호출 시 크래시
            cells.append(_cell(rec.get("buy_fx")))
        elif key in ("stop", "target", "entry_date"):
            cells.append(_cell(rec.get(key)))
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
    """헤더·구분선·데이터 행을 headers_raw 기준으로 재작성하여 파일 저장.
    (구 5컬럼 파일이 8컬럼으로 승격될 때 헤더도 함께 갱신된다.)"""
    header_line = "| " + " | ".join(h.strip() for h in headers_raw) + " |\n"
    sep_line = "|" + "|".join("------" for _ in headers_raw) + "|\n"
    new_rows = [_render_row(headers_raw, _std_rec(r)) for r in records]
    new_lines = lines[:start] + [header_line, sep_line] + new_rows + lines[end:]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _ensure_v8_headers(headers_raw):
    """헤더에 손절가/목표가/진입일 컬럼이 없으면 정본 8컬럼으로 승격."""
    keys = {_HEADER_MAP.get(h.strip(), h.strip()) for h in headers_raw}
    if {"stop", "target", "entry_date"} <= keys:
        return headers_raw
    return list(_CANON_HEADERS)


def _std_rec(r: dict) -> dict:
    """원시 행 dict → 렌더용 표준 dict."""
    return {
        "ticker": (r.get("ticker") or "").strip(),
        "quantity": _to_float(r.get("quantity")) or 0,
        "buy_price": _to_float(r.get("buy_price")) or 0,
        "currency": _norm_currency(r.get("currency")),
        "buy_fx": r.get("buy_fx"),
        "stop": r.get("stop"),
        "target": r.get("target"),
        "entry_date": r.get("entry_date"),
    }


def _append_trade(rec: dict, trades_path=None) -> str:
    """체결 레저(data/trades.jsonl)에 1행 1 JSON append. 기록 경로 반환."""
    path = trades_path or _TRADES_PATH
    d = os.path.dirname(path)
    if d:  # 상대경로 파일명만 준 경우 makedirs('') 크래시 방지
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def _trade_record(action, ticker, qty, price, ccy, fx, stop=None, target=None,
                  realized_pnl=None, r_multiple=None, note=None, trade_date=None) -> dict:
    """trades.jsonl 정본 스키마 레코드 구성. stop은 숫자만(규칙 문자열은 note로)."""
    stop_num = stop if isinstance(stop, (int, float)) else None
    if stop is not None and stop_num is None:
        note = f"stop_rule={stop}" + (f"; {note}" if note else "")
    return {
        "date": trade_date or date.today().isoformat(),
        "action": action,
        "ticker": ticker,
        "qty": qty,
        "price": price,
        "ccy": ccy,
        "fx": fx if isinstance(fx, (int, float)) else None,
        "stop": stop_num,
        "target": target if isinstance(target, (int, float)) else None,
        "realized_pnl": realized_pnl,
        "r_multiple": r_multiple,
        "note": note,
    }


def add_holding(ticker, quantity, buy_price, currency=None, buy_fx=None,
                stop=None, target=None, entry_date=None, replace=False,
                path=None, trades_path=None) -> dict:
    """보유 종목 매수. 같은 티커가 있으면 **수량 합산 + 금액가중 평단·매입환율 병합**
    (피라미딩, action='pyramided')이 기본. 전량 교체(정정)는 replace=True.
    신규/피라미딩 매수는 data/trades.jsonl 원장에 buy로 기록한다. 파일 없으면 생성."""
    path = path or _DEFAULT_PATH
    ticker = str(ticker).strip()
    currency = _norm_currency(currency) if currency else _suggest_currency(ticker)
    quantity = float(quantity)
    buy_price = float(buy_price)
    buy_fx = _to_float(buy_fx)
    stop = _stop_value(stop)
    target = _to_float(target)
    entry_date = _clean_str(entry_date)
    warnings = []
    if currency != "KRW" and buy_fx is None:
        warnings.append(f"{currency} 종목인데 매입환율 누락 → 원화 손익 계산이 부정확합니다.")
    if currency not in ("USD", "KRW"):
        warnings.append(f"비USD/KRW 통화({currency}) — 평가 시 {currency}KRW=X 환율을 자동 조회합니다"
                        "(조회 실패 시 해당 종목은 미평가 처리).")
    if stop is None:
        warnings.append("손절가 미지정 — 손절 규율 기반 전략의 필수 입력입니다 (--stop 숫자 또는 MA20류 규칙).")

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(_PORTFOLIO_SCAFFOLD)

    lines, start, end, headers_raw, records = _load_records(path)
    headers_raw = _ensure_v8_headers(headers_raw)

    new_rec = {
        "ticker": ticker, "quantity": quantity, "buy_price": buy_price,
        "currency": currency, "buy_fx": buy_fx, "stop": stop, "target": target,
        "entry_date": entry_date or date.today().isoformat(),
    }
    action = "added"
    for i, r in enumerate(records):
        if (r.get("ticker") or "").strip().upper() != ticker.upper():
            continue
        if replace:
            records[i] = new_rec
            action = "replaced"
            warnings.append("--replace: 기존 행 전량 교체(정정 용도) — 원장(trades.jsonl)에는 기록하지 않음.")
            break
        # 피라미딩 병합: 수량 합산 + 금액가중 평단/매입환율
        old_qty = _to_float(r.get("quantity")) or 0.0
        old_price = _to_float(r.get("buy_price")) or 0.0
        old_ccy = _norm_currency(r.get("currency"))
        if old_ccy != currency:
            warnings.append(f"기존 보유 통화({old_ccy}) ≠ 입력 통화({currency}) → 기존 통화 유지. "
                            "통화를 바꾸려면 --replace 사용.")
            currency = old_ccy
        tot_qty = old_qty + quantity
        avg_price = ((old_qty * old_price + quantity * buy_price) / tot_qty) if tot_qty else buy_price
        old_fx = _to_float(r.get("buy_fx"))
        old_cost, new_cost = old_qty * old_price, quantity * buy_price
        if old_fx is not None and buy_fx is not None and (old_cost + new_cost):
            avg_fx = (old_cost * old_fx + new_cost * buy_fx) / (old_cost + new_cost)
        elif old_fx is not None or buy_fx is not None:
            avg_fx = old_fx if old_fx is not None else buy_fx
            warnings.append("매입환율이 한쪽만 있어 금액가중 병합 불가 → 있는 값으로 유지(원화 손익 부정확).")
        else:
            avg_fx = None
        records[i] = {
            "ticker": (r.get("ticker") or "").strip() or ticker,
            "quantity": tot_qty,
            "buy_price": round(avg_price, 6),
            "currency": currency,
            "buy_fx": round(avg_fx, 4) if avg_fx is not None else None,
            # 손절/목표는 이번 입력이 있으면 갱신, 없으면 기존 유지. 진입일은 최초 진입 유지.
            "stop": stop if stop is not None else _stop_value(r.get("stop")),
            "target": target if target is not None else _to_float(r.get("target")),
            "entry_date": _clean_str(r.get("entry_date")) or entry_date or date.today().isoformat(),
        }
        action = "pyramided"
        break
    else:
        records.append(new_rec)

    _write_table(path, lines, start, end, headers_raw, records)

    # 실제 매수(added/pyramided)만 원장 기록 — replace는 정정이라 미기록
    ledger = None
    if action in ("added", "pyramided"):
        ledger = _append_trade(_trade_record(
            "buy", ticker, quantity, buy_price, currency, buy_fx,
            stop=stop, target=target, trade_date=entry_date,
        ), trades_path)

    saved = next(r for r in records if (r.get("ticker") or "").strip().upper() == ticker.upper())
    std = _std_rec(saved)
    return {"action": action, "ticker": ticker,
            "quantity": _num(std["quantity"]), "buy_price": _num(std["buy_price"]),
            "currency": std["currency"],
            "buy_fx": _cell(std.get("buy_fx")),
            "stop": _cell(std.get("stop")), "target": _cell(std.get("target")),
            "entry_date": std.get("entry_date") or "-",
            "added_qty": _num(quantity), "added_price": _num(buy_price),
            "count": len(records), "trade_logged": bool(ledger),
            "warnings": warnings}


def sell_holding(ticker, qty=None, price=None, fx=None, note=None,
                 path=None, trades_path=None) -> dict:
    """보유 종목 매도(부분/전량). 수량 차감(전량이면 행 제거) + 실현손익·R-multiple을
    계산해 data/trades.jsonl 원장에 sell로 기록한다. qty=None이면 전량 매도."""
    path = path or _DEFAULT_PATH
    ticker = str(ticker).strip()
    price = _to_float(price)
    qty = _to_float(qty)
    fx = _to_float(fx)
    if price is None:
        return {"error": "매도가(--price) 필수: portfolio sell <TICKER> --qty N --price P [--fx]"}
    if not os.path.exists(path):
        return {"error": f"포트폴리오 파일 없음: {path}"}

    lines, start, end, headers_raw, records = _load_records(path)
    idx = next((i for i, r in enumerate(records)
                if (r.get("ticker") or "").strip().upper() == ticker.upper()), None)
    if idx is None:
        return {"action": "not_found", "ticker": ticker,
                "message": f"{ticker} 보유 종목에 없음", "count": len(records)}

    r = records[idx]
    held_qty = _to_float(r.get("quantity")) or 0.0
    buy_price = _to_float(r.get("buy_price")) or 0.0
    currency = _norm_currency(r.get("currency"))
    stop = _stop_value(r.get("stop"))
    target = _to_float(r.get("target"))
    warnings = []

    sell_qty = qty if qty is not None else held_qty
    if sell_qty <= 0:
        return {"error": f"매도 수량이 유효하지 않음: {sell_qty}"}
    if sell_qty > held_qty + 1e-9:
        return {"error": f"매도 수량({_num(sell_qty)})이 보유 수량({_num(held_qty)})을 초과합니다."}

    # 실현손익(매입 통화 기준) + R-multiple(고정 손절가가 있을 때만)
    realized_pnl = round((price - buy_price) * sell_qty, 4)
    realized_pnl_pct = round((price / buy_price - 1) * 100, 2) if buy_price else None
    r_multiple = None
    if isinstance(stop, (int, float)) and buy_price > stop:
        r_multiple = round((price - buy_price) / (buy_price - stop), 2)
    elif isinstance(stop, (int, float)):
        warnings.append("손절가가 평단 이상(트레일링 인상) → 초기 리스크 기준 R-multiple 산출 불가.")
    elif stop is not None:
        warnings.append(f"손절이 규칙 문자열('{stop}') → R-multiple은 고정 손절가일 때만 계산.")
    else:
        warnings.append("손절가 미기록 → R-multiple 계산 불가.")

    remaining = held_qty - sell_qty
    if remaining <= 1e-9:
        records.pop(idx)
        action = "sold_all"
        remaining = 0.0
    else:
        r["quantity"] = remaining
        action = "sold_partial"
    _write_table(path, lines, start, end, headers_raw, records)

    ledger = _append_trade(_trade_record(
        "sell", ticker, sell_qty, price, currency, fx,
        stop=stop, target=target,
        realized_pnl=realized_pnl, r_multiple=r_multiple, note=note,
    ), trades_path)

    return {"action": action, "ticker": ticker,
            "sold_qty": _num(sell_qty), "sell_price": _num(price),
            "remaining_qty": _num(remaining), "currency": currency,
            "realized_pnl": realized_pnl, "realized_pnl_pct": realized_pnl_pct,
            "r_multiple": r_multiple,
            "count": len(records), "trade_logged": bool(ledger),
            "warnings": warnings}


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


def _pick_extended_price(info: dict):
    """marketState 기준으로 프리/정규/애프터 중 최신 체결가 선택.
    반환 (price, session) — session ∈ {PRE, REGULAR, POST, CLOSED}."""
    state = (info.get("marketState") or "").upper()
    reg = info.get("regularMarketPrice")
    pre = info.get("preMarketPrice")
    post = info.get("postMarketPrice")
    if state == "PRE" and pre:
        return pre, "PRE"
    # 장 마감 후(POST/POSTPOST/CLOSED)엔 애프터마켓 최종가가 최신
    if state in ("POST", "POSTPOST", "CLOSED") and post:
        return post, "POST"
    if reg:
        # 정규가를 쓰면 세션은 REGULAR (연장가 미사용)
        return reg, "REGULAR"
    # 정규가 없으면 가용한 연장거래가라도
    if post:
        return post, "POST"
    if pre:
        return pre, "PRE"
    return None, state or None


def _fetch_price(ticker: str):
    """현재가·상장통화·세션 반환. 정규장 외 시간엔 프리/애프터마켓 최신가 우선.
    실패 시 (None, None, None)."""
    try:
        tk = yf.Ticker(ticker)
        price, listed_ccy, session = None, None, None
        # 1순위: .info — 프리/정규/애프터 + marketState 제공
        try:
            info = tk.info
            listed_ccy = info.get("currency")
            price, session = _pick_extended_price(info)
        except Exception:
            pass
        # 2순위: fast_info 최종체결가
        if price is None:
            try:
                fi = tk.fast_info
                price = fi.get("last_price") or fi.get("lastPrice")
                listed_ccy = listed_ccy or fi.get("currency")
                if price is not None:
                    session = session or "REGULAR"
            except Exception:
                pass
        # 3순위: 최근 종가
        if price is None:
            hist = tk.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].dropna().iloc[-1])
                session = session or "REGULAR"
        return (float(price) if price else None,
                listed_ccy.upper() if listed_ccy else None,
                session)
    except Exception:
        return (None, None, None)


def _resolve_fx_map(holdings, fx_override=None, warnings=None, errors=None) -> dict:
    """보유 통화별 원화 환산 환율 맵 {CCY: rate|None}.
    비KRW 통화는 <CCY>KRW=X 자동 조회 (USD는 fx_override 우선).
    조회 실패 시 해당 통화 보유 행의 매입환율 중앙값 폴백(+경고), 그것도 없으면 None(+에러)."""
    warnings = warnings if warnings is not None else []
    errors = errors if errors is not None else []
    fx_map = {}
    for ccy in sorted({h["currency"] for h in holdings if h["currency"] != "KRW"}):
        if ccy == "USD" and fx_override:
            fx_map["USD"] = float(fx_override)
            continue
        rate, _, _ = _fetch_price(f"{ccy}KRW=X")
        if rate is None:
            buy_fxs = [h["buy_fx"] for h in holdings
                       if h["currency"] == ccy and h["buy_fx"]]
            if buy_fxs:
                rate = statistics.median(buy_fxs)
                warnings.append(f"{ccy}KRW 환율 조회 실패 → 보유행 매입환율 중앙값({rate:,.2f}) 대체"
                                "(원화 평가 부정확)")
            else:
                errors.append(f"{ccy}KRW 환율 조회 실패 — 해당 통화 종목은 미평가 처리"
                              + (". USD는 --fx 로 수동 지정 가능" if ccy == "USD" else ""))
        fx_map[ccy] = rate
    return fx_map


def _stop_target_fields(price, stop, target) -> dict:
    """현재가 대비 손절가/목표가 판정 필드. 고정 숫자 손절만 즉시 판정,
    규칙 문자열(MA20 등)은 'portfolio check'에서 시계열로 판정."""
    out = {"stop": stop, "target": target,
           "stop_status": "미설정", "stop_gap_pct": None,
           "target_status": "미설정", "target_gap_pct": None}
    if isinstance(stop, (int, float)) and price:
        gap = round((price - stop) / price * 100, 2)  # 손절선까지 하락 여유(%)
        out["stop_gap_pct"] = gap
        out["stop_status"] = "위반" if price <= stop else ("근접" if gap <= _NEAR_PCT else "정상")
    elif stop is not None:
        out["stop_status"] = f"규칙({stop}) — check로 판정"
    if isinstance(target, (int, float)) and price:
        gap = round((target - price) / price * 100, 2)  # 목표까지 상승 여력(%)
        out["target_gap_pct"] = gap
        out["target_status"] = "도달" if price >= target else ("근접" if gap <= _NEAR_PCT else "미도달")
    return out


def _theme_clusters(rows, warnings) -> list:
    """보유 비중을 themes_for_ticker로 테마별 합산 — 클러스터 집중도 산출.
    (멤버십 판정은 theme_etf_map 소관 — 여기선 조인만.)"""
    try:
        try:
            from tools.theme_etf_map import themes_for_ticker
        except ImportError:
            from theme_etf_map import themes_for_ticker
        theme_w = {}
        for r in rows:
            w = r.get("weight_pct")
            if not w:
                continue
            for th in themes_for_ticker(r["ticker"]):
                d = theme_w.setdefault(th, {"weight_pct": 0.0, "tickers": []})
                d["weight_pct"] += w
                d["tickers"].append(r["ticker"])
        clusters = [{"theme": t, "weight_pct": round(v["weight_pct"], 2), "tickers": v["tickers"]}
                    for t, v in sorted(theme_w.items(), key=lambda kv: -kv[1]["weight_pct"])]
        for c in clusters:
            if c["weight_pct"] > 40:
                warnings.append(f"클러스터 집중: '{c['theme']}' 테마 합산 {c['weight_pct']}% > 40% "
                                f"({', '.join(c['tickers'])}) — 신규 비중은 잔여 한도로 캡 검토")
        return clusters
    except Exception as e:
        warnings.append(f"테마 클러스터 계산 실패: {e}")
        return []


def analyze_portfolio(path: str = None, fx_override: float = None) -> dict:
    """보유 종목을 평가하여 종목별 손익·비중·손절/목표 판정과 합계를 계산.

    - 합계(totals)는 **평가 성공 종목만** 집계 — 조회 실패분은 unpriced_cost_krw/
      unpriced_tickers로 분리(유령 -100% 손익 방지).
    - 비USD/KRW 통화는 <CCY>KRW=X 환율 자동 조회로 환산, 실패 시 미평가 처리.
    - clusters: 테마별 합산 비중(themes_for_ticker 조인) — 클러스터 집중도 감시.
    """
    holdings = load_holdings(path)
    if not holdings:
        return {"error": "보유 종목이 없습니다.", "holdings": [], "totals": {}}

    rows, warnings, errors = [], [], []
    fx_map = _resolve_fx_map(holdings, fx_override, warnings, errors)
    usdkrw = fx_map.get("USD")

    total_cost_krw = total_value_krw = 0.0   # 평가 성공(priced) 종목만
    unpriced_cost_krw, unpriced_tickers = 0.0, []

    for h in holdings:
        price, listed_ccy, session = _fetch_price(h["ticker"])
        qty, buy = h["quantity"], h["buy_price"]
        ccy = h["currency"]

        # 통화별 원화 환산 환율 결정
        if ccy == "KRW":
            cur_fx = buy_fx = 1.0
        else:
            cur_fx = fx_map.get(ccy)
            buy_fx = h["buy_fx"] or cur_fx  # 매입환율 없으면 현재환율로 대체(경고)
            if h["buy_fx"] is None and cur_fx is not None:
                warnings.append(f"{h['ticker']}: 매입환율 누락 → 현재환율로 대체(원화 손익 부정확)")

        if listed_ccy and ccy and listed_ccy != ccy:
            warnings.append(f"{h['ticker']}: 입력통화({ccy}) ≠ 상장통화({listed_ccy})")

        cost_native = qty * buy
        cost_krw = cost_native * buy_fx if buy_fx is not None else None

        # 현재가 또는 환산환율 불명 → 미평가(합계에서 제외, 별도 집계)
        if price is None or cur_fx is None:
            if price is None:
                warnings.append(f"{h['ticker']}: 현재가 조회 실패 → 합계에서 제외(미평가)")
            else:
                warnings.append(f"{h['ticker']}: {ccy}KRW 환율 불명 → 합계에서 제외(미평가)")
            rows.append({
                **h, "current_price": round(price, 2) if price else None,
                "value_native": None,
                "value_krw": None, "pnl_native": None, "pnl_pct_native": None,
                "pnl_krw": None, "pnl_pct_krw": None, "weight_pct": None,
                "cost_krw": round(cost_krw, 0) if cost_krw is not None else None,
                "price_session": session, "priced": False,
            })
            if cost_krw is not None:
                unpriced_cost_krw += cost_krw
            unpriced_tickers.append(h["ticker"])
            continue

        value_native = qty * price
        value_krw = value_native * cur_fx
        pnl_native = value_native - cost_native
        pnl_krw = value_krw - cost_krw if cost_krw is not None else None

        rows.append({
            "ticker": h["ticker"],
            "quantity": qty,
            "buy_price": buy,
            "currency": ccy,
            "buy_fx": h["buy_fx"],
            "entry_date": h.get("entry_date"),
            "current_price": round(price, 2),
            "price_session": session,
            "current_fx": round(cur_fx, 2) if ccy != "KRW" else None,
            "cost_krw": round(cost_krw, 0) if cost_krw is not None else None,
            "value_native": round(value_native, 2),
            "value_krw": round(value_krw, 0),
            "pnl_native": round(pnl_native, 2),
            "pnl_pct_native": round(pnl_native / cost_native * 100, 2) if cost_native else None,
            "pnl_krw": round(pnl_krw, 0) if pnl_krw is not None else None,
            "pnl_pct_krw": round(pnl_krw / cost_krw * 100, 2) if cost_krw else None,
            "weight_pct": None,  # 합계 후 채움
            "priced": True,
            **_stop_target_fields(price, h.get("stop"), h.get("target")),
        })
        if cost_krw is not None:
            total_cost_krw += cost_krw
        total_value_krw += value_krw

    # 비중 계산 (평가 성공 종목 기준)
    for r in rows:
        if r.get("value_krw"):
            r["weight_pct"] = round(r["value_krw"] / total_value_krw * 100, 2) if total_value_krw else None

    # 손절선 위반/근접 요약 경고
    for r in rows:
        if r.get("stop_status") == "위반":
            warnings.append(f"🔴 {r['ticker']}: 손절선 위반 — 현재가 {r['current_price']} ≤ 손절 {r['stop']}")
        elif r.get("stop_status") == "근접":
            warnings.append(f"🟡 {r['ticker']}: 손절선 근접 — 여유 {r['stop_gap_pct']}%")

    clusters = _theme_clusters(rows, warnings)

    total_pnl_krw = total_value_krw - total_cost_krw
    return {
        "usdkrw": round(usdkrw, 2) if usdkrw else None,
        "holdings": rows,
        "totals": {
            # 평가 성공(priced) 종목만 — 조회 실패 원가는 아래 unpriced_*로 분리
            "cost_krw": round(total_cost_krw, 0),
            "value_krw": round(total_value_krw, 0),
            "pnl_krw": round(total_pnl_krw, 0),
            "pnl_pct": round(total_pnl_krw / total_cost_krw * 100, 2) if total_cost_krw else None,
            "unpriced_cost_krw": round(unpriced_cost_krw, 0),
            "unpriced_tickers": unpriced_tickers,
        },
        "clusters": clusters,
        "warnings": warnings,
        "errors": errors,
    }


def _effective_stop(close, stop):
    """손절 입력 → (유효 손절가, 종류, 경고). 숫자면 고정, 문자열이면 트레일링 규칙 해석.
    지원 규칙: 'MA20'(N일 이동평균), '직전고점-15%'/'고점-15%'(기간 고점 대비 -X% 라인)."""
    if isinstance(stop, (int, float)):
        return float(stop), "fixed", None
    if not stop:
        return None, None, None
    rule = str(stop).strip()
    m = re.match(r"^MA\s*(\d+)$", rule, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        if len(close) < n:
            return None, f"trailing(MA{n})", f"데이터 부족({len(close)}봉 < {n}봉) → MA{n} 판정 불가"
        return float(close.rolling(n).mean().iloc[-1]), f"trailing(MA{n})", None
    m = re.match(r"^(?:직전)?고점\s*-\s*(\d+(?:\.\d+)?)\s*%$", rule)
    if m:
        pct = float(m.group(1))
        high = float(close.max())
        return high * (1 - pct / 100), f"trailing(고점-{pct:g}%)", None
    return None, "unknown", f"손절 규칙 해석 불가: '{rule}' (지원: 숫자, MA20, 직전고점-15%)"


def check_portfolio(path: str = None) -> dict:
    """손절선·트레일링 규칙·목표가·피라미딩 트리거 점검 (portfolio check).

    종목별 1년 일봉으로:
    - 손절: 고정가 또는 트레일링 규칙(MA20/직전고점-X%)의 유효 손절가 산출 →
      위반(종가 ≤ 손절) / 근접(여유 ≤ 3%) / 정상 / 미설정 판정
    - 목표: 도달 / 근접 / 미도달 / 미설정
    - 피라미딩 트리거: 종가가 직전 최고 종가 경신 + 당일 상승(신고가 돌파)
    """
    holdings = load_holdings(path)
    if not holdings:
        return {"error": "보유 종목이 없습니다.", "results": []}

    results, warnings, errors = [], [], []
    violations, near_stop, targets_hit, pyramiding_triggers = [], [], [], []

    for h in holdings:
        ticker = h["ticker"]
        try:
            hist = yf.Ticker(ticker).history(period="1y")
            close = hist["Close"].dropna() if not hist.empty else None
        except Exception as e:
            close = None
            errors.append(f"{ticker}: 시세 조회 실패 ({e})")
        if close is None or close.empty:
            if not any(ticker in e for e in errors):
                errors.append(f"{ticker}: 시세 조회 실패")
            results.append({"ticker": ticker, "current_price": None,
                            "stop_status": "판정불가", "target_status": "판정불가",
                            "pyramiding_trigger": None})
            continue

        cur = float(close.iloc[-1])
        eff_stop, stop_kind, warn = _effective_stop(close, h.get("stop"))
        if warn:
            warnings.append(f"{ticker}: {warn}")

        # 손절 판정
        if eff_stop is not None:
            gap = round((cur - eff_stop) / cur * 100, 2)
            if cur <= eff_stop:
                stop_status = "위반"
                violations.append(ticker)
            elif gap <= _NEAR_PCT:
                stop_status = "근접"
                near_stop.append(ticker)
            else:
                stop_status = "정상"
        else:
            gap, stop_status = None, "미설정"

        # 목표 판정
        target = h.get("target")
        if isinstance(target, (int, float)):
            t_gap = round((target - cur) / cur * 100, 2)
            if cur >= target:
                target_status = "도달"
                targets_hit.append(ticker)
            elif t_gap <= _NEAR_PCT:
                target_status = "근접"
            else:
                target_status = "미도달"
        else:
            t_gap, target_status = None, "미설정"

        # 피라미딩 트리거: 신고가 경신 + 당일 상승 (분산일 오탐 방지)
        new_high = bool(len(close) >= 2
                        and cur >= float(close.iloc[:-1].max())
                        and cur > float(close.iloc[-2]))
        if new_high:
            pyramiding_triggers.append(ticker)

        results.append({
            "ticker": ticker,
            "current_price": round(cur, 2),
            "currency": h["currency"],
            "buy_price": h["buy_price"],
            "stop_input": h.get("stop"),
            "stop_kind": stop_kind,
            "effective_stop": round(eff_stop, 4) if eff_stop is not None else None,
            "stop_gap_pct": gap,       # 손절선까지 하락 여유(%)
            "stop_status": stop_status,
            "target": target,
            "target_gap_pct": t_gap,   # 목표까지 상승 여력(%)
            "target_status": target_status,
            "pyramiding_trigger": new_high,
            "data_span_days": len(close),
        })

    no_stop = [r["ticker"] for r in results if r.get("stop_status") == "미설정"]
    if no_stop:
        warnings.append(f"손절가 미설정 종목: {', '.join(no_stop)} — 손절 규율 전략의 필수 입력"
                        " (portfolio add --stop 또는 파일 직접 편집)")

    return {
        "as_of": date.today().isoformat(),
        "results": results,
        "violations": violations,          # 🔴 손절선 위반 — 즉시 청산 검토
        "near_stop": near_stop,            # 🟡 손절선 근접(여유 ≤ 3%)
        "targets_hit": targets_hit,        # 목표가 도달 — 익절/트레일링 전환 검토
        "pyramiding_triggers": pyramiding_triggers,  # 신고가 돌파 — 피라미딩 후보
        "warnings": warnings,
        "errors": errors,
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
        sess = r.get("price_session")
        mark = "*" if sess in ("PRE", "POST") else ""
        line = (
            f"{(r['ticker'] + mark):<11}"
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

    # 미평가 종목 (합계에서 제외 — 유령 손실 방지)
    if t.get("unpriced_tickers"):
        out.append(f"⚠️  미평가 종목(합계 제외): {', '.join(t['unpriced_tickers'])}"
                   f"  — 원가 {_fmt(t.get('unpriced_cost_krw'))} KRW 별도")

    # 손절/목표 판정 (위반·근접·도달만 — 상세는 portfolio check)
    alerts = []
    for r in rows:
        if r.get("stop_status") == "위반":
            alerts.append(f"  🔴 {r['ticker']:<11} 손절선 위반 — 현재가 {_fmt(r.get('current_price'), 2)}"
                          f" ≤ 손절 {_fmt(r.get('stop'), 2)}")
        elif r.get("stop_status") == "근접":
            alerts.append(f"  🟡 {r['ticker']:<11} 손절선 근접 — 여유 {_fmt(r.get('stop_gap_pct'), 1)}%")
        if r.get("target_status") == "도달":
            alerts.append(f"  🎯 {r['ticker']:<11} 목표가 도달 — 현재가 {_fmt(r.get('current_price'), 2)}"
                          f" ≥ 목표 {_fmt(r.get('target'), 2)}")
    if alerts:
        out.append("-" * 96)
        out.append("손절·목표 판정 (트레일링 규칙 포함 상세는 `portfolio check`):")
        out.extend(alerts)

    # 테마 클러스터 노출 (합산 비중)
    clusters = result.get("clusters") or []
    if clusters:
        out.append("-" * 96)
        out.append("테마 클러스터 노출:")
        for c in clusters:
            flag = " ⚠️" if c["weight_pct"] > 40 else ""
            out.append(f"  {c['theme']:<14} {c['weight_pct']:>6.1f}%  ({', '.join(c['tickers'])}){flag}")

    # 연장거래(프리/애프터) 반영 종목 표기
    ext = [(r["ticker"], r["price_session"], r.get("current_price"))
           for r in rows if r.get("price_session") in ("PRE", "POST")]
    if ext:
        label = {"PRE": "프리마켓", "POST": "애프터마켓"}
        tags = ", ".join(f"{tk} {label[s]} {_fmt(p, 2)}" for tk, s, p in ext)
        out.append(f"* 연장거래 최신가 반영: {tags}")

    # 종목별 현지통화 수익률(환손익 분리) 보조 표기
    usd_rows = [r for r in rows if r.get("currency") == "USD" and r.get("pnl_pct_native") is not None]
    if usd_rows:
        out.append("-" * 96)
        out.append("현지통화 기준 수익률(환율 효과 제외):")
        for r in usd_rows:
            out.append(f"  {r['ticker']:<11} {_sign(r['pnl_pct_native'], 1, pct=True)}  "
                       f"(원화 {_sign(r.get('pnl_pct_krw'), 1, pct=True)})")

    if result.get("errors"):
        out.append("-" * 96)
        out.append("❌ 에러:")
        for e in result["errors"]:
            out.append(f"  - {e}")

    if result.get("warnings"):
        out.append("-" * 96)
        out.append("⚠️  경고:")
        for w in result["warnings"]:
            out.append(f"  - {w}")

    return "\n".join(out)
