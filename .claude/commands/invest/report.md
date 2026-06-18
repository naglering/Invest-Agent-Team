PDF 보고서 — 위원회 종합보고서(report.md)를 증권사 스타일 PDF로 출력합니다.

요청: $ARGUMENTS

---

## 역할

이미 작성된 투자위원회 종합보고서(`data/histories/<날짜>_<TICKER>/report.md`)를 **증권사 애널리스트 리포트 스타일의 PDF**로 변환합니다. 본문은 report.md를 그대로 이식하고, 1페이지 표지(헤더 + Key-Data 사이드바 + Key Takeaways + Risk-Reward 차트)는 메타 JSON으로 정밀 렌더합니다.

> 보고서가 아직 없으면 먼저 `/invest:stock <TICKER>`(주식) 또는 `/invest:crypto <TICKER>`(디지털자산)로 심층 분석을 수행해 report.md를 생성하세요. 두 트랙 모두 동일한 `data/histories/<날짜>_<TICKER>/report.md` 구조로 저장되므로 PDF 변환은 동일하게 동작합니다.

**스타일**: 하이브리드(한국 증권사 헤더/사이드바 + 글로벌 IB의 Risk-Reward 세로축 차트·Exhibit 번호 규칙). 본문 표는 자동으로 `Exhibit N` + 출처 푸터가 붙고, 판정 이모지(🟢🟡🔴✅❌ 등)는 색상 기호(●▲▼✓✗)로 깔끔하게 치환됩니다(이모지 폰트 불필요).

## 인자 파싱

`$ARGUMENTS`에서 다음을 추출합니다:
- **TICKER** (필수): 예 `TSLA`, `005930.KS`
- `--mode deep|brief` (선택, 기본 `deep`): `deep`=report.md 전체 심층형(약 5–11p), `brief`=summary.md 요약형(1–2p)
- `--date YYYY-MM-DD` (선택): 특정 날짜 메모 지정. 미지정 시 해당 티커 **최신** 디렉토리 자동 선택

TICKER가 없으면 어떤 종목인지 사용자에게 질문합니다.

## 실행 절차

### Step 1 — 대상 메모 확인
`python3 src/tools/cli.py memo read <TICKER> report` (deep) 또는 `... summary`(brief)로 본문이 존재하는지 확인하고 내용을 읽습니다. 없으면 `/invest:stock`(주식)·`/invest:crypto`(디지털자산)을 안내하고 중단합니다.

### Step 2 — 메타 JSON 구성 (표지/사이드바/차트용)
report.md(또는 summary.md)의 내용을 읽고, 아래 스키마로 **메타 JSON**을 작성해 임시 파일(예 `/tmp/<TICKER>_meta.json`)로 저장합니다. **모든 필드는 선택적**이며, 없으면 표지에서 우아하게 생략됩니다. 수치는 본문에서 그대로 인용하되, 현재가·시총·52주·베타 등 Key-Data는 정확도를 위해 `python3 src/tools/cli.py portfolio quote <TICKER>`로 보강해도 됩니다.

```json
{
  "company": "회사명",
  "exchange": "NASDAQ | KOSPI 등",
  "report_type": "Company In-depth | Company Brief",
  "headline": "보고서 한 줄 핵심 메시지(Executive Summary의 한줄 요약에서)",
  "rating": {
    "action": "매수 | 관망 | 매도",
    "action_en": "BUY | NEUTRAL | SELL",
    "stance": "신규 | 유지 | 상향 | 하향",
    "target_price": "$569 (확률가중 적정가 등 대표 목표가)",
    "current_price": "$396.38",
    "upside_pct": "+43.6% (음수면 자동 빨강)",
    "conviction_stars": 2,          // 1~5 정수 (⭐ 개수)
    "conviction_label": "중하",
    "position_pct": "3.0% (권고 비중)"
  },
  "key_data": [                      // 우측 사이드바 (라벨/값 쌍, 순서대로)
    {"label": "현재가", "value": "$396.38"},
    {"label": "시가총액", "value": "$1.49T"},
    {"label": "52주 범위", "value": "$293.94 – $498.83"},
    {"label": "베타", "value": "2.04"},
    {"label": "PER (현/선행)", "value": "363x / 159x"},
    {"label": "mandate", "value": "default (보수)"}
  ],
  "price_return": [                  // 선택: 기간별 수익률(상대강도)
    {"period": "3M", "abs": "+0.9%", "rel": "SPY -11.4%p"},
    {"period": "12M", "abs": "+23.1%", "rel": "—"}
  ],
  "takeaways": [                     // Key Takeaways 3~5 불릿(Executive Summary 압축)
    "...", "...", "..."
  ],
  "scenarios": [                     // Risk-Reward 차트 + 표 (반드시 Bull/Base/Bear 3개)
    {"name": "Bull", "price": "$1,100", "ret": "+178%", "prob": "30%", "assumption": "핵심 가정"},
    {"name": "Base", "price": "$420",   "ret": "+6%",   "prob": "45%", "assumption": "핵심 가정"},
    {"name": "Bear", "price": "$200",   "ret": "-50%",  "prob": "25%", "assumption": "핵심 가정"}
  ],
  "weighted": {"price": "$569", "ret": "+43.6%"}
}
```

> 📌 **scenarios의 name은 반드시 영문 Bull/Base/Bear** 로 쓰세요(차트가 이 키로 색상·위치를 잡습니다). price는 `$` 포함 숫자면 됩니다(범위 `$900–1,400`도 첫 숫자를 사용). 시나리오 3개가 모두 있어야 Risk-Reward 차트가 그려집니다.

### Step 3 — PDF 생성
```bash
python3 src/tools/cli.py report-pdf <TICKER> --meta /tmp/<TICKER>_meta.json --mode <deep|brief>
# 또는 메타를 stdin으로:  ... report-pdf <TICKER> --meta-stdin --mode deep   (stdin에 JSON)
```
출력: 같은 디렉토리에 `report.pdf`(deep) 또는 `summary.pdf`(brief) 생성. 함께 `report.html`도 남습니다(디버그/재인쇄용).

### Step 4 — 결과 보고
생성된 **PDF 경로**와 페이지 수(가능하면), 표지에 반영된 투자의견·목표가·확신도를 한 줄로 요약 보고합니다.

## 주의사항
- 본문 내용은 **report.md를 그대로** 사용합니다(재작성·요약하지 않음). 메타 JSON은 표지/사이드바/차트 렌더용 구조화 데이터일 뿐입니다.
- 큰 숫자는 읽기 쉽게(예: $1.49T, 약 ₩2,056조), 데이터 없는 항목은 "N/A".
- 물결표(`~`)는 본문 규칙대로 사용하지 않습니다(범위는 `–`/`-`, 근사는 `약`).
- 투자 참고 자료이며 투자 권유가 아닙니다(PDF 맨뒤 Disclosures에 자동 포함).
