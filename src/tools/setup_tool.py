"""초기 세팅 도구 — 개인 데이터/설정 파일을 템플릿으로 생성.

GitHub에는 **골격(skeleton)만** 올라간다. 개인 투자 데이터(보유 종목·Thesis·
포지션·투자 메모)는 `.gitignore` 처리되어 추적되지 않으므로, 클론 직후 아래
명령으로 본인 데이터 파일을 생성한 뒤 직접 편집해 사용한다.

    python3 src/tools/cli.py setup            # data/mandates/*.json 생성
    python3 src/tools/cli.py portfolio init   # portfolio.md / theses.md / positions.md 생성

기존 파일은 보존한다(덮어쓰지 않음). 강제로 정본을 다시 깔려면 --force.
"""

import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _data_path(*parts):
    return os.path.normpath(os.path.join(_DATA_DIR, *parts))


# ── mandate 정본 (skeleton) ───────────────────────────────────────────────

MANDATE_DEFAULT = {
    "name": "기본 투자 mandate",
    "max_position_pct": 10,
    "min_market_cap_usd": 1000000000,
    "allowed_sectors": [],
    "excluded_sectors": [],
    "max_pe_ratio": 50,
    "min_dividend_yield": 0,
    "max_debt_to_equity": 3.0,
    "risk_tolerance": "moderate",
    "description": "일반적인 분산 투자 전략. 중간 위험 허용도, 대형주 중심.",
}

MANDATE_MEGATREND = {
    "name": "메가트렌드 공격 mandate",
    "max_position_pct": 25,
    "min_market_cap_usd": 200000000,
    "allowed_sectors": [],
    "excluded_sectors": [],
    "max_pe_ratio": None,
    "min_dividend_yield": 0,
    "max_debt_to_equity": 5.0,
    "risk_tolerance": "aggressive",
    "description": (
        "메가트렌드(AI/반도체, SMR·원자력, 우주, 비만치료제, 양자, 방산, "
        "데이터센터 전력) 집중·모멘텀 베팅 전략. PER 게이트 비활성(고성장은 "
        "P/S·매출성장·룰40으로 평가), 고변동·고베타 허용, 승자 집중·피라미딩 "
        "허용. 리스크는 거부권이 아니라 손절 규율과 포지션 사이징으로 관리한다."
    ),
}

MANDATE_CRYPTO = {
    "name": "크립토 공격 mandate",
    "max_position_pct": 20,
    "min_market_cap_usd": 1000000000,
    "allowed_sectors": [],
    "excluded_sectors": [],
    "max_pe_ratio": None,
    "min_dividend_yield": 0,
    "max_debt_to_equity": None,
    "risk_tolerance": "aggressive",
    "description": (
        "디지털자산(BTC·ETH·주요 알트) 집중·모멘텀 베팅 mandate. PER/부채비율/배당 "
        "게이트는 주식 지표라 N/A — 대신 토크노믹스(발행·언락 희석, FDV/MC), 온체인 "
        "네트워크 가치(NVT·MVRV·P/F·실질 스테이킹 수익률), 홀더/거래소 집중도, 규제 "
        "리스크로 판단한다. 극단적 변동성(80%+ 낙폭 전례)을 손절 규율과 포지션 사이징"
        "으로 관리하며, 단일 자산 최대 20%·시총 $1B 미만(저유동·러그 위험) 회피. "
        "리스크는 거부권이 아니라 사이징·손절선 입력이다."
    ),
}


# ── 개인 데이터 템플릿 (skeleton) ─────────────────────────────────────────

PORTFOLIO_TEMPLATE = """# 내 포트폴리오 (보유 종목)

이 파일은 **직접 편집**하여 관리합니다. 행을 추가/수정/삭제한 뒤
`python3 src/tools/cli.py portfolio` 를 실행하면 현재가·환율을 자동 조회해
평가금액·손익·비중을 계산해 줍니다.

## 입력 규칙

- **종목**: 티커 (미국 `NVDA`, 한국 `005930.KS`)
- **수량**: 보유 주식 수
- **매입가**: 1주당 평균 매입 단가 (해당 종목의 통화 기준)
- **통화**: `USD` 또는 `KRW`
- **매입시환율**: USD 종목만 입력 (매입 시점 원/달러 환율, 예 `1380`). KRW 종목은 `-`
  - 누락 시 현재환율로 대체 → **원화 손익은 부정확**(현지통화 USD 수익률은 정확)

> 아래 표는 **예시**입니다. 본인 보유 종목으로 교체하세요.

## 보유 종목

| 종목 | 수량 | 매입가 | 통화 | 매입시환율 |
|------|------|--------|------|-----------|
| NVDA | 10 | 120.00 | USD | 1380 |
| 005930.KS | 50 | 70000 | KRW | - |
"""

THESES_TEMPLATE = """# 보유 종목 투자 Thesis & 흔들림 판정 기준

각 종목을 **왜 보유하는가(Thesis)** 와, 그 논거가 **흔들렸는지 판정하는 트리거**를 정의한다.
직접 편집하여 본인 견해에 맞게 수정하세요. (아래는 예시 — 본인 종목으로 교체)

판정 등급:
- 🟢 **견고(Intact)**: 부정 트리거 없음, 논거 유지
- 🟡 **흔들림(Cracking)**: 흔들림 신호 1개 이상, 주시 필요
- 🔴 **훼손(Broken)**: 논거 훼손 트리거 확인, 비중 축소/매도 검토

---

### NVDA — (예시) AI 가속기 (GPU/데이터센터)
- **Thesis**: AI 학습·추론 인프라 표준. 데이터센터 GPU 수요 폭증 + CUDA 생태계 해자.
- **핵심 가정(KPI)**: ① 데이터센터 매출 성장, ② 차세대 아키텍처 로드맵, ③ 공급/캐파, ④ 경쟁(커스텀 ASIC) 대응.
- 🟡 **흔들림**: 하이퍼스케일러 capex 둔화, 매출 성장률 감속, 경쟁 점유 잠식, 멀티플 과열 후 조정.
- 🔴 **훼손**: AI capex 사이클 꺾임, 핵심 고객 인하우스 칩 전환, 매출 역성장.

---

## 판정 → 액션 연동
- 🔴 훼손 → 🔴 매도/축소 우선
- 🟡 흔들림 → 🟡 보유(주시), 신규매수 보류
- 🟢 견고 + 긍정 모멘텀 → 🟢 비중확대 검토

> ※ 참고용이며 투자 권유가 아님.
"""

POSITIONS_TEMPLATE = """# 포지션 비중 (실제 보유 기준)

이 파일의 비중은 **실제 보유 포트폴리오**에서 산출(`python3 src/tools/cli.py portfolio`).
루틴은 이 비중을 ① 뉴스/Thesis **영향도 가중치**, ② **집중도** 참고로 사용한다.
임의 상한(cap)은 두지 않음 — 실제 보유 그대로가 기준.

## 기준일: (YYYY-MM-DD)

| 순위 | 종목 | 비중 | 비고 |
|------|------|------|------|
| 1 | (예시) | -% | |

## 사용 규칙 (루틴)

- 비중 = 뉴스/Thesis **영향도 가중치**. 비중 큰 종목의 악재·Thesis 흔들림을 우선 처리.
- 집중 종목(단일 20%+)은 단일 악재의 손익 영향이 큼 → 보고서에서 강조.
- 갱신: 보유/가격 변동 시 `cli.py portfolio` 재실행 후 비중·기준일 업데이트.

> ※ 참고용이며 투자 권유가 아님.
"""


def _write(path: str, content: str, force: bool) -> str:
    """파일 기록. 존재 시 force가 아니면 건너뜀. 상태 문자열 반환."""
    rel = os.path.relpath(path, os.path.join(os.path.dirname(__file__), "..", ".."))
    existed = os.path.exists(path)
    if existed and not force:
        return f"skip(존재): {rel}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"{'overwrite' if existed else 'create'}: {rel}"


def setup_mandates(force: bool = False) -> dict:
    """data/mandates/{default,megatrend,crypto}.json 정본 생성."""
    results = [
        _write(_data_path("mandates", "default.json"),
               json.dumps(MANDATE_DEFAULT, ensure_ascii=False, indent=2) + "\n", force),
        _write(_data_path("mandates", "megatrend.json"),
               json.dumps(MANDATE_MEGATREND, ensure_ascii=False, indent=2) + "\n", force),
        _write(_data_path("mandates", "crypto.json"),
               json.dumps(MANDATE_CRYPTO, ensure_ascii=False, indent=2) + "\n", force),
    ]
    return {"action": "setup-mandates", "force": force, "results": results,
            "hint": "프로파일 값을 본인 전략에 맞게 편집하세요. 기존 파일은 --force로만 덮어씁니다."}


def setup_portfolio(force: bool = False) -> dict:
    """개인 데이터 파일(portfolio.md / theses.md / positions.md) 템플릿 생성."""
    results = [
        _write(_data_path("portfolio.md"), PORTFOLIO_TEMPLATE, force),
        _write(_data_path("theses.md"), THESES_TEMPLATE, force),
        _write(_data_path("positions.md"), POSITIONS_TEMPLATE, force),
    ]
    return {"action": "setup-portfolio", "force": force, "results": results,
            "hint": "예시 데이터를 본인 보유 종목/Thesis로 교체한 뒤 `cli.py portfolio`로 평가하세요."}
