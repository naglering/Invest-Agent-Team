"""크로스에셋 매크로 레짐 대시보드 — '시장 전체가 어떤 경기·정책·유동성 레짐인가'.

yfinance로 국채금리(일드커브)·달러(DXY)·변동성(VIX)·신용(HY/IG 가격비율 프록시)·
원자재(금/유가/구리)·크립토(BTC)·주식(SPY/QQQ)·한국(코스피/원달러)을 수집해
**결정론적** 레짐 분류기(risk_score, 성장x인플레 4분면 quadrant, cycle_stage)를 산출한다.
모든 레짐 라벨은 산출 수치(drivers)에서 재현 가능하다 — LLM 인상비평을 배격한다.

시장가격 기반 크로스에셋(yfinance)에 더해, 연준 **net liquidity = WALCL − TGA − RRP**를
FRED로 직접 산출한다: 환경변수 INVEST_FRED_API_KEY가 있으면 공식 API(JSON·throttle 없음),
없으면 공개 CSV(키 불필요)로 폴백, 둘 다 실패 시 null. 그 외 발표형 지표(Sahm·ISM·LEI·
Core PCE·NY연준 침체확률 등)는 macro-strategist 에이전트가 WebSearch로 보강한다.

신선도 주의: ^TNX 등 금리 인덱스는 spot/futures보다 며칠 지연된다 → 블록별 last_bar 동봉.
프록시 주의: 신용은 FRED HY OAS(BAMLH0A0HYM2)가 1차 — 실패 시에만 HYG/LQD 가격비율 폴백
(듀레이션 미스매치로 금리 방향에 오염될 수 있어 method 라벨로 구분). 인플레축도 FRED
T10YIE(10y 브레이크이븐) 3M 변화가 1차, 실패 시 명목 10y 폴백. 실질금리는 TIP 추세,
10y-2y는 2YY=F 선물 기반이다(모두 method/source 라벨). 의존 심볼 실패 시 null로 degrade한다.

레짐 '전환' 감지: 실행마다 data/macro_snapshots/YYYY-MM-DD.json 스냅샷을 저장하고,
직전(오늘 이전) 스냅샷 대비 regime_change(score_delta·flipped·quadrant 이동)를 출력한다.
직전 스냅샷이 없으면 status="first_run".

INVEST_MACRO_LIVE=0 이면 네트워크를 건너뛰고 well-formed 스켈레톤을 반환한다(오프라인 테스트).
"""

import math
import os
from datetime import date

import yfinance as yf

# sector_scan의 수익률 헬퍼를 재사용(21=1m, 63=3m, 126=6m 거래일). import 실패 시 동일 복제.
try:
    from tools.sector_scan import _ret_pct
except ImportError:  # pragma: no cover - 경로 차이 폴백
    try:
        from sector_scan import _ret_pct
    except ImportError:
        def _ret_pct(series, days):
            if series is None or len(series) <= days:
                return None
            base = float(series.iloc[-1 - days])
            if base == 0:
                return None
            return round((float(series.iloc[-1]) / base - 1) * 100, 2)


# 검증된 yfinance 심볼만 사용(설계 단계에서 가용성 확인). DX=F(404)·^US2Y 등 빈값 심볼은 배제.
SYMBOLS = {
    "ust_3m": "^IRX",      # 13주 T-bill 수익률(%)
    "ust_5y": "^FVX",      # 5년 국채 수익률(%)
    "ust_10y": "^TNX",     # 10년 국채 수익률(%) — 핵심 장기금리
    "ust_30y": "^TYX",     # 30년 국채 수익률(%)
    "ust_2y": "2YY=F",     # 2년 수익률 선물(프록시 — 깔끔한 2y 인덱스가 야후에 없음)
    "dxy": "DX-Y.NYB",     # 달러 인덱스
    "vix": "^VIX",         # 변동성 지수
    "gold": "GC=F",        # 금 선물($/oz)
    "wti": "CL=F",         # WTI 원유 선물($/bbl)
    "copper": "HG=F",      # 구리 선물($/lb)
    "btc": "BTC-USD",      # 비트코인
    "hyg": "HYG",          # 하이일드 회사채 ETF
    "lqd": "LQD",          # 투자등급 회사채 ETF
    "tlt": "TLT",          # 20년+ 국채 ETF(듀레이션/안전자산 레그)
    "spy": "SPY",          # S&P 500
    "qqq": "QQQ",          # 나스닥 100(성장/테크 레그)
    "kospi": "^KS11",      # 코스피
    "usdkrw": "KRW=X",     # 원/달러
    "tip": "TIP",          # TIPS ETF(실질금리 프록시용)
}


# ---------------------------------------------------------------------------
# 작은 헬퍼들 (전부 None-safe)
# ---------------------------------------------------------------------------
def _last(close):
    if close is None or len(close) == 0:
        return None
    return float(close.iloc[-1])


def _val_ago(close, days):
    """days봉 전의 값(없으면 None)."""
    if close is None or len(close) <= days:
        return None
    return float(close.iloc[-1 - days])


def _above_ma(close, n):
    """현재가가 n일 단순이동평균 위인지(데이터 부족 시 None)."""
    if close is None or len(close) < n:
        return None
    return bool(float(close.iloc[-1]) > float(close.tail(n).mean()))


def _delta_bps(close, days):
    """수익률(%) 시계열의 days봉 전 대비 레벨 변화(bps). 금리 인덱스에 사용."""
    prev = _val_ago(close, days)
    if prev is None:
        return None
    return round((float(close.iloc[-1]) - prev) * 100, 1)


def _spread_bps(a, b):
    """두 수익률(%)의 스프레드(bps). 금리는 %이므로 *100."""
    if a is None or b is None:
        return None
    return round((a - b) * 100, 1)


def _ratio_series(num, den):
    """두 가격 시계열의 정렬된 비율 시계열(inf/NaN 제거). 비율 추세·인덱스 산출용."""
    if num is None or den is None:
        return None
    s = (num / den).replace([float("inf"), float("-inf")], float("nan")).dropna()
    return s if len(s) else None


def _round(x, n=2):
    # bool은 int 하위형이라 명시 배제, inf/nan은 비표준 JSON('Infinity'/'NaN')이 되므로 None 처리.
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if not math.isfinite(x):
        return None
    return round(x, n)


def _days_between(a, b):
    """두 'YYYY-MM-DD' 문자열 사이의 일수(파싱 실패 시 None)."""
    try:
        return (date.fromisoformat(a) - date.fromisoformat(b)).days
    except Exception:
        return None


def _http_text(url, timeout=10):
    """URL 본문 텍스트. curl 우선 — Python HTTP 스택이 FRED에 read-hang하고, curl도 stdout
    파이프는 HTTP/2 스트림 에러(92)를 내므로 임시파일(-o)로 받아 읽는다. 모두 실패 시 None.
    (CDN 스로틀 시 HTTP/2 92는 빠르게 실패하므로 retry로 회복하되 전체 지연은 짧게 캡.)"""
    import os
    import subprocess
    import tempfile
    try:
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            p = subprocess.run(
                ["curl", "-sS", "-m", str(timeout),
                 "--retry", "2", "--retry-delay", "1", "--retry-all-errors",  # CDN HTTP/2 간헐 에러 회복
                 "-o", path, "-H", "User-Agent: Mozilla/5.0", url],
                capture_output=True, text=True, timeout=timeout * 2 + 6,
            )
            if p.returncode == 0:
                with open(path, encoding="utf-8") as f:
                    txt = f.read()
                if txt.strip():
                    return txt
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception:
        pass
    try:  # curl 부재 환경 폴백
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


def _fetch_fred_api(series_id, api_key, timeout=10, limit=60):
    """FRED 공식 API(JSON) — INVEST_FRED_API_KEY 있을 때. 최신 limit관측 → 오름차순 [(date, value)]."""
    import json
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
           f"&api_key={api_key}&file_type=json&sort_order=desc&limit={limit}")
    txt = _http_text(url, timeout)
    if not txt:
        return None
    try:
        obs = json.loads(txt).get("observations", [])
    except Exception:
        return None
    pts = []
    for o in obs:
        v = o.get("value")
        if v in (".", "", None):
            continue
        try:
            pts.append((o.get("date"), float(v)))
        except (ValueError, TypeError):
            continue
    pts.sort(key=lambda x: x[0])  # CSV와 동일하게 오름차순
    return pts or None


def _fetch_fred_csv(series_id, timeout=10):
    """FRED 공개 CSV(그래프 엔드포인트, 키 불필요) → [(date, value)]. 실패 시 None."""
    import csv
    import io
    txt = _http_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout)
    if not txt:
        return None
    pts = []
    for row in list(csv.reader(io.StringIO(txt)))[1:]:  # 첫 줄은 헤더
        if len(row) < 2 or row[1] in (".", "", None):
            continue
        try:
            pts.append((row[0], float(row[1])))
        except ValueError:
            continue
    return pts or None


def _fetch_fred(series_id, timeout=10, limit=60):
    """FRED 시계열 [(date, value)] — 공식 API(INVEST_FRED_API_KEY 있으면) → CSV 폴백 → None.

    공식 API는 정본·throttle 사실상 없음(120req/분). 키 미설정/실패 시 공개 CSV로 자동 폴백.
    limit은 API 경로의 최신 관측 수(일간 시계열 3M 비교엔 90 권장) — CSV는 전체 이력 반환.
    """
    key = os.environ.get("INVEST_FRED_API_KEY")
    if key:
        pts = _fetch_fred_api(series_id, key, timeout, limit)
        if pts:
            return pts
    return _fetch_fred_csv(series_id, timeout)


def _fred_level_delta_bps(pts, obs_back=63):
    """일간 FRED %시계열의 (현재 레벨, obs_back관측 전 대비 변화 bps, 최신 날짜).

    pts는 _fetch_fred의 오름차순 [(date, value)]. 이력 부족/None이면 (None, None, None).
    """
    if not pts or len(pts) <= obs_back:
        return None, None, None
    last_d, last_v = pts[-1]
    prev_v = pts[-1 - obs_back][1]
    return last_v, round((last_v - prev_v) * 100.0, 1), last_d


def _net_liquidity(timeout=10):
    """연준 net liquidity = WALCL − TGA(WTREGEN) − RRP(RRPONTSYD), 전부 $bn 환산.

    WALCL·WTREGEN은 millions·주간(수요일), RRPONTSYD는 billions·일간 → 주간 인덱스에 asof(ffill) 정렬.
    risk asset 베타의 1차 드라이버. 실패 시 None(에이전트가 WebSearch로 보강).
    """
    walcl = _fetch_fred("WALCL", timeout)
    tga = _fetch_fred("WTREGEN", timeout)
    rrp = _fetch_fred("RRPONTSYD", timeout)
    if not walcl or not tga or not rrp:
        return None
    import pandas as pd

    def _s(pts):
        return pd.Series([v for _, v in pts], index=pd.to_datetime([d for d, _ in pts]))

    w, t, r = _s(walcl), _s(tga), _s(rrp)
    t_al = t.reindex(w.index, method="ffill")
    r_al = r.reindex(w.index, method="ffill")
    net_bn = ((w / 1000.0) - (t_al / 1000.0) - r_al).dropna()  # millions→bn, rrp는 이미 bn
    if len(net_bn) < 5:
        return None
    net_now = float(net_bn.iloc[-1])
    net_4w = round((net_now / float(net_bn.iloc[-5]) - 1) * 100, 2)
    trend = ("expanding(순풍)" if net_4w > 0.5
             else "contracting(역풍)" if net_4w < -0.5 else "flat")
    return {
        "net_liquidity_usd_tn": round(net_now / 1000.0, 3),
        "walcl_usd_tn": round(float(w.iloc[-1]) / 1e6, 3),
        "tga_usd_bn": round(float(t.iloc[-1]) / 1000.0, 1),
        "rrp_usd_bn": round(float(r.iloc[-1]), 2),
        "net_4w_change_pct": net_4w,
        "trend": trend,
        "last_bar": str(net_bn.index[-1].date()),
        "source": ("FRED " + ("공식 API" if os.environ.get("INVEST_FRED_API_KEY") else "공개 CSV")
                   + " — WALCL−TGA(WTREGEN)−RRP(RRPONTSYD)"),
    }


# 레짐 스냅샷 저장소 — 이 파일: src/tools/macro_data.py → repo 루트 data/macro_snapshots/
_SNAPSHOT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "macro_snapshots")
)


def _load_prev_snapshot(today_str):
    """오늘 이전 날짜의 최신 스냅샷 로드 — 같은 날 재실행은 전일 스냅샷과 비교(멱등).

    손상 파일은 건너뛰고 그 이전 스냅샷을 시도. 없으면 None(first_run).
    """
    import glob
    import json
    try:
        files = sorted(glob.glob(os.path.join(_SNAPSHOT_DIR, "*.json")))
    except Exception:
        return None
    for path in reversed(files):
        name = os.path.splitext(os.path.basename(path))[0]
        if name >= today_str:  # 오늘(또는 미래 오기입) 파일은 비교 대상 제외
            continue
        try:
            with open(path, encoding="utf-8") as f:
                snap = json.load(f)
            if isinstance(snap, dict):
                return snap
        except Exception:
            continue
    return None


def _save_snapshot(today_str, snap):
    """data/macro_snapshots/YYYY-MM-DD.json 저장(같은 날 재실행은 덮어쓰기)."""
    import json
    os.makedirs(_SNAPSHOT_DIR, exist_ok=True)
    with open(os.path.join(_SNAPSHOT_DIR, f"{today_str}.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)


def _skeleton(errors=None, note="네트워크 미사용(INVEST_MACRO_LIVE=0) — 모든 값 null"):
    """오프라인/전면실패 시 반환하는 well-formed 스켈레톤(스키마 키 보존)."""
    return {
        "asof": None,
        "asof_core": None,
        "data_freshness_note": note,
        "rates": {"ust_3m_pct": None, "ust_5y_pct": None, "ust_10y_pct": None,
                  "ust_30y_pct": None, "ust_2y_pct_proxy": None,
                  "ust_2y_source": "2YY=F_futures", "last_bar": None},
        "curve": {"spread_10y_3m_bps": None, "spread_10y_5y_bps": None,
                  "spread_30y_5y_bps": None, "spread_10y_2y_bps_proxy": None,
                  "inverted": None, "shape": None, "direction_1m": None,
                  "stale_days": None, "stale": None, "read": None},
        "liquidity": None,
        "fx": {"dxy_level": None, "dxy_trend_1m_pct": None, "dxy_trend_3m_pct": None,
               "above_50ma": None, "above_200ma": None, "usdkrw": None,
               "usdkrw_trend_3m_pct": None, "korea_spillover": None, "rating": None},
        "vol": {"vix": None, "vix_1m_change_pct": None, "regime": None,
                "bands": "<15 complacent / 15-20 normal / 20-30 elevated / >30 stress"},
        "credit": {"hy_oas_pct": None, "hy_oas_delta_3m_bps": None, "hy_oas_last_bar": None,
                   "hyg": None, "lqd": None, "tlt": None, "hyg_lqd_ratio": None,
                   "hyg_lqd_trend_3m_pct": None, "hyg_tlt_ratio": None,
                   "hyg_tlt_trend_3m_pct": None, "spread_signal": None,
                   "method": None, "read": None},
        "commodities": {"gold": None, "wti": None, "copper": None,
                        "copper_gold_index": None, "copper_gold_trend_3m_pct": None,
                        "wti_trend_3m_pct": None, "copper_trend_3m_pct": None,
                        "growth_signal": None},
        "real_yield": None,
        "crypto": {"btc_usd": None, "btc_trend_3m_pct": None, "risk_appetite_signal": None},
        "equity": {"spy": None, "qqq": None, "spy_above_200ma": None,
                   "qqq_spy_ratio": None, "qqq_spy_trend_3m_pct": None, "growth_tilt": None},
        "regime": {"risk_appetite": "UNKNOWN", "risk_score": None, "quadrant": None,
                   "growth_axis": None, "inflation_axis": None,
                   "inflation_axis_method": None, "breakeven_10y_pct": None,
                   "breakeven_10y_delta_3m_bps": None, "breakeven_10y_last_bar": None,
                   "cycle_stage": None, "drivers": [], "degraded": True,
                   "missing_inputs": ["all (offline/failed)"]},
        "regime_change": None,
        "rating_rule": (
            "risk_score: VIX밴드·신용 3M(HY OAS 우선, 폴백 HYG/LQD)·구리금 3M·DXY 3M·SPY 이평·"
            "QQQ/SPY 3M·net liquidity 4주·VIX급등 가산 후 [-5,+5] clamp "
            "→ >=+3 RISK-ON / <=-3 RISK-OFF / else NEUTRAL. "
            "quadrant: 성장축(구리금·곡선·SPY200ma) x 인플레축(T10YIE 3M ±15bp·유가, 폴백 명목10y ±25bp). "
            "축 0 조합: growth=+1 → EXPANSION/GOLDILOCKS-LEAN, growth=-1 → SLOWDOWN-LEAN."
        ),
        "errors": errors or [{"symbol": "*", "error": "offline skeleton"}],
    }


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------
def macro_dashboard(period: str = "1y") -> dict:
    """크로스에셋 레짐 대시보드를 산출한다(JSON-able dict)."""
    if os.environ.get("INVEST_MACRO_LIVE") == "0":
        return _skeleton()

    errors = []
    data = {}        # key -> Close Series
    last_bars = {}   # key -> 'YYYY-MM-DD'

    for key, sym in SYMBOLS.items():
        try:
            df = yf.Ticker(sym).history(period=period)
            if df.empty or "Close" not in df:
                errors.append({"symbol": sym, "error": "데이터 없음"})
                continue
            close = df["Close"].dropna()
            if len(close) < 2:
                errors.append({"symbol": sym, "error": "이력 부족"})
                continue
            data[key] = close
            last_bars[key] = str(close.index[-1].date())
        except Exception as e:  # noqa: BLE001 - 심볼당 격리(전체 죽지 않게)
            errors.append({"symbol": sym, "error": str(e)})

    if not data:  # 전면 네트워크 실패
        return _skeleton(errors=errors, note="모든 심볼 수집 실패 — 네트워크/yfinance 확인")

    # 연준 net liquidity (FRED, best-effort). 실패해도 가격 코어는 유지 — degraded 불변, errors에만 기록.
    liquidity = None
    if os.environ.get("INVEST_MACRO_FRED") != "0":
        try:
            liquidity = _net_liquidity()
            if liquidity is None:
                errors.append({"symbol": "FRED",
                               "error": "net liquidity 수집 실패(curl/네트워크) — 에이전트 WebSearch 보강 권장"})
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": "FRED", "error": str(e)})

    # FRED 보강 시계열(키리스) — HY OAS(신용 1차)·T10YIE 브레이크이븐(인플레축 1차).
    # 실패해도 각자 가격 프록시로 폴백(method 라벨 구분) — degraded 불변, errors에만 기록.
    hy_oas_pct = hy_oas_d3m = None
    hy_oas_bar = None
    t10yie_pct = t10yie_d3m = None
    t10yie_bar = None
    if os.environ.get("INVEST_MACRO_FRED") != "0":
        try:
            hy_oas_pct, hy_oas_d3m, hy_oas_bar = _fred_level_delta_bps(
                _fetch_fred("BAMLH0A0HYM2", limit=90))
            if hy_oas_d3m is None:
                errors.append({"symbol": "FRED:BAMLH0A0HYM2",
                               "error": "HY OAS 수집 실패 — HYG/LQD 가격비율 폴백"})
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": "FRED:BAMLH0A0HYM2", "error": str(e)})
        try:
            t10yie_pct, t10yie_d3m, t10yie_bar = _fred_level_delta_bps(
                _fetch_fred("T10YIE", limit=90))
            if t10yie_d3m is None:
                errors.append({"symbol": "FRED:T10YIE",
                               "error": "브레이크이븐 수집 실패 — 인플레축 명목 10y 폴백"})
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": "FRED:T10YIE", "error": str(e)})

    g = data.get  # 시계열 게터

    # --- rates ---------------------------------------------------------------
    ust_3m, ust_5y = _last(g("ust_3m")), _last(g("ust_5y"))
    ust_10y, ust_30y = _last(g("ust_10y")), _last(g("ust_30y"))
    ust_2y = _last(g("ust_2y"))
    rates_last_bar = last_bars.get("ust_10y") or last_bars.get("ust_3m")

    # --- curve ---------------------------------------------------------------
    sp_10y_3m = _spread_bps(ust_10y, ust_3m)
    sp_10y_5y = _spread_bps(ust_10y, ust_5y)
    sp_30y_5y = _spread_bps(ust_30y, ust_5y)
    sp_10y_2y = _spread_bps(ust_10y, ust_2y)  # 프록시(2YY=F 실패 시 None)

    tnx, irx = g("ust_10y"), g("ust_3m")
    sp_now = sp_10y_3m
    sp_1m_ago = None
    sp_3m_ago = None
    if tnx is not None and irx is not None:
        t1, i1 = _val_ago(tnx, 21), _val_ago(irx, 21)
        if t1 is not None and i1 is not None:
            sp_1m_ago = round((t1 - i1) * 100, 1)
        t3, i3 = _val_ago(tnx, 63), _val_ago(irx, 63)
        if t3 is not None and i3 is not None:
            sp_3m_ago = round((t3 - i3) * 100, 1)

    inverted = (sp_now < 0) if sp_now is not None else None
    if sp_now is None:
        shape = None
    elif sp_now < -25:
        shape = "strongly_inverted"
    elif sp_now <= 25:
        shape = "flat"
    elif sp_now <= 100:
        shape = "normal"
    else:
        shape = "steep"

    direction_1m = None
    if sp_now is not None and sp_1m_ago is not None:
        if sp_now - sp_1m_ago > 2:
            direction_1m = "steepening"
        elif sp_now - sp_1m_ago < -2:
            direction_1m = "flattening"
        else:
            direction_1m = "flat"

    irx_d1, tnx_d1 = _delta_bps(irx, 21), _delta_bps(tnx, 21)
    bull_steepen = bool(
        direction_1m == "steepening" and irx_d1 is not None and tnx_d1 is not None
        and irx_d1 < 0 and irx_d1 < tnx_d1
    )
    bear_steepen = bool(
        direction_1m == "steepening" and irx_d1 is not None and tnx_d1 is not None
        and tnx_d1 > 0 and tnx_d1 > irx_d1
    )
    shape_kr = {"strongly_inverted": "강역전", "flat": "평탄",
                "normal": "정상", "steep": "가파름"}.get(shape)
    if direction_1m == "steepening":
        steep_kr = ("bull steepening(단기금리 선행 하락)" if bull_steepen
                    else "bear steepening(장기금리 선행 상승)" if bear_steepen else "스티프닝")
    elif direction_1m == "flattening":
        steep_kr = "플래트닝"
    else:
        steep_kr = "방향 미미"
    curve_read = (f"{shape_kr}; {steep_kr}" if shape_kr else None)

    # --- fx ------------------------------------------------------------------
    dxy = _last(g("dxy"))
    dxy_1m, dxy_3m = _ret_pct(g("dxy"), 21), _ret_pct(g("dxy"), 63)
    dxy_50, dxy_200 = _above_ma(g("dxy"), 50), _above_ma(g("dxy"), 200)
    usdkrw = _last(g("usdkrw"))
    usdkrw_3m = _ret_pct(g("usdkrw"), 63)
    if dxy_3m is not None and usdkrw_3m is not None:
        if dxy_3m < -1 and usdkrw_3m > 1:
            korea_spillover = "DXY 하락에도 원화 약세 — 한국 특이 압력(외국인 수급·반도체 사이클 점검)"
        elif dxy_3m > 1 and usdkrw_3m > 1:
            korea_spillover = "달러 강세發 원화 약세 — 글로벌 유동성 긴축 동조"
        else:
            korea_spillover = "원/달러와 DXY 방향 정합 — 한국 특이 압력 제한적"
    else:
        korea_spillover = None
    if dxy_3m is None:
        fx_rating = None
    elif dxy_3m > 3 and dxy_50:
        fx_rating = "🔴 USD 강세(리스크자산 역풍)"
    elif dxy_3m < -3 and dxy_50 is False:
        fx_rating = "🟢 USD 약세(리스크자산 순풍)"
    else:
        fx_rating = "🟡 중립"

    # --- vol -----------------------------------------------------------------
    vix = _last(g("vix"))
    vix_1m = _ret_pct(g("vix"), 21)
    if vix is None:
        vix_regime = None
    elif vix < 15:
        vix_regime = "complacent"
    elif vix <= 20:
        vix_regime = "normal"
    elif vix <= 30:
        vix_regime = "elevated"
    else:
        vix_regime = "stress"

    # --- credit (FRED HY OAS 1차, HYG/LQD 가격비율 폴백) -----------------------
    # HYG(~3.5y) vs LQD(~8.5y) 듀레이션 미스매치 — 금리 하락기에 스프레드 불변에도
    # '와이드닝' 역발화하므로 실제 OAS(BAMLH0A0HYM2)를 1차 신호로 쓴다(3M ±30bp 문턱).
    hyg, lqd, tlt = _last(g("hyg")), _last(g("lqd")), _last(g("tlt"))
    hyg_lqd_s = _ratio_series(g("hyg"), g("lqd"))
    hyg_tlt_s = _ratio_series(g("hyg"), g("tlt"))
    hyg_lqd_ratio = _last(hyg_lqd_s)
    hyg_tlt_ratio = _last(hyg_tlt_s)
    hyg_lqd_3m = _ret_pct(hyg_lqd_s, 63)
    hyg_tlt_3m = _ret_pct(hyg_tlt_s, 63)
    if hy_oas_d3m is not None:
        credit_method = "FRED HY OAS(BAMLH0A0HYM2) 레벨·3M 변화 — 듀레이션 미스매치 없음"
        if hy_oas_d3m > 30:
            spread_signal = "widening(위험회피)"
        elif hy_oas_d3m < -30:
            spread_signal = "tightening(위험선호)"
        else:
            spread_signal = "neutral"
        credit_read = (f"HY OAS {hy_oas_pct:.2f}% (3M {hy_oas_d3m:+.0f}bp) → {spread_signal}"
                       + (" — 레벨 경계(≥5%)" if hy_oas_pct >= 5 else ""))
    elif hyg_lqd_3m is not None:
        credit_method = ("proxy(HYG/LQD 가격비율, OAS 아님 — FRED 실패 폴백; "
                         "듀레이션 미스매치로 금리 방향에 오염될 수 있음)")
        if hyg_lqd_3m > 1:
            spread_signal = "tightening(위험선호)"
        elif hyg_lqd_3m < -1:
            spread_signal = "widening(위험회피)"
        else:
            spread_signal = "neutral"
        credit_read = f"HY/IG 3M {hyg_lqd_3m}% → {spread_signal} (가격비율 프록시)"
    else:
        credit_method = "N/A(FRED OAS·가격비율 프록시 모두 실패)"
        spread_signal = None
        credit_read = None

    # --- commodities ---------------------------------------------------------
    gold, wti, copper = _last(g("gold")), _last(g("wti")), _last(g("copper"))
    cg_s = _ratio_series(g("copper"), g("gold"))
    cg_index = None
    if cg_s is not None and len(cg_s) >= 200:  # 252일 평균 기준선 — 짧은 이력은 오도성이라 생략
        base = float(cg_s.tail(252).mean())
        if base:
            cg_index = round(float(cg_s.iloc[-1]) / base * 100, 1)
    cg_3m = _ret_pct(cg_s, 63)
    wti_3m = _ret_pct(g("wti"), 63)
    copper_3m = _ret_pct(g("copper"), 63)
    if cg_3m is None:
        growth_signal = None
    elif cg_3m > 5:
        growth_signal = "growth-on(시클리컬)"
    elif cg_3m < -5:
        growth_signal = "growth-off(디펜시브)"
    else:
        growth_signal = "neutral"

    # --- real yield (프록시) -------------------------------------------------
    tip_3m = _ret_pct(g("tip"), 63)
    if tip_3m is None:
        real_yield = None
    else:
        if tip_3m < -3:
            ry_dir = "real_yields_rising(금/듀레이션 역풍)"
        elif tip_3m > 3:
            ry_dir = "real_yields_falling(금/듀레이션 순풍)"
        else:
            ry_dir = "flat"
        real_yield = {"method": "proxy(TIP 추세)", "tip_trend_3m_pct": tip_3m,
                      "direction": ry_dir,
                      "note": "true TIPS-implied real yield 아님 — 방향성만 참고"}

    # --- crypto --------------------------------------------------------------
    btc = _last(g("btc"))
    btc_3m = _ret_pct(g("btc"), 63)
    if btc_3m is None:
        btc_signal = None
    elif btc_3m > 5:
        btc_signal = "on"
    elif btc_3m < -5:
        btc_signal = "off"
    else:
        btc_signal = "neutral"

    # --- equity --------------------------------------------------------------
    spy, qqq = _last(g("spy")), _last(g("qqq"))
    spy_50, spy_200 = _above_ma(g("spy"), 50), _above_ma(g("spy"), 200)
    qqq_spy_s = _ratio_series(g("qqq"), g("spy"))
    qqq_spy_ratio = _last(qqq_spy_s)
    qqq_spy_3m = _ret_pct(qqq_spy_s, 63)
    if qqq_spy_3m is None:
        growth_tilt = None
    elif qqq_spy_3m > 2:
        growth_tilt = "growth_leading"
    elif qqq_spy_3m < -2:
        growth_tilt = "value_defensive_leading"
    else:
        growth_tilt = "neutral"

    # --- 결정론적 레짐 분류기 -------------------------------------------------
    drivers = []
    missing = []
    score = 0

    if vix is not None:
        if vix < 15:
            score += 1; drivers.append(f"VIX {vix:.2f} 안주(<15) → +1")
        elif vix <= 20:
            score += 1; drivers.append(f"VIX {vix:.2f} 정상(15-20) → +1")
        elif vix <= 30:
            score -= 1; drivers.append(f"VIX {vix:.2f} 경계(20-30) → -1")
        else:
            score -= 2; drivers.append(f"VIX {vix:.2f} 스트레스(>30) → -2")
    else:
        missing.append("vix")

    if spread_signal is not None:
        credit_txt = (f"HY OAS 3M {hy_oas_d3m:+.0f}bp" if hy_oas_d3m is not None
                      else f"HYG/LQD 3M {hyg_lqd_3m:+}%(프록시)")
        if spread_signal.startswith("tightening"):
            score += 1; drivers.append(f"신용 {credit_txt} 타이트닝 → +1")
        elif spread_signal.startswith("widening"):
            score -= 1; drivers.append(f"신용 {credit_txt} 와이드닝 → -1")
        else:
            drivers.append(f"신용 {credit_txt} 중립 → 0")
    else:
        missing.append("hy_ig_credit")

    if cg_3m is not None:
        if cg_3m > 5:
            score += 1; drivers.append(f"구리/금 3M +{cg_3m}% growth-on → +1")
        elif cg_3m < -5:
            score -= 1; drivers.append(f"구리/금 3M {cg_3m}% growth-off → -1")
        else:
            drivers.append(f"구리/금 3M {cg_3m}% 중립 → 0")
    else:
        missing.append("copper_gold")

    if dxy_3m is not None:
        if dxy_3m < -3:
            score += 1; drivers.append(f"DXY 3M {dxy_3m}% 약세(순풍) → +1")
        elif dxy_3m > 3:
            score -= 1; drivers.append(f"DXY 3M +{dxy_3m}% 강세(역풍) → -1")
        else:
            drivers.append(f"DXY 3M {dxy_3m}% 중립 → 0")
    else:
        missing.append("dxy")

    if spy_200 is not None:
        if spy_50 and spy_200:
            score += 1; drivers.append("SPY 50·200일선 상회 → +1")
        elif spy_200 is False:
            score -= 1; drivers.append("SPY 200일선 하회 → -1")
        else:
            drivers.append("SPY 이평 혼조 → 0")
    else:
        missing.append("spy_ma")

    if qqq_spy_3m is not None:
        if qqq_spy_3m > 2:
            score += 1; drivers.append(f"QQQ/SPY 3M +{qqq_spy_3m}% 성장주도 → +1")
        else:
            drivers.append(f"QQQ/SPY 3M {qqq_spy_3m}% → 0")
    else:
        missing.append("qqq_spy")

    if vix_1m is not None and vix_1m > 50:
        score -= 1; drivers.append(f"VIX 1M +{vix_1m}% 급등 → -1")

    net_liq_4w = liquidity["net_4w_change_pct"] if liquidity else None
    if net_liq_4w is not None:
        if net_liq_4w > 0.5:
            score += 1; drivers.append(f"net liquidity 4주 +{net_liq_4w}% 순풍 → +1")
        elif net_liq_4w < -0.5:
            score -= 1; drivers.append(f"net liquidity 4주 {net_liq_4w}% 역풍 → -1")
        else:
            drivers.append(f"net liquidity 4주 {net_liq_4w}% 중립 → 0")

    score = max(-5, min(5, score))  # 광고 범위 [-5,+5]로 clamp (라벨 컷오프 ±3엔 무영향)

    if score >= 3:
        risk_appetite = "RISK-ON"
    elif score <= -3:
        risk_appetite = "RISK-OFF"
    else:
        risk_appetite = "NEUTRAL/MIXED"

    # 성장축 / 인플레축
    growth_axis = 0
    if (cg_3m is not None and cg_3m > 5) or bull_steepen or (spy_200 is True):
        growth_axis = 1
    elif (cg_3m is not None and cg_3m < -5) or (inverted is True and direction_1m == "flattening"):
        growth_axis = -1

    # 인플레축 1차 = FRED T10YIE(브레이크이븐) 3M ±15bp — 명목금리는 실질금리·텀프리미엄
    # 상승(성장 신호)에 오염되므로 폴백 전용(±25bp). 구리는 성장축(구리/금)과 중복 점화라 제외.
    tnx_3m_delta = _delta_bps(tnx, 63)
    inflation_axis = 0
    if t10yie_d3m is not None:
        infl_method = "FRED T10YIE 브레이크이븐 3M ±15bp (+유가 3M ±10%)"
        if t10yie_d3m > 15 or (wti_3m is not None and wti_3m > 10):
            inflation_axis = 1
        elif t10yie_d3m < -15 or (wti_3m is not None and wti_3m < -10):  # 상방과 대칭
            inflation_axis = -1
    else:
        infl_method = "명목 10y 3M ±25bp (+유가 3M ±10%) — T10YIE 수집 실패 폴백(실질금리 오염 유의)"
        if ((tnx_3m_delta is not None and tnx_3m_delta > 25)
                or (wti_3m is not None and wti_3m > 10)):
            inflation_axis = 1
        elif ((tnx_3m_delta is not None and tnx_3m_delta < -25)
              or (wti_3m is not None and wti_3m < -10)):  # 상방과 대칭
            inflation_axis = -1

    if growth_axis >= 1 and inflation_axis >= 1:
        quadrant = "REFLATION / OVERHEAT (리플레이션)"
    elif growth_axis >= 1 and inflation_axis <= -1:
        quadrant = "GOLDILOCKS / DISINFLATIONARY GROWTH (골디락스)"
    elif growth_axis >= 1:  # 인플레 보합 — 강세장 최빈 셀(구 TRANSITION 오라벨 방지)
        quadrant = "EXPANSION / GOLDILOCKS-LEAN (성장 확장·인플레 안정)"
    elif growth_axis <= -1 and inflation_axis >= 1:
        quadrant = "STAGFLATION RISK (스태그플레이션)"
    elif growth_axis <= -1 and inflation_axis <= -1:
        quadrant = "DEFLATION / SLOWDOWN (디플레이션·둔화)"
    elif growth_axis <= -1:  # 인플레 보합 둔화
        quadrant = "SLOWDOWN-LEAN (둔화 진행·인플레 안정)"
    else:
        quadrant = "TRANSITION / UNCLEAR (전환·불명확)"
    infl_src = (f"T10YIE 3M {t10yie_d3m:+.0f}bp" if t10yie_d3m is not None
                else f"명목10y 3M {tnx_3m_delta:+.0f}bp 폴백" if tnx_3m_delta is not None
                else "인플레 입력 결측")
    drivers.append(f"growth_axis={growth_axis}, inflation_axis={inflation_axis}({infl_src}) → {quadrant}")

    irx_3m_delta = _delta_bps(irx, 63)
    was_inv_now_pos = (sp_3m_ago is not None and sp_now is not None
                       and sp_3m_ago < 0 and sp_now > 0)
    if inverted is True and direction_1m != "steepening":
        cycle_stage = "LATE CYCLE (curve inverted)"
    elif was_inv_now_pos and irx_3m_delta is not None and irx_3m_delta < 0:
        cycle_stage = "EARLY CYCLE / EASING PIVOT"
    elif sp_now is not None and sp_now > 25 and inflation_axis >= 0:  # 무인플레 확장도 MID CYCLE
        cycle_stage = "MID CYCLE / EXPANSION"
    else:
        cycle_stage = "TRANSITION / UNCLEAR"

    if sp_now is None:  # 금리 피드(^TNX/^IRX) 전면 실패 → 곡선·인플레축·cycle_stage 모두 degrade
        missing.append("rates_curve")
    degraded = len(missing) > 0

    asof = max(last_bars.values()) if last_bars else None
    # 핵심 미국 리스크 신호만의 asof — BTC(주말봉)·코스피(상이 캘린더) 편향 제거
    core_keys = ("spy", "qqq", "vix", "hyg", "lqd", "tlt", "ust_10y")
    core_bars = [last_bars[k] for k in core_keys if k in last_bars]
    asof_core = max(core_bars) if core_bars else None
    rates_stale_days = (_days_between(asof_core or asof, rates_last_bar)
                        if rates_last_bar else None)
    rates_stale = bool(rates_stale_days is not None and rates_stale_days > 3)
    curve_read_out = curve_read
    if rates_stale and curve_read_out:
        curve_read_out = f"{curve_read_out} (금리 {rates_stale_days}일 지연 — 곡선 해석 유의)"

    # --- 레짐 스냅샷 이력 + 전환 감지 --------------------------------------
    # 알파는 레짐 '레벨'이 아니라 '전환'(score 부호 전환·분면 이동)에서 나온다 —
    # 실행마다 스냅샷을 저장하고 직전(오늘 이전) 스냅샷과 결정론적으로 비교한다.
    today_str = str(date.today())
    regime_change = {
        "status": "first_run", "prev_date": None, "days_since_prev": None,
        "score_prev": None, "score_delta": None,
        "risk_appetite_prev": None, "flipped": None,
        "quadrant_prev": None, "quadrant_now": quadrant, "quadrant_moved": None,
    }
    try:
        prev = _load_prev_snapshot(today_str)
        if prev:
            score_prev = prev.get("risk_score")
            appetite_prev = prev.get("risk_appetite")
            quadrant_prev = prev.get("quadrant")
            regime_change = {
                "status": "compared",
                "prev_date": prev.get("date"),
                "days_since_prev": _days_between(today_str, prev.get("date") or ""),
                "score_prev": score_prev,
                "score_delta": (round(score - score_prev, 2)
                                if isinstance(score_prev, (int, float))
                                and not isinstance(score_prev, bool) else None),
                "risk_appetite_prev": appetite_prev,
                "flipped": (bool(appetite_prev != risk_appetite)
                            if appetite_prev else None),  # RISK-ON/OFF/NEUTRAL 라벨 전환
                "quadrant_prev": quadrant_prev,
                "quadrant_now": quadrant,
                "quadrant_moved": (bool(quadrant_prev != quadrant)
                                   if quadrant_prev else None),
            }
        _save_snapshot(today_str, {
            "date": today_str, "asof_core": asof_core,
            "risk_score": score, "risk_appetite": risk_appetite,
            "quadrant": quadrant, "cycle_stage": cycle_stage,
            "growth_axis": growth_axis, "inflation_axis": inflation_axis,
            "drivers": drivers,
        })
    except Exception as e:  # noqa: BLE001 - 스냅샷 IO 실패가 대시보드를 죽이면 안 됨
        errors.append({"symbol": "SNAPSHOT", "error": str(e)})

    return {
        "asof": asof,
        "asof_core": asof_core,
        "data_freshness_note": (
            "금리 인덱스(^TNX·^IRX 등)는 spot/futures보다 며칠 지연될 수 있음 — "
            "rates.last_bar·curve.stale_days를 확인하고 곡선 해석 시 유의. "
            "asof는 BTC(주말)·코스피 포함 최신봉, asof_core는 미국 리스크 신호 기준."
        ),
        "rates": {
            "ust_3m_pct": _round(ust_3m, 3), "ust_5y_pct": _round(ust_5y, 3),
            "ust_10y_pct": _round(ust_10y, 3), "ust_30y_pct": _round(ust_30y, 3),
            "ust_2y_pct_proxy": _round(ust_2y, 3), "ust_2y_source": "2YY=F_futures",
            "last_bar": rates_last_bar,
        },
        "curve": {
            "spread_10y_3m_bps": sp_10y_3m, "spread_10y_5y_bps": sp_10y_5y,
            "spread_30y_5y_bps": sp_30y_5y, "spread_10y_2y_bps_proxy": sp_10y_2y,
            "inverted": inverted, "shape": shape, "direction_1m": direction_1m,
            "stale_days": rates_stale_days, "stale": rates_stale,
            "read": curve_read_out,
        },
        "liquidity": liquidity,
        "fx": {
            "dxy_level": _round(dxy, 3), "dxy_trend_1m_pct": dxy_1m,
            "dxy_trend_3m_pct": dxy_3m, "above_50ma": dxy_50, "above_200ma": dxy_200,
            "usdkrw": _round(usdkrw, 2), "usdkrw_trend_3m_pct": usdkrw_3m,
            "korea_spillover": korea_spillover, "rating": fx_rating,
        },
        "vol": {
            "vix": _round(vix, 2), "vix_1m_change_pct": vix_1m, "regime": vix_regime,
            "bands": "<15 complacent / 15-20 normal / 20-30 elevated / >30 stress",
        },
        "credit": {
            "hy_oas_pct": _round(hy_oas_pct, 2), "hy_oas_delta_3m_bps": hy_oas_d3m,
            "hy_oas_last_bar": hy_oas_bar,
            "hyg": _round(hyg, 2), "lqd": _round(lqd, 2), "tlt": _round(tlt, 2),
            "hyg_lqd_ratio": _round(hyg_lqd_ratio, 4), "hyg_lqd_trend_3m_pct": hyg_lqd_3m,
            "hyg_tlt_ratio": _round(hyg_tlt_ratio, 4), "hyg_tlt_trend_3m_pct": hyg_tlt_3m,
            "spread_signal": spread_signal, "method": credit_method,
            "read": credit_read,
        },
        "commodities": {
            "gold": _round(gold, 2), "wti": _round(wti, 2), "copper": _round(copper, 4),
            "copper_gold_index": cg_index, "copper_gold_trend_3m_pct": cg_3m,
            "wti_trend_3m_pct": wti_3m, "copper_trend_3m_pct": copper_3m,
            "growth_signal": growth_signal,
        },
        "real_yield": real_yield,
        "crypto": {
            "btc_usd": _round(btc, 2), "btc_trend_3m_pct": btc_3m,
            "risk_appetite_signal": btc_signal,
        },
        "equity": {
            "spy": _round(spy, 2), "qqq": _round(qqq, 2), "spy_above_200ma": spy_200,
            "qqq_spy_ratio": _round(qqq_spy_ratio, 4), "qqq_spy_trend_3m_pct": qqq_spy_3m,
            "growth_tilt": growth_tilt,
        },
        "regime": {
            "risk_appetite": risk_appetite, "risk_score": score, "quadrant": quadrant,
            "growth_axis": growth_axis, "inflation_axis": inflation_axis,
            "inflation_axis_method": infl_method,
            "breakeven_10y_pct": _round(t10yie_pct, 2),
            "breakeven_10y_delta_3m_bps": t10yie_d3m,
            "breakeven_10y_last_bar": t10yie_bar,
            "cycle_stage": cycle_stage, "drivers": drivers, "degraded": degraded,
            "missing_inputs": missing,
        },
        "regime_change": regime_change,
        "rating_rule": (
            "risk_score: VIX밴드(+1/-1/-2)·신용 3M(±1: HY OAS ±30bp 우선, 폴백 HYG/LQD ±1%)·"
            "구리금 3M(±1)·DXY 3M(±1)·SPY 50/200이평(±1)·QQQ/SPY 3M(+1)·"
            "net liquidity 4주(±1)·VIX 1M급등(-1) "
            "가산 후 [-5,+5] clamp → >=+3 RISK-ON / <=-3 RISK-OFF / else NEUTRAL. "
            "quadrant: 성장축(구리금 3M·bull스티프닝·SPY200ma) x "
            "인플레축(T10YIE 브레이크이븐 3M ±15bp·유가 3M ±10%, 폴백 명목10y ±25bp — 구리 제외). "
            "축 0 조합: growth=+1 → EXPANSION/GOLDILOCKS-LEAN, growth=-1 → SLOWDOWN-LEAN. "
            "모든 라벨은 drivers 수치로 재현 가능 — 인상비평 배격."
        ),
        "errors": errors,
    }
