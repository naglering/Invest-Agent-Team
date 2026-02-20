# Investment Agent Team — 프로젝트 지침

## 프로젝트 개요

멀티 에이전트 투자 분석 시스템. Claude Code Agent Teams 기반으로 7+1명의 전문 에이전트가 협업하여 종합 투자 판단을 수행한다.

## 통합 CLI 사용법

모든 분석 도구는 통합 CLI를 통해 실행한다:

```bash
# 기본 분석
python3 src/tools/cli.py fundamental <TICKER>    # 재무 분석
python3 src/tools/cli.py technical <TICKER>      # 기술적 분석
python3 src/tools/cli.py news <TICKER>           # 뉴스 수집
python3 src/tools/cli.py earnings <TICKER>       # 실적발표 일정 + 컨센서스
python3 src/tools/cli.py risk <TICKER>           # 리스크 분석
python3 src/tools/cli.py mandate-check <TICKER>  # mandate 준수 확인

# 웹 검색
python3 src/tools/cli.py news-search "<QUERY>"   # 뉴스 키워드 검색 (yfinance)

# 메모 관리
python3 src/tools/cli.py memo list               # 메모 목록
python3 src/tools/cli.py memo read <TICKER>      # 메모 조회
python3 src/tools/cli.py memo search "<QUERY>"   # 메모 검색
python3 src/tools/cli.py memo write <TICKER>     # 메모 작성 (stdin으로 JSON 입력)

# 빠른 통합 분석 (기존 코드)
python3 src/main.py <TICKER>
```

## 티커 형식

- 미국 주식: `AAPL`, `MSFT`, `GOOGL`
- 한국 주식: `005930.KS` (삼성전자)

## 데이터 디렉토리 규약

- `data/memos/` — 투자 메모 저장소. 파일명: `YYYY-MM-DD_TICKER.md`
- `data/knowledge/` — 지식 베이스 (리서치 자료, 과거 분석)
- `data/mandates/` — 투자 mandate 설정 파일

## 메모 포맷 규격

투자 메모는 다음 섹션을 포함해야 한다:

1. **헤더**: 티커, 회사명, 작성일, 분석가
2. **투자 논거 (Thesis)**: 핵심 투자 이유
3. **재무 요약**: 주요 재무 지표
4. **기술적 분석 요약**: 주요 기술적 시그널
5. **리스크 요인**: 식별된 위험 요소
6. **투자 결정**: 매수/매도/관망 + 확신도
7. **후속 조치**: 모니터링 항목

## 에이전트 간 소통 규칙

1. 모든 도구 출력은 **JSON 형식**이다.
2. 에이전트는 도구 실행 결과를 그대로 전달하지 말고, **핵심 내용을 요약**하여 보고한다.
3. 의사결정 시 **근거(evidence)를 명시**한다.
4. 불확실한 정보는 반드시 **불확실성을 표기**한다.

## 주의사항

- 모든 분석은 **참고 자료**이며 투자 권유가 아님
- 큰 숫자는 읽기 쉽게 표현 (예: 3조 2,000억원, $3.2T)
- 데이터가 없는 항목은 "N/A"로 표시
