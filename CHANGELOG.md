# 변경사항 (CHANGELOG)

## 2026-06-17 — 포트폴리오 관리 명령 + 슬래시 커맨드

세팅·포트폴리오 관리를 슬래시 커맨드와 CLI 서브커맨드로 노출했다.

- **슬래시 커맨드 신설** `/invest:setup`(부트스트랩 — mandate + 개인데이터 생성), `/invest:portfolio`(구성·매수·매도·평가).
- **CLI 서브커맨드 추가** (`src/tools/portfolio.py`):
  - `portfolio quote <TICKER>` — 매수 입력용 간단 종목정보(이름·현재가·통화·섹터·52주·시총).
  - `portfolio add <TICKER> --qty N --price P [--ccy] [--fx]` — 매수(추가/평단 갱신). 파일 없으면 생성, 같은 티커는 덮어쓰기. USD 환율 누락 시 경고.
  - `portfolio remove <TICKER>` — 매도(보유 행 제거).
  - 테이블 편집은 주변 텍스트(규칙·메모)를 보존하며 데이터 행만 안전하게 갱신.

## 2026-06-17 — 개인 데이터 분리 (골격만 공개)

GitHub에는 **골격(skeleton)만** 올리도록 데이터 정책을 정리했다. 개인 투자 데이터(보유 종목·Thesis·포지션·실제 투자 메모)는 `.gitignore` 처리하고, 클론 직후 명령으로 생성·편집하도록 했다.

- **`.gitignore`** — `data/histories/*`(단 `EXAMPLE.md` 추적), `data/portfolio.md`, `data/theses.md`, `data/positions.md` 무시. `budget_*.pdf`, `*:Zone.Identifier` 로컬 산출물도 무시.
- **신규** `src/tools/setup_tool.py` — mandate 정본 + 개인 데이터 템플릿.
- **CLI 추가** `setup`(`data/mandates/{default,megatrend}.json` 생성), `portfolio init`(`portfolio.md`/`theses.md`/`positions.md` 템플릿 생성). 둘 다 기존 파일은 보존(`--force`로만 덮어씀).
- **신규** `data/histories/EXAMPLE.md` — 메모 포맷 가이드(추적 대상).
- 이미 푸시됐던 개인 데이터는 `git filter-repo`로 전체 히스토리에서 제거(force-push).

## 2026-06-17 — 투자 분석 스위트 공격형 전면 개편

보수적 가치투자 프레임을 **"규율 있는 과감한 메가트렌드 베팅"** 자세로 전환. 자금이 몰리는 메가트렌드·강한 서사 종목에 대해 손절 규율을 전제로 한 집중·모멘텀·피라미딩 의사결정이 가능하도록 코드·프롬프트·mandate를 전면 개편했다.

> 페르소나: 20년차 개인 투자 전문가(연 100%+ 수익) 관점. 단, 모든 산출물은 참고 자료이며 투자 권유가 아니다.

---

### 배경 — 진단된 문제

개편 전 시스템은 구조적으로 "사지마/팔아라 기계"였다. 최근 5개 메가트렌드 메모(SPCX·GEV·SOXL·BWXT·NOC) 중 4개가 회피/관망으로 수렴했고, 서사가 가장 약한 저PER 방산주(NOC)만 매수에 근접했다. 보수 편향의 3대 구조적 뿌리:

1. **mandate** — `max_pe_ratio: 50`, `max_position_pct: 10`, `risk_tolerance: moderate`(코드 미반영 라벨). 고PER 메가트렌드 승자를 자동 "위반"으로 차단.
2. **포지션 사이징** — `recommended_pct = min(VaR, Kelly, mandate)`. 고변동 승자일수록 비중이 자동 축소되어 집중·피라미딩이 수식 차원에서 불가능.
3. **밸류에이션** — 음수 FCF면 DCF가 `null`, 성장률 30% 하드캡, 역내재 35%+를 "비현실적"으로 단정. 적자 J커브 종목을 평가 불능/과소평가 처리.

---

### 1. mandate — 2종 프로파일 + 자동선택

- **신설** `data/mandates/megatrend.json` — `max_pe_ratio: null`(PER 게이트 비활성), `max_position_pct: 25`, `max_debt_to_equity: 5.0`, `risk_tolerance: aggressive`.
- `data/mandates/default.json`(보수)은 유지.
- `src/tools/risk_analyzer.py`
  - `_load_mandate(profile)` — 프로파일별 파일 로드(폴백: default).
  - 티커→테마 자동선택: 메가트렌드 테마 종목이면 자동으로 `megatrend` 프로파일 적용(`theme_etf_map.mandate_profile_for_ticker`).
  - `check_mandate(ticker, mandate_profile)`:
    - `max_pe_ratio`가 `null`이면 PER 하드 게이트 비활성 → PER·선행PER·P/S·매출성장·PEG를 **참고치**로만 표기.
    - ETF/펀드(`quoteType`)는 PER 게이트 면제(decay/경로의존성으로 별도 판단).
    - 보수 프로파일에서도 trailingPE 없으면 forwardPE 폴백, 둘 다 없으면(적자) 자동 위반 처리 금지.
    - 부채비율 단위 혼선 방어(값 ≥ 10이면 % 표기로 간주해 배수 환산).

### 2. 포지션 사이징 — `min()` 캡 → 확신도 가중

- `src/tools/risk_analyzer.py` `analyze_risk(...)` 시그니처 확장: `mandate_profile`, `conviction`(0.5~2.0), `entry_mode`(breakout/accumulate/full), `scenarios`, `stop_loss_pct`.
- **사이징 공식 교체**: `recommended_pct = min(mandate_max × 0.5 × conviction, mandate_max)`. 확신도가 비중을 **키우는** 입력. mandate_max가 천장.
- `var_based_max`·Kelly는 자동 감점이 아니라 `soft_warnings` 참고치로 강등.
- **시나리오 기반 Kelly** `calc_scenario_kelly(scenarios)` 신설 — Bull/Base/Bear 확률·수익률로 기대수익·분산 기반 Kelly 산출. 기대수익 음수면 `0`이 아니라 `avoid` 신호. 시나리오 미입력 시 일별 노이즈 Kelly는 "참고용" 라벨.
- `entry_size_pct` 진입모드별 분기(breakout 0.8 / accumulate 0.5 / full 1.0).
- `risk_per_trade` — 손절 폭 입력 시 "자본의 1~2%만 손실" 사이즈 병기.
- **스트레스 테스트** 음수 가격 클램프(`max(..., 0)`, 손실 -100% 하한) — 고베타/레버리지 ETF의 비현실적 음수가 제거.
- `risk_level` 추세 맥락화(`{grade, trend, note}`) — 상승추세의 고변동성은 "위험"이 아니라 "추세 변동성(기회)"으로 구분.
- 피라미딩 가이드(`position_sizing.pyramiding`) — 추세 유효+신고가 돌파+거래량 동반 시 손절선 상향하며 추가 진입(물타기 아님).

### 3. 밸류에이션 — 적자/초기 고성장주 대응

- `src/tools/valuation.py`
  - 음수/부재 FCF면 `dcf.intrinsic_value=null` 대신 `dcf.growth_valuation` 제공: 정규화 DCF(매출 × 목표 FCF마진) + P/S + EV/Sales + 정상화 upside + caveat.
  - 성장률 캡 30% → **60%**(`GROWTH_CAP`), `growth_capped` 플래그 노출.
  - 성장률 입력은 매출성장 우선(흑자전환기 이익성장 폭발/노이즈 회피).
  - 역내재 성장률: "비현실적" 단정 제거 → "시장이 정당화하는지 검증 필요"로 재정의. 탐색 상한 50% → 100%(50%+ 기대 종목 역산 가능).
  - capex 부호 방어(`fcf = ocf - abs(capex)`), beta 출처 명시.

### 4. 신규 도구 (없던 역량)

- **`src/tools/theme_etf_map.py`** — 메가트렌드 8개 테마(AI·반도체 / SMR·원자력 / 우주 / 양자 / 방산 / 데이터센터 전력 / 비만치료제·GLP-1 / 디지털인프라·비트코인)의 ETF 바스켓·대표종목·키워드. 전통 GICS 섹터맵(하위호환) 포함. `themes_for_ticker`, `mandate_profile_for_ticker` 헬퍼.
- **`src/tools/sector_scan.py`** + CLI `sectors` — 테마·섹터 ETF의 1/3/6M 수익률·SPY 대비 상대강도·50/200일선 위치를 `momentum_score`로 랭킹하는 **발굴 엔진**. 🟢자금유입/🟡중립/🔴자금이탈 판정(명시적 임계값), `top_megatrend` 제공.
- **`src/tools/momentum.py`** + CLI `momentum <T>` — 절대수익률(1/3/6/12M), 상대강도(RS vs SPY/QQQ), 52주 신고가 근접도·돌파 셋업, 거래량 급증, 200일선 상회 비율 → `momentum_score`(0~100).

### 5. 기존 도구 개선

- **`src/technical.py`** — `summary.trend_confirmed`(정배열+ADX>25+상승) 시 RSI>70·%B>1(밴드워킹)·스토캐스틱>80 과매수를 강세로 재해석. `raw_signals`/`reinterpreted` 병기(재해석 전 점수 보존).
- **`src/tools/insider_analysis.py`** — 내부자 거래를 SEC Form4 성격으로 분류(open-market 매수/매도 vs routine: 옵션행사·10b5-1·세금·grant). sentiment는 open-market만 반영(RSU 자동매도 ≠ 약세). 공매도 `squeeze_score`(short %float + days-to-cover + 공매도 증가율). dead code 제거, `except: pass` → `data_status`/`errors` 가시화.
- **`src/tools/peer_comparison.py`** — 순위 계산을 `bisect`로 교체(float == 버그 수정). INDUSTRY_PEERS 매칭 실패 시 메가트렌드 테마 reps로 피어 폴백(`peer_source`/`theme`/`ps_rank`). 적자 테마는 P/S 중심 해석 note.
- **`src/tools/earnings_calendar.py`** — 성장률 단위 휴리스틱 제거(`_growth_pct`: 항상 ×100, 0.0 정상 처리, 1200% 같은 폭발성장 단위 혼선 수정). 실적일 tz 정규화(UTC).
- **`src/tools/news_search.py`** — `news_velocity`(기사 빈도·일평균·최근 3일 추세) 추가. 티커 추출 정규식 수정(AI·SMR 같은 테마어를 티커로 오인하지 않음) + 키워드 검색 폴백. 에러 가시화.
- **`src/tools/memo_manager.py`** — MEMO_TEMPLATE 확장: 보유자 3분기(유지/확대-피라미딩/축소), 피라미딩 트리거, 비대칭 손익비(R-multiple), 트레일링 스톱(초기 손절과 분리), 서사·모멘텀·자금흐름 상태, 카탈리스트 캘린더. 같은 날 덮어쓰기 방지(`overwrite`/version suffix).

### 6. CLI (`src/tools/cli.py`)

- 신규 서브커맨드: `momentum <T>`, `sectors`.
- `risk` / `mandate-check`에 옵션 추가: `--mandate default|megatrend`, `--conviction 0.5~2.0`, `--entry-mode breakout|accumulate|full`, `--stop-loss-pct N`.

### 7. 에이전트 프롬프트 (`.claude/agents/`)

- **risk-officer** — "최소값" 교리 폐기 → 확신도 가중 + 손절 규율 + 피라미딩. 52주 신고가 자동 리스크 가점 제거(양방향 해석). 시나리오 Kelly 교차검증. "모든 시나리오 양수=편향"은 손절선 미설정 시에만 경고. 거부권이 아니라 사이징·손절 입력.
- **valuation-analyst** — 적자/고성장은 표준 DCF를 보조로, TAM·EV/Sales·룰40을 1차로. `growth_valuation` 활용. Bull 비대칭 상방(3~10배) 정량화. 역내재 단정 제거. `tools`에 WebSearch 추가. few-shot placeholder/편향 교정.
- **financial-analyst** — 사이클 분석 대칭화(피크 함정 ↔ S커브 초입 과소평가). 성장 재투자를 선행지표로 긍정 해석 옵션.
- **earnings-analyst** — 기저효과 대칭(변곡점 모멘텀 긍정 평가). 실적 이벤트를 비대칭 상방 촉매로. `tools`에 WebSearch 추가.
- **market-analyst** — 섹터 자금흐름·서사 강도를 1급 정량 분석으로(`sectors`/`momentum`). 모멘텀 카탈리스트(자금유입·리레이팅·내러티브 점화) 추가. 긍정 신호(클러스터 매수·기관 매집·숏스퀴즈) 능동 탐지. 연도 하드코딩 제거.
- **technical-analyst** — 추세장 과매수 강세 재해석. 신규 섹션 "상대강도·모멘텀·돌파매수"(`momentum`).
- **memo-writer** — 이중 추천 확장(보유자 3분기, 신규 추세추종/돌파추격), 확신도 '상'이면 양 트랙 정렬(헤징 배격). thesis 첫 문장 -90% DCF 금지. 피라미딩·R-multiple·트레일링 스톱·payoff ratio.
- **knowledge-agent** — 섹터/테마 단위 교차 검색, 서사·모멘텀 변화 비교.

### 8. 커맨드 (`.claude/commands/invest/`)

- **stock.md** — T0(메가트렌드 테마·서사·RS/자금흐름) 1급 단계 신설 → conviction 산출 → risk-officer 전달. Exec Summary에 🚀메가트렌드/모멘텀 판정축. "지금 살 이유 없으면 관망"을 추세 기반 입증책임 반전으로 교체 + Bull Advocate(10-2) 신설. 음수 Bear 강제 완화. 이중 추천에 피라미딩/돌파추격 1급 옵션. 비교모드에 RS·거래대금 추가, 순위 "테마강도×모멘텀×펀더멘털". 빠른모드 키워드 라우팅 확장.
- **market.md** — 0단계 `sectors` 스캔(능동 발굴). **섹터 미지정 시 사용자에게 방향 선택**(① 전반적 시장 상황 분석 = 모드 M / ② 핫섹터 후보 제시 → 선택 = 모드 S). 모드 M 신설(매크로·자금흐름 폭·섹터 로테이션 맵·시장 국면·관전 리스트). 종목 스캔에 RS·모멘텀·서사 칼럼, 톱픽 가중(펀40/모35/촉25), 진입 3분류+피라미딩. earnings-analyst 필수 격상(추정치 리비전 모멘텀). 자금흐름 판정 임계값 룰 명시.

### 9. 지침 (`CLAUDE.md`)

- 투자 철학 한 줄 추가(손절 규율 기반 과감한 메가트렌드 베팅). CLI 사용법에 `momentum`/`sectors` + risk/mandate-check 옵션. mandate 2종·자동선택. 메모 규격(보유자 3분기·피라미딩·R-multiple·트레일링 스톱).

---

### 검증 (라이브 실행)

- 전체 Python `py_compile` + 교차 임포트 통과. 마크다운 frontmatter 유효(WebSearch 추가 확인), 파일 잘림 없음.
- `mandate-check PLTR` → 자동 megatrend, PER 149.7가 위반 아님(참고치), compliant.
- `risk PLTR --conviction 1.8 --entry-mode breakout` → 권고 22.5%(과거 한 자릿수), 스트레스 가격 전부 양수, VaR 초과는 경고만.
- `valuation RKLB`(적자) → 표준 DCF null 대신 `growth_valuation`(정규화 $14.7·P/S 96).
- `momentum NVDA`, `insider AAPL`(Form4 분류·squeeze_score 18.3), `peers OKLO`(원자력 테마 폴백), `sectors`(AI/양자/비트코인인프라 🟢자금유입 랭킹) 정상.
- `calc_scenario_kelly` 단위 검증(비대칭 불 +88% → Half-Kelly 50.6%, 음수 EV → avoid).

### 알아둘 점 / 향후 과제

- 변경은 **작업트리에만** 존재(커밋 안 함).
- **테마 키워드 뉴스 검색은 여전히 약함**: yfinance에 키워드 뉴스 API가 없어 순수 테마 검색("AI datacenter")은 0건. 종목별 news velocity는 작동. 진짜 서사 강도 측정엔 Finnhub/FMP 등 실제 뉴스 API 연동 필요.
- `sectors`/`momentum`은 ETF 다수 조회로 수 초 소요.
- yfinance 1.2.0은 공식 PyPI 정품으로 확인됨(재설치 불필요).
