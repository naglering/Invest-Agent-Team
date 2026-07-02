# 개선 작업 재개 계획 (feat/improve-suite)

> **목적**: 새 세션에서 이 문서만 읽고 남은 작업(Integrate → Verify → Fix)을 이어서 완료.
> **근거 감사 보고서**: `docs/audit-2026-07-02.md` (38건), 원시 발견 `docs/audit-2026-07-02-findings.json`.
> **작성**: 2026-07-02, 브랜치 `feat/improve-suite`, 커밋 `bfadce2` 기준.

---

## 1. 현재 상태

3단계 워크플로(Implement → Integrate → Verify → Fix) 중 **Implement만 완료·커밋됨.** 나머지 미실행.

### 완료 (커밋 `bfadce2` — 31 파일, +5327/−409)
- **파이썬 구현 50항목 전부 done** (11 클러스터, partial/skipped 0).
- 수정 모듈 20개 + 신규 4개: `backtest.py`, `watch_alerts.py`, `track_performance.py`, `revisions.py`.
- mandates JSON 3종에 `risk_budget_pct` 추가, `.gitignore` 갱신, 감사 보고서 `docs/`.
- `python3 -m compileall -q src` 통과.

### ⚠️ 미완료 (남은 작업)
1. **Integrate-CLI**: `src/tools/cli.py` 배선 — 신규 커맨드(`portfolio sell/check`, `watch`, `track`, `revisions`, `backtest`) + 신규 옵션(`risk --scenarios/--regime`, `portfolio add --stop/--target/--replace`). **현재 cli.py 무변경 → 신규 기능 상당수 CLI로 도달 불가**(모듈 직접 실행만 가능).
2. **Integrate-Docs**: 스킬 md·에이전트 md·CLAUDE.md·README 반영 (문서 항목 15건 + 신규 CLI 문서화).
3. **Verify**: 전 CLI 스모크 매트릭스 + 클러스터별 diff 정밀 리뷰.
4. **Fix**: 검증 이슈 수정 + 재스모크.

---

## 2. 재개 방법

> **금지**: 기존 fix-all 워크플로(`invest-suite-fix-all`)를 처음부터 재실행하지 말 것. Implement 클러스터가 **이미 커밋된 파일 위에 재적용**되어 중복 편집·충돌 위험. (워크플로 resume 캐시는 같은 세션 전용이라 새 세션에선 무효.)

**권장 절차 — Integrate부터 새 워크플로 또는 수동으로:**

- 실데이터 `data/portfolio.md`·`data/theses.md` 등 수정 금지, git commit은 사용자 지시 시에만.
- 통합은 **현재 디스크의 실제 함수 시그니처를 Read로 확인**하고 배선(아래 spec은 구현 시점 반환값 — 실제와 다르면 실제 우선).
- 아래 §3(cli.py)·§4(docs)를 그대로 적용 → §5 스모크 → 실패 시 소유 파일 수정.

새 워크플로로 돌린다면 3-phase(Integrate 2병렬 → Verify 스모크+리뷰 → Fix)만; Implement 단계는 빼고 이 문서의 spec을 프롬프트에 인용.

---

## 3. Integrate-CLI — `src/tools/cli.py` 배선 명세 (구현자 반환 verbatim)

배선 후 사용법 docstring(상단)·usage 헤더도 함께 갱신. 기존 수동 디스패치 스타일(`_parse_opt` 헬퍼, `elif command ==` 체인) 준수.

### 3.1 `risk --scenarios / --regime` (analyze_risk 함수측 이미 지원 — CLI만)
```python
def cmd_risk(ticker, mandate=None, conviction=None, entry_mode="accumulate",
             stop_loss_pct=None, scenarios=None, regime=None):
    from tools.risk_analyzer import analyze_risk
    return analyze_risk(ticker, mandate_profile=mandate, conviction=conviction,
                        entry_mode=entry_mode, stop_loss_pct=stop_loss_pct,
                        scenarios=scenarios, regime=regime)
```
- risk 디스패치(현 cli.py:315-326)에 `scenarios=_parse_opt(args,"--scenarios")`, `regime=_parse_opt(args,"--regime")` 두 인자 추가.
- **scenarios는 JSON 문자열 그대로 전달** — analyze_risk가 자체 `json.loads`. 파싱 실패·형식 오류·regime 오타는 analyze_risk가 ValueError → 기존 에러 JSON 경로.
- 사용법: `risk <TICKER> [--mandate default|megatrend|crypto] [--conviction 0.5~2.0] [--entry-mode breakout|accumulate|full] [--stop-loss-pct N] [--scenarios '<JSON>'] [--regime risk_on|neutral|risk_off]`
- 호출 예: `risk NVDA --conviction 1.5 --stop-loss-pct 20 --regime risk_off --scenarios '[{"prob":0.5,"return_pct":100},{"prob":0.3,"return_pct":10},{"prob":0.2,"return_pct":-40}]'`
- 출력 신규: `annualization_basis`(루트), `position_sizing.{regime, regime_multiplier, implied_capital_risk_pct, risk_budget_pct, mandate_fallback, kelly.basis="scenario"}`. --regime 미지정 시 `regime:"unspecified"`·승수 1.0.

### 3.2 `portfolio add`(옵션 4개) / `sell` / `check`
```python
# add — 기존 add_holding 호출 교체:
return add_holding(args[1], float(qty), float(price),
    currency=_parse_opt(args,"--ccy"), buy_fx=_parse_opt(args,"--fx"),
    stop=_parse_opt(args,"--stop"),      # 숫자 또는 규칙문자열('MA20','직전고점-15%')
    target=_parse_opt(args,"--target"),
    entry_date=_parse_opt(args,"--date"),# YYYY-MM-DD, 미지정=오늘
    replace="--replace" in args)         # 전량 교체(정정), trades.jsonl 미기록
# sell:
if sub=="sell":
    from tools.portfolio import sell_holding
    if len(args)<2: return {"error":"사용법: portfolio sell <TICKER> [--qty N(생략=전량)] --price P [--fx 1490] [--note ...]"}
    return sell_holding(args[1], qty=_parse_opt(args,"--qty"), price=_parse_opt(args,"--price"),
                        fx=_parse_opt(args,"--fx"), note=_parse_opt(args,"--note"))
# check:
if sub=="check":
    from tools.portfolio import check_portfolio
    return check_portfolio(path=_parse_opt(args,"--file"))
```
- 시그니처: `sell_holding(ticker, qty=None, price=None, fx=None, note=None, path=None, trades_path=None)` — price 누락/초과매도는 `{"error":...}`, 미보유는 `{"action":"not_found"}`. `check_portfolio(path=None)`.
- add 출력 `action ∈ added|pyramided|replaced`(피라미딩=수량합산+금액가중 평단·환율). sell 출력 `action ∈ sold_partial|sold_all` + `realized_pnl/realized_pnl_pct/r_multiple/trade_logged`. check `stop_status ∈ 위반|근접|정상|미설정|판정불가`, `target_status ∈ 도달|근접|미도달|미설정|판정불가`.
- 사용법: `portfolio add <T> --qty N --price P [--ccy USD|KRW] [--fx 1380] [--stop 96|MA20] [--target 180] [--date YYYY-MM-DD] [--replace]`. remove 설명에 "(원장 미기록 — 매도 기록은 sell 권장)".

### 3.3 `watch`
```python
def cmd_watch(args):
    from tools.watch_alerts import run_watch
    return run_watch(portfolio_path=_parse_opt(args,"--portfolio"),
                     watchlist_path=_parse_opt(args,"--watchlist"),
                     append="--no-append" not in args)
# 디스패치:  elif command=="watch": result = cmd_watch(args)
```
- 시그니처: `run_watch(portfolio_path=None, watchlist_path=None, alerts_dir=None, histories_dir=None, append=True, period="1y")`. 경로 None이면 `data/` 기본값.
- 사용법: `watch [--no-append] [--portfolio <PATH>] [--watchlist <PATH>]` — 손절 위반🔴/근접🟡·목표🟢·돌파 점화🟢·메모 triggers D-day → `data/alerts/YYYY-MM-DD.md` append.
- alert kind: `stop_violation`🔴 / `stop_near`·`breakout_watch`🟡 / `target_hit`·`breakout_ignition`·`earnings_dday`·`event_dday`🟢. 판정은 완성 일봉 종가 기준(장중 미완성 봉 제외).

### 3.4 `track` / `revisions`
```python
def cmd_track(ticker=None):
    from tools.track_performance import track
    return track(ticker=ticker)
def cmd_revisions(theme):
    from tools.revisions import rank_revisions
    return rank_revisions(theme)
# 디스패치:
#   elif command=="track": result = cmd_track(ticker=_parse_opt(args,"--ticker"))
#   elif command=="revisions":
#       if not args: raise ValueError("사용법: revisions <테마명> (예: AI, 우주, 방산 — 부분 일치 허용)")
#       result = cmd_revisions(args[0])
```
- `track(ticker=None)` — None이면 전체 히스토리(~30티커, 수십 초). `rank_revisions(theme)` — 테마 미해석 시 `{"error","available_themes"}`(예외 없음).
- 사용법: `track [--ticker T]`(메모 예측 vs 실현 채점 — 권고별 승률·평균 R·시나리오 확률 캘리브레이션·conviction 구간 성과 + trades.jsonl), `revisions <테마명>`(EPS 리비전 7d/30d 랭킹).

### 3.5 `backtest`
```python
def cmd_backtest(universe, period="3y"):
    from tools.backtest import backtest_momentum
    return backtest_momentum(universe, period=period)
# 디스패치:
#   elif command=="backtest":
#       uni = _parse_opt(args,"--universe") or (args[0] if args and not args[0].startswith("--") else None)
#       if not uni: raise ValueError("사용법: backtest --universe <테마명|T1,T2,T3> [--period 3y]")
#       result = cmd_backtest(uni, period=_parse_opt(args,"--period") or "3y")
```
- ⚠️ universe에 `.upper()` 적용 금지 — 테마 키가 한국어 정확일치, 티커 대문자화는 `backtest._resolve_universe`가 자체 수행.
- `backtest_momentum(universe, period="3y")` — period는 `3y·18mo·90d` 형식만. 출력: `score_quartiles`(사분위 1M/3M 수익률·단조성), `ic_spearman`(pooled/크로스섹션), `breakout.{strict,legacy}`(20일 승률·평균 R, -8% 스톱). 유니버스 15개 초과 시 reps 우선 샘플(`sampled:true`).

### 3.6 기타 (기능 무변경, 도움말 정합)
- technical 기본 period `1y`는 `analyze_technical(ticker)` 인자 무전달이라 자동 적용 — 배선 불필요.
- cli.py 상단 docstring `sectors` 줄: "자금흐름 랭킹" → "상대모멘텀 랭킹(가격 프록시)". `momentum` 줄에 `short_pct_float` 언급.
- `themes` 서브커맨드(#42): info 조회 후 name/sector를 판정에 전달(현 cli.py:159 부근 — risk와 mandate 갈리는 문제). `main.py`(#42): 레거시 경로에 'momentum/risk 미포함' 안내 필드.

---

## 4. Integrate-Docs — 문서·프롬프트 반영

> stock.md·market.md·glossary.md에 사용자 미커밋 수정이 있었음(이제 커밋됨) — 덮어쓰지 말고 그 위에 편집.

### 4.1 감사 문서 항목 (보고서 §번호)
- **#15**: stock.md·crypto.md에 **Step -1**(분석 전 `cli.py portfolio --json` + `themes <T>`로 보유·평단·클러스터 합산 확인 → 위원회 컨텍스트 고정). risk-officer.md에 **0단계 클러스터 캡**(단일 테마 40~50% 초과 시 recommended를 잔여 한도로 캡).
- **#19**: stock.md T7에 "T6 Bull/Base/Bear를 `risk --scenarios`로, macro 레짐을 `--regime`으로 전달" 지시(§4.3 문구 참조).
- **#20**: stock.md:714 부근 '최대 허용 비중 = VaR/Kelly/Mandate 중 **최소**' → 'mandate_max (VaR/Kelly는 soft_warnings 참고 병기)'.
- **#21**: stock.md(+crypto.md) conviction **결정론적 루브릭**: 기본 1.0, momentum_score≥70 +0.3, breakout_buy +0.2, 테마 🟢 +0.3/🔴 −0.3, 서사 과열 −0.2, RS(SPY) 음수면 상한 1.0 → [0.5,2.0] 클램프 → **산출식을 보고서에 기록**.
- **#22**: market.md sector_scan 해석을 '가격 기반 상대모멘텀'으로 정정, conviction '자금흐름' 항목은 가격 외 증거로만 충족(§4.2 상세).
- **#34**: risk-officer.md 한정 **하드 거부권**(손절 무력화 3종: 유동성 부족·회계 적신호·희석 폭탄). memo-writer.md 헤징 배격에 'T6 기대수익 음수/Kelly avoid면 예외'.
- **#37**: market.md:240 숏인터레스트 출처를 `cli.py momentum`의 `short_pct_float`(null이면 `cli.py insider`)로.
- **#38**: crypto.md risk 프롬프트에 `--mandate crypto` 명시 + '출력 mandate_profile 확인' 1줄.
- **#39**: portfolio.md 공통 절차에 크립토 심볼 해석(`cli.py crypto <SYM>` → yfinance_symbol로 add/quote + name 확인).
- **#40**: 보유자 권고 **4분기(유지/확대/축소/전량 청산)** — memo-writer.md, CLAUDE.md 규격 7, stock.md, crypto.md 4곳 동시.
- **#41**: knowledge-agent.md tools에 `Glob, WebSearch` 추가.
- **#42 문서행**: Bear 음수-손절선 예외 병기(stock.md·valuation-analyst.md), report 템플릿에 트레일링 스톱·R-multiple 행, crypto.md·market.md·macro.md glossary 금지어 치환(glossary.md 참조), setup.md crypto.json 3종·`EXAMPLE/` 정정, CLAUDE.md MVRV 오기 정정, earnings-analyst.md 필드 해석.

### 4.2 클러스터 doc_spec (구현자 반환 — 신규 출력 필드에 맞춘 지침)

**signals(market.md 필수)**: 출력 키 rating 라벨 '🟢 상대모멘텀 유입(가격 프록시)/🟡 중립/🔴 이탈', 신규 키 `rs_vs_spy_1m_pct, spy_1m_return_pct, benchmark_available, score_available_max, data_span_days`. **rating은 fund flow 아님** 명시. `benchmark_available=false`/RS null이면 breadth 판정 보류(`errors` 먼저 확인). 🟢 조건에 "AND 1M RS ≥ 0" 추가, 음수면 🟡 강등. sector rating을 '💵 유동성/자금흐름' 근거로 재사용 금지(이중계상). 240행 숏 출처 `short_pct_float` 명시. CLAUDE.md `sectors`/`momentum` 줄 갱신. 구 '자금유입' 어휘 잔존: market-analyst.md:34,116 / macro-strategist.md:76,78 / macro.md:175 / stock.md:148,164,650 / memo-writer.md:56.

**risk**: (§4.1 #19에 반영) + CLAUDE.md risk 옵션 블록에 `--scenarios`/`--regime` 2줄, `--mandate` 설명 'default|megatrend|crypto'로(risk·mandate-check 둘 다).

**macro**: macro.md 26행 출력키 — 신용 "HY OAS(FRED BAMLH0A0HYM2) 1차·HYG/LQD 폴백(credit.method)", 인플레축 "T10YIE 3M ±15bp 1차·명목10y 폴백(inflation_axis_method)", 신규 `regime_change` 키. 174행 분면→섹터에 2행 추가: EXPANSION/GOLDILOCKS-LEAN(골디락스 준용), SLOWDOWN-LEAN(디플레 준용). `regime_change.flipped`/`quadrant_moved`=true면 헤드라인에 '레짐 전환' 명시. macro-strategist.md 27·43행, CLAUDE.md macro 줄 동일 취지. data/macro_snapshots 저장 언급.

**crypto**: crypto.md 21행 티커 주의 — `yfinance_symbol=null`이면 CoinGecko ±20% 교차검증 실패(동명 자산) → technical/risk/momentum 금지. `data_status='identity_mismatch'`면 오자산 폐기 → 정확 id 재시도. 섹터 로테이션은 시총>$1B 7d/30d 시총가중(24h 보조), `sector_rotation_method`에 '폴백'이면 지속성 판정 보류. CLAUDE.md 38·39행 갱신.

**valuation(선택)**: valuation-analyst.md — `implied_growth_saturated=true`면 `implied_growth_display`('≥100%'/'≤-10%')로 보고, `excluded_negative`/`failed_peers` 있으면 표본 축소 병기. 신규 필드: `dcf.assumptions.growth_components{annual_cagr_pct,quarterly_yoy_pct,forward_consensus_pct}`, `dcf.sensitivity_basis`, `assumptions.{currency,rate_basis}`, `growth_valuation.{margin_ramp,start_fcf_margin_pct,target_margin_basis}`, peers `{excluded_negative,failed_peers,benchmark_basis}`.

**newsdata(earnings-analyst.md)**: §3 — `earnings_growth_yoy_pct`·`quarterly_earnings_growth_yoy_pct`는 **모두 YoY**(QoQ 오독 금지, 구 키 하위호환). QoQ는 `earnings_history.records` eps_actual로 직접. §4 — `beat_rate_pct`는 actual>estimate만(meet는 `meet_count` 별도). 신규 `result/gap_t1_pct/drift_t5_pct/beat_and_fade_count`. **beat-and-fade**(EPS beat인데 gap_t1<0 = 기대 소진 출구신호): §6 실적 전 베팅에서 beat_and_fade 최근 2회↑면 진입 논거 강등. `data_status:"error"`=조회 실패(≠이력 없음 `empty`).

**memopdf**: memo-writer.md — 메모 JSON에 `entry_case_a`·`entry_case_b`·`triggers`(리스트: type earnings|price_stop|price_target|event, 실적/이벤트는 date, 가격은 level) 키 추가, '주의사항'에 triggers 필수(watch 정본) + write 결과 `missing_fields`/`soft_warnings` 확인 후 재저장. report.md — 메타 스키마에 `currency:"USD|KRW"`, 실행 단계에 "빌드 JSON의 `cover_check`·`soft_warnings` 확인(표지 upside_pct·weighted.price는 재계산 검산, 오차>1%면 재계산값 인쇄)". CLAUDE.md `memo write` 주석 보강.

**watch(CLAUDE.md 3곳)**: 사용법 블록에 `watch` 추가, '데이터 디렉토리 규약'에 `data/watchlist.md`·`data/alerts/`(+.gitignore, 이미 반영), 신규 섹션 **'상시 감시 규약'**(장 마감 후 cron 1일 1회 예시 + 대화 시작 시 alerts 우선 판독 🔴→🟡→🟢 + 메모 triggers 파싱). /invest:portfolio 스킬 평가모드에 alerts 판독 병행.

**track/revisions(CLAUDE.md 2줄)**: `track`·`revisions` 사용법 추가. market.md 종목스캔에 "sectors 상위 테마는 `revisions <테마>`로 리비전 breadth 교차확인(가격 외 신호)". **`/invest:review` 분기 스킬(#14③, 미작성)**: track 출력(by_recommendation·scenario_calibration·by_conviction)을 conviction 루브릭·momentum 임계값 보정 1차 입력으로. 주의: 관망/회피 수익률은 기회비용, `trades_ledger.available=false`면 실현손익 축 미가동(trades.jsonl 축적 선행). knowledge-agent.md 재분석 시 `track --ticker` 먼저.

**backtest(CLAUDE.md 1줄)**: 사용법 블록에 `backtest` 추가. `/invest:review` 스킬에 'backtest 실행 → IC·승률 확인 → 가중치 변경 시 momentum.py docstring에 근거 기록' 절차.

### 4.3 stock.md T7 추가 지시 문구 (verbatim)
- "T6 시나리오 분석의 Bull/Base/Bear 확률·수익률을 risk의 `--scenarios '[{"prob":<Bull확률>,"return_pct":<Bull%>},{"prob":<Base>,"return_pct":<Base%>},{"prob":<Bear>,"return_pct":<Bear%>}]'`로 전달 → `kelly.basis='scenario'` 확인. `kelly.signal='avoid'`(기대수익 음수)면 결정론적 진입 보류 신호 — 보고서에 명시하고 확신도·논거 재검토."
- "매크로 레짐을 `--regime risk_on|neutral|risk_off`로 전달(macro risk-on/off 점수 또는 /invest:macro 최신). recommended_pct에 승수 1.0/0.75/0.5 적용. 불명 시 미지정 → `regime:"unspecified"`(1.0), 보고서에 '레짐 미반영' 표기."
- "`implied_capital_risk_pct`(권고비중×손절폭)가 `risk_budget_pct`(default 2.0/megatrend 3.0/crypto 3.0)를 초과해 soft_warning 발화 시, 포지션 사이징 섹션에 '비중 축소 vs 스톱 타이트닝' 택일 권고 반영."

---

## 5. Verify — 스모크 매트릭스

`python3 -m compileall -q src` 후 각 실행(JSON 파싱 + 신규 필드 확인; 레이트리밋이면 15초 후 1회 재시도). **파괴적 커맨드(add/sell/remove)는 --help/미보유 경로만, 실데이터 data/portfolio.md 수정 금지.**

| 커맨드 | 확인 포인트 |
|---|---|
| `technical AAPL` | sma_200 non-null(period 1y) |
| `momentum AAPL` | rs_available·bar_status·short_pct_float |
| `risk AAPL --stop-loss-pct 15` | implied_capital_risk_pct |
| `risk BTC-USD` | annualization_basis=365 |
| `mandate-check NVDA` | D/E 게이트 통과(compliant) |
| `valuation AAPL` | growth_components assumptions |
| `peers RIVN` | excluded_negative(음수 멀티플) |
| `insider NVDA` | 분류가 unknown 아님 |
| `earnings AAPL` | result/gap_t1/beat_and_fade |
| `macro` | regime_change 블록 |
| `crypto GRT` | The Graph로 해석(죽은 토큰 아님) |
| `crypto-market` | 시총 필터 로테이션 |
| `portfolio quote AAPL` | 크래시 없음(3튜플) |
| `portfolio check` | 스키마 파싱(구 5컬럼 호환) |
| `watch --no-append` | 픽스처/그레이스풀 |
| `track --ticker AAPL` | 파싱·채점 |
| `revisions AI` | breadth 랭킹 |
| `backtest --universe NVDA,MSFT --period 1y` | IC·돌파 승률 |

이후 클러스터별 `git diff` 정밀 리뷰(감사 개선안 대조·회귀·시그니처 호환) → 이슈는 소유 파일에서 수정 → 재스모크.

---

## 6. 참고 — 항목→파일→클러스터 맵

| 클러스터 | 파일 | 항목 |
|---|---|---|
| portfolio | portfolio.py, setup_tool.py, .gitignore | #1 #10 #11 #12 #13 #14(전) #44 #15(일부) |
| risk | risk_analyzer.py, mandates/*.json | #2 #7 #19 #24 #31 #38 #45 #50 #17(risk) |
| signals | momentum.py, technical.py, sector_scan.py | #4 #5 #22 #36 #43 #48 #50 #18c |
| macro | macro_data.py | #29 #30 #17(macro) |
| crypto | crypto_data.py | #8 #9 #35 #46 |
| valuation | valuation.py, fundamental.py, peer_comparison.py | #25 #26 #27 #32 #33 #50 |
| newsdata | news.py, news_search.py, insider_analysis.py, earnings_calendar.py | #6 #28 #47 #42 #18b #50 |
| memopdf | memo_manager.py, report_pdf.py | #42 #49 |
| backtest | backtest.py(신규) | #23 |
| watch | watch_alerts.py(신규) | #16 |
| track | track_performance.py, revisions.py(신규) | #14(후) #18a |

**공유 정본 스키마**(클러스터 간 합의): portfolio.md 8컬럼 `종목|수량|평단|통화|매입환율|손절가|목표가|진입일`(구 5컬럼 파싱 허용); `data/trades.jsonl` 체결 원장; `data/alerts/YYYY-MM-DD.md`; `data/macro_snapshots/YYYY-MM-DD.json`; risk `--regime` 승수 1.0/0.75/0.5.
