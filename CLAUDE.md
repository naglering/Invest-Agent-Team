# Investment Agent Team — 프로젝트 지침

## 프로젝트 개요

멀티 에이전트 투자 분석 시스템. Claude Code Agent Teams 기반으로 8+1명의 전문 에이전트가 협업하여 종합 투자 판단을 수행한다.

### 투자 철학

보수적 분산 일변도가 아니라, 자금이 몰리는 **메가트렌드·강한 서사 종목**에 대해서는 **손절 규율 기반의 과감한 집중·모멘텀 베팅**을 허용한다. (단, 모든 분석은 참고 자료이며 투자 권유가 아니다 — '주의사항' 면책 유지.)

## 통합 CLI 사용법

모든 분석 도구는 통합 CLI를 통해 실행한다:

```bash
# 기본 분석
python3 src/tools/cli.py fundamental <TICKER>    # 재무 분석
python3 src/tools/cli.py technical <TICKER>      # 기술적 분석
python3 src/tools/cli.py news <TICKER>           # 뉴스 수집
python3 src/tools/cli.py earnings <TICKER>       # 실적발표 일정 + 컨센서스
python3 src/tools/cli.py risk <TICKER>           # 리스크 분석 + 포지션 사이징
#   옵션: --mandate default|megatrend   # mandate 프로파일 선택 (미지정 시 티커→테마 자동선택)
#         --conviction 0.5~2.0          # 확신도 배수 (포지션 사이징에 반영)
#         --entry-mode breakout|accumulate|full  # 진입 방식 (돌파/분할매수/일괄)
#         --stop-loss-pct N             # 손절 라인(%) 지정 → R-multiple/포지션 산출
python3 src/tools/cli.py mandate-check <TICKER>  # mandate 준수 확인
#   옵션: --mandate default|megatrend   # 검증할 mandate 프로파일 (미지정 시 자동선택)
python3 src/tools/cli.py valuation <TICKER>      # DCF/상대가치 분석
python3 src/tools/cli.py peers <TICKER>                    # 동종업계 비교 (자동 피어)
python3 src/tools/cli.py peers <TICKER> --peers T1,T2,T3   # 동종업계 비교 (커스텀 피어)
python3 src/tools/cli.py insider <TICKER>         # 내부자 거래/기관보유
python3 src/tools/cli.py momentum <TICKER>        # 모멘텀 분석 (상대강도 RS, 52주 신고가 돌파, 거래량 급증, momentum_score)
python3 src/tools/cli.py sectors                  # 테마·섹터 자금흐름 랭킹 (발굴 엔진)
python3 src/tools/cli.py themes <TICKER>          # 티커가 속한 메가트렌드 테마 + 적용 mandate
python3 src/tools/cli.py themes list              # 테마별 멤버십 (ETF holdings ∪ reps − exclude)
python3 src/tools/cli.py themes refresh           # ETF holdings 캐시 강제 갱신 (TTL 7일)

# 웹 검색
python3 src/tools/cli.py news-search "<QUERY>"   # 뉴스 키워드 검색 (yfinance)

# 메모 관리 (data/histories/YYYY-MM-DD_TICKER/ 디렉토리: summary.md + report.md 쌍)
python3 src/tools/cli.py memo list               # 메모 목록
python3 src/tools/cli.py memo read <TICKER> [summary|report|both]  # 메모 조회 (기본 summary)
python3 src/tools/cli.py memo search "<QUERY>"   # 메모 검색 (요약+종합보고서 전체)
python3 src/tools/cli.py memo write <TICKER>     # 요약 작성 (stdin JSON → summary.md)
python3 src/tools/cli.py memo report <TICKER>    # 종합보고서 저장 (stdin 마크다운 → report.md)
python3 src/tools/cli.py memo migrate [--apply]  # 레거시 flat 파일 → 디렉토리 구조 이전

# 포트폴리오 관리 (data/portfolio.md 보유 종목 평가)
python3 src/tools/cli.py portfolio                # 현재가·환율 조회 → 평가/손익/비중 테이블
python3 src/tools/cli.py portfolio --json         # JSON 출력
python3 src/tools/cli.py portfolio --fx 1380      # 원/달러 환율 수동 지정
python3 src/tools/cli.py portfolio quote <TICKER> # 매수 입력용 간단 종목정보 (이름·현재가·통화·섹터·52주·시총)
python3 src/tools/cli.py portfolio add <TICKER> --qty N --price P [--ccy USD|KRW] [--fx 1490]  # 매수(추가/평단 갱신)
python3 src/tools/cli.py portfolio remove <TICKER># 매도(보유 종목 제거)
#   → 포트폴리오 구성·매수·매도는 슬래시 커맨드 /invest:portfolio 로도 가능

# 초기 세팅 (개인 데이터는 .gitignore — 클론 직후 1회 생성 후 직접 편집)
python3 src/tools/cli.py setup                    # data/mandates/{default,megatrend}.json 정본 생성
python3 src/tools/cli.py portfolio init           # portfolio.md / theses.md / positions.md 템플릿 생성
#   옵션: --force    # 기존 파일 덮어쓰기 (기본은 존재 시 건너뜀)

# 빠른 통합 분석 (기존 코드)
python3 src/main.py <TICKER>
```

## 티커 형식

- 미국 주식: `AAPL`, `MSFT`, `GOOGL`
- 한국 주식: `005930.KS` (삼성전자)

## 데이터 디렉토리 규약

> **GitHub엔 골격(skeleton)만.** 개인 투자 데이터(보유 종목·Thesis·포지션·실제 투자 메모)는
> `.gitignore` 처리되어 추적되지 않는다. 레포에는 구조 + `data/mandates` + `data/histories/EXAMPLE.md`만 포함.
> 클론 직후 `cli.py setup` + `cli.py portfolio init`으로 개인 데이터 파일을 생성한 뒤 직접 편집한다.

- `data/histories/` — 투자 메모 저장소. **디렉토리 단위**: `YYYY-MM-DD_TICKER/`에 `summary.md`(요약) + `report.md`(위원회 종합보고서) 쌍. (실제 메모는 ignore, `EXAMPLE/`만 추적. 레거시 flat `.md`는 `memo migrate`로 이전)
- `data/portfolio.md` · `data/theses.md` · `data/positions.md` — 개인 데이터 (ignore, `portfolio init`로 생성)
- `data/mandates/` — 투자 mandate 설정 파일 (추적)
  - `data/mandates/default.json` — **보수 프로파일** (PER ≤ 50 게이트, 최대 비중 10%, moderate)
  - `data/mandates/megatrend.json` — **공격 프로파일** (PER 게이트 비활성, 최대 비중 25%, aggressive, D/E 5.0)

### mandate 프로파일 (2종)

- **default (보수)**: 밸류에이션 게이트(PER ≤ 50)와 보수적 포지션 한도(최대 10%, moderate)를 적용한다.
- **megatrend (공격)**: 메가트렌드 테마 종목에 한해 PER 게이트를 비활성화하고, 더 큰 집중(최대 25%, aggressive, D/E 5.0)을 허용한다.
- **티커 → 테마 자동선택**: 다음 메가트렌드 테마에 속한 티커는 자동으로 `megatrend` 프로파일을 사용한다 — AI·반도체 / SMR·원자력 / 우주 / 양자 / 방산 / DC(데이터센터) 전력 / 비만치료제 / 디지털 인프라. (그 외 종목은 `default`.)
- **테마 멤버십은 동적**: `theme_members = (ETF 실제 top holdings ∪ reps) − exclude`. ETF 큐레이터가 정한 현재 구성을 yfinance로 라이브 반영(디스크 캐시 TTL 7일, 오프라인/실패 시 `reps` 폴백)하여 수기 명단이 낡아 신규 수혜주를 놓치는 문제를 막는다. `reps`=수동 시드(ETF top10 밖 핵심주), `exclude`=holdings로 딸려오나 megatrend 성격이 아닌 종목 차단(예: 방산 성숙 prime). 환경변수 `INVEST_ETF_LIVE=0`이면 정적 `reps`만 사용.
  - ⚠️ 멤버십(리스크 컨테이너=mandate)은 ETF 편입이라는 **슬로우·구조적** 신호로만 판정한다. 뉴스/모멘텀 같은 변동 신호로 mandate를 흔들면 하이프가 집중 한도를 자동 해제하는 반사성 위험 → 그쪽은 확신도·진입 타이밍(`momentum`/`sectors`)에서만 다룬다.
- CLI의 `--mandate` 옵션으로 자동선택을 수동 오버라이드할 수 있다 (`risk`, `mandate-check`).

## 메모 포맷 규격

> 메모는 `data/histories/YYYY-MM-DD_TICKER/` 디렉토리에 **요약(`summary.md`) + 종합보고서(`report.md`)** 쌍으로 저장된다. 아래 규격은 **요약(summary)** 기준이며, `report.md`는 위원회 최종 종합보고서 전문이다.

투자 메모(요약)는 다음 섹션을 포함해야 한다:

1. **헤더**: 티커, 회사명, 작성일, 분석가
2. **투자 논거 (Thesis)**: 핵심 투자 이유
3. **재무 요약**: 주요 재무 지표
4. **밸류에이션 분석 요약**: DCF, 상대가치, 역내재 분석
5. **기술적 분석 요약**: 주요 기술적 시그널 + **서사/모멘텀 상태** (스토리 강도, 상대강도 RS, 자금흐름)
6. **리스크 요인**: 식별된 위험 요소
7. **투자 결정**: 이중 추천 + 확신도
   - 보유자: **비중 유지 / 비중 확대(피라미딩 트리거 명시) / 비중 축소** (3분기)
   - 신규: 매수 / 관망 / 회피 + **추세 추종 진입 / 돌파 시 추격매수** 옵션
   - **진입가 2-Case 필수**: 신규 진입은 **(A) 현재가 즉시 진입**과 **(B) 눌림목 대기 진입** 두 Case로 각각 진입 비중을 권고한다. 추세 유효 시 Case A(현재가 선진입)가 디폴트이며, 눌림목에만 앵커링하지 않는다.
8. **포지션 사이징**: 권고 비중, 최대 비중, 진입 비중
   - **진입가 2-Case**: 현재가 진입 비중 + 눌림목 진입 비중을 분리 제시 (Case A는 추세추종 디폴트, Case B는 평단 개선·미진입 리스크 병기)
   - **피라미딩 규칙**: 추가 매수 트리거 조건(예: 신고가 돌파·수익 확보 후 단계적 증설)과 단계별 비중
   - **비대칭 손익비 (R-multiple)**: 손절폭 대비 목표 수익폭 비율 (예: 3R)
   - **트레일링 스톱**: 추세 추종을 위한 동적 손절 라인(% 또는 이동평균 기준)
9. **시나리오 분석**: Bull/Base/Bear 시나리오별 목표가와 확률
10. **후속 조치**: 모니터링 항목 + **카탈리스트 캘린더** (실적·이벤트 등 일정 슬롯)

## 에이전트 간 소통 규칙

1. 모든 도구 출력은 **JSON 형식**이다.
2. 에이전트는 도구 실행 결과를 그대로 전달하지 말고, **핵심 내용을 요약**하여 보고한다.
3. 의사결정 시 **근거(evidence)를 명시**한다.
4. 불확실한 정보는 반드시 **불확실성을 표기**한다.

## 주의사항

- 모든 분석은 **참고 자료**이며 투자 권유가 아님
- 큰 숫자는 읽기 쉽게 표현 (예: 3조 2,000억원, $3.2T)
- 데이터가 없는 항목은 "N/A"로 표시
