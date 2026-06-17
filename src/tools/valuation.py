"""밸류에이션 분석 도구 - DCF, 역내재 분석, 애널리스트 타겟

yfinance 기반 간이 DCF 모델, 민감도 매트릭스, 역내재 성장률 역산.
"""

import numpy as np
import yfinance as yf


RISK_FREE_RATE = 0.045
EQUITY_RISK_PREMIUM = 0.055
TERMINAL_GROWTH = 0.025
DCF_YEARS = 10
GROWTH_CAP = 0.60          # 고성장 허용 상한(과거 0.30 → 메가트렌드 폭발성장 반영)
GROWTH_FLOOR = -0.10
NORMALIZED_FCF_MARGIN = 0.15  # 적자성장주 정상화 FCF 마진 가정(성숙기 도달 시)
IMPLIED_SEARCH_HI = 1.0    # 역내재 성장 탐색 상한(과거 0.50 → 50%+ 기대 종목 역산 가능)


def _safe_get(info: dict, key: str, default=None):
    val = info.get(key, default)
    return val if val is not None else default


def _calc_wacc(beta: float) -> float:
    """CAPM 기반 WACC 추정 (간이: 100% 자기자본 가정)"""
    if beta is None or beta <= 0:
        beta = 1.0
    return RISK_FREE_RATE + beta * EQUITY_RISK_PREMIUM


def _dcf_value(fcf: float, growth: float, wacc: float, shares: int) -> dict | None:
    """2단계 DCF + 영구가치로 내재가치 산출

    Phase 1 (1~5년): high_growth 그대로 적용
    Phase 2 (6~10년): high_growth에서 TERMINAL_GROWTH까지 선형 체감(fade)
    """
    if fcf is None or fcf <= 0 or shares is None or shares <= 0:
        return None
    if wacc <= TERMINAL_GROWTH:
        return None

    pv_sum = 0.0
    projected_fcf = fcf
    phase2_growths = []
    for year in range(1, DCF_YEARS + 1):
        if year <= 5:
            yearly_growth = growth
        else:
            fade_factor = (year - 5) / 5  # 0.2, 0.4, 0.6, 0.8, 1.0
            yearly_growth = growth * (1 - fade_factor) + TERMINAL_GROWTH * fade_factor
            phase2_growths.append(yearly_growth)
        projected_fcf *= (1 + yearly_growth)
        pv_sum += projected_fcf / (1 + wacc) ** year

    terminal_value = projected_fcf * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH)
    pv_terminal = terminal_value / (1 + wacc) ** DCF_YEARS
    enterprise_value = pv_sum + pv_terminal
    intrinsic = round(enterprise_value / shares, 2)
    phase2_avg = round(sum(phase2_growths) / len(phase2_growths) * 100, 2) if phase2_growths else None

    return {
        "intrinsic_value": intrinsic,
        "phase1_growth_pct": round(growth * 100, 2),
        "phase2_avg_growth_pct": phase2_avg,
    }


def _normalized_dcf(revenue: float, growth: float, wacc: float, shares: int,
                    margin: float = NORMALIZED_FCF_MARGIN) -> dict | None:
    """적자/음수 FCF 종목용 정상화 DCF.

    현재 FCF가 음수여도, 매출 × 성숙기 목표 FCF마진으로 '정상화 FCF'를 만들어 2단계 DCF를 돌린다.
    J커브 초기 메가트렌드 종목의 내재가치 앵커(추정)를 제공한다. 가정 민감도가 크므로 보조 지표로만 사용.
    """
    if revenue is None or revenue <= 0 or shares is None or shares <= 0:
        return None
    normalized_fcf = revenue * margin
    result = _dcf_value(normalized_fcf, growth, wacc, shares)
    if result is None:
        return None
    result["normalized_fcf"] = round(normalized_fcf, 0)
    result["assumed_fcf_margin_pct"] = round(margin * 100, 1)
    return result


def _implied_growth(fcf: float, wacc: float, shares: int, market_cap: float) -> float | None:
    """현재 시총을 정당화하는 FCF 성장률을 이진 탐색으로 역산"""
    if fcf is None or fcf <= 0 or shares is None or shares <= 0 or market_cap is None:
        return None

    target_price = market_cap / shares

    lo, hi = -0.10, IMPLIED_SEARCH_HI
    for _ in range(100):
        mid = (lo + hi) / 2
        result = _dcf_value(fcf, mid, wacc, shares)
        if result is None:
            return None
        if result["intrinsic_value"] < target_price:
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
                    fcf = ocf - abs(capex)  # capex 부호 방어(양수로 와도 차감)
        except Exception:
            pass

    wacc = _calc_wacc(beta)
    revenue = _safe_get(info, "totalRevenue") or _safe_get(info, "totalRevenues")

    # 성장률 추정: 하이퍼그로스엔 매출성장 우선(이익성장은 흑자전환기 폭발/노이즈가 큼)
    earnings_growth = _safe_get(info, "earningsGrowth")
    revenue_growth = _safe_get(info, "revenueGrowth")
    base_growth = None
    if revenue_growth is not None:
        base_growth = revenue_growth
    elif earnings_growth is not None and abs(earnings_growth) < 5:
        base_growth = earnings_growth
    if base_growth is None:
        base_growth = 0.05  # 기본 5%
    # 성장률 상한/하한 (메가트렌드 폭발성장 반영: 상한 60%)
    growth_capped = base_growth > GROWTH_CAP
    base_growth = max(min(base_growth, GROWTH_CAP), GROWTH_FLOOR)

    # --- 2단계 DCF ---
    dcf_result = _dcf_value(fcf, base_growth, wacc, shares)
    intrinsic_value = dcf_result["intrinsic_value"] if dcf_result else None
    upside_pct = round((intrinsic_value / current_price - 1) * 100, 2) if intrinsic_value and current_price else None

    # --- 적자/음수 FCF 종목: 정상화 DCF + EV/Sales 보조 경로 ---
    growth_valuation = None
    dcf_reason = None
    if intrinsic_value is None:
        if fcf is not None and fcf <= 0:
            dcf_reason = "negative_fcf"
        elif fcf is None:
            dcf_reason = "fcf_unavailable"
        norm = _normalized_dcf(revenue, base_growth, wacc, shares)
        ps_ratio = _safe_get(info, "priceToSalesTrailing12Months")
        ev = _safe_get(info, "enterpriseValue")
        ev_sales = round(ev / revenue, 2) if ev and revenue else None
        growth_valuation = {
            "method": "표준 DCF 불가(적자/음수 FCF) → 정상화 DCF + 매출배수 보조 사용",
            "reason": dcf_reason,
            "normalized_intrinsic_value": norm["intrinsic_value"] if norm else None,
            "normalized_upside_pct": round((norm["intrinsic_value"] / current_price - 1) * 100, 2) if norm and current_price else None,
            "assumed_fcf_margin_pct": norm["assumed_fcf_margin_pct"] if norm else None,
            "price_to_sales": round(ps_ratio, 2) if ps_ratio else None,
            "ev_to_sales": ev_sales,
            "revenue_growth_pct": round(revenue_growth * 100, 1) if revenue_growth is not None else None,
            "caveat": "정상화 가정(매출×목표마진) 민감도가 큼. 결론 1순위 근거로 -90%대 표준DCF를 쓰지 말 것. TAM 침투·P/S 역사밴드와 함께 해석.",
        }

    dcf = {
        "intrinsic_value": intrinsic_value,
        "upside_pct": upside_pct,
        "growth_valuation": growth_valuation,
        "assumptions": {
            "fcf": fcf,
            "growth_rate_pct": round(base_growth * 100, 2),
            "growth_capped": growth_capped,
            "phase1_growth_pct": dcf_result["phase1_growth_pct"] if dcf_result else None,
            "phase2_avg_growth_pct": dcf_result["phase2_avg_growth_pct"] if dcf_result else None,
            "wacc_pct": round(wacc * 100, 2),
            "terminal_growth_pct": round(TERMINAL_GROWTH * 100, 2),
            "beta": beta,
            "beta_source": "yfinance info['beta'] (통상 5년 월간) — risk 도구의 회귀 베타와 다를 수 있음",
            "years": DCF_YEARS,
            "model": "2-stage (Phase1: 1-5yr high growth, Phase2: 6-10yr fade to terminal)",
        },
    }

    # --- 민감도 매트릭스 (Phase1 성장률 ±2%p × WACC ±1%p, 3×3) ---
    growth_offsets = [-0.02, 0.0, 0.02]
    wacc_offsets = [-0.01, 0.0, 0.01]
    sensitivity = []
    for g_off in growth_offsets:
        row = []
        for w_off in wacc_offsets:
            r = _dcf_value(fcf, base_growth + g_off, wacc + w_off, shares)
            row.append(r["intrinsic_value"] if r else None)
        sensitivity.append({
            "growth_pct": round((base_growth + g_off) * 100, 2),
            "values": {
                f"wacc_{round((wacc + w) * 100, 1)}": row[i]
                for i, w in enumerate(wacc_offsets)
            },
        })
    dcf["sensitivity_matrix"] = sensitivity

    # --- 역내재 분석 ---
    # 시장이 가격에 반영한 FCF 성장률. '높다=고평가'로 단정하지 않고, 서사·자금흐름이 그 성장을
    # 정당화하는지 양방향으로 검증하도록 라벨을 재정의(메가트렌드 리더는 통상 35%+가 정상).
    implied_growth = _implied_growth(fcf, wacc, shares, market_cap)
    implied_assumptions = {
        "implied_growth_rate_pct": implied_growth,
        "assessment": (
            "시장 기대 보수적 (저성장 반영)" if implied_growth is not None and implied_growth < 15
            else "시장 기대 보통" if implied_growth is not None and implied_growth < 30
            else "시장이 고성장을 가격에 반영 — 서사/TAM/자금흐름이 정당화하는지 검증 필요(맞으면 추세추종, 틀리면 고평가)" if implied_growth is not None and implied_growth < 60
            else "시장이 초고성장을 반영 — 강한 메가트렌드 리더는 가능하나 실현 리스크 큼. 모멘텀·카탈리스트로 교차검증" if implied_growth is not None
            else "계산 불가 (적자/음수 FCF — growth_valuation 참조)"
        ),
        "note": "고내재성장 자체는 위반이 아니다. '시장이 바보가 아니라면 왜 이 멀티플인가'를 먼저 묻고, 그 근거가 틀렸을 때만 고평가.",
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
