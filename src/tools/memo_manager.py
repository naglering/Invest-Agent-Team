"""메모 관리 도구 - Memo Writer / Committee Chair 에이전트용

투자 메모 작성, 조회, 검색 기능 제공.

저장 구조 (디렉토리 단위 — 요약/종합보고서 쌍):
    data/histories/YYYY-MM-DD_TICKER/
        ├── summary.md   # 규격화된 투자 메모 요약 (memo-writer)
        └── report.md    # 위원회 최종 종합보고서 (Committee Chair)

하위호환: 과거의 flat 파일(data/histories/YYYY-MM-DD_TICKER.md)도 조회/검색에서
계속 인식한다. `memo migrate`로 디렉토리 구조로 이전할 수 있다.
"""

import os
import re
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MEMOS_DIR = os.path.join(DATA_DIR, "histories")

SUMMARY_NAME = "summary.md"
REPORT_NAME = "report.md"

# YYYY-MM-DD_TICKER (디렉토리/레거시 파일 공통 파싱)
_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(?:\.md)?$")


def _ensure_dir():
    os.makedirs(MEMOS_DIR, exist_ok=True)


def _dir_name(ticker: str, date: str = None, suffix: str = "") -> str:
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return f"{date}_{ticker.upper()}{suffix}"


MEMO_TEMPLATE = """# 투자 메모: {ticker} ({company_name})

**작성일**: {date}
**분석가**: {analyst}
**확신도**: {conviction}

> 📄 이 파일은 **요약(summary)**입니다. 같은 디렉토리의 `report.md`에 위원회 최종 종합보고서가 있습니다.

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

## 서사·모멘텀·자금흐름

<!-- 메가트렌드 테마, 상대강도(RS), 섹터 자금유입 등 정성적 모멘텀 상태 요약 -->
{narrative_momentum}

## 투자 결정

### 현재 보유자
<!-- 3분기 권고: ① 비중 유지(Hold) ② 비중 확대-피라미딩(Add) ③ 비중 축소(Trim) 중 택일 -->
<!-- 예시: "비중 확대(피라미딩) — 신고가 안착 시 추가 진입, 현 RS 우위 지속" -->
- **권고**: {decision_holder}

### 신규 투자자
- **권고**: {decision_new}

- **목표가**: {target_price}

### 손절 체계 (손실은 짧게, 이익은 길게)
<!-- 단일 손절값이 아닌 초기 손절 + 트레일링 규칙으로 분리 운용 -->
- **초기 손절가(initial stop)**: {stop_loss}
- **트레일링 규칙(trailing stop)**: {trailing_stop_rule}
  <!-- 예: "20일선 종가 이탈 시 청산", "직전 고점 대비 -15% 추격손절" -->

### 비대칭 손익비 (Payoff / R-multiple)
<!-- 상방(현재가→목표가)과 하방(현재가→초기손절)의 비율. 예: 3:1 이면 +3R / -1R -->
- **손익비**: {payoff_ratio}

### 피라미딩 (승자에 더 태우기)
<!-- 추세가 입증된 후 단계적 추가 진입 조건 -->
- **트리거**: {pyramiding_trigger}
  <!-- 예: "신고가 돌파 + 거래대금 증가 시 추가 X% 진입" -->

## 카탈리스트 캘린더

<!-- 임박한 촉매(실적/이벤트/규제 결정 등)와 예상 날짜 -->
{catalyst_calendar}

## 포지션 사이징

{position_sizing}

## 시나리오 분석

{scenario_analysis}

## 후속 조치

{follow_up}

---

*이 메모는 투자 참고 자료이며, 투자 권유가 아닙니다.*
"""


def _render_summary(ticker: str, data: dict, date: str) -> str:
    decision_holder = data.get("decision_holder", data.get("decision", "N/A"))
    decision_new = data.get("decision_new", data.get("decision", "N/A"))
    return MEMO_TEMPLATE.format(
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
        narrative_momentum=data.get("narrative_momentum", "N/A"),
        decision_holder=decision_holder,
        decision_new=decision_new,
        target_price=data.get("target_price", "N/A"),
        stop_loss=data.get("stop_loss", "N/A"),
        trailing_stop_rule=data.get("trailing_stop_rule", "N/A"),
        payoff_ratio=data.get("payoff_ratio", "N/A"),
        pyramiding_trigger=data.get("pyramiding_trigger", "N/A"),
        catalyst_calendar=data.get("catalyst_calendar", "N/A"),
        position_sizing=data.get("position_sizing", "N/A"),
        scenario_analysis=data.get("scenario_analysis", "N/A"),
        follow_up=data.get("follow_up", "N/A"),
    )


def write_memo(ticker: str, data: dict, overwrite: bool = True) -> dict:
    """투자 메모(요약)를 디렉토리 구조로 저장한다.

    `data/histories/YYYY-MM-DD_TICKER/summary.md` 에 요약을 기록하고,
    `data["full_report"]`가 있으면 같은 디렉토리에 `report.md`도 함께 저장한다.
    (일반적으로 종합보고서는 Committee Chair가 `write_report`로 별도 저장한다.)

    Args:
        ticker: 종목 티커
        data: 메모 데이터(dict). 표준 요약 필드 + 선택 키:
            - version: 지정 시 디렉토리명 suffix로 별도 보관
            - full_report: 종합보고서 마크다운(있으면 report.md로 저장)
        overwrite: False면 같은 날 디렉토리가 이미 있을 때 시각(HHMM) suffix로 분리.
    Returns:
        dict: 저장 경로 및 메타데이터
    """
    _ensure_dir()
    date = datetime.now().strftime("%Y-%m-%d")

    # 디렉토리명 suffix: version 우선, 아니면 overwrite=False+기존 존재 시 HHMM
    suffix = ""
    version = data.get("version")
    if version not in (None, "", "N/A"):
        suffix = f"_{str(version).strip()}"
    elif not overwrite and os.path.isdir(os.path.join(MEMOS_DIR, _dir_name(ticker, date))):
        suffix = f"_{datetime.now().strftime('%H%M')}"

    dirname = _dir_name(ticker, date, suffix)
    dirpath = os.path.join(MEMOS_DIR, dirname)
    os.makedirs(dirpath, exist_ok=True)

    summary_path = os.path.join(dirpath, SUMMARY_NAME)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(_render_summary(ticker, data, date))

    report_path = None
    full_report = data.get("full_report")
    if full_report not in (None, "", "N/A"):
        report_path = os.path.join(dirpath, REPORT_NAME)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(full_report)

    return {
        "status": "success",
        "dir": dirpath,
        "summary_path": summary_path,
        "report_path": report_path,
        "ticker": ticker.upper(),
        "date": date,
        "hint": ("종합보고서는 Committee Chair가 `cli.py memo report <TICKER>`로 "
                 "report.md에 저장합니다." if report_path is None else None),
    }


def write_report(ticker: str, content: str, date: str = None) -> dict:
    """위원회 최종 종합보고서를 같은 분석 디렉토리의 report.md로 저장한다.

    summary.md가 만들어진 `YYYY-MM-DD_TICKER/` 디렉토리에 report.md를 기록한다.
    디렉토리가 없으면 생성한다(요약 없이 보고서만 저장하는 경우 대비).
    """
    _ensure_dir()
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    dirpath = os.path.join(MEMOS_DIR, _dir_name(ticker, date))
    os.makedirs(dirpath, exist_ok=True)
    report_path = os.path.join(dirpath, REPORT_NAME)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content if content is not None else "")
    return {
        "status": "success",
        "dir": dirpath,
        "report_path": report_path,
        "has_summary": os.path.exists(os.path.join(dirpath, SUMMARY_NAME)),
        "ticker": ticker.upper(),
        "date": date,
    }


def _iter_records():
    """histories의 모든 메모를 (dir/legacy) 레코드로 열거."""
    _ensure_dir()
    records = []
    for name in os.listdir(MEMOS_DIR):
        path = os.path.join(MEMOS_DIR, name)
        if os.path.isdir(path):
            has_summary = os.path.exists(os.path.join(path, SUMMARY_NAME))
            has_report = os.path.exists(os.path.join(path, REPORT_NAME))
            if not (has_summary or has_report):
                continue  # 메모 디렉토리가 아님
            m = _NAME_RE.match(name)
            records.append({
                "kind": "dir", "name": name, "path": path,
                "date": m.group(1) if m else "",
                "ticker": (m.group(2) if m else name).upper(),
                "has_summary": has_summary, "has_report": has_report,
            })
        elif name.endswith(".md") and name != "README.md":
            m = _NAME_RE.match(name)
            if not m:
                continue  # 날짜 형식이 아닌 flat 파일은 제외(예: 구 EXAMPLE.md)
            records.append({
                "kind": "flat", "name": name, "path": path,
                "date": m.group(1), "ticker": m.group(2).upper(),
                "has_summary": True, "has_report": False,
            })
    # 최신(날짜) 우선, 같은 날짜면 dir 우선
    records.sort(key=lambda r: (r["date"], r["kind"] == "dir", r["name"]), reverse=True)
    return records


def _read_record(rec: dict, which: str = "summary") -> dict:
    """레코드에서 summary/report/both 내용을 읽어 반환."""
    out = {"ticker": rec["ticker"], "date": rec["date"], "kind": rec["kind"],
           "name": rec["name"], "path": rec["path"], "has_report": rec["has_report"]}
    if rec["kind"] == "flat":
        with open(rec["path"], encoding="utf-8") as f:
            out["content"] = f.read()
        out["which"] = "summary(legacy)"
        return out

    sp = os.path.join(rec["path"], SUMMARY_NAME)
    rp = os.path.join(rec["path"], REPORT_NAME)
    summary = open(sp, encoding="utf-8").read() if os.path.exists(sp) else None
    report = open(rp, encoding="utf-8").read() if os.path.exists(rp) else None

    if which == "report":
        out["which"] = "report"
        out["content"] = report if report is not None else (summary or "")
        if report is None:
            out["note"] = "report.md 없음 → summary 반환"
    elif which == "both":
        out["which"] = "both"
        out["summary"] = summary
        out["report"] = report
    else:
        out["which"] = "summary"
        out["content"] = summary if summary is not None else (report or "")
    out["summary_path"] = sp if summary is not None else None
    out["report_path"] = rp if report is not None else None
    return out


def read_memo(ticker: str, which: str = "summary") -> dict:
    """특정 티커의 가장 최신 메모를 읽는다. which: summary|report|both."""
    ticker = ticker.upper()
    recs = [r for r in _iter_records() if r["ticker"] == ticker]
    if not recs:
        return {"error": f"티커 '{ticker}'에 대한 메모가 없습니다.", "ticker": ticker}
    out = _read_record(recs[0], which)
    out["all_memos"] = [r["name"] for r in recs]
    return out


def list_memos() -> dict:
    """저장된 모든 메모(디렉토리/레거시) 목록을 반환한다."""
    recs = _iter_records()
    memos = [{
        "name": r["name"], "date": r["date"], "ticker": r["ticker"],
        "kind": r["kind"], "has_summary": r["has_summary"], "has_report": r["has_report"],
    } for r in recs]
    return {"total_count": len(memos), "memos": memos, "directory": MEMOS_DIR}


def search_memos(query: str) -> dict:
    """histories 내 모든 메모(summary/report, 레거시 포함)에서 키워드 검색."""
    _ensure_dir()
    q = query.lower()
    results = []
    for root, _dirs, files in os.walk(MEMOS_DIR):
        for fname in files:
            if not fname.endswith(".md") or fname == "README.md":
                continue
            fpath = os.path.join(root, fname)
            try:
                content = open(fpath, encoding="utf-8").read()
            except OSError:
                continue
            if q not in content.lower():
                continue
            rel = os.path.relpath(fpath, MEMOS_DIR)
            lines = [ln.strip() for ln in content.split("\n")
                     if q in ln.lower() and ln.strip()][:3]
            parent = os.path.basename(os.path.dirname(fpath))
            m = _NAME_RE.match(parent if parent != "histories" else fname)
            results.append({
                "file": rel,
                "date": m.group(1) if m else "",
                "ticker": (m.group(2).upper() if m else ""),
                "doc": ("report" if fname == REPORT_NAME else
                        "summary" if fname == SUMMARY_NAME else "legacy"),
                "matching_lines": lines,
            })
    results.sort(key=lambda r: r["date"], reverse=True)
    return {"query": query, "total_results": len(results), "results": results}


def migrate_legacy(apply: bool = False) -> dict:
    """레거시 flat 파일(YYYY-MM-DD_TICKER.md)을 디렉토리 구조로 이전.

    각 파일을 `YYYY-MM-DD_TICKER/summary.md`로 이동한다. apply=False면 계획만 반환.
    이미 디렉토리가 존재하는 항목은 충돌로 표기하고 건너뛴다.
    """
    _ensure_dir()
    plan = []
    for name in sorted(os.listdir(MEMOS_DIR)):
        if not name.endswith(".md") or name == "README.md":
            continue
        m = _NAME_RE.match(name)
        if not m:
            continue  # 날짜 형식 아닌 flat 파일은 대상 외
        src = os.path.join(MEMOS_DIR, name)
        if not os.path.isfile(src):
            continue
        dirname = name[:-3]  # .md 제거 → YYYY-MM-DD_TICKER
        dirpath = os.path.join(MEMOS_DIR, dirname)
        dst = os.path.join(dirpath, SUMMARY_NAME)
        if os.path.exists(dirpath):
            plan.append({"file": name, "status": "conflict(디렉토리 이미 존재)", "skipped": True})
            continue
        if apply:
            os.makedirs(dirpath, exist_ok=True)
            os.rename(src, dst)
            plan.append({"file": name, "status": "migrated", "to": os.path.relpath(dst, MEMOS_DIR)})
        else:
            plan.append({"file": name, "status": "planned", "to": os.path.relpath(dst, MEMOS_DIR)})
    migrated = sum(1 for p in plan if p["status"] == "migrated")
    planned = sum(1 for p in plan if p["status"] == "planned")
    return {"applied": apply, "count": len(plan),
            "migrated": migrated, "planned": planned, "plan": plan}
