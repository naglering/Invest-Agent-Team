"""보유·관심 종목 상시 감시 도구 — `cli.py watch` (장 마감 후 1일 1회 실행 권장)

data/portfolio.md(보유) + data/watchlist.md(관심, 없으면 스킵)를 순회하며 점검한다:
  (1) 현재가 vs 손절가 — 위반(🔴) / 5% 이내 근접(🟡). 숫자 손절가와 'MA20'류 트레일링 규칙 모두 지원
  (2) 목표가 도달(🟢)
  (3) 신고가 경신 + 거래량 동반 — 돌파 점화(🟢) / 고점 -3% 이내 근접은 돌파 관찰(🟡)
  (4) data/histories 최신 메모의 'triggers:' YAML 블록 — 실적 D-7/D-1·이벤트 임박(🟢)

결과는 JSON dict로 반환하고, 알림이 있으면 data/alerts/YYYY-MM-DD.md 에 append 한다.

주의:
  - 모든 가격 판정은 **완성 일봉 종가** 기준 — 진행 중(장중/당일 미마감) 봉은 제외한다.
  - portfolio.py 는 병렬 개편 중이므로 import 하지 않고 자체 경량 파서를 쓴다.
    정본 8컬럼(| 종목 | 수량 | 평단 | 통화 | 매입환율 | 손절가 | 목표가 | 진입일 |)과
    구 5컬럼(| 종목 | 수량 | 매입가 | 통화 | 매입시환율 |) 모두 파싱한다(누락 컬럼은 None).
"""

import json
import os
import re
import time
from datetime import date, datetime

import yfinance as yf

# 경로 (이 파일: src/tools/watch_alerts.py → repo 루트로 2단계 상위)
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_PORTFOLIO_PATH = os.path.join(_DATA_DIR, "portfolio.md")
_WATCHLIST_PATH = os.path.join(_DATA_DIR, "watchlist.md")
_ALERTS_DIR = os.path.join(_DATA_DIR, "alerts")
_HISTORIES_DIR = os.path.join(_DATA_DIR, "histories")

# 컬럼 헤더 별칭 → 표준 키 (정본 8컬럼 + 구 5컬럼 호환)
_HEADER_MAP = {
    "종목": "ticker", "티커": "ticker", "ticker": "ticker",
    "수량": "quantity", "주수": "quantity", "qty": "quantity",
    "평단": "buy_price", "매입가": "buy_price", "진입가": "buy_price", "buy_price": "buy_price",
    "통화": "currency", "ccy": "currency",
    "매입환율": "buy_fx", "매입시환율": "buy_fx", "환율": "buy_fx", "fx": "buy_fx",
    "손절가": "stop", "손절": "stop", "stop": "stop",
    "목표가": "target", "목표": "target", "target": "target",
    "진입일": "entry_date", "entry": "entry_date", "date": "entry_date",
    "메모": "note", "note": "note",
}

# 트레일링 규칙 문자열: 'MA20' / 'SMA50' / '20일선' / '직전고점-15%'(portfolio.py와 동일 문법)
_MA_RULE_RE = re.compile(r"^(?:SMA|MA)\s*_?(\d{1,3})$", re.I)
_MA_RULE_KR_RE = re.compile(r"^(\d{1,3})\s*일선")
_HIGH_RULE_RE = re.compile(r"^(?:직전)?고점\s*-\s*(\d+(?:\.\d+)?)\s*%$")

# 메모 디렉토리/레거시 파일: YYYY-MM-DD_TICKER (memo_manager와 동일 규칙)
_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(?:\.md)?$")

_ICON = {"violation": "🔴", "near": "🟡", "trigger": "🟢"}
_SEV_ORDER = {"violation": 0, "near": 1, "trigger": 2}


# ---------------------------------------------------------------------------
# 파일 파싱 (자체 경량 파서 — portfolio.py 미의존)
# ---------------------------------------------------------------------------
def _to_float(s):
    """쉼표/통화기호 제거 후 float. 빈값/'-'/'N/A'/규칙 문자열은 None."""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace("$", "").replace("₩", "")
    if t in ("", "-", "—", "N/A", "n/a"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _cell(s):
    """표 셀 원문 정리. 빈값/'-'류는 None (규칙 문자열은 원문 유지)."""
    if s is None:
        return None
    t = str(s).strip()
    return None if t in ("", "-", "—", "N/A", "n/a") else t


def _parse_first_table(path: str) -> list:
    """마크다운 파일의 첫 '|' 테이블을 파싱해 표준 키 dict 리스트 반환."""
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    table, in_table = [], False
    for line in lines:
        if line.lstrip().startswith("|"):
            table.append(line.strip())
            in_table = True
        elif in_table:
            break
    if len(table) < 3:  # 헤더+구분선+데이터 최소 3행
        return []

    def split_row(row):
        return [c.strip() for c in row.strip().strip("|").split("|")]

    headers = [_HEADER_MAP.get(h, h) for h in split_row(table[0])]
    rows = []
    for raw in table[2:]:  # table[1] = 구분선(---)
        cells = split_row(raw)
        if not any(cells):
            continue
        rec = dict(zip(headers, cells))
        if not (rec.get("ticker") or "").strip():
            continue
        rows.append(rec)
    return rows


def load_portfolio(path: str = None) -> list:
    """portfolio.md → 보유 종목 리스트. 정본 8컬럼/구 5컬럼 호환(누락 컬럼 None)."""
    path = path or _PORTFOLIO_PATH
    if not os.path.exists(path):
        return []
    holdings = []
    for rec in _parse_first_table(path):
        holdings.append({
            "ticker": rec["ticker"].strip(),
            "quantity": _to_float(rec.get("quantity")),
            "buy_price": _to_float(rec.get("buy_price")),
            "currency": (_cell(rec.get("currency")) or "KRW").upper(),
            "buy_fx": _to_float(rec.get("buy_fx")),
            # 손절가·목표가: 숫자 또는 'MA20'류 규칙 문자열 — 원문 보존
            "stop": _cell(rec.get("stop")),
            "target": _cell(rec.get("target")),
            "entry_date": _cell(rec.get("entry_date")),
        })
    return holdings


def load_watchlist(path: str = None) -> list:
    """watchlist.md(| 종목 | 메모 |) → 관심 종목 리스트. 파일 없으면 빈 리스트(스킵)."""
    path = path or _WATCHLIST_PATH
    if not os.path.exists(path):
        return []
    return [{"ticker": rec["ticker"].strip(), "note": _cell(rec.get("note"))}
            for rec in _parse_first_table(path)]


# ---------------------------------------------------------------------------
# 가격 데이터 (완성봉 기준)
# ---------------------------------------------------------------------------
def _completed_bars(df, ticker: str):
    """진행 중인 마지막 봉을 제거하고 완성봉만 남긴다.

    - 마지막 봉 날짜 < 오늘(거래소 시간대) → 전부 완성봉
    - 크립토(-USD, 24/7): 당일 봉은 항상 미완성 → 제외
    - 주식: 당일 봉은 장 마감 시각(+15분 버퍼) 이후에만 완성 간주(미국 16:00, 한국 15:30)
    """
    if df is None or df.empty:
        return df
    idx = df.index[-1]
    try:
        now_tz = datetime.now(idx.tzinfo) if idx.tzinfo else datetime.now()
    except Exception:
        return df
    if idx.date() < now_tz.date():
        return df
    t = ticker.upper()
    if t.endswith("-USD"):  # 크립토 일봉은 UTC 자정 마감 — 당일 봉은 미완성
        return df.iloc[:-1]
    close_h, close_m = (15, 30) if t.endswith((".KS", ".KQ")) else (16, 0)
    if (now_tz.hour * 60 + now_tz.minute) >= (close_h * 60 + close_m + 15):
        return df
    return df.iloc[:-1]


def _fetch_history(ticker: str, period: str = "1y"):
    """일봉 이력 조회(레이트리밋 대비 1회 재시도) → 완성봉 DataFrame. 실패 시 예외."""
    last_err = None
    for attempt in range(2):
        try:
            df = yf.Ticker(ticker).history(period=period)
            if df is not None and not df.empty:
                return _completed_bars(df, ticker)
            last_err = ValueError("가격 데이터 없음")
        except Exception as e:  # noqa: BLE001 - 티커당 격리
            last_err = e
        if attempt == 0:
            time.sleep(2)
    raise last_err


# ---------------------------------------------------------------------------
# 점검 로직
# ---------------------------------------------------------------------------
def _resolve_stop_level(stop_raw, close):
    """손절가 원문 → (기준레벨, 규칙라벨). 해석 불가 시 (None, None).

    지원: 숫자 / 'MA20'·'20일선'(N일 이동평균) / '직전고점-15%'(기간 고점 대비 -X%).
    """
    num = _to_float(stop_raw)
    if num is not None:
        return num, None
    s = str(stop_raw).strip()
    m = _MA_RULE_RE.match(s) or _MA_RULE_KR_RE.match(s)
    if m:
        n = int(m.group(1))
        if len(close) < n:
            raise ValueError(f"이력 부족(봉 {len(close)}개 < MA{n})")
        return float(close.rolling(n).mean().iloc[-1]), f"MA{n}"
    m = _HIGH_RULE_RE.match(s)
    if m:
        pct = float(m.group(1))
        return float(close.max()) * (1 - pct / 100), f"고점-{pct:g}%"
    return None, None


def _check_stop(holding: dict, close) -> dict:
    """손절가 위반/5% 이내 근접 판정. 반환 dict의 state ∈ violated|near|ok|no_stop|unparsed."""
    stop_raw = holding.get("stop")
    if stop_raw is None:
        return {"state": "no_stop"}
    cur = float(close.iloc[-1])
    try:
        level, rule = _resolve_stop_level(stop_raw, close)
    except ValueError as e:
        return {"state": "unparsed", "raw": stop_raw, "reason": str(e)}
    if level is None or level <= 0:
        return {"state": "unparsed", "raw": stop_raw,
                "reason": "숫자 또는 MA규칙(MA20/20일선)이 아님"}
    gap_pct = round((cur / level - 1) * 100, 2)
    state = "violated" if cur <= level else ("near" if gap_pct <= 5 else "ok")
    return {"state": state, "raw": stop_raw, "rule": rule,
            "stop_level": round(level, 4), "close": round(cur, 4),
            "gap_pct": gap_pct}


def _check_target(holding: dict, close) -> dict:
    """목표가 도달 판정. state ∈ hit|ok|no_target|unparsed."""
    target_raw = holding.get("target")
    if target_raw is None:
        return {"state": "no_target"}
    level = _to_float(target_raw)
    if level is None or level <= 0:
        return {"state": "unparsed", "raw": target_raw, "reason": "목표가가 숫자가 아님"}
    cur = float(close.iloc[-1])
    gap_pct = round((cur / level - 1) * 100, 2)
    return {"state": "hit" if cur >= level else "ok",
            "target": level, "close": round(cur, 4), "gap_pct": gap_pct}


def _check_breakout(close, vol) -> dict:
    """신고가 경신 + 거래량 동반(돌파 점화) 판정 — 완성봉 기준.

    ignition: 마지막 완성봉이 (a) 직전까지의 기간 고점 경신, (b) 상승 마감,
              (c) 직전 20일 평균 대비 거래량 1.3배 이상.
    watch:    점화는 아니나 고점 -3% 이내 + 거래량 동반 — 돌파 임박 관찰.
    """
    if close is None or len(close) < 40:
        return {"state": "insufficient", "reason": f"이력 부족(완성봉 {0 if close is None else len(close)}개 < 40)"}
    cur = float(close.iloc[-1])
    prior_high = float(close.iloc[:-1].max())
    up_day = cur > float(close.iloc[-2])
    vol20 = float(vol.iloc[:-1].tail(20).mean()) if vol is not None and len(vol) >= 21 else None
    vol_surge = round(float(vol.iloc[-1]) / vol20, 2) if vol20 and vol20 > 0 else None
    pct_from_high = round((cur / prior_high - 1) * 100, 2) if prior_high else None
    new_high = bool(prior_high and cur >= prior_high)
    ignition = bool(new_high and up_day and vol_surge and vol_surge >= 1.3)
    watch = bool(not ignition and pct_from_high is not None and pct_from_high >= -3
                 and vol_surge and vol_surge >= 1.3)
    return {"state": "ignition" if ignition else ("watch" if watch else "none"),
            "new_high": new_high, "up_day": up_day,
            "prior_high": round(prior_high, 4), "close": round(cur, 4),
            "pct_from_high": pct_from_high, "vol_surge_x": vol_surge}


# ---------------------------------------------------------------------------
# 메모 triggers: 블록 파싱 (실적 D-7/D-1·이벤트 임박)
# ---------------------------------------------------------------------------
def _latest_memo_file(ticker: str, histories_dir: str):
    """티커의 최신 메모 파일 경로(summary 우선, 레거시 flat 포함). 없으면 None."""
    if not os.path.isdir(histories_dir):
        return None
    candidates = []
    for name in os.listdir(histories_dir):
        m = _NAME_RE.match(name)
        if not m or m.group(2).upper() != ticker.upper():
            continue
        path = os.path.join(histories_dir, name)
        if os.path.isdir(path):
            for fname in ("summary.md", "report.md"):
                fp = os.path.join(path, fname)
                if os.path.exists(fp):
                    candidates.append((m.group(1), fp))
                    break
        elif name.endswith(".md"):
            candidates.append((m.group(1), path))
    if not candidates:
        return None
    candidates.sort(reverse=True)  # 최신 날짜 우선
    return candidates[0][1]


def _parse_yamlish(text: str):
    """YAML(가능하면)/JSON으로 파싱. 실패 시 None."""
    try:
        import yaml  # PyYAML — 없으면 JSON 폴백
        return yaml.safe_load(text)
    except ImportError:
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None
    except Exception:
        return None


def _extract_triggers(md_text: str):
    """메모 마크다운에서 'triggers:' 블록을 찾아 트리거 리스트 반환. 없으면 []."""
    # 1) 펜스 코드블록(```yaml/```json 등) 안의 triggers:
    for m in re.finditer(r"```[A-Za-z]*\s*\n(.*?)```", md_text, re.S):
        block = m.group(1)
        if not re.search(r"^\s*[\"']?triggers[\"']?\s*:", block, re.M):
            continue
        data = _parse_yamlish(block)
        if isinstance(data, dict) and isinstance(data.get("triggers"), list):
            return data["triggers"]
    # 2) 본문의 'triggers:' 라인부터 들여쓰기/리스트 블록 (비-펜스)
    m = re.search(r"^triggers\s*:.*(?:\n(?:[ \t]+.*|[ \t]*-.*|\s*)$)*",
                  md_text, re.M)
    if m:
        data = _parse_yamlish(m.group(0))
        if isinstance(data, dict) and isinstance(data.get("triggers"), list):
            return data["triggers"]
    return []


def _to_date(v):
    """트리거 date 값(문자열/date/datetime) → date. 실패 시 None."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _memo_trigger_alerts(ticker: str, histories_dir: str, today: date):
    """최신 메모 triggers: 블록에서 임박(7일 이내) 일정 알림 생성."""
    alerts, warnings = [], []
    memo_path = _latest_memo_file(ticker, histories_dir)
    if memo_path is None:
        return alerts, warnings
    try:
        with open(memo_path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        warnings.append(f"{ticker}: 메모 읽기 실패 — {e}")
        return alerts, warnings
    for tr in _extract_triggers(text):
        if not isinstance(tr, dict):
            continue
        d = _to_date(tr.get("date"))
        if d is None:
            continue  # 가격형 트리거(price_stop/price_target)는 손절가·목표가 점검에서 담당
        days = (d - today).days
        if days < 0 or days > 7:
            continue
        ttype = str(tr.get("type") or "event").lower()
        is_earnings = ttype in ("earnings", "실적")
        if is_earnings and days not in (7, 1, 0):
            continue  # 실적은 D-7/D-1/당일에만 알림(일간 반복 소음 방지) — 이벤트는 7일 내 임박 알림
        label = "실적" if is_earnings else (tr.get("note") or tr.get("label") or ttype)
        dday = "D-DAY(당일)" if days == 0 else f"D-{days}"
        alerts.append({
            "severity": "trigger", "icon": _ICON["trigger"],
            "kind": "earnings_dday" if is_earnings else "event_dday",
            "ticker": ticker,
            "message": f"{label} {dday} — {d.isoformat()}",
            "detail": {"type": ttype, "date": d.isoformat(), "days_until": days,
                       "memo": os.path.relpath(memo_path, histories_dir)},
        })
    return alerts, warnings


# ---------------------------------------------------------------------------
# 알림 파일 append
# ---------------------------------------------------------------------------
def _append_alerts_md(alerts: list, alerts_dir: str, asof: str) -> str:
    """data/alerts/YYYY-MM-DD.md 에 이번 실행 알림을 append. 반환: 파일 경로."""
    os.makedirs(alerts_dir, exist_ok=True)
    path = os.path.join(alerts_dir, f"{asof}.md")
    lines = []
    if not os.path.exists(path):
        lines.append(f"# 감시 알림 — {asof}\n")
        lines.append("\n> `cli.py watch` 자동 생성. 🔴 손절 위반 / 🟡 근접·주의 / 🟢 트리거(돌파·목표가·일정)\n")
    lines.append(f"\n## {datetime.now().strftime('%H:%M')} watch\n\n")
    for a in sorted(alerts, key=lambda x: (_SEV_ORDER.get(x["severity"], 9), x["ticker"])):
        lines.append(f"- {a['icon']} **{a['ticker']}** {a['message']}\n")
    with open(path, "a", encoding="utf-8") as f:
        f.writelines(lines)
    return path


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------
def run_watch(portfolio_path: str = None, watchlist_path: str = None,
              alerts_dir: str = None, histories_dir: str = None,
              append: bool = True, period: str = "1y") -> dict:
    """보유+관심 종목 일괄 감시. JSON-able dict 반환 + 알림 md append."""
    alerts_dir = alerts_dir or _ALERTS_DIR
    histories_dir = histories_dir or _HISTORIES_DIR
    today = date.today()
    asof = today.strftime("%Y-%m-%d")

    soft_warnings, errors, alerts, checked = [], [], [], []

    holdings = load_portfolio(portfolio_path)
    if not holdings and not os.path.exists(portfolio_path or _PORTFOLIO_PATH):
        soft_warnings.append("portfolio.md 없음 — 보유 종목 감시 생략 (`cli.py portfolio init`)")
    watchlist = load_watchlist(watchlist_path)
    if not os.path.exists(watchlist_path or _WATCHLIST_PATH):
        soft_warnings.append("watchlist.md 없음 — 관심 종목 감시 생략 (| 종목 | 메모 | 테이블로 생성)")

    # 유니버스: 보유 우선, watchlist 중복 제거
    universe = []
    seen = set()
    for h in holdings:
        if h["ticker"].upper() not in seen:
            universe.append({"source": "portfolio", **h})
            seen.add(h["ticker"].upper())
    for w in watchlist:
        if w["ticker"].upper() not in seen:
            universe.append({"source": "watchlist", "stop": None, "target": None, **w})
            seen.add(w["ticker"].upper())

    if not universe:
        return {
            "asof": asof, "alerts": [], "checked": [],
            "universe": {"portfolio": [], "watchlist": []},
            "alerts_file": None, "appended": False,
            "soft_warnings": soft_warnings,
            "errors": [{"ticker": "*", "error": "감시 대상 없음 (portfolio.md/watchlist.md 비어 있음)"}],
            "data_status": "no_data",
        }

    fetched = 0
    for item in universe:
        ticker = item["ticker"]
        row = {"ticker": ticker, "source": item["source"]}
        try:
            df = _fetch_history(ticker, period=period)
            if df is None or df.empty or len(df) < 2:
                raise ValueError("완성봉 부족")
        except Exception as e:  # noqa: BLE001 - 티커당 격리(전체 죽지 않게)
            errors.append({"ticker": ticker, "error": str(e)})
            row["status"] = "fetch_failed"
            checked.append(row)
            continue
        fetched += 1
        close, vol = df["Close"].dropna(), df.get("Volume")
        cur = float(close.iloc[-1])
        row.update({"status": "ok", "close": round(cur, 4),
                    "bar_date": str(close.index[-1].date())})

        # (1) 손절가 위반/근접
        stop = _check_stop(item, close)
        row["stop"] = stop
        if stop["state"] == "violated":
            rule = f"({stop['rule']}) " if stop.get("rule") else ""
            alerts.append({
                "severity": "violation", "icon": _ICON["violation"], "kind": "stop_violation",
                "ticker": ticker,
                "message": (f"손절선 위반 — 종가 {cur:,.2f} ≤ 손절 {rule}{stop['stop_level']:,.2f} "
                            f"({stop['gap_pct']:+.1f}%)"),
                "detail": stop,
            })
        elif stop["state"] == "near":
            rule = f"({stop['rule']}) " if stop.get("rule") else ""
            alerts.append({
                "severity": "near", "icon": _ICON["near"], "kind": "stop_near",
                "ticker": ticker,
                "message": (f"손절 근접(5% 이내) — 종가 {cur:,.2f}, 손절 {rule}{stop['stop_level']:,.2f}"
                            f"까지 {stop['gap_pct']:+.1f}%"),
                "detail": stop,
            })
        elif stop["state"] == "unparsed":
            soft_warnings.append(f"{ticker}: 손절가 해석 불가('{stop['raw']}') — {stop['reason']}")
        elif stop["state"] == "no_stop" and item["source"] == "portfolio":
            soft_warnings.append(f"{ticker}: 손절가 미설정 — 손절 감시 불가(portfolio.md 손절가 컬럼 입력 권장)")

        # (2) 목표가 도달
        target = _check_target(item, close)
        row["target"] = target
        if target["state"] == "hit":
            alerts.append({
                "severity": "trigger", "icon": _ICON["trigger"], "kind": "target_hit",
                "ticker": ticker,
                "message": (f"목표가 도달 — 종가 {cur:,.2f} ≥ 목표 {target['target']:,.2f} "
                            f"({target['gap_pct']:+.1f}%)"),
                "detail": target,
            })
        elif target["state"] == "unparsed":
            soft_warnings.append(f"{ticker}: 목표가 해석 불가('{target['raw']}') — {target['reason']}")

        # (3) 돌파 점화 (신고가 경신 + 거래량 — 완성봉 기준)
        brk = _check_breakout(close, vol)
        row["breakout"] = brk
        if brk["state"] == "ignition":
            alerts.append({
                "severity": "trigger", "icon": _ICON["trigger"], "kind": "breakout_ignition",
                "ticker": ticker,
                "message": (f"돌파 점화 — 기간 신고가 경신(종가 {cur:,.2f} ≥ 직전고점 "
                            f"{brk['prior_high']:,.2f}) + 거래량 {brk['vol_surge_x']}x"),
                "detail": brk,
            })
        elif brk["state"] == "watch":
            alerts.append({
                "severity": "near", "icon": _ICON["near"], "kind": "breakout_watch",
                "ticker": ticker,
                "message": (f"돌파 임박 관찰 — 고점 대비 {brk['pct_from_high']:+.1f}% + "
                            f"거래량 {brk['vol_surge_x']}x (신고가 경신은 미확인)"),
                "detail": brk,
            })
        elif brk["state"] == "insufficient":
            soft_warnings.append(f"{ticker}: 돌파 점검 생략 — {brk['reason']}")

        # (4) 메모 triggers: 블록 — 실적 D-7/D-1·이벤트 임박
        t_alerts, t_warnings = _memo_trigger_alerts(ticker, histories_dir, today)
        alerts.extend(t_alerts)
        soft_warnings.extend(t_warnings)
        row["memo_triggers_hit"] = len(t_alerts)

        checked.append(row)

    alerts.sort(key=lambda a: (_SEV_ORDER.get(a["severity"], 9), a["ticker"]))

    alerts_file, appended = None, False
    if alerts and append:
        alerts_file = _append_alerts_md(alerts, alerts_dir, asof)
        appended = True
    elif alerts:
        alerts_file = os.path.join(alerts_dir, f"{asof}.md")  # append 생략 시에도 경로 안내

    data_status = "ok" if fetched == len(universe) else ("degraded" if fetched else "no_data")
    return {
        "asof": asof,
        "price_basis": "완성 일봉 종가 (진행 중 봉 제외 — 장 마감 후 실행 권장)",
        "universe": {
            "portfolio": [h["ticker"] for h in holdings],
            "watchlist": [w["ticker"] for w in watchlist],
        },
        "summary": {
            "violations": sum(1 for a in alerts if a["severity"] == "violation"),
            "near": sum(1 for a in alerts if a["severity"] == "near"),
            "triggers": sum(1 for a in alerts if a["severity"] == "trigger"),
        },
        "alerts": alerts,
        "checked": checked,
        "alerts_file": alerts_file,
        "appended": appended,
        "soft_warnings": soft_warnings,
        "errors": errors,
        "data_status": data_status,
    }
