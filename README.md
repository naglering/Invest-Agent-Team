# Investment Agent Team

Claude Code Agent Teams 기반 멀티 에이전트 투자 분석 시스템. 8명의 전문 에이전트가 협업하여 종합 투자 판단을 수행합니다.

> 모든 분석은 참고 자료이며 투자 권유가 아닙니다.

## 아키텍처

```
Committee Chair (파이프라인 오케스트레이터)
├── Knowledge Agent ─────── 과거 메모/지식 베이스 검색
├── Earnings Analyst ────── 실적 컨센서스, 기저효과 분석
├── Financial Analyst ───── 재무제표, DuPont, ROIC, 이익의 질
├── Technical Analyst ───── RSI, MACD, 볼린저, 이동평균선
├── Valuation Analyst ───── 2단계 DCF, 피어 멀티플, 시나리오 분석
├── Market Analyst ──────── 뉴스 감성, 내부자 거래, 거버넌스
├── Risk Officer ─────────── VaR, 꼬리 리스크, 포지션 사이징
└── Memo Writer ─────────── 최종 투자 메모 작성
```

## 설치

```bash
pip install -r requirements.txt
```

**의존성**: yfinance, ta, pandas, numpy, requests, beautifulsoup4

## 사용법

### Claude Code 슬래시 커맨드 (권장)

```bash
# 멀티 에이전트 순차+병렬 파이프라인 (가장 상세한 분석)
/invest:pipeline AAPL

# 단일 에이전트 종합 분석
/invest:analyze TSLA

# 모든 에이전트 병렬 독립 평가
/invest:broadcast 005930.KS

# 질의 기반 동적 에이전트 활성화
/invest:coordinate "RKLB의 밸류에이션과 리스크를 분석해줘"

# 단일 에이전트 빠른 라우팅
/invest:route "삼성전자 기술적 분석"

# 복잡한 요청 자동 분해
/invest:task "반도체 섹터 상위 3개 종목 비교 분석"
```

### 통합 CLI (직접 실행)

```bash
# 기본 분석
python3 src/tools/cli.py fundamental <TICKER>    # 재무 분석 (ROIC, 이익의 질 포함)
python3 src/tools/cli.py technical <TICKER>      # 기술적 분석
python3 src/tools/cli.py news <TICKER>           # 뉴스 수집
python3 src/tools/cli.py earnings <TICKER>       # 실적발표 일정 + 컨센서스
python3 src/tools/cli.py risk <TICKER>           # 리스크 분석
python3 src/tools/cli.py valuation <TICKER>      # 2단계 DCF / 상대가치 분석
python3 src/tools/cli.py peers <TICKER>                    # 동종업계 비교 (자동 피어)
python3 src/tools/cli.py peers <TICKER> --peers T1,T2,T3   # 동종업계 비교 (커스텀 피어)
python3 src/tools/cli.py insider <TICKER>        # 내부자 거래 / 기관 보유
python3 src/tools/cli.py mandate-check <TICKER>  # 투자 mandate 준수 확인

# 웹 검색
python3 src/tools/cli.py news-search "<QUERY>"   # 뉴스 키워드 검색

# 메모 관리
python3 src/tools/cli.py memo list               # 메모 목록
python3 src/tools/cli.py memo read <TICKER>      # 메모 조회
python3 src/tools/cli.py memo search "<QUERY>"   # 메모 검색
python3 src/tools/cli.py memo write <TICKER>     # 메모 작성

# 빠른 통합 분석 (레거시)
python3 src/main.py <TICKER>
```

### 티커 형식

| 시장 | 형식 | 예시 |
|------|------|------|
| 미국 | `TICKER` | `AAPL`, `MSFT`, `GOOGL` |
| 한국 | `CODE.KS` | `005930.KS` (삼성전자) |

## 분석 모듈

| 모듈 | 파일 | 주요 분석 항목 |
|------|------|---------------|
| 재무 분석 | `src/fundamental.py` | 수익성, 성장성, 재무 건전성, 현금흐름, 운전자본, ROIC, 이익의 질, DuPont 분해, 분기별 추세 |
| 기술적 분석 | `src/technical.py` | RSI, MACD, 볼린저 밴드, 이동평균선, 거래량 분석 |
| 뉴스 분석 | `src/news.py` | 최근 14일간 관련 뉴스 수집 |
| 밸류에이션 | `src/tools/valuation.py` | 2단계 DCF (Phase1 고성장 + Phase2 체감), 상대가치, 역내재 성장률, 민감도 매트릭스 |
| 피어 비교 | `src/tools/peer_comparison.py` | 동종업계 멀티플 비교 (PER, PBR, EV/EBITDA, PS), 커스텀 피어 지원 |
| 실적 캘린더 | `src/tools/earnings_calendar.py` | 실적발표 일정, 컨센서스 EPS/매출 |
| 리스크 분석 | `src/tools/risk_analyzer.py` | VaR, 변동성, 최대 낙폭, 베타 |
| 내부자 분석 | `src/tools/insider_analysis.py` | 내부자 거래 패턴, 기관 보유 비중 |
| 메모 관리 | `src/tools/memo_manager.py` | 투자 메모 CRUD, 검색 |

## 에이전트 구성

| 에이전트 | 역할 | 핵심 산출물 |
|---------|------|-----------|
| Knowledge Agent | 과거 분석 메모, 지식 베이스 검색 | 이전 분석 대비 변화 요약 |
| Earnings Analyst | 실적 컨센서스, 기저효과 분석 | 서프라이즈 가능성, 정상화 성장률 |
| Financial Analyst | 재무제표 심층 분석 | 사이클 위치, ROIC, 이익의 질 |
| Technical Analyst | 차트 기반 기술적 분석 | 매매 시그널, 지지/저항선 |
| Valuation Analyst | 내재가치 산출 | DCF 적정가, 시나리오별 목표가 |
| Market Analyst | 시장 심리, 뉴스, 거버넌스 | 감성 스코어, 내부자 동향 |
| Risk Officer | 리스크 평가, 포지션 사이징 | 리스크 등급, Kelly 기반 비중 |
| Memo Writer | 최종 보고서 작성 | 투자 메모 (MD 파일) |

## 파이프라인 흐름

```
Step 0: 팀 생성
    │
Step 1: 데이터 수집 (병렬)
    ├── Knowledge Agent ──── 과거 메모 검색
    ├── Earnings Analyst ─── 실적 데이터
    ├── Financial Analyst ── 재무 분석
    ├── Technical Analyst ── 기술적 분석
    ├── Valuation Analyst ── 밸류에이션
    └── Market Analyst ───── 시장/뉴스 분석
    │
Step 2: 리스크 평가
    └── Risk Officer ─────── 리스크 통합 + 포지션 사이징
    │
Step 3: Committee Chair 종합
    ├── Devil's Advocate (반대 논거 검증)
    ├── 이중 추천 (보유자 / 신규 투자자)
    ├── 시나리오 분석 (Bear / Base / Bull)
    └── 투자 결정 + 확신도
    │
Step 4: 메모 작성
    └── Memo Writer ─────── 최종 투자 메모 저장
```

## 프로젝트 구조

```
invest-principal/
├── src/
│   ├── main.py                  # 레거시 통합 분석
│   ├── fundamental.py           # 재무 분석 (ROIC, 이익의 질 포함)
│   ├── technical.py             # 기술적 분석
│   ├── news.py                  # 뉴스 수집
│   └── tools/
│       ├── cli.py               # 통합 CLI 진입점
│       ├── valuation.py         # 2단계 DCF, 상대가치
│       ├── peer_comparison.py   # 피어 비교
│       ├── earnings_calendar.py # 실적 캘린더
│       ├── risk_analyzer.py     # 리스크 분석
│       ├── insider_analysis.py  # 내부자 거래
│       ├── memo_manager.py      # 메모 관리
│       └── news_search.py       # 뉴스 검색
├── .claude/
│   ├── agents/                  # 에이전트 프롬프트 정의 (8명)
│   └── commands/invest/         # 슬래시 커맨드 정의 (6개)
├── data/
│   ├── memos/                   # 투자 메모 (YYYY-MM-DD_TICKER.md)
│   ├── knowledge/               # 지식 베이스
│   └── mandates/                # 투자 mandate 설정
├── CLAUDE.md                    # 프로젝트 지침
├── requirements.txt
└── README.md
```

## 주요 특징

- **2단계 DCF 모델**: Phase 1(1~5년) 고성장 + Phase 2(6~10년) 영구성장률까지 선형 체감
- **이중 추천 체계**: 현재 보유자와 신규 투자자에게 각각 다른 행동 지침 제시
- **Devil's Advocate**: Committee Chair가 의도적으로 반대 논거를 검증
- **사이클 분석**: 사이클 산업의 피크 이익 함정 경고
- **이익의 질 검증**: FCF/순이익 비율, 발생액 비율로 이익의 현금 전환 품질 평가
- **포지션 사이징**: Half-Kelly 기반 권고 비중, 승률/수익손실 비율 투명 공개
