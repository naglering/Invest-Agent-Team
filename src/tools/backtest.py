"""momentum_score·breakout 트리거 백테스트 하니스 — 수기 상수 캘리브레이션 근거 생성 (#23).

momentum.py의 점수 가중치(3M수익 25 / RS 25 / 고점근접 25 / 200일선 10 / 돌파 15)와
돌파 트리거 상수(거래량 1.3배 등)는 한 번도 채점된 적 없는 수기 상수다.
이 하니스는 과거 데이터로 그 예측력을 측정한다:

  (a) 월말 리밸런스 시점마다 momentum_score 구성요소를 **그 시점까지의 데이터만으로**
      재계산(look-ahead 금지) → score 사분위별 이후 1M/3M 평균 수익률 + IC(스피어만)
  (b) breakout 트리거 발생 후 20일 승률·평균 R(-8% 스톱 가정)
      - strict : 종가 신고가 경신 + 상승 마감 + 거래량 1.3배 — momentum.py 현행 정의(감사 #4 반영)
      - legacy : 구 정의 — 고점 -3% 이내 + 거래량 1.3배 (신고가/방향 미확인, 분산일 오발화 소지)
      두 정의를 나란히 채점해 #4 수정의 효과(분산일 오발화 제거)를 정량 확인한다.

momentum.py 자체는 '현재 시점' 전용이라 수정 없이 두고, 시점(point-in-time)용 로직을
여기서 재구현한다(_ret_pct만 재사용 — 수익률 정의 일치 보장). 점수는 momentum.py와
동일하게 가용 컴포넌트 만점 기준으로 재정규화(0~100)한다.

유니버스: 테마명(theme_etf_map.THEME_ETF_MAP 키) 또는 콤마 티커 목록.
크면 상위 15티커(reps 우선 + 나머지 알파벳순) 샘플 + sampled:true 표기.
"""

import re
import sys
import os
from datetime import datetime, timedelta

import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from tools.momentum import _ret_pct  # 현행 도구와 동일한 수익률 정의 재사용
    from tools.theme_etf_map import THEME_ETF_MAP, theme_members
except ImportError:
    from momentum import _ret_pct
    from theme_etf_map import THEME_ETF_MAP, theme_members

# momentum.py의 수기 상수 미러 (원본 analyze_momentum — 여기 값을 바꾸면 채점 대상이 달라짐)
LOOKBACK = 252            # '1y' 시점 창 (52주 고점·200일선·3M 수익 계산 범위)
BREAKOUT_NEAR_HIGH = -3   # legacy(구) 돌파 셋업: 고점 -3% 이내 (현행은 breakout_watch로 강등됨)
BREAKOUT_VOL_X = 1.3      # 돌파 셋업 공통: 거래량 20일 평균 대비 1.3배
FWD_1M, FWD_3M = 21, 63   # 이후 수익률 지평 (거래일)
BREAKOUT_HORIZON = 20     # 돌파 후 평가 지평 (거래일)
STOP_PCT = -8.0           # 돌파 트레이드 스톱 가정 → R = 수익률 / 8%
MIN_HISTORY = 64          # 시점 스코어 최소 이력 (3M 수익률 확보)
MAX_UNIVERSE = 15         # 유니버스 샘플 상한
BENCHMARK = "SPY"


# ─────────────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _period_days(period: str) -> int:
    """'3y'·'18mo'·'90d' → 대략 캘린더 일수."""
    m = re.fullmatch(r"(\d+)\s*(y|yr|mo|m|d)", str(period).strip().lower())
    if not m:
        raise ValueError(f"지원하지 않는 period 형식: '{period}' (예: 3y, 18mo, 90d)")
    n, unit = int(m.group(1)), m.group(2)
    return n * {"y": 365, "yr": 365, "mo": 30, "m": 30, "d": 1}[unit]


def _fetch_history(symbol: str, start: str):
    """일봉 이력(시작일 지정). 인덱스는 tz-naive 자정으로 정규화. 실패 시 None."""
    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if df is None or df.empty:
        return None
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    return df[~df.index.duplicated(keep="last")]


def _rank_avg(xs):
    """평균 순위(동률은 평균) — 스피어만용."""
    order = sorted(range(len(xs)), key=lambda k: xs[k])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    """스피어만 순위상관 (scipy 없이). 표본 <3 또는 분산 0이면 None."""
    n = len(xs)
    if n < 3:
        return None
    rx, ry = _rank_avg(xs), _rank_avg(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def _resolve_universe(universe: str):
    """유니버스 문자열 → (티커 목록, 테마명|None, sampled 여부).

    THEME_ETF_MAP 키와 정확히 일치하면 theme_members(동적 멤버십) 사용,
    아니면 콤마 구분 티커 목록으로 해석. 15개 초과 시 reps 우선 순서로 샘플.
    """
    u = universe.strip()
    if u in THEME_ETF_MAP:
        cfg = THEME_ETF_MAP[u]
        members = theme_members(u)
        reps = [r.upper() for r in cfg.get("reps", []) if r.upper() in members]
        rest = sorted(members - set(reps))
        tickers, theme = reps + rest, u
    else:
        tickers = [t.strip().upper() for t in u.split(",") if t.strip()]
        theme = None
    # 중복 제거 (순서 보존)
    seen, uniq = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    sampled = len(uniq) > MAX_UNIVERSE
    return uniq[:MAX_UNIVERSE], theme, sampled


# ─────────────────────────────────────────────────────────────────────────────
# 시점(point-in-time) momentum_score — momentum.py analyze_momentum 재구현 (look-ahead 금지)
# ─────────────────────────────────────────────────────────────────────────────

def _score_at(close, vol, i, spy_r3m_val):
    """인덱스 i 시점의 momentum_score(재정규화 0~100). i까지의 데이터만 사용(트레일링 창).

    momentum.py 현행 정의와의 구성요소 일치:
      3M 절대수익 25 + SPY RS 25 + 52주 고점근접 25 + 200일선 상회 10 + 돌파 셋업 15,
      돌파 = 종가 신고가 경신 + 상승 마감 + 거래량 1.3배 (감사 #4 반영 strict 정의),
      결측 컴포넌트는 가용 만점 기준 재정규화 (0점 처리 아님).
    12M 수익·저점 대비는 원본에서도 점수 미반영 → 생략.
    """
    window = close.iloc[max(0, i - LOOKBACK + 1): i + 1]
    cur = float(window.iloc[-1])
    r3 = _ret_pct(window, FWD_3M)  # 63거래일 = 3M (원본과 동일 정의)
    if r3 is None:
        return None
    high = float(window.max())
    pct_from_high = round((cur / high - 1) * 100, 2) if high else None

    vol_win = vol.iloc[max(0, i - 19): i + 1]
    vol20 = float(vol_win.mean()) if len(vol_win) >= 20 else None
    vol_surge = float(vol.iloc[i]) / vol20 if vol20 and vol20 > 0 else None

    # 돌파 셋업 (momentum.py 현행 strict 정의 — 신고가 경신 + 상승 마감 + 거래량)
    prior_high = float(window.iloc[:-1].max()) if len(window) >= 2 else None
    new_high = bool(prior_high is not None and cur >= prior_high)
    up_day = bool(len(window) >= 2 and cur > float(window.iloc[-2]))
    breakout = bool(new_high and up_day and vol_surge and vol_surge >= BREAKOUT_VOL_X)

    above_200 = None
    if len(window) >= 200:
        above_200 = bool(cur > float(window.tail(200).mean()))

    score, avail = 0.0, 0.0
    avail += 25
    score += max(0.0, min(r3 / 30.0, 1.0)) * 25
    if spy_r3m_val is not None:
        avail += 25
        score += max(0.0, min((r3 - spy_r3m_val) / 20.0, 1.0)) * 25
    if pct_from_high is not None:
        avail += 25
        score += max(0.0, min((pct_from_high + 25) / 25.0, 1.0)) * 25
    if above_200 is not None:
        avail += 10
        if above_200:
            score += 10
    if vol_surge is not None:
        avail += 15
        if breakout:
            score += 15
    return round(score / avail * 100, 1) if avail > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# 돌파 트리거 시뮬레이션 (비중복 트레이드, -8% 스톱)
# ─────────────────────────────────────────────────────────────────────────────

def _breakout_triggers(df):
    """strict(현행)/legacy(구) 돌파 트리거 불리언 시리즈 (전부 트레일링 계산 — look-ahead 없음)."""
    close, vol = df["Close"], df["Volume"]
    vol20 = vol.rolling(20, min_periods=20).mean()
    vol_ok = vol >= BREAKOUT_VOL_X * vol20

    # strict: momentum.py 현행(감사 #4 반영) — 직전 최고 종가 경신 + 상승 마감 + 거래량
    prev_high = close.shift(1).rolling(LOOKBACK, min_periods=MIN_HISTORY - 1).max()
    trig_strict = (close >= prev_high) & (close > close.shift(1)) & vol_ok

    # legacy: 구 정의 — 52주 고점(당일 포함) -3% 이내 + 거래량 (신고가·방향 미확인 → 분산일 오발화)
    roll_high = close.rolling(LOOKBACK, min_periods=MIN_HISTORY).max()
    near_high = (close / roll_high - 1) * 100 >= BREAKOUT_NEAR_HIGH
    trig_legacy = near_high & vol_ok
    return trig_strict.fillna(False), trig_legacy.fillna(False)


def _simulate_trades(trigger, close, low, start_pos):
    """트리거 발생일 종가 진입 → 20거래일 내 저가가 -8% 스톱 터치 시 R=-1 청산,
    아니면 20일째 종가 청산. 비중복(청산 전 재진입 금지). 미완결 트레이드 제외."""
    trades = []
    n = len(close)
    i = max(start_pos, 0)
    while i < n:
        if bool(trigger.iloc[i]) and i + BREAKOUT_HORIZON < n:
            entry = float(close.iloc[i])
            stop_price = entry * (1 + STOP_PCT / 100)
            ret, stopped = None, False
            for d in range(i + 1, i + BREAKOUT_HORIZON + 1):
                if float(low.iloc[d]) <= stop_price:
                    ret, stopped = STOP_PCT, True  # 스톱가 체결 가정 (갭 슬리피지 무시)
                    break
            if ret is None:
                ret = (float(close.iloc[i + BREAKOUT_HORIZON]) / entry - 1) * 100
            trades.append({"r": ret / abs(STOP_PCT), "ret": ret, "stopped": stopped})
            i += BREAKOUT_HORIZON + 1
        else:
            i += 1
    return trades


def _aggregate_trades(trades):
    if not trades:
        return {"n_trades": 0, "win_rate_pct": None, "avg_r": None,
                "median_r": None, "stop_hit_rate_pct": None, "avg_ret_20d_pct": None}
    rs = sorted(t["r"] for t in trades)
    n = len(rs)
    median = rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2
    return {
        "n_trades": n,
        "win_rate_pct": round(100 * sum(1 for t in trades if t["r"] > 0) / n, 1),
        "avg_r": round(sum(t["r"] for t in trades) / n, 3),
        "median_r": round(median, 3),
        "stop_hit_rate_pct": round(100 * sum(1 for t in trades if t["stopped"]) / n, 1),
        "avg_ret_20d_pct": round(sum(t["ret"] for t in trades) / n, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 메인 엔트리
# ─────────────────────────────────────────────────────────────────────────────

def backtest_momentum(universe: str, period: str = "3y") -> dict:
    """momentum_score 사분위 예측력 + breakout 트리거 승률/R을 과거 데이터로 채점한다."""
    tickers, theme, sampled = _resolve_universe(universe)
    if not tickers:
        raise ValueError(f"유니버스가 비었습니다: '{universe}' (테마명 또는 T1,T2,T3)")

    eval_days = _period_days(period)
    # 평가 시작 시점에도 트레일링 252거래일(≈365캘린더일) 창이 필요 → 여유 포함 선행 구간 확보
    start = (datetime.now() - timedelta(days=eval_days + 460)).strftime("%Y-%m-%d")
    eval_start = datetime.now() - timedelta(days=eval_days)

    errors, soft_warnings = [], []

    # 벤치마크(SPY): RS 계산 + 월말 리밸런스 캘린더의 기준
    spy_df = _fetch_history(BENCHMARK, start)
    if spy_df is None or len(spy_df) < MIN_HISTORY:
        raise ValueError(f"벤치마크 {BENCHMARK} 데이터 수집 실패 — 네트워크/yfinance 확인")
    spy_close = spy_df["Close"]
    spy_r3m = (spy_close / spy_close.shift(FWD_3M) - 1) * 100  # 시점별 3M 수익(트레일링)

    # 월말 리밸런스 날짜 (SPY 거래일 기준, 평가구간 내)
    idx = spy_close.index
    rebalance_dates = [idx[k] for k in range(len(idx) - 1)
                       if idx[k + 1].month != idx[k].month and idx[k] >= eval_start]

    # 티커별 데이터 수집 + 시점 스코어·포워드 수익률·돌파 트레이드
    observations = []          # {date, ticker, score, fwd_1m, fwd_3m}
    trades_strict, trades_legacy = [], []
    per_ticker_obs = {}
    failed = []

    for t in tickers:
        try:
            df = _fetch_history(t, start)
        except Exception as e:
            errors.append({"symbol": t, "error": str(e)})
            failed.append(t)
            continue
        if df is None or len(df) < MIN_HISTORY + BREAKOUT_HORIZON:
            errors.append({"symbol": t, "error": "이력 부족(최소 84거래일)"})
            failed.append(t)
            continue
        close, vol, low = df["Close"], df["Volume"], df["Low"]

        # (a) 월말 시점 스코어 + 이후 1M/3M 수익률
        n_obs = 0
        for d in rebalance_dates:
            pos = df.index.get_indexer([d], method="pad")[0]
            if pos < MIN_HISTORY - 1:
                continue
            if (d - df.index[pos]).days > 7:
                continue  # 리밸런스일 근처 데이터 없음(상장폐지/거래정지 의심) → 제외
            spy_val = spy_r3m.asof(d)
            spy_val = float(spy_val) if spy_val == spy_val else None  # NaN 가드
            score = _score_at(close, vol, pos, spy_val)
            if score is None:
                continue
            cur = float(close.iloc[pos])
            fwd1 = round((float(close.iloc[pos + FWD_1M]) / cur - 1) * 100, 2) \
                if pos + FWD_1M < len(close) else None
            fwd3 = round((float(close.iloc[pos + FWD_3M]) / cur - 1) * 100, 2) \
                if pos + FWD_3M < len(close) else None
            observations.append({"date": d.strftime("%Y-%m-%d"), "ticker": t,
                                 "score": score, "fwd_1m": fwd1, "fwd_3m": fwd3})
            n_obs += 1
        per_ticker_obs[t] = n_obs

        # (b) 돌파 트리거 시뮬레이션 (평가구간 내 일 단위 스캔)
        trig_str, trig_leg = _breakout_triggers(df)
        start_pos = int(df.index.searchsorted(eval_start))
        start_pos = max(start_pos, MIN_HISTORY - 1)
        trades_strict.extend(_simulate_trades(trig_str, close, low, start_pos))
        trades_legacy.extend(_simulate_trades(trig_leg, close, low, start_pos))

    ok_tickers = [t for t in tickers if t not in failed]
    if not observations:
        return {
            "as_of": datetime.now().strftime("%Y-%m-%d"),
            "universe_input": universe, "universe": tickers, "theme": theme,
            "sampled": sampled, "period": period,
            "observations": 0, "errors": errors,
            "soft_warnings": soft_warnings, "data_status": "empty",
            "note": "관측치 0 — 유니버스/기간/네트워크 확인",
        }

    # ── 사분위 분석 (pooled: 전체 date×ticker 관측치의 스코어 분포 기준) ──
    obs_1m = [o for o in observations if o["fwd_1m"] is not None]
    scores_sorted = sorted(o["score"] for o in observations)

    def _pct(p):
        k = max(0, min(len(scores_sorted) - 1, int(round(p * (len(scores_sorted) - 1)))))
        return scores_sorted[k]

    q1, q2, q3 = _pct(0.25), _pct(0.50), _pct(0.75)

    def _quartile(s):
        return 0 if s <= q1 else 1 if s <= q2 else 2 if s <= q3 else 3

    quartiles = []
    for qi, label in enumerate(["Q1(저점수)", "Q2", "Q3", "Q4(고점수)"]):
        qobs = [o for o in observations if _quartile(o["score"]) == qi]
        q1m = [o["fwd_1m"] for o in qobs if o["fwd_1m"] is not None]
        q3m = [o["fwd_3m"] for o in qobs if o["fwd_3m"] is not None]
        quartiles.append({
            "quartile": label,
            "n": len(qobs),
            "score_range": [min(o["score"] for o in qobs), max(o["score"] for o in qobs)] if qobs else None,
            "avg_fwd_1m_pct": round(sum(q1m) / len(q1m), 2) if q1m else None,
            "n_1m": len(q1m),
            "avg_fwd_3m_pct": round(sum(q3m) / len(q3m), 2) if q3m else None,
            "n_3m": len(q3m),
        })

    def _monotonic(key):
        vals = [q[key] for q in quartiles if q[key] is not None]
        return bool(len(vals) >= 3 and all(vals[k] <= vals[k + 1] for k in range(len(vals) - 1)))

    # ── IC (스피어만): pooled + 날짜별 크로스섹션 평균 ──
    def _pooled_ic(fwd_key):
        pairs = [(o["score"], o[fwd_key]) for o in observations if o[fwd_key] is not None]
        ic = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
        return round(ic, 3) if ic is not None else None

    def _cross_sectional_ic(fwd_key):
        by_date = {}
        for o in observations:
            if o[fwd_key] is not None:
                by_date.setdefault(o["date"], []).append((o["score"], o[fwd_key]))
        ics = []
        for pairs in by_date.values():
            if len(pairs) >= 3:
                ic = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if ic is not None:
                    ics.append(ic)
        return (round(sum(ics) / len(ics), 3), len(ics)) if ics else (None, 0)

    cs_1m, n_dates_1m = _cross_sectional_ic("fwd_1m")
    cs_3m, n_dates_3m = _cross_sectional_ic("fwd_3m")

    if len(ok_tickers) < 8:
        soft_warnings.append(
            f"유니버스 {len(ok_tickers)}종목 — 사분위가 특정 티커에 쏠릴 수 있고 "
            "크로스섹션 IC 신뢰도가 낮음. 테마 전체 또는 8종목 이상 권장.")
    if failed:
        soft_warnings.append(f"수집 실패 티커 제외: {', '.join(failed)}")
    if sampled:
        soft_warnings.append(f"유니버스 {MAX_UNIVERSE}개 초과 → reps 우선 상위 {MAX_UNIVERSE}개 샘플")

    agg_strict = _aggregate_trades(trades_strict)
    agg_legacy = _aggregate_trades(trades_legacy)

    return {
        "as_of": datetime.now().strftime("%Y-%m-%d"),
        "universe_input": universe,
        "universe": tickers,
        "theme": theme,
        "sampled": sampled,
        "period": period,
        "benchmark": BENCHMARK,
        "rebalance": "month_end",
        "lookback_trading_days": LOOKBACK,
        "look_ahead_free": True,  # 각 시점 스코어는 해당 시점까지 데이터만 사용
        "score_method": "momentum.py 현행과 동일 — 가용 컴포넌트 만점 재정규화(0~100), 돌파=strict 정의",
        "observations": len(observations),
        "per_ticker_obs": per_ticker_obs,
        "score_quartiles": {
            "method": "pooled",  # 전체 관측치 스코어 분포 기준 사분위 (날짜별 아님)
            "score_edges_q25_q50_q75": [q1, q2, q3],
            "buckets": quartiles,
            "monotonic_1m": _monotonic("avg_fwd_1m_pct"),
            "monotonic_3m": _monotonic("avg_fwd_3m_pct"),
        },
        "ic_spearman": {
            "pooled_1m": _pooled_ic("fwd_1m"),
            "pooled_3m": _pooled_ic("fwd_3m"),
            "cross_sectional_mean_1m": cs_1m,
            "cross_sectional_mean_3m": cs_3m,
            "n_dates_1m": n_dates_1m,
            "n_dates_3m": n_dates_3m,
            "note": "IC>0.05면 유의미한 예측력, 음수면 가중치 재검토 필요",
        },
        "breakout": {
            "horizon_days": BREAKOUT_HORIZON,
            "stop_loss_pct": STOP_PCT,
            "entry": "트리거 발생일 종가",
            "strict": {
                "definition": "momentum.py 현행(감사 #4 반영) — 종가 신고가 경신(직전 52주 최고 종가 상회) "
                              f"+ 상승 마감 + 거래량 20일 평균 {BREAKOUT_VOL_X}배",
                **agg_strict,
            },
            "legacy": {
                "definition": f"구 정의 — 52주 고점 {BREAKOUT_NEAR_HIGH}% 이내 "
                              f"+ 거래량 {BREAKOUT_VOL_X}배 (신고가·당일 방향 미확인)",
                **agg_legacy,
            },
            "note": "strict 승률/avg_r > legacy면 감사 #4 수정('분산일 오발화' 제거)의 효과가 데이터로 확인된 것",
        },
        "errors": errors,
        "soft_warnings": soft_warnings,
        "data_status": "ok" if not failed else "degraded",
        "disclaimer": "백테스트는 과거 데이터 기반 참고 자료이며 미래 수익을 보장하지 않음",
    }


if __name__ == "__main__":
    # 단독 실행: python3 src/tools/backtest.py --universe NVDA,MSFT,AMD --period 1y
    #           python3 src/tools/backtest.py "AI/반도체" --period 3y
    import json

    argv = sys.argv[1:]

    def _opt(name, default=None):
        for k, a in enumerate(argv):
            if a == name and k + 1 < len(argv):
                return argv[k + 1]
        return default

    uni = _opt("--universe")
    if uni is None:
        positional = [a for k, a in enumerate(argv)
                      if not a.startswith("--") and (k == 0 or argv[k - 1] not in ("--universe", "--period"))]
        uni = positional[0] if positional else None
    if not uni:
        print(json.dumps({"error": "사용법: backtest --universe <테마명|T1,T2,T3> [--period 3y]"},
                         ensure_ascii=False))
        sys.exit(1)
    try:
        result = backtest_momentum(uni, period=_opt("--period", "3y"))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)
