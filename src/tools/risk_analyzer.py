"""리스크 분석 도구 - Risk Officer 에이전트용

변동성, VaR, 최대낙폭, 베타, 샤프비율 계산 및 mandate 준수 검증.
"""

import json
import os

import numpy as np
import yfinance as yf

try:
    from tools.theme_etf_map import SECTOR_ETF_MAP, mandate_profile_for_ticker
except ImportError:  # 직접 실행 등 path 차이 대응
    from theme_etf_map import SECTOR_ETF_MAP, mandate_profile_for_ticker


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MANDATE_DIR = os.path.join(DATA_DIR, "mandates")
MANDATE_PATH = os.path.join(MANDATE_DIR, "default.json")  # 하위호환
MARKET_TICKER = "SPY"  # S&P 500 ETF (베타 계산용)
RISK_FREE_RATE = 0.045  # 무위험 수익률 (미국 10년물 근사)


def _load_mandate(profile: str = None) -> dict:
    """mandate 파일을 로드한다.

    profile=None이면 default. profile='megatrend' 등이면 해당 프로파일 파일을 읽는다.
    """
    name = (profile or "default").strip()
    path = os.path.join(MANDATE_DIR, f"{name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # 폴백: default
        try:
            with open(MANDATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}


def calc_scenario_kelly(scenarios: list) -> dict:
    """시나리오(확률·수익률) 기반 Kelly 비중을 산출한다.

    Args:
        scenarios: [{"prob": 0.25, "return_pct": 200}, ...] 형태. 확률 합은 ~1.

    Returns:
        dict: 기대수익률, Full/Half Kelly(%), 신호(avoid/bet). 기대수익 음수면 'avoid'.

    다중 결과 Kelly 근사: f* = 기대수익 / 분산 (연속형 Kelly). 일별 노이즈가 아니라
    실제 베팅 단위(시나리오)의 비대칭 페이오프를 반영한다.
    """
    if not scenarios:
        return {"basis": "none", "signal": "no_data"}
    rets = []
    probs = []
    for s in scenarios:
        p = s.get("prob")
        r = s.get("return_pct")
        if p is None or r is None:
            continue
        probs.append(float(p))
        rets.append(float(r) / 100.0)
    if not probs:
        return {"basis": "none", "signal": "no_data"}
    psum = sum(probs)
    if psum > 0:
        probs = [p / psum for p in probs]  # 정규화
    exp_return = sum(p * r for p, r in zip(probs, rets))
    variance = sum(p * (r - exp_return) ** 2 for p, r in zip(probs, rets))
    if exp_return <= 0:
        return {
            "basis": "scenario",
            "expected_return_pct": round(exp_return * 100, 2),
            "full_kelly_pct": 0.0,
            "half_kelly_pct": 0.0,
            "signal": "avoid",  # 기대수익 음수 → 베팅 금지 신호 (0으로 뭉개지 않음)
        }
    kelly_full = exp_return / variance if variance > 0 else 0.0
    return {
        "basis": "scenario",
        "expected_return_pct": round(exp_return * 100, 2),
        "full_kelly_pct": round(min(kelly_full * 100, 100), 1),
        "half_kelly_pct": round(min(kelly_full * 50, 100), 1),
        "signal": "bet",
    }


def analyze_risk(
    ticker_symbol: str,
    period: str = "1y",
    mandate_profile: str = None,
    conviction: float = None,
    entry_mode: str = "accumulate",
    scenarios: list = None,
    stop_loss_pct: float = None,
) -> dict:
    """
    주어진 티커의 리스크 지표와 (확신도 가중) 포지션 사이징을 계산한다.

    Args:
        ticker_symbol: 주식 티커 심볼
        period: 데이터 조회 기간 (기본 1년)
        mandate_profile: 'default'(보수) | 'megatrend'(공격). None이면 default.
        conviction: 확신도 배수 0.5~2.0 (서사·모멘텀·자금흐름·카탈리스트 종합). None이면 1.0(중립).
        entry_mode: 'breakout'(돌파 추격, 1회 크게) | 'accumulate'(분할) | 'full'.
        scenarios: 시나리오 기반 Kelly 입력 [{"prob","return_pct"}]. 있으면 노이즈 Kelly 대체.
        stop_loss_pct: 손절 폭(%). 있으면 risk-per-trade(자본 1~2% 룰) 사이징 병기.

    Returns:
        dict: 변동성, VaR, 최대낙폭, 베타, 샤프비율, 확신도 가중 포지션 사이징 포함
    """
    ticker = yf.Ticker(ticker_symbol)
    df = ticker.history(period=period)

    if df.empty or len(df) < 20:
        raise ValueError(f"티커 '{ticker_symbol}'의 가격 데이터가 부족합니다.")

    close = df["Close"]
    daily_returns = close.pct_change().dropna()

    # --- 변동성 ---
    daily_volatility = float(daily_returns.std())
    annual_volatility = daily_volatility * np.sqrt(252)

    # --- VaR (Value at Risk) ---
    var_95 = float(np.percentile(daily_returns, 5))
    var_99 = float(np.percentile(daily_returns, 1))

    # --- 최대 낙폭 (Maximum Drawdown) ---
    cumulative = (1 + daily_returns).cumprod()
    running_max = cumulative.cummax()
    drawdowns = (cumulative - running_max) / running_max
    max_drawdown = float(drawdowns.min())

    # --- 베타 (시장 대비) ---
    beta = None
    try:
        market = yf.Ticker(MARKET_TICKER)
        market_df = market.history(period=period)
        if not market_df.empty:
            market_returns = market_df["Close"].pct_change().dropna()
            # 날짜 인덱스 정렬
            common_idx = daily_returns.index.intersection(market_returns.index)
            if len(common_idx) > 20:
                stock_r = daily_returns.loc[common_idx].values
                market_r = market_returns.loc[common_idx].values
                covariance = np.cov(stock_r, market_r)[0][1]
                market_variance = np.var(market_r)
                if market_variance > 0:
                    beta = round(float(covariance / market_variance), 3)
    except Exception:
        pass

    # --- 샤프 비율 ---
    mean_annual_return = float(daily_returns.mean()) * 252
    sharpe_ratio = None
    if annual_volatility > 0:
        sharpe_ratio = round((mean_annual_return - RISK_FREE_RATE) / annual_volatility, 3)

    # --- 현재가 대비 52주 위치 ---
    high_52w = float(close.max())
    low_52w = float(close.min())
    current_price = float(close.iloc[-1])
    position_52w = round((current_price - low_52w) / (high_52w - low_52w) * 100, 1) if high_52w != low_52w else 50.0

    # --- 소르티노 비율 ---
    downside_returns = daily_returns[daily_returns < 0]
    downside_std = float(downside_returns.std()) * np.sqrt(252) if len(downside_returns) > 0 else None
    sortino_ratio = None
    if downside_std and downside_std > 0:
        sortino_ratio = round((mean_annual_return - RISK_FREE_RATE) / downside_std, 3)

    # --- CVaR (Expected Shortfall) ---
    var_95_returns = daily_returns[daily_returns <= var_95]
    cvar_95 = float(var_95_returns.mean()) if len(var_95_returns) > 0 else None
    var_99_returns = daily_returns[daily_returns <= var_99]
    cvar_99 = float(var_99_returns.mean()) if len(var_99_returns) > 0 else None

    # --- 상관관계 분석 ---
    correlations = {}
    benchmark_tickers = {"SPY": "S&P 500", "QQQ": "NASDAQ 100"}

    # 섹터 ETF 추가 (info는 1회만 조회해 재사용)
    ticker_info = {}
    sector = ""
    quote_type = ""
    try:
        ticker_info = ticker.info or {}
        sector = ticker_info.get("sector", "")
        quote_type = (ticker_info.get("quoteType") or "").upper()
        sector_etf = SECTOR_ETF_MAP.get(sector)
        if sector_etf:
            benchmark_tickers[sector_etf] = f"섹터 ETF ({sector})"
    except Exception:
        pass

    company_name = ticker_info.get("longName") or ticker_info.get("shortName") or ""
    is_crypto = quote_type == "CRYPTOCURRENCY"

    # mandate 프로파일 결정: 명시값 우선 → 크립토면 crypto → 그 외 티커→테마 자동 매핑
    if mandate_profile is None:
        mandate_profile = ("crypto" if is_crypto
                           else mandate_profile_for_ticker(ticker_symbol, sector, company_name))

    for bench_ticker, bench_name in benchmark_tickers.items():
        try:
            bench_df = yf.Ticker(bench_ticker).history(period=period)
            if not bench_df.empty:
                bench_returns = bench_df["Close"].pct_change().dropna()
                common_idx = daily_returns.index.intersection(bench_returns.index)
                if len(common_idx) > 20:
                    corr = float(np.corrcoef(
                        daily_returns.loc[common_idx].values,
                        bench_returns.loc[common_idx].values
                    )[0][1])
                    correlations[bench_ticker] = {
                        "name": bench_name,
                        "correlation": round(corr, 3),
                        "interpretation": (
                            "강한 양의 상관" if corr > 0.7
                            else "보통 양의 상관" if corr > 0.4
                            else "약한 상관" if corr > -0.4
                            else "음의 상관"
                        ),
                    }
        except Exception:
            pass

    # --- 포지션 사이징 (확신도 가중 + 손절 규율) ---
    mandate = _load_mandate(mandate_profile)
    max_position_pct = mandate.get("max_position_pct", 10)
    risk_tolerance = mandate.get("risk_tolerance", "moderate")

    # 소프트 참고치 (자동으로 비중을 깎지 않음 — 초과 시 경고만)
    var_based_max = None
    if var_95 and abs(var_95) > 0:
        var_based_max = round(min(1.0 / abs(var_95), 100), 1)

    # 시나리오 기반 Kelly (있으면) — 비대칭 페이오프 반영. 없으면 일별 노이즈 Kelly(참고용).
    if scenarios:
        kelly = calc_scenario_kelly(scenarios)
    else:
        kelly = {"basis": "noise_based_daily", "signal": "reference"}
        win_rate = float(len(daily_returns[daily_returns > 0]) / len(daily_returns)) if len(daily_returns) > 0 else None
        if win_rate and 0 < win_rate < 1:
            avg_win = float(daily_returns[daily_returns > 0].mean()) if len(daily_returns[daily_returns > 0]) > 0 else 0
            avg_loss = float(abs(daily_returns[daily_returns < 0].mean())) if len(daily_returns[daily_returns < 0]) > 0 else 0
            if avg_loss > 0 and avg_win > 0:
                win_loss_ratio = avg_win / avg_loss
                kelly_full = win_rate - (1 - win_rate) / win_loss_ratio
                kelly["full_kelly_pct"] = round(kelly_full * 100, 1)
                kelly["half_kelly_pct"] = round(kelly_full * 50, 1)
                kelly["note"] = "일별 수익률 빈도 기반 — 미래 기대수익 미반영. 시나리오 Kelly로 교차검증 권장."

    # 확신도 배수: 서사·모멘텀·자금흐름·카탈리스트 종합 점수(외부 주입). 0.5~2.0로 클램프.
    conviction_multiplier = 1.0 if conviction is None else max(0.5, min(float(conviction), 2.0))

    # 중립 기준(neutral_base) = mandate 최대비중의 절반. 확신도로 0.25x~1.0x(=최대)까지 스케일.
    neutral_base = max_position_pct * 0.5
    recommended_pct = round(min(neutral_base * conviction_multiplier, max_position_pct), 1)

    # 진입 모드별 1회 진입 비중 (돌파=크게, 분할=절반)
    entry_factor = {"breakout": 0.8, "full": 1.0, "accumulate": 0.5}.get(entry_mode, 0.5)
    entry_size_pct = round(recommended_pct * entry_factor, 1)

    # 소프트 경고 (자동 감점 대신 명시)
    soft_warnings = []
    if var_based_max is not None and recommended_pct > var_based_max:
        soft_warnings.append(
            f"권고 비중 {recommended_pct}%가 VaR 기준 참고상한({var_based_max}%)을 초과 — 손절 규율(타이트한 스톱) 필수."
        )
    if kelly.get("signal") == "avoid":
        soft_warnings.append("시나리오 Kelly 기대수익 음수 → 진입 보류 신호. 확신도/논거 재검토.")

    # risk-per-trade: 손절 폭이 주어지면 '자본의 1~2%만 잃는' 사이즈 병기
    risk_per_trade = None
    if stop_loss_pct and stop_loss_pct > 0:
        risk_per_trade = {
            "stop_loss_pct": round(stop_loss_pct, 1),
            "size_for_1pct_capital_risk": round(1.0 / stop_loss_pct * 100, 1),
            "size_for_2pct_capital_risk": round(2.0 / stop_loss_pct * 100, 1),
            "note": "손절 시 자본의 1~2%만 손실 보도록 한 비중(%). 권고비중과 비교해 더 보수적인 쪽 채택 가능.",
        }

    position_sizing = {
        "mandate_profile": mandate_profile,
        "risk_tolerance": risk_tolerance,
        "conviction_multiplier": conviction_multiplier,
        "entry_mode": entry_mode,
        "mandate_max_pct": max_position_pct,
        "recommended_pct": recommended_pct,
        "entry_size_pct": entry_size_pct,
        "pyramiding": "추세 유효(정배열+ADX>25) & 신고가 돌파 + 거래량 동반 시, 손절선 상향하며 권고비중까지 추가 진입(불타기). 물타기 아님.",
        "var_based_max_pct": var_based_max,
        "kelly": kelly,
        "risk_per_trade": risk_per_trade,
        "soft_warnings": soft_warnings,
        "method": "neutral_base(=mandate_max×0.5) × conviction(0.5~2.0), mandate_max 천장. VaR/Kelly는 경고용 참고치(자동 감점 안 함).",
    }

    # --- 스트레스 테스트 (선형 베타 외삽 + 가격 0 하한 클램프) ---
    stress_scenarios = []
    for scenario_name, market_drop in [("경미 (-5%)", -0.05), ("중간 (-15%)", -0.15), ("심각 (-30%)", -0.30)]:
        expected_loss = max(market_drop * (beta if beta else 1.0), -1.0)  # 손실 -100% 하한
        expected_price = round(max(current_price * (1 + expected_loss), 0.0), 2)  # 음수가 방지
        stress_scenarios.append({
            "scenario": scenario_name,
            "market_drop_pct": round(market_drop * 100, 1),
            "expected_loss_pct": round(expected_loss * 100, 2),
            "expected_price": expected_price,
        })

    stress_test = {
        "beta_used": beta,
        "method": "선형 베타 외삽 (손실 -100% 클램프). 고베타/레버리지 ETF는 경로의존성으로 실제 낙폭이 더 클 수 있음 — 참고치.",
        "scenarios": stress_scenarios,
    }

    return {
        "ticker": ticker_symbol,
        "period": period,
        "current_price": round(current_price, 2),
        "volatility": {
            "daily_pct": round(daily_volatility * 100, 3),
            "annual_pct": round(annual_volatility * 100, 2),
        },
        "var": {
            "var_95_daily_pct": round(var_95 * 100, 3),
            "var_99_daily_pct": round(var_99 * 100, 3),
            "cvar_95_daily_pct": round(cvar_95 * 100, 3) if cvar_95 else None,
            "cvar_99_daily_pct": round(cvar_99 * 100, 3) if cvar_99 else None,
            "interpretation": f"95% 신뢰도: 일일 최대 {abs(round(var_95 * 100, 2))}% 손실 예상 (평균 {abs(round(cvar_95 * 100, 2))}%)" if cvar_95 else f"95% 신뢰도: 일일 최대 {abs(round(var_95 * 100, 2))}% 손실 예상",
        },
        "max_drawdown": {
            "value_pct": round(max_drawdown * 100, 2),
            "interpretation": f"분석 기간 내 최대 {abs(round(max_drawdown * 100, 2))}% 하락",
        },
        "beta": {
            "value": beta,
            "benchmark": MARKET_TICKER,
            "interpretation": (
                "시장보다 변동성 높음" if beta and beta > 1.2
                else "시장과 유사" if beta and 0.8 <= beta <= 1.2
                else "시장보다 안정적" if beta and beta < 0.8
                else "계산 불가"
            ),
        },
        "sharpe_ratio": {
            "value": sharpe_ratio,
            "risk_free_rate": RISK_FREE_RATE,
            "interpretation": (
                "우수 (위험 대비 수익 양호)" if sharpe_ratio and sharpe_ratio > 1
                else "보통" if sharpe_ratio and 0 <= sharpe_ratio <= 1
                else "부진 (위험 대비 수익 부족)" if sharpe_ratio and sharpe_ratio < 0
                else "계산 불가"
            ),
        },
        "sortino_ratio": {
            "value": sortino_ratio,
            "interpretation": (
                "우수 (하방 리스크 대비 수익 양호)" if sortino_ratio and sortino_ratio > 1.5
                else "보통" if sortino_ratio and sortino_ratio > 0
                else "부진" if sortino_ratio is not None
                else "계산 불가"
            ),
        },
        "correlations": correlations,
        "position_sizing": position_sizing,
        "stress_test": stress_test,
        "price_range_52w": {
            "high": round(high_52w, 2),
            "low": round(low_52w, 2),
            "position_pct": position_52w,
        },
        "risk_level": _risk_level(annual_volatility, close),
    }


def _risk_level(annual_volatility: float, close) -> dict:
    """변동성 + 추세 방향으로 리스크 등급을 매긴다.

    상승추세에서의 고변동성은 '추세 변동성'(기회)이고, 하락추세 고변동성은 '위험 변동성'이다.
    같은 변동성을 양방향으로 똑같이 처벌하지 않는다 — 공격적 투자자는 추세를 본다.
    """
    base = "높음" if annual_volatility > 0.6 else "중간" if annual_volatility > 0.3 else "낮음"
    trend = "N/A"
    try:
        sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
        cur = float(close.iloc[-1])
        if sma50:
            trend = "상승추세" if cur > sma50 else "하락추세"
    except Exception:
        pass
    if base == "높음" and trend == "상승추세":
        note = "고변동이나 상승추세 — '추세 변동성'(기회). 손절 규율로 관리하면 베팅 가능. 변동성만으로 회피 금물."
    elif base == "높음" and trend == "하락추세":
        note = "고변동 + 하락추세 — '위험 변동성'. 추세 회복 전까지 신규 진입 신중."
    else:
        note = "변동성 보통/낮음."
    return {"grade": base, "trend": trend, "note": note}


def check_mandate(ticker_symbol: str, mandate_profile: str = None) -> dict:
    """
    주어진 티커가 투자 mandate를 준수하는지 검증한다.

    Args:
        ticker_symbol: 티커
        mandate_profile: 'default' | 'megatrend'. None이면 티커→테마 자동 매핑.

    Returns:
        dict: 각 mandate 항목별 통과/위반 상태
    """
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}
    sector = info.get("sector", "")
    company_name = info.get("longName") or info.get("shortName") or ""
    quote_type = (info.get("quoteType") or "").upper()
    is_fund = quote_type in ("ETF", "MUTUALFUND")
    is_crypto = quote_type == "CRYPTOCURRENCY"

    if mandate_profile is None:
        mandate_profile = ("crypto" if is_crypto
                           else mandate_profile_for_ticker(ticker_symbol, sector, company_name))

    mandate = _load_mandate(mandate_profile)
    if not mandate:
        return {"error": "mandate 파일을 찾을 수 없습니다.", "profile": mandate_profile}

    checks = []
    all_pass = True
    notes = []

    # 시가총액 확인
    market_cap = info.get("marketCap")
    min_cap = mandate.get("min_market_cap_usd", 0)
    if market_cap and min_cap:
        passed = market_cap >= min_cap
        checks.append({
            "rule": "최소 시가총액",
            "threshold": f"${min_cap:,.0f}",
            "actual": f"${market_cap:,.0f}" if market_cap else "N/A",
            "passed": passed,
        })
        if not passed:
            all_pass = False

    # PER / 성장조정 밸류에이션 확인
    pe_ratio = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    ps_ratio = info.get("priceToSalesTrailing12Months")
    rev_growth = info.get("revenueGrowth")
    peg = info.get("pegRatio") or info.get("trailingPegRatio")
    max_pe = mandate.get("max_pe_ratio")

    if max_pe is None:
        # 공격/메가트렌드 프로파일: PER 하드 게이트 비활성. P/S·매출성장·PEG는 참고치로만.
        ref = []
        if pe_ratio: ref.append(f"PER {pe_ratio:.1f}")
        if forward_pe: ref.append(f"선행PER {forward_pe:.1f}")
        if ps_ratio: ref.append(f"P/S {ps_ratio:.1f}")
        if rev_growth is not None: ref.append(f"매출성장 {rev_growth*100:.0f}%")
        if peg: ref.append(f"PEG {peg:.2f}")
        checks.append({
            "rule": "밸류에이션(참고)",
            "threshold": ("주식 멀티플 N/A(크립토) — 온체인 네트워크 가치(NVT·MVRV·P/F)로 판단"
                          if is_crypto
                          else "PER 게이트 비활성 — 성장조정(P/S·매출성장·룰40)로 판단"),
            "actual": ("N/A (디지털자산 — 매출/이익 없음)" if is_crypto
                       else (", ".join(ref) if ref else "N/A")),
            "passed": True,
        })
        if is_crypto:
            notes.append("디지털자산: PER/P-S 등 주식 멀티플 미적용. 밸류에이션은 토크노믹스(발행·언락 희석)와 온체인 네트워크 가치(NVT·MVRV·스톡투플로우·P/F 수수료배수)로 crypto-analyst가 판단 — `cli.py crypto <TICKER>` 참조.")
        else:
            notes.append("고성장 프로파일: PER 하드캡 미적용. 고PER 자체를 위반으로 보지 않음 — 서사·성장이 멀티플을 정당화하는지 valuation/financial 에이전트가 판단.")
    elif is_fund:
        # ETF/펀드: 개별주 PER 게이트 부적합 (PER은 의미 없음). 게이트 면제.
        checks.append({
            "rule": "최대 PER",
            "threshold": str(max_pe),
            "actual": "N/A (ETF/펀드 — PER 게이트 면제)",
            "passed": True,
        })
        notes.append("ETF/레버리지 상품은 PER 게이트 면제. 핵심 리스크는 PER이 아니라 decay/경로의존성 — risk 지표로 별도 판단.")
    else:
        # 보수 프로파일 게이트: trailing 없으면 forward로 폴백, 둘 다 없으면(적자) 위반 아님
        effective_pe = pe_ratio if pe_ratio is not None else forward_pe
        if effective_pe is None:
            passed = True  # 적자/데이터없음 → 자동 위반 처리하지 않음
            actual_str = "N/A (적자 또는 데이터 없음)"
            notes.append("trailing/forward PER 모두 없음(적자 가능) — PER 게이트 자동 통과. P/S·매출성장으로 별도 평가 필요.")
        else:
            passed = effective_pe <= max_pe
            label = "" if pe_ratio is not None else " (선행)"
            actual_str = f"{effective_pe:.1f}{label}"
        checks.append({
            "rule": "최대 PER",
            "threshold": str(max_pe),
            "actual": actual_str,
            "passed": passed,
        })
        if not passed:
            all_pass = False

    # 배당수익률 확인
    div_yield = info.get("dividendYield", 0) or 0
    min_div = mandate.get("min_dividend_yield", 0)
    if min_div > 0:
        passed = div_yield >= min_div / 100
        checks.append({
            "rule": "최소 배당수익률",
            "threshold": f"{min_div}%",
            "actual": f"{div_yield * 100:.2f}%",
            "passed": passed,
        })
        if not passed:
            all_pass = False

    # 부채비율 확인 (yfinance debtToEquity 단위 혼선 방어: %표기 vs 배수표기)
    debt_to_equity = info.get("debtToEquity")
    max_de = mandate.get("max_debt_to_equity")
    if max_de and debt_to_equity is not None:
        # 값이 10 이상이면 % 표기(예: 150 = 1.5배), 미만이면 이미 배수(예: 1.5)로 간주
        de_multiple = debt_to_equity / 100 if debt_to_equity >= 10 else debt_to_equity
        passed = de_multiple <= max_de
        checks.append({
            "rule": "최대 부채비율",
            "threshold": f"{max_de}x",
            "actual": f"{de_multiple:.2f}x",
            "passed": passed,
        })
        if not passed:
            all_pass = False

    # 섹터 제외 확인
    sector = info.get("sector", "")
    excluded = mandate.get("excluded_sectors", [])
    if excluded and sector:
        passed = sector not in excluded
        checks.append({
            "rule": "제외 섹터",
            "threshold": ", ".join(excluded) if excluded else "없음",
            "actual": sector,
            "passed": passed,
        })
        if not passed:
            all_pass = False

    # 허용 섹터 확인
    allowed = mandate.get("allowed_sectors", [])
    if allowed and sector:
        passed = sector in allowed
        checks.append({
            "rule": "허용 섹터",
            "threshold": ", ".join(allowed),
            "actual": sector,
            "passed": passed,
        })
        if not passed:
            all_pass = False

    return {
        "ticker": ticker_symbol,
        "mandate_profile": mandate_profile,
        "mandate_name": mandate.get("name", "Unknown"),
        "risk_tolerance": mandate.get("risk_tolerance", "N/A"),
        "overall_compliant": all_pass,
        "checks": checks,
        "notes": notes,
        "company_name": company_name or "N/A",
        "sector": sector or "N/A",
        "quote_type": quote_type or "N/A",
    }
