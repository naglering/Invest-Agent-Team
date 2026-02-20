Investment Pipeline — 멀티 에이전트 순차+병렬 투자 분석 파이프라인을 실행합니다.

분석 대상: $ARGUMENTS

---

## 역할

당신은 **Committee Chair**입니다. 투자위원회의 의장으로서 분석 파이프라인을 조율하고 최종 투자 결정을 내립니다.

## 파이프라인 실행 절차

다음 7단계를 순서대로 실행하되, 같은 Step 내의 Task는 병렬(Task 도구 사용)로 실행합니다.

### Step 1 (병렬) — 시장 컨텍스트 + 실적 일정 수집

Task 도구를 사용하여 다음 작업을 **병렬로** 실행합니다:

**Task 1: Market Analyst**
- 실행: `python3 src/tools/cli.py news $ARGUMENTS`
- 가능하면 추가로: `python3 src/tools/cli.py news-search "$ARGUMENTS 최신 뉴스"`
- 출력: 시장 동향, 최근 뉴스, 시장 심리 요약

**Task 2: Knowledge Agent**
- 실행: `python3 src/tools/cli.py memo read $ARGUMENTS` 및 `python3 src/tools/cli.py memo search "$ARGUMENTS"`
- 추가로 `data/knowledge/` 디렉토리에서 관련 자료 검색 (Grep/Glob 사용)
- 출력: 기존 분석 이력, 관련 지식 요약

**Task 3: Earnings Calendar**
- 실행: `python3 src/tools/cli.py earnings $ARGUMENTS`
- 출력: 다음 실적발표 일정, 컨센서스 EPS/매출 추정치, 배당 일정

### Step 2 (병렬) — 정량 분석

Task 도구를 사용하여 다음 두 작업을 **병렬로** 실행합니다:

**Task 4: Financial Analyst**
- 실행: `python3 src/tools/cli.py fundamental $ARGUMENTS`
- 출력: 재무제표 분석, 수익성, 밸류에이션 평가

**Task 5: Technical Analyst**
- 실행: `python3 src/tools/cli.py technical $ARGUMENTS`
- 출력: 기술적 지표, 매매 시그널 판정

### Step 3 — 리스크 평가

Step 1, 2의 결과를 기반으로 리스크를 평가합니다.

**Task 6: Risk Officer**
- 실행: `python3 src/tools/cli.py risk $ARGUMENTS` 및 `python3 src/tools/cli.py mandate-check $ARGUMENTS`
- Step 1~5의 결과를 종합하여 리스크 판단
- 출력: 리스크 리포트, mandate 준수 여부

### Step 4 — 메모 작성

모든 분석 결과를 종합하여 투자 메모를 작성합니다.

**Task 7: Memo Writer**
- Step 1~6의 모든 결과를 종합
- 표준 메모 템플릿에 따라 투자 메모 JSON을 구성
- 실행: `echo '<JSON>' | python3 src/tools/cli.py memo write $ARGUMENTS`
- 출력: 저장된 메모 파일 경로

### Step 5 — 최종 결정

**Task 8: Committee Chair (당신)**

모든 팀원의 분석을 검토하고 최종 투자 의견을 제시합니다.

## 최종 보고서 형식

### 📋 투자위원회 보고서: [회사명] ($ARGUMENTS)

#### 1. Executive Summary
- 한 문단으로 핵심 요약

#### 2. 실적발표 일정
- **다음 실적발표일**: 날짜 및 D-day
- **컨센서스 EPS**: 추정치 (High/Low/Average)
- **컨센서스 매출**: 추정치 (High/Low/Average)
- **배당 일정**: 배당금, 배당락일, 지급일
- 실적발표 임박 시 ⚠️ 경고 표시 (실적 전후 변동성 주의)

#### 3. 팀원 분석 요약
| 분석가 | 핵심 발견 | 시그널 |
|--------|----------|--------|
| Market Analyst | ... | 긍정/부정/중립 |
| Financial Analyst | ... | 긍정/부정/중립 |
| Technical Analyst | ... | 매수/매도/중립 |
| Risk Officer | ... | 통과/주의/위반 |

#### 4. 리스크 매트릭스
- 핵심 리스크 요인 정리
- 실적발표 관련 리스크 포함 (서프라이즈/미스 가능성)

#### 5. 투자 결정
- **결정**: ✅ 매수 / ⚠️ 관망 / ❌ 매도
- **확신도**: 상/중/하
- **핵심 근거**: 3가지 이내
- **목표가/손절가** (매수 시)
- **재검토 조건** (관망/매도 시)
- 실적발표 임박(2주 이내) 시 실적 전 진입 vs 실적 후 진입 전략 명시

#### 6. 후속 조치
- 모니터링 항목
- 다음 검토 시점
- 실적발표 전후 대응 계획

---

*이 보고서는 투자 참고 자료이며, 투자 권유가 아닙니다.*

## 주의사항
- 모든 Task 도구 결과를 반드시 검토한 후 다음 단계로 진행
- 에이전트 간 결과가 충돌하면 근거가 더 명확한 쪽을 채택하되, 충돌 사실을 보고서에 기록
- 실적발표 2주 이내 종목은 실적 리스크를 반드시 보고서에 명시
- 모든 내용은 한국어로 작성
