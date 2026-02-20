"""밸류에이션 분석 도구 - DCF, 역내재 분석, 애널리스트 타겟

yfinance 기반 간이 DCF 모델, 민감도 매트릭스, 역내재 성장률 역산.
"""

import numpy as np
import yfinance as yf


RISK_FREE_RATE = 0.045
EQUITY_RISK_PREMIUM = 0.055
TERMINAL_GROWTH = 0.025
DCF_YEARS = 10


def _safe_get(info: dict, key: str, default=None):
    val = info.get(key, default)
    return val if val is not None else default


def _calc_wacc(beta: float) -> float:
    """CAPM 기반 WACC 추정 (간이: 100% 자기자본 가정)"""
    if beta is None or beta <= 0:
        beta = 1.0
    return RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM


def _dcf_value(fcf: float, growth: float, wacc: float, shares: int) -> float | None:
    """10년 DCF + 영구가치로 내재가치 산출"""
    if fcf is None or fcf <= 0 or shares is None or shares <= 0:
        return None
    if wacc <= TERMINAL_GROWTH:
        return None

    pv_sum = 0.0
    projected_fcf = fcf
    for year in range(1, DCF_YEARS + 1):
        projected_fcf *= (1 + growth)
        pv_sum += projected_fcf / (1 + wacc) ** year

    terminal_value = projected_fcf * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH)
    pv_terminal = terminal_value / (1 + wacc) ** DCF_YEARS
    enterprise_value = pv_sum + pv_terminal
    return round(enterprise_value / shares, 2)


def _implied_growth(fcf: float, wacc: float, shares: int, market_cap: float) -> float | None:
    """현재 시총을 정당화하는 FCF 성장률을 이진 탐색으로 역산"""
    if fcf is None or fcf <= 0 or shares is None or shares <= 0 or market_cap is None:
        return None

    target_price = market_cap / shares

    lo, hi = -0.10, 0.50
    for _ in range(100):
        mid = (lo + hi) / 2
        val = _dcf_value(fcf, mid, wacc, shares)
        if val is None:
            return None
        if val < target_price:
            lo = mid
        else:
            hi = mid
        if abs(hi - lo) < 0.0001:
            break
    return round((lo + hi) / 2 * 100, 2)


def analyze_valuation(ticker_symbol: str) -> dict:
    """DCF 밸류에이션, 민감도 매트릭스, 역내재 분석, 애널리스트 타겟을 산출한다."""
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info or {}

    if not info or (info.get("currentPrice") is None and info.get("regularMarketPrice") is None):
        raise ValueError(f"티커 '{ticker_symbol}'에 대한 데이터를 찾을 수 없습니다.")

    current_price = _safe_get(info, "currentPrice") or _safe_get(info, "regularMarketPrice")
    market_cap = _safe_get(info, "marketCap")
    shares = _safe_get(info, "sharesOutstanding")
    beta = _safe_get(info, "beta", 1.0)
    fcf = _safe_get(info, "freeCashflow")

    # cashflow에서 FCF 보완
    if fcf is None:
        try:
            cf = ticker.cashflow
            if cf is not None and not cf.empty:
                ocf_names = ["Operating Cash Flow", "Total Cash From Operating Activities"]
                capex_names = ["Capital Expenditure", "Capital Expenditures"]
                ocf = None
                capex = None
                for name in ocf_names:
                    if name in cf.index:
                        val = cf.loc[name].dropna()
                        if not val.empty:
                            ocf = float(val.iloc[0])
                            break
                for name in capex_names:
                    if name in cf.index:
                        val = cf.loc[name].dropna()
                        if not val.empty:
                            capex = float(val.iloc[0])
                            break
                if ocf is not None and capex is not None:
                    fcf = ocf + capex  # capex는 보통 음수
        except Exception:
            pass

    wacc = _calc_wacc(beta)

    # 성장률 추정: earningsGrowth 또는 revenueGrowth 사용
    earnings_growth = _safe_get(info, "earningsGrowth")
    revenue_growth = _safe_get(info, "revenueGrowth")
    base_growth = None
    if earnings_growth is not None and abs(earnings_growth) < 10:
        base_growth = earnings_growth
    elif revenue_growth is not None and abs(revenue_growth) < 10:
        base_growth = revenue_growth
    if base_growth is None:
        base_growth = 0.05  # 기본 5%
    # 성장률 상한/하한 적용 (DCF에서 비현실적 성장률 방지)
    base_growth = max(min(base_growth, 0.30), -0.10)  # -10% ~ +30%

    # --- 간이 DCF ---
    intrinsic_value = _dcf_value(fcf, base_growth, wacc, shares)
    upside_pct = round((intrinsic_value / current_price - 1) * 100, 2) if intrinsic_value and current_price else None

    dcf = {
        "intrinsic_value": intrinsic_value,
        "upside_pct": upside_pct,
        "assumptions": {
            "fcf": fcf,
            "growth_rate_pct": round(base_growth * 100, 2),
            "wacc_pct": round(wacc * 100, 2),
            "terminal_growth_pct": round(TERMINAL_GROWTH * 100, 2),
            "beta": beta,
            "years": DCF_YEARS,
        },
    }

    # --- 민감도 매트릭스 (성장률 ±2%p × WACC ±1%p, 3×3) ---
    growth_offsets = [-0.02, 0.0, 0.02]
    wacc_offsets = [-0.01, 0.0, 0.01]
    sensitivity = []
    for g_off in growth_offsets:
        row = []
        for w_off in wacc_offsets:
            val = _dcf_value(fcf, base_growth + g_off, wacc + w_off, shares)
            row.append(val)
        sensitivity.append({
            "growth_pct": round((base_growth + growth_offsets[growth_offsets.index(g_off)]) * 100, 2),
            "values": {
                f"wacc_{round((wacc + w) * 100, 1)}": row[i]
                for i, w in enumerate(wacc_offsets)
            },
        })
    dcf["sensitivity_matrix"] = sensitivity

    # --- 역내재 분석 ---
    implied_growth = _implied_growth(fcf, wacc, shares, market_cap)
    implied_assumptions = {
        "implied_growth_rate_pct": implied_growth,
        "is_realistic": (
            "현실적" if implied_growth is not None and implied_growth < 20
            else "낙관적" if implied_growth is not None and implied_growth < 35
            else "비현실적" if implied_growth is not None
            else "계산 불가"
        ),
    }

    # --- 애널리스트 타겟 ---
    target_mean = _safe_get(info, "targetMeanPrice")
    target_high = _safe_get(info, "targetHighPrice")
    target_low = _safe_get(info, "targetLowPrice")
    analyst_count = _safe_get(info, "numberOfAnalystOpinions")
    recommendation = _safe_get(info, "recommendationKey")

    analyst_upside = round((target_mean / current_price - 1) * 100, 2) if target_mean and current_price else None

    analyst_target = {
        "mean": target_mean,
        "high": target_high,
        "low": target_low,
        "count": analyst_count,
        "recommendation": recommendation,
        "upside_pct": analyst_upside,
    }

    # --- 상대 밸류에이션 ---
    trailing_pe = _safe_get(info, "trailingPE")
    forward_pe = _safe_get(info, "forwardPE")
    pe_gap = None
    if trailing_pe and forward_pe and trailing_pe > 0:
        pe_gap = round((trailing_pe - forward_pe) / trailing_pe * 100, 2)

    relative_valuation = {
        "trailing_pe": round(trailing_pe, 2) if trailing_pe else None,
        "forward_pe": round(forward_pe, 2) if forward_pe else None,
        "pe_gap_pct": pe_gap,
        "pe_gap_interpretation": (
            "시장이 이익 성장을 기대" if pe_gap and pe_gap > 10
            else "적절한 성장 반영" if pe_gap and pe_gap > 0
            else "이익 감소 예상" if pe_gap is not None
            else "N/A"
        ),
    }

    return {
        "ticker": ticker_symbol,
        "current_price": current_price,
        "market_cap": market_cap,
        "dcf": dcf,
        "implied_assumptions": implied_assumptions,
        "analyst_target": analyst_target,
        "relative_valuation": relative_valuation,
    }
