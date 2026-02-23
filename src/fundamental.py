"""재무 분석 모듈 - yfinance 기반 펀더멘털 데이터 수집 및 분석"""

import pandas as pd
import yfinance as yf


def _safe_get(data: dict, key: str, default=None):
    """딕셔너리에서 안전하게 값을 가져온다."""
    val = data.get(key, default)
    if val is None:
        return default
    return val


def _calc_growth_rate(current, previous):
    """전년 대비 성장률 계산"""
    if previous is None or current is None:
        return None
    if previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def _safe_round(value, digits=2):
    """None 안전 반올림"""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _get_latest_value(df, row_names):
    """재무제표 DataFrame에서 최신 연도 값을 가져온다. 여러 이름 후보를 시도."""
    if df is None or df.empty:
        return None
    for name in row_names:
        if name in df.index:
            val = df.loc[name].dropna()
            if not val.empty:
                return float(val.iloc[0])
    return None


def _get_prev_value(df, row_names):
    """재무제표 DataFrame에서 전년도 값을 가져온다."""
    if df is None or df.empty:
        return None
    for name in row_names:
        if name in df.index:
            val = df.loc[name].dropna()
            if len(val) >= 2:
                return float(val.iloc[1])
    return None


def analyze_fundamentals(ticker_symbol: str) -> dict:
    """
    주어진 티커의 펀더멘털 분석을 수행한다.

    Args:
        ticker_symbol: 주식 티커 심볼 (e.g., AAPL, 005930.KS)

    Returns:
        dict: 기본정보, 수익성, 성장성, 건전성, 현금흐름, 밸류에이션 포함
    """
    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        raise ValueError(f"티커 '{ticker_symbol}'에 대한 데이터를 찾을 수 없습니다.")

    # 재무제표 로드
    try:
        income_stmt = ticker.income_stmt
    except Exception:
        income_stmt = None
    try:
        balance_sheet = ticker.balance_sheet
    except Exception:
        balance_sheet = None
    try:
        cashflow = ticker.cashflow
    except Exception:
        cashflow = None

    # --- 기본 정보 ---
    current_price = _safe_get(info, "currentPrice") or _safe_get(info, "regularMarketPrice")
    basic_info = {
        "company_name": _safe_get(info, "longName") or _safe_get(info, "shortName", "N/A"),
        "sector": _safe_get(info, "sector", "N/A"),
        "industry": _safe_get(info, "industry", "N/A"),
        "market_cap": _safe_get(info, "marketCap"),
        "current_price": current_price,
        "currency": _safe_get(info, "currency", "USD"),
        "exchange": _safe_get(info, "exchange", "N/A"),
    }

    # --- 수익성 ---
    revenue = _get_latest_value(income_stmt, ["Total Revenue", "Revenue"])
    operating_income = _get_latest_value(income_stmt, ["Operating Income", "EBIT"])
    net_income = _get_latest_value(income_stmt, ["Net Income", "Net Income Common Stockholders"])

    operating_margin = _safe_round(operating_income / revenue * 100) if revenue and operating_income else _safe_round(_safe_get(info, "operatingMargins", None), 2)
    if operating_margin and _safe_get(info, "operatingMargins") and operating_margin == _safe_round(_safe_get(info, "operatingMargins"), 2):
        operating_margin = _safe_round(operating_margin * 100)

    net_margin = _safe_round(net_income / revenue * 100) if revenue and net_income else None

    profitability = {
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "operating_margin_pct": _safe_round(operating_income / revenue * 100) if revenue and operating_income else None,
        "net_margin_pct": net_margin,
        "roe_pct": _safe_round(_safe_get(info, "returnOnEquity", None), 4),
        "roa_pct": _safe_round(_safe_get(info, "returnOnAssets", None), 4),
    }
    # yfinance의 ROE/ROA는 소수 형태 (0.15 = 15%) → 퍼센트로 변환
    if profitability["roe_pct"] is not None and abs(profitability["roe_pct"]) < 10:
        profitability["roe_pct"] = _safe_round(profitability["roe_pct"] * 100)
    if profitability["roa_pct"] is not None and abs(profitability["roa_pct"]) < 10:
        profitability["roa_pct"] = _safe_round(profitability["roa_pct"] * 100)

    # --- 성장성 ---
    prev_revenue = _get_prev_value(income_stmt, ["Total Revenue", "Revenue"])
    prev_net_income = _get_prev_value(income_stmt, ["Net Income", "Net Income Common Stockholders"])

    growth = {
        "revenue_growth_pct": _calc_growth_rate(revenue, prev_revenue),
        "net_income_growth_pct": _calc_growth_rate(net_income, prev_net_income),
        "earnings_growth_pct": _safe_round(_safe_get(info, "earningsGrowth", None), 4),
        "revenue_growth_yf_pct": _safe_round(_safe_get(info, "revenueGrowth", None), 4),
    }
    # 소수 → 퍼센트 변환
    if growth["earnings_growth_pct"] is not None and abs(growth["earnings_growth_pct"]) < 10:
        growth["earnings_growth_pct"] = _safe_round(growth["earnings_growth_pct"] * 100)
    if growth["revenue_growth_yf_pct"] is not None and abs(growth["revenue_growth_yf_pct"]) < 10:
        growth["revenue_growth_yf_pct"] = _safe_round(growth["revenue_growth_yf_pct"] * 100)

    # --- 재무 건전성 ---
    total_debt = _get_latest_value(balance_sheet, ["Total Debt", "Long Term Debt"])
    total_equity = _get_latest_value(balance_sheet, ["Total Stockholder Equity", "Stockholders Equity", "Total Equity Gross Minority Interest"])
    current_assets = _get_latest_value(balance_sheet, ["Current Assets", "Total Current Assets"])
    current_liabilities = _get_latest_value(balance_sheet, ["Current Liabilities", "Total Current Liabilities"])

    debt_to_equity = _safe_round(total_debt / total_equity * 100) if total_debt and total_equity and total_equity != 0 else None
    current_ratio = _safe_round(current_assets / current_liabilities) if current_assets and current_liabilities and current_liabilities != 0 else None

    # 이자보상배율
    interest_expense = _get_latest_value(income_stmt, ["Interest Expense", "Interest Expense Non Operating"])
    ebit = operating_income
    interest_coverage = _safe_round(ebit / abs(interest_expense)) if ebit and interest_expense and interest_expense != 0 else None

    financial_health = {
        "debt_to_equity_pct": debt_to_equity,
        "current_ratio": current_ratio,
        "interest_coverage_ratio": interest_coverage,
        "total_debt": total_debt,
        "total_equity": total_equity,
    }

    # --- 현금흐름 ---
    operating_cf = _get_latest_value(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities"])
    investing_cf = _get_latest_value(cashflow, ["Investing Cash Flow", "Total Cashflows From Investing Activities"])
    financing_cf = _get_latest_value(cashflow, ["Financing Cash Flow", "Total Cash From Financing Activities"])
    capex = _get_latest_value(cashflow, ["Capital Expenditure", "Capital Expenditures"])

    fcf = None
    if operating_cf is not None and capex is not None:
        fcf = operating_cf + capex  # capex는 보통 음수
    elif _safe_get(info, "freeCashflow"):
        fcf = _safe_get(info, "freeCashflow")

    cash_flow = {
        "operating_cf": operating_cf,
        "investing_cf": investing_cf,
        "financing_cf": financing_cf,
        "capex": capex,
        "free_cash_flow": fcf,
    }

    # --- 운전자본 & 재고 분석 ---
    inventory = _get_latest_value(balance_sheet, ["Inventory", "Net Inventory"])
    prev_inventory = _get_prev_value(balance_sheet, ["Inventory", "Net Inventory"])
    receivables = _get_latest_value(balance_sheet, ["Net Receivables", "Accounts Receivable", "Receivables"])
    payables = _get_latest_value(balance_sheet, ["Accounts Payable", "Payables And Accrued Expenses"])

    working_capital = {
        "inventory": inventory,
        "inventory_prev": prev_inventory,
        "inventory_change_pct": _calc_growth_rate(inventory, prev_inventory),
        "receivables": receivables,
        "payables": payables,
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "working_capital": current_assets - current_liabilities if current_assets and current_liabilities else None,
    }

    # --- ROIC ---
    cash = _get_latest_value(balance_sheet, ["Cash And Cash Equivalents", "Cash"])
    tax_rate_val = _safe_get(info, "taxRate")
    if tax_rate_val is None or tax_rate_val == 0:
        tax_expense = _get_latest_value(income_stmt, ["Tax Provision", "Income Tax Expense"])
        pretax_income = _get_latest_value(income_stmt, ["Pretax Income", "Income Before Tax"])
        tax_rate_val = abs(tax_expense / pretax_income) if tax_expense and pretax_income and pretax_income != 0 else 0.21
    elif tax_rate_val > 1:
        tax_rate_val = tax_rate_val / 100

    nopat = operating_income * (1 - tax_rate_val) if operating_income else None
    invested_capital = None
    if total_equity is not None:
        ic = total_equity + (total_debt or 0) - (cash or 0)
        invested_capital = ic if ic > 0 else None
    roic_pct = _safe_round(nopat / invested_capital * 100) if nopat and invested_capital and invested_capital != 0 else None

    roic = {
        "nopat": nopat,
        "invested_capital": invested_capital,
        "roic_pct": roic_pct,
        "tax_rate_used": _safe_round(tax_rate_val, 4),
    }

    # --- 이익의 질 (Earnings Quality) ---
    total_assets_eq = _get_latest_value(balance_sheet, ["Total Assets"])
    fcf_to_net_income = _safe_round(fcf / net_income) if fcf and net_income and net_income != 0 else None
    accruals_ratio = _safe_round((net_income - operating_cf) / total_assets_eq * 100) if net_income and operating_cf and total_assets_eq and total_assets_eq != 0 else None

    earnings_quality = {
        "fcf_to_net_income": fcf_to_net_income,
        "fcf_to_net_income_interpretation": (
            "양호 (현금 전환 우수)" if fcf_to_net_income and fcf_to_net_income >= 1.0
            else "보통" if fcf_to_net_income and fcf_to_net_income >= 0.5
            else "우려 (현금 전환 부족)" if fcf_to_net_income is not None
            else "N/A"
        ),
        "accruals_ratio_pct": accruals_ratio,
        "accruals_interpretation": (
            "양호 (발생액 낮음)" if accruals_ratio is not None and abs(accruals_ratio) < 5
            else "주의 (발생액 보통)" if accruals_ratio is not None and abs(accruals_ratio) < 10
            else "우려 (발생액 높음)" if accruals_ratio is not None
            else "N/A"
        ),
    }

    # --- 밸류에이션 ---
    valuation = {
        "pe_ratio": _safe_round(_safe_get(info, "trailingPE")),
        "forward_pe": _safe_round(_safe_get(info, "forwardPE")),
        "pb_ratio": _safe_round(_safe_get(info, "priceToBook")),
        "ps_ratio": _safe_round(_safe_get(info, "priceToSalesTrailing12Months")),
        "ev_to_ebitda": _safe_round(_safe_get(info, "enterpriseToEbitda")),
        "peg_ratio": _safe_round(_safe_get(info, "pegRatio")),
        "dividend_yield_pct": _safe_round(_safe_get(info, "dividendYield") or 0),
    }

    # --- 분기별 추세 (quarterly_trends) ---
    quarterly_trends = []
    try:
        q_income = ticker.quarterly_income_stmt
        if q_income is not None and not q_income.empty:
            cols = list(q_income.columns)[:8]  # 최근 8분기
            for col in cols:
                q_rev = None
                q_op = None
                q_ni = None
                for name in ["Total Revenue", "Revenue"]:
                    if name in q_income.index and pd.notna(q_income.loc[name, col]):
                        q_rev = float(q_income.loc[name, col])
                        break
                for name in ["Operating Income", "EBIT"]:
                    if name in q_income.index and pd.notna(q_income.loc[name, col]):
                        q_op = float(q_income.loc[name, col])
                        break
                for name in ["Net Income", "Net Income Common Stockholders"]:
                    if name in q_income.index and pd.notna(q_income.loc[name, col]):
                        q_ni = float(q_income.loc[name, col])
                        break

                op_margin = _safe_round(q_op / q_rev * 100) if q_rev and q_op else None
                ni_margin = _safe_round(q_ni / q_rev * 100) if q_rev and q_ni else None

                quarterly_trends.append({
                    "quarter": str(col.date()) if hasattr(col, 'date') else str(col),
                    "revenue": q_rev,
                    "operating_income": q_op,
                    "net_income": q_ni,
                    "operating_margin_pct": op_margin,
                    "net_margin_pct": ni_margin,
                })

            # QoQ/YoY 성장률 계산
            for i, qt in enumerate(quarterly_trends):
                # QoQ (직전 분기 대비)
                if i + 1 < len(quarterly_trends) and quarterly_trends[i + 1]["revenue"]:
                    qt["revenue_qoq_pct"] = _calc_growth_rate(qt["revenue"], quarterly_trends[i + 1]["revenue"])
                # YoY (4분기 전 대비)
                if i + 4 < len(quarterly_trends) and quarterly_trends[i + 4]["revenue"]:
                    qt["revenue_yoy_pct"] = _calc_growth_rate(qt["revenue"], quarterly_trends[i + 4]["revenue"])
    except Exception:
        pass

    # --- DuPont 분해 ---
    dupont = {}
    try:
        roe_val = profitability.get("roe_pct")
        if revenue and net_income and revenue > 0:
            net_profit_margin = net_income / revenue
        else:
            net_profit_margin = None

        total_assets = _get_latest_value(balance_sheet, ["Total Assets"])
        asset_turnover = revenue / total_assets if revenue and total_assets and total_assets > 0 else None
        equity_multiplier = total_assets / total_equity if total_assets and total_equity and total_equity > 0 else None

        dupont = {
            "net_profit_margin_pct": _safe_round(net_profit_margin * 100) if net_profit_margin else None,
            "asset_turnover": _safe_round(asset_turnover),
            "equity_multiplier": _safe_round(equity_multiplier),
            "roe_decomposed_pct": _safe_round(
                net_profit_margin * asset_turnover * equity_multiplier * 100
            ) if net_profit_margin and asset_turnover and equity_multiplier else None,
            "roe_reported_pct": roe_val,
        }
    except Exception:
        pass

    # --- 추가 비율 ---
    quick_ratio = _safe_get(info, "quickRatio")
    ebitda_margins = _safe_get(info, "ebitdaMargins")
    if ebitda_margins and abs(ebitda_margins) < 10:
        ebitda_margins = _safe_round(ebitda_margins * 100)
    else:
        ebitda_margins = _safe_round(ebitda_margins)

    total_assets_val = _get_latest_value(balance_sheet, ["Total Assets"])
    asset_turnover_ratio = _safe_round(revenue / total_assets_val) if revenue and total_assets_val and total_assets_val > 0 else None
    fcf_margin = _safe_round(fcf / revenue * 100) if fcf and revenue and revenue > 0 else None

    additional_ratios = {
        "quick_ratio": _safe_round(quick_ratio),
        "ebitda_margin_pct": ebitda_margins,
        "fcf_margin_pct": fcf_margin,
        "asset_turnover": asset_turnover_ratio,
    }

    # --- 애널리스트 컨센서스 ---
    target_mean = _safe_get(info, "targetMeanPrice")
    target_high = _safe_get(info, "targetHighPrice")
    target_low = _safe_get(info, "targetLowPrice")
    analyst_count = _safe_get(info, "numberOfAnalystOpinions")
    recommendation = _safe_get(info, "recommendationKey")

    analyst_upside = _safe_round((target_mean / current_price - 1) * 100) if target_mean and current_price else None

    analyst_consensus = {
        "target_mean": target_mean,
        "target_high": target_high,
        "target_low": target_low,
        "analyst_count": analyst_count,
        "recommendation": recommendation,
        "upside_pct": analyst_upside,
    }

    return {
        "basic_info": basic_info,
        "profitability": profitability,
        "growth": growth,
        "financial_health": financial_health,
        "cash_flow": cash_flow,
        "working_capital": working_capital,
        "roic": roic,
        "earnings_quality": earnings_quality,
        "valuation": valuation,
        "quarterly_trends": quarterly_trends,
        "dupont": dupont,
        "additional_ratios": additional_ratios,
        "analyst_consensus": analyst_consensus,
    }
