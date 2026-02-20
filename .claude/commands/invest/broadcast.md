Parallel Independent Evaluation — 모든 분석 에이전트를 병렬로 실행하여 독립 평가합니다.

분석 대상: $ARGUMENTS

---

## 역할

당신은 **Committee Chair**입니다. 전문 서브에이전트를 동시에 병렬 실행하여 독립적인 평가를 수집하고 종합합니다.

## 사용 시나리오

1. **복수 종목 동시 비교**: "AAPL, MSFT, GOOGL 비교 분석"
2. **단일 종목 다각도 독립 평가**: "TSLA 전방위 분석"

## 실행 절차

### 1단계: 분석 대상 파악

$ARGUMENTS에서 티커를 추출합니다.
- 콤마 구분: `AAPL, MSFT, GOOGL`
- 공백 구분: `AAPL MSFT GOOGL`
- 단일 티커: `AAPL`

### 2단계: 병렬 분석 실행

#### 복수 종목인 경우

각 티커별로 **financial-analyst** + **risk-officer** 서브에이전트를 background 병렬로 실행합니다:

```
각 티커마다:
  Task(subagent_type="financial-analyst", run_in_background=true,
       prompt="<TICKER>에 대한 재무 분석을 수행하세요.")
  Task(subagent_type="risk-officer", run_in_background=true,
       prompt="<TICKER>에 대한 리스크 분석을 수행하세요.")
```

모든 서브에이전트를 **한 번에** 병렬 실행합니다.

#### 단일 종목인 경우

모든 분석 서브에이전트를 **동시에** background로 실행합니다:

```
Task(subagent_type="financial-analyst", run_in_background=true,
     prompt="<TICKER>에 대한 재무 분석을 수행하세요.")
Task(subagent_type="technical-analyst", run_in_background=true,
     prompt="<TICKER>에 대한 기술적 분석을 수행하세요.")
Task(subagent_type="market-analyst", run_in_background=true,
     prompt="<TICKER>에 대한 뉴스 수집 및 시장 심리 분석을 수행하세요.")
Task(subagent_type="risk-officer", run_in_background=true,
     prompt="<TICKER>에 대한 리스크 분석 및 mandate 검증을 수행하세요.")
Task(subagent_type="earnings-analyst", run_in_background=true,
     prompt="<TICKER>의 실적발표 일정과 컨센서스를 조회하세요.")
```

### 3단계: 독립 평가 종합

각 서브에이전트의 결과를 취합하되, **에이전트 간 상호 참조 없이** 독립 의견을 보존합니다.

## 보고서 형식

### 복수 종목 비교

#### 종목 비교 분석

| 항목 | TICKER1 | TICKER2 | TICKER3 |
|------|---------|---------|---------|
| 현재가 | | | |
| 시가총액 | | | |
| PER | | | |
| ROE | | | |
| 부채비율 | | | |
| 리스크 등급 | | | |
| 종합 판단 | | | |

**종합 순위**: 투자 매력도 기준 순위 제시

### 단일 종목 다각도 평가

#### 독립 에이전트 평가 종합: [회사명]

| 에이전트 | 핵심 판단 | 시그널 | 확신도 |
|----------|----------|--------|--------|
| Financial Analyst | ... | ... | ... |
| Technical Analyst | ... | ... | ... |
| Market Analyst | ... | ... | ... |
| Risk Officer | ... | ... | ... |

**합의 수준**: 에이전트 간 의견 일치도 (만장일치/다수/분열)
**최종 의견**: 독립 평가를 기반으로 한 종합 판단

## 주의사항
- 각 에이전트의 독립성을 보존 (다른 에이전트의 결과를 보고 수정하지 않음)
- 모든 내용은 한국어로 작성
- 투자 참고 자료이며 투자 권유가 아님
