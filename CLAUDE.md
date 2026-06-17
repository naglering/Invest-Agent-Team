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

# 웹 검색
python3 src/tools/cli.py news-search "<QUERY>"   # 뉴스 키워드 검색 (yfinance)

# 메모 관리
python3 src/tools/cli.py memo list               # 메모 목록
python3 src/tools/cli.py memo read <TICKER>      # 메모 조회
python3 src/tools/cli.py memo search "<QUERY>"   # 메모 검색
python3 src/tools/cli.py memo write <TICKER>     # 메모 작성 (stdin으로 JSON 입력)

# 포트폴리오 관리 (data/portfolio.md 보유 종목 평가)
python3 src/tools/cli.py portfolio                # 현재가·환율 조회 → 평가/손익/비중 테이블
python3 src/tools/cli.py portfolio --json         # JSON 출력
python3 src/tools/cli.py portfolio --fx 1380      # 원/달러 환율 수동 지정

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

- `data/histories/` — 투자 메모 저장소. 파일명: `YYYY-MM-DD_TICKER.md` (실제 메모는 ignore, `EXAMPLE.md`만 추적)
- `data/portfolio.md` · `data/theses.md` · `data/positions.md` — 개인 데이터 (ignore, `portfolio init`로 생성)
- `data/mandates/` — 투자 mandate 설정 파일 (추적)
  - `data/mandates/default.json` — **보수 프로파일** (PER ≤ 50 게이트, 최대 비중 10%, moderate)
  - `data/mandates/megatrend.json` — **공격 프로파일** (PER 게이트 비활성, 최대 비중 25%, aggressive, D/E 5.0)

### mandate 프로파일 (2종)

- **default (보수)**: 밸류에이션 게이트(PER ≤ 50)와 보수적 포지션 한도(최대 10%, moderate)를 적용한다.
- **megatrend (공격)**: 메가트렌드 테마 종목에 한해 PER 게이트를 비활성화하고, 더 큰 집중(최대 25%, aggressive, D/E 5.0)을 허용한다.
- **티커 → 테마 자동선택**: 다음 메가트렌드 테마에 속한 티커는 자동으로 `megatrend` 프로파일을 사용한다 — AI·반도체 / SMR·원자력 / 우주 / 양자 / 방산 / DC(데이터센터) 전력 / 비만치료제 / 디지털 인프라. (그 외 종목은 `default`.)
- CLI의 `--mandate` 옵션으로 자동선택을 수동 오버라이드할 수 있다 (`risk`, `mandate-check`).

## 메모 포맷 규격

투자 메모는 다음 섹션을 포함해야 한다:

1. **헤더**: 티커, 회사명, 작성일, 분석가
2. **투자 논거 (Thesis)**: 핵심 투자 이유
3. **재무 요약**: 주요 재무 지표
4. **밸류에이션 분석 요약**: DCF, 상대가치, 역내재 분석
5. **기술적 분석 요약**: 주요 기술적 시그널 + **서사/모멘텀 상태** (스토리 강도, 상대강도 RS, 자금흐름)
6. **리스크 요인**: 식별된 위험 요소
7. **투자 결정**: 이중 추천 + 확신도
   - 보유자: **비중 유지 / 비중 확대(피라미딩 트리거 명시) / 비중 축소** (3분기)
   - 신규: 매수 / 관망 / 회피 + **추세 추종 진입 / 돌파 시 추격매수** 옵션
8. **포지션 사이징**: 권고 비중, 최대 비중, 진입 비중
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
