"""리스크 분석 도구 - Risk Officer 에이전트용

변동성, VaR, 최대낙폭, 베타, 샤프비율 계산 및 mandate 준수 검증.
"""

import json
import os

import numpy as np
import yfinance as yf


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MANDATE_PATH = os.path.join(DATA_DIR, "mandates", "default.json")
MARKET_TICKER = "SPY"  # S&P 500 ETF (베타 계산용)
RISK_FREE_RATE = 0.045  # 무위험 수익률 (미국 10년물 근사)

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def _load_mandate() -> dict:
    """기본 mandate 파일을 로드한다."""
    try:
        with open(MANDATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def analyze_risk(ticker_symbol: str, period: str = "1y") -> dict:
    """
    주어진 티커의 리스크 지표를 계산한다.

    Args:
        ticker_symbol: 주식 티커 심볼
        period: 데이터 조회 기간 (기본 1년)

    Returns:
        dict: 변동성, VaR, 최대낙폭, 베타, 샤프비율 포함
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

    # 섹터 ETF 추가
    try:
        ticker_info = yf.Ticker(ticker_symbol).info or {}
        sector = ticker_info.get("sector", "")
        sector_etf = SECTOR_ETF_MAP.get(sector)
        if sector_etf:
            benchmark_tickers[sector_etf] = f"섹터 ETF ({sector})"
    except Exception:
        pass

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

    # --- 포지션 사이징 ---
    mandate = _load_mandate()
    max_position_pct = mandate.get("max_position_pct", 10)

    # VaR 기반 최대 비중: 포트폴리오의 VaR 기여를 1% 이내로 제한
    var_based_max = None
    if var_95 and abs(var_95) > 0:
        var_based_max = round(min(1.0 / abs(var_95), 100), 1)

    # Half-Kelly Criterion
    kelly_pct = None
    win_rate = float(len(daily_returns[daily_returns > 0]) / len(daily_returns)) if len(daily_returns) > 0 else None
    if win_rate and win_rate > 0 and win_rate < 1:
        avg_win = float(daily_returns[daily_returns > 0].mean()) if len(daily_returns[daily_returns > 0]) > 0 else 0
        avg_loss = float(abs(daily_returns[daily_returns < 0].mean())) if len(daily_returns[daily_returns < 0]) > 0 else 0
        if avg_loss > 0:
            win_loss_ratio = avg_win / avg_loss
            kelly_full = win_rate - (1 - win_rate) / win_loss_ratio
            kelly_pct = round(max(kelly_full * 50, 0), 1)  # Half Kelly, as %

    recommended_pct = min(
        var_based_max if var_based_max else max_position_pct,
        kelly_pct if kelly_pct else max_position_pct,
        max_position_pct,
    )

    position_sizing = {
        "var_based_max_pct": var_based_max,
        "half_kelly_pct": kelly_pct,
        "mandate_max_pct": max_position_pct,
        "recommended_pct": round(recommended_pct, 1),
        "entry_size_pct": round(recommended_pct * 0.5, 1),  # 1회 진입: 절반
    }

    # --- 스트레스 테스트 ---
    stress_scenarios = []
    for scenario_name, market_drop in [("경미 (-5%)", -0.05), ("중간 (-15%)", -0.15), ("심각 (-30%)", -0.30)]:
        expected_loss = market_drop * (beta if beta else 1.0)
        expected_price = round(current_price * (1 + expected_loss), 2)
        stress_scenarios.append({
            "scenario": scenario_name,
            "market_drop_pct": round(market_drop * 100, 1),
            "expected_loss_pct": round(expected_loss * 100, 2),
            "expected_price": expected_price,
        })

    stress_test = {
        "beta_used": beta,
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
        "risk_level": (
            "높음" if annual_volatility > 0.4
            else "중간" if annual_volatility > 0.2
            else "낮음"
        ),
    }


def check_mandate(ticker_symbol: str) -> dict:
    """
    주어진 티커가 투자 mandate를 준수하는지 검증한다.

    Returns:
        dict: 각 mandate 항목별 통과/위반 상태
    """
    mandate = _load_mandate()
    if not mandate:
        return {"error": "mandate 파일을 찾을 수 없습니다.", "path": MANDATE_PATH}

    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    checks = []
    all_pass = True

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

    # PER 확인
    pe_ratio = info.get("trailingPE")
    max_pe = mandate.get("max_pe_ratio")
    if max_pe:
        passed = pe_ratio is None or pe_ratio <= max_pe
        checks.append({
            "rule": "최대 PER",
            "threshold": str(max_pe),
            "actual": f"{pe_ratio:.1f}" if pe_ratio else "N/A",
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

    # 부채비율 확인
    debt_to_equity = info.get("debtToEquity")
    max_de = mandate.get("max_debt_to_equity")
    if max_de and debt_to_equity is not None:
        # yfinance의 debtToEquity는 이미 비율(예: 1.5)
        passed = debt_to_equity <= max_de * 100  # mandate는 배수, yfinance는 %
        checks.append({
            "rule": "최대 부채비율",
            "threshold": f"{max_de}x",
            "actual": f"{debt_to_equity / 100:.2f}x" if debt_to_equity else "N/A",
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
        "mandate_name": mandate.get("name", "Unknown"),
        "risk_tolerance": mandate.get("risk_tolerance", "N/A"),
        "overall_compliant": all_pass,
        "checks": checks,
        "company_name": info.get("longName", info.get("shortName", "N/A")),
        "sector": sector or "N/A",
    }
