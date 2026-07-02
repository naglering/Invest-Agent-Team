"""밸류에이션 분석 도구 - DCF, 역내재 분석, 애널리스트 타겟

yfinance 기반 간이 DCF 모델, 민감도 매트릭스, 역내재 성장률 역산.
"""

import numpy as np
import yfinance as yf


RISK_FREE_RATE = 0.045
EQUITY_RISK_PREMIUM = 0.055
TERMINAL_GROWTH = 0.025
# 통화별 할인 파라미터 — KRW 현금흐름(.KS 등)에 USD 명목 금리를 적용하는 통화 불일치 방지.
# 미지원 통화는 USD 기본값 폴백(assumptions의 rate_basis에 표기).
CURRENCY_RATE_TABLE = {
    "USD": {"risk_free": RISK_FREE_RATE, "terminal_growth": TERMINAL_GROWTH},
    "KRW": {"risk_free": 0.032, "terminal_growth": 0.020},  # 한국 국고채 금리·저성장 기조 반영
}
DCF_YEARS = 10
GROWTH_CAP = 0.60          # 고성장 허용 상한(과거 0.30 → 메가트렌드 폭발성장 반영)
GROWTH_FLOOR = -0.10
NORMALIZED_FCF_MARGIN = 0.15  # 적자성장주 정상화 FCF 마진 가정(성숙기 도달 시)
NORMALIZED_FCF_MARGIN_SOFTWARE = 0.25  # SW/SaaS는 성숙기 FCF 마진이 구조적으로 높음
MARGIN_RAMP_FLOOR = -0.50  # 램프 시작 마진 하한(극단 캐시번 클램프 — 초기 음수 FCF 반영은 유지)
IMPLIED_SEARCH_HI = 1.0    # 역내재 성장 탐색 상한(과거 0.50 → 50%+ 기대 종목 역산 가능)


def _safe_get(info: dict, key: str, default=None):
    val = info.get(key, default)
    return val if val is not None else default


def _calc_wacc(beta: float, risk_free: float = RISK_FREE_RATE) -> float:
    """CAPM 기반 WACC 추정 (간이: 100% 자기자본 가정, 무위험금리는 통화별 테이블)"""
    if beta is None or beta <= 0:
        beta = 1.0
    return risk_free + beta * EQUITY_RISK_PREMIUM


def _dcf_value(fcf: float, growth: float, wacc: float, shares: int,
               terminal_growth: float = TERMINAL_GROWTH) -> dict | None:
    """2단계 DCF + 영구가치로 내재가치 산출

    Phase 1 (1~5년): high_growth 그대로 적용
    Phase 2 (6~10년): high_growth에서 terminal_growth까지 선형 체감(fade)
    """
    if fcf is None or fcf <= 0 or shares is None or shares <= 0:
        return None
    if wacc <= terminal_growth:
        return None

    pv_sum = 0.0
    projected_fcf = fcf
    phase2_growths = []
    for year in range(1, DCF_YEARS + 1):
        if year <= 5:
            yearly_growth = growth
        else:
            fade_factor = (year - 5) / 5  # 0.2, 0.4, 0.6, 0.8, 1.0
            yearly_growth = growth * (1 - fade_factor) + terminal_growth * fade_factor
            phase2_growths.append(yearly_growth)
        projected_fcf *= (1 + yearly_growth)
        pv_sum += projected_fcf / (1 + wacc) ** year

    terminal_value = projected_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** DCF_YEARS
    enterprise_value = pv_sum + pv_terminal
    intrinsic = round(enterprise_value / shares, 2)
    phase2_avg = round(sum(phase2_growths) / len(phase2_growths) * 100, 2) if phase2_growths else None

    return {
        "intrinsic_value": intrinsic,
        "phase1_growth_pct": round(growth * 100, 2),
        "phase2_avg_growth_pct": phase2_avg,
    }


def _target_fcf_margin(sector: str, industry: str) -> float:
    """정상화 목표 FCF 마진 — 섹터/업종별 차등 (기본 15%, SW/SaaS 25%)."""
    text = f"{sector or ''} {industry or ''}".lower()
    if "software" in text:
        return NORMALIZED_FCF_MARGIN_SOFTWARE
    return NORMALIZED_FCF_MARGIN


def _normalized_dcf(revenue: float, growth: float, wacc: float, shares: int,
                    current_margin: float = 0.0, margin: float = NORMALIZED_FCF_MARGIN,
                    terminal_growth: float = TERMINAL_GROWTH) -> dict | None:
    """적자/음수 FCF 종목용 정상화 DCF.

    매출을 2단계 성장 경로(Phase1 고성장 → Phase2 fade)로 투영하고, FCF 마진은
    현재 마진 → 목표 마진으로 Phase-1~2(10년) 선형 램프업한다 — '성숙기 마진 즉시
    달성 + 하이퍼그로스 지속'이라는 이중 낙관 제거. 램프 초기의 음수 FCF도 그대로
    할인에 반영해 J커브 비용을 정직하게 차감한다. 목표 마진은 섹터별 차등
    (기본 15%, SW/SaaS 25%). 가정 민감도가 크므로 보조 지표로만 사용.
    """
    if revenue is None or revenue <= 0 or shares is None or shares <= 0:
        return None
    if wacc <= terminal_growth:
        return None

    start_margin = current_margin if current_margin is not None else 0.0
    start_margin = min(max(start_margin, MARGIN_RAMP_FLOOR), margin)  # 하한 클램프 + 목표 초과 방지

    pv_sum = 0.0
    projected_rev = revenue
    final_fcf = None
    for year in range(1, DCF_YEARS + 1):
        if year <= 5:
            yearly_growth = growth
        else:
            fade_factor = (year - 5) / 5
            yearly_growth = growth * (1 - fade_factor) + terminal_growth * fade_factor
        projected_rev *= (1 + yearly_growth)
        margin_t = start_margin + (margin - start_margin) * year / DCF_YEARS  # 선형 램프업
        fcf_t = projected_rev * margin_t
        pv_sum += fcf_t / (1 + wacc) ** year
        final_fcf = fcf_t

    terminal_value = final_fcf * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** DCF_YEARS
    intrinsic = round((pv_sum + pv_terminal) / shares, 2)

    return {
        "intrinsic_value": intrinsic,
        "phase1_growth_pct": round(growth * 100, 2),
        "normalized_fcf_year10": round(final_fcf, 0),
        "assumed_fcf_margin_pct": round(margin * 100, 1),
        "start_fcf_margin_pct": round(start_margin * 100, 1),
        "margin_ramp": (
            f"현재 FCF마진 {round(start_margin * 100, 1)}% → 목표 {round(margin * 100, 1)}%를 "
            f"{DCF_YEARS}년차에 선형 램프업으로 도달 (목표마진은 터미널 가치부터 온전 적용)"
        ),
    }


def _implied_growth(fcf: float, wacc: float, shares: int, market_cap: float,
                    terminal_growth: float = TERMINAL_GROWTH) -> tuple:
    """현재 시총을 정당화하는 FCF 성장률을 이진 탐색으로 역산.

    Returns:
        (implied_growth_pct, saturation) — saturation은 탐색 경계 포화 시
        'high'(실제 ≥100%) / 'low'(실제 ≤-10%), 정상 수렴 시 None.
    """
    if fcf is None or fcf <= 0 or shares is None or shares <= 0 or market_cap is None:
        return None, None

    target_price = market_cap / shares

    # 경계 포화 검사 — 경계값을 정답처럼 반환하지 않고 '≥/≤' 표기용 플래그를 세운다
    hi_result = _dcf_value(fcf, IMPLIED_SEARCH_HI, wacc, shares, terminal_growth)
    lo_result = _dcf_value(fcf, GROWTH_FLOOR, wacc, shares, terminal_growth)
    if hi_result is None or lo_result is None:
        return None, None
    if hi_result["intrinsic_value"] < target_price:
        return round(IMPLIED_SEARCH_HI * 100, 2), "high"
    if lo_result["intrinsic_value"] > target_price:
        return round(GROWTH_FLOOR * 100, 2), "low"

    lo, hi = GROWTH_FLOOR, IMPLIED_SEARCH_HI
    for _ in range(100):
        mid = (lo + hi) / 2
        result = _dcf_value(fcf, mid, wacc, shares, terminal_growth)
        if result is None:
            return None, None
        if result["intrinsic_value"] < target_price:
            lo = mid
        else:
            hi = mid
        if abs(hi - lo) < 0.0001:
            break
    return round((lo + hi) / 2 * 100, 2), None


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

    # --- 통화별 할인 파라미터 (.KS 등 KRW 종목에 USD 명목 금리 적용 방지) ---
    currency = _safe_get(info, "currency") or "USD"
    rates = CURRENCY_RATE_TABLE.get(currency, CURRENCY_RATE_TABLE["USD"])
    risk_free = rates["risk_free"]
    terminal_growth = rates["terminal_growth"]

    wacc = _calc_wacc(beta, risk_free)
    revenue = _safe_get(info, "totalRevenue") or _safe_get(info, "totalRevenues")

    # 성장률 추정: 단일 분기 YoY 하나로 10년 외삽하지 않고 3개 성분을 블렌드한다.
    #   (a) 연간 재무제표 2~3년 매출 CAGR  (b) 최근 분기 매출 YoY(revenueGrowth)
    #   (c) forward 컨센서스(revenue_estimate 당해·차기 회계연도 평균)
    # 가용한 성분의 단순평균 — 세 값 모두 assumptions.growth_components에 노출해 괴리를 드러낸다.
    earnings_growth = _safe_get(info, "earningsGrowth")
    quarterly_yoy = _safe_get(info, "revenueGrowth")  # (b) 소수 형태

    annual_cagr = None  # (a)
    try:
        ist = ticker.income_stmt
        if ist is not None and not ist.empty:
            for name in ("Total Revenue", "Revenue"):
                if name in ist.index:
                    rev_series = ist.loc[name].dropna()
                    vals = [float(v) for v in rev_series.iloc[:4]]  # 최신 → 과거 (최대 4개년)
                    if len(vals) >= 3 and vals[0] > 0 and vals[-1] > 0:
                        n_years = len(vals) - 1  # 2 또는 3년 CAGR
                        annual_cagr = (vals[0] / vals[-1]) ** (1.0 / n_years) - 1
                    break
    except Exception:
        pass

    forward_growth = None  # (c)
    try:
        rev_est = ticker.revenue_estimate
        if rev_est is not None and not rev_est.empty and "growth" in rev_est.columns:
            g_series = rev_est["growth"].dropna()
            g_vals = [float(g_series.loc[idx]) for idx in ("0y", "+1y") if idx in g_series.index]
            if g_vals:
                forward_growth = sum(g_vals) / len(g_vals)
    except Exception:
        pass

    growth_components = [c for c in (annual_cagr, quarterly_yoy, forward_growth) if c is not None]
    if growth_components:
        base_growth = sum(growth_components) / len(growth_components)
    elif earnings_growth is not None and abs(earnings_growth) < 5:
        base_growth = earnings_growth
    else:
        base_growth = 0.05  # 기본 5%
    # 성장률 상한/하한 (메가트렌드 폭발성장 반영: 상한 60%)
    growth_capped = base_growth > GROWTH_CAP
    base_growth = max(min(base_growth, GROWTH_CAP), GROWTH_FLOOR)

    # --- 2단계 DCF ---
    dcf_result = _dcf_value(fcf, base_growth, wacc, shares, terminal_growth)
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
        current_margin = (fcf / revenue) if (fcf is not None and revenue) else 0.0
        target_margin = _target_fcf_margin(_safe_get(info, "sector"), _safe_get(info, "industry"))
        norm = _normalized_dcf(revenue, base_growth, wacc, shares,
                               current_margin, target_margin, terminal_growth)
        ps_ratio = _safe_get(info, "priceToSalesTrailing12Months")
        ev = _safe_get(info, "enterpriseValue")
        ev_sales = round(ev / revenue, 2) if ev and revenue else None
        growth_valuation = {
            "method": "표준 DCF 불가(적자/음수 FCF) → 정상화 DCF(마진 램프업) + 매출배수 보조 사용",
            "reason": dcf_reason,
            "normalized_intrinsic_value": norm["intrinsic_value"] if norm else None,
            "normalized_upside_pct": round((norm["intrinsic_value"] / current_price - 1) * 100, 2) if norm and current_price else None,
            "assumed_fcf_margin_pct": norm["assumed_fcf_margin_pct"] if norm else round(target_margin * 100, 1),
            "target_margin_basis": "섹터별 목표마진 (기본 15%, SW/SaaS 25%)",
            "current_fcf_margin_pct": norm["start_fcf_margin_pct"] if norm else None,
            "margin_ramp": norm["margin_ramp"] if norm else None,
            "price_to_sales": round(ps_ratio, 2) if ps_ratio else None,
            "ev_to_sales": ev_sales,
            "revenue_growth_pct": round(quarterly_yoy * 100, 1) if quarterly_yoy is not None else None,
            "caveat": "정상화 가정(매출 투영×램프업 마진) 민감도가 큼. 결론 1순위 근거로 -90%대 표준DCF를 쓰지 말 것. TAM 침투·P/S 역사밴드와 함께 해석.",
        }

    dcf = {
        "intrinsic_value": intrinsic_value,
        "upside_pct": upside_pct,
        "growth_valuation": growth_valuation,
        "assumptions": {
            "fcf": fcf,
            "growth_rate_pct": round(base_growth * 100, 2),
            "growth_capped": growth_capped,
            "growth_components": {
                "annual_cagr_pct": round(annual_cagr * 100, 2) if annual_cagr is not None else None,
                "quarterly_yoy_pct": round(quarterly_yoy * 100, 2) if quarterly_yoy is not None else None,
                "forward_consensus_pct": round(forward_growth * 100, 2) if forward_growth is not None else None,
                "blend": "가용 성분 단순평균 — 단일 분기 YoY 외삽 방지 (성분 간 괴리가 크면 사이클 피크/저점 의심)",
            },
            "phase1_growth_pct": dcf_result["phase1_growth_pct"] if dcf_result else None,
            "phase2_avg_growth_pct": dcf_result["phase2_avg_growth_pct"] if dcf_result else None,
            "wacc_pct": round(wacc * 100, 2),
            "risk_free_rate_pct": round(risk_free * 100, 2),
            "terminal_growth_pct": round(terminal_growth * 100, 2),
            "currency": currency,
            "rate_basis": "통화별 무위험금리·터미널성장 테이블 (USD/KRW 지원, 미지원 통화는 USD 폴백)",
            "beta": beta,
            "beta_source": "yfinance info['beta'] (통상 5년 월간) — risk 도구의 회귀 베타와 다를 수 있음",
            "years": DCF_YEARS,
            "model": "2-stage (Phase1: 1-5yr high growth, Phase2: 6-10yr fade to terminal)",
        },
    }

    # --- 민감도 매트릭스 (Phase1 성장률 base ±25% 상대 × WACC ±1%p, 3×3) ---
    g_delta = round(abs(base_growth) * 0.25, 4) or 0.01  # base_growth 비례, 0이면 ±1%p 폴백
    growth_offsets = [-g_delta, 0.0, g_delta]
    wacc_offsets = [-0.01, 0.0, 0.01]
    sensitivity = []
    for g_off in growth_offsets:
        row = []
        for w_off in wacc_offsets:
            r = _dcf_value(fcf, base_growth + g_off, wacc + w_off, shares, terminal_growth)
            row.append(r["intrinsic_value"] if r else None)
        sensitivity.append({
            "growth_pct": round((base_growth + g_off) * 100, 2),
            "values": {
                f"wacc_{round((wacc + w) * 100, 1)}": row[i]
                for i, w in enumerate(wacc_offsets)
            },
        })
    dcf["sensitivity_matrix"] = sensitivity
    dcf["sensitivity_basis"] = f"growth ±{round(g_delta * 100, 2)}%p (base_growth ±25% 상대) × WACC ±1%p"

    # --- 역내재 분석 ---
    # 시장이 가격에 반영한 FCF 성장률. '높다=고평가'로 단정하지 않고, 서사·자금흐름이 그 성장을
    # 정당화하는지 양방향으로 검증하도록 라벨을 재정의(메가트렌드 리더는 통상 35%+가 정상).
    implied_growth, implied_saturation = _implied_growth(fcf, wacc, shares, market_cap, terminal_growth)
    implied_assumptions = {
        "implied_growth_rate_pct": implied_growth,
        "implied_growth_saturated": (implied_saturation is not None) if implied_growth is not None else None,
        "implied_growth_display": (
            "≥100%" if implied_saturation == "high"
            else "≤-10%" if implied_saturation == "low"
            else f"{implied_growth}%" if implied_growth is not None
            else None
        ),
        "assessment": (
            "탐색 상한 포화 — 시장이 100% 이상의 초고성장을 반영(수치는 하한 표기일 뿐 정확값 아님). 모멘텀·카탈리스트로 교차검증" if implied_saturation == "high"
            else "탐색 하한 포화 — 시장이 -10% 이하의 역성장을 반영(딥밸류/구조적 쇠퇴 의심, 수치는 상한 표기)" if implied_saturation == "low"
            else "시장 기대 보수적 (저성장 반영)" if implied_growth is not None and implied_growth < 15
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
    forward_pe_negative = forward_pe is not None and forward_pe <= 0  # 음수 forward P/E = 적자 전환 예상 (성장 기대 아님)
    if not forward_pe_negative and trailing_pe and forward_pe and trailing_pe > 0:
        pe_gap = round((trailing_pe - forward_pe) / trailing_pe * 100, 2)

    relative_valuation = {
        "trailing_pe": round(trailing_pe, 2) if trailing_pe else None,
        "forward_pe": round(forward_pe, 2) if forward_pe else None,
        "pe_gap_pct": pe_gap,
        "pe_gap_interpretation": (
            "향후 EPS 적자 예상 (forward P/E 음수 — 이익 성장 기대로 오독 금지)" if forward_pe_negative
            else "시장이 이익 성장을 기대" if pe_gap and pe_gap > 10
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
