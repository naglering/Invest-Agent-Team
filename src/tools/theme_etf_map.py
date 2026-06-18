"""테마/섹터 ETF 매핑 — 자금흐름·섹터로테이션·자동 mandate 선택의 공용 지식 베이스.

- SECTOR_ETF_MAP: 전통 GICS 11개 섹터 → 대표 ETF (베타/상관 계산용, 하위호환)
- THEME_ETF_MAP: 메가트렌드 테마 → ETF 바스켓 + 키워드 + 대표 종목

메가트렌드 투자자는 "지금 자금이 어디로 몰리는가"를 먼저 본다. 이 모듈이 그 측정의 기반이다.
"""

# 전통 GICS 섹터 ETF (risk_analyzer 하위호환 — 베타/상관 벤치마크)
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

# 메가트렌드 테마 — 자금이 몰리는 섹터를 식별·랭킹하고 그 안의 강한 종목을 발굴하기 위한 맵.
# etfs[0]를 대표 ETF(자금흐름 프록시)로 사용.
#
# 멤버십(자동 mandate 선정·피어 발굴)은 정적 reps만 보지 않고 동적으로 해석된다:
#   theme_members = (ETF 실제 top holdings  ∪  reps)  −  exclude
#   - reps    : 수동 시드(must-include). ETF top10에 못 드는 핵심주(WDC 등)·확정 종목.
#   - exclude : 수동 차단(blocklist). ETF holdings로 딸려오지만 megatrend 성격이 아닌 종목.
#   - etfs    : 라이브 holdings 소스(yfinance, 디스크 캐시 TTL 7일). 오프라인/실패 시 reps로 폴백.
THEME_ETF_MAP = {
    "AI/반도체": {
        "etfs": ["SMH", "SOXX", "BOTZ"],
        "keywords": ["artificial intelligence", "semiconductor", "gpu", "accelerator", "data center", "ai "],
        # AI 메모리/스토리지 슈퍼사이클(니어라인 HDD·NAND·HBM) — 회사명에 키워드가 없어
        # 자동 매칭에서 누락되던 데이터센터 수혜주를 reps에 명시 추가: WDC·STX·SNDK.
        "reps": ["NVDA", "AMD", "AVGO", "TSM", "ARM", "MU", "MRVL", "SMCI", "PLTR", "ASML", "LRCX", "AMAT",
                 "WDC", "STX", "SNDK"],
    },
    "원자력/SMR/우라늄": {
        "etfs": ["URA", "URNM", "NLR"],
        "keywords": ["nuclear", "uranium", "smr", "small modular reactor", "enrichment"],
        "reps": ["OKLO", "SMR", "NNE", "BWXT", "CEG", "VST", "GEV", "LEU", "CCJ", "UEC", "NRG"],
    },
    "우주": {
        "etfs": ["ARKX", "UFO"],
        "keywords": ["space", "satellite", "launch", "rocket", "orbital"],
        "reps": ["RKLB", "LUNR", "RDW", "ASTS", "PL", "SPCX", "KTOS"],
    },
    "양자컴퓨팅": {
        "etfs": ["QTUM"],
        "keywords": ["quantum computing", "quantum"],
        "reps": ["IONQ", "RGTI", "QBTS", "QUBT"],
    },
    "방산": {
        "etfs": ["ITA", "PPA", "SHLD"],
        "keywords": ["defense", "aerospace", "military", "missile", "munition"],
        # 고베타 모멘텀주만 megatrend 자동선정 대상으로 남김.
        "reps": ["KTOS", "AVAV"],
        # 성숙 US 메가-prime은 저성장·저멀티플 방어주라 aggressive megatrend mandate와 불일치.
        # ITA/PPA/SHLD holdings로 딸려오지만 차단 → default(보수)로 떨어뜨림.
        # (BWXT는 원자력 테마에서 megatrend 유지 / RKLB는 우주에서 유지 / 유럽·한국 재무장
        #  모멘텀주 RHM.DE·LDO.MI·012450.KS 등은 차단 안 함 = megatrend 유지)
        "exclude": ["LMT", "RTX", "NOC", "GD", "LHX", "BA", "GE", "HON", "HWM", "TDG"],
    },
    "데이터센터 전력": {
        "etfs": ["GRID", "XLU"],
        "keywords": ["power", "electrification", "grid", "data center power", "electrical equipment"],
        "reps": ["VRT", "GEV", "ETN", "PWR", "CEG", "POWL", "NRG", "TLN", "VST"],
    },
    "비만치료제/GLP-1": {
        "etfs": ["XLV"],
        "keywords": ["glp-1", "obesity", "weight loss", "incretin", "semaglutide", "tirzepatide"],
        "reps": ["LLY", "NVO", "VKTX", "AMGN", "ALT"],
    },
    "디지털인프라/비트코인": {
        "etfs": ["WGMI", "BITQ"],
        "keywords": ["bitcoin", "crypto", "mining", "blockchain", "digital asset"],
        "reps": ["IREN", "MARA", "RIOT", "CIFR", "WULF", "CLSK", "COIN", "HUT"],
    },
}

# 메가트렌드 mandate를 적용할 테마(자동 선택용). 위 전부가 대상.
MEGATREND_THEMES = set(THEME_ETF_MAP.keys())


# ─────────────────────────────────────────────────────────────────────────────
# ETF 실제 holdings 기반 동적 멤버십 (디스크 캐시)
#
# 수기 reps는 시간이 지나면 낡는다(자금이 몰리는 신규 수혜주를 놓침). ETF 큐레이터가
# 정한 '현재 구성'을 라이브로 끌어와 멤버십을 자동 보강한다. ETF 편입은 슬로우 시그널이라
# 뉴스/모멘텀처럼 매일 흔들리지 않음 → 리스크 컨테이너(mandate)로 쓰기에 안정적.
# 확신도·진입 타이밍의 동적 신호(news velocity·자금유입)는 별도(momentum/sectors)에서 다룬다.
# ─────────────────────────────────────────────────────────────────────────────
import os as _os
import json as _json
import time as _time

# 라이브 holdings 비활성화 스위치(오프라인/테스트/재현성). 0이면 정적 reps만 사용.
_LIVE_HOLDINGS = _os.getenv("INVEST_ETF_LIVE", "1") != "0"
_CACHE_TTL = 7 * 24 * 3600  # 7일 (ETF 구성은 천천히 바뀜)
_CACHE_PATH = _os.path.normpath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "cache", "etf_holdings.json")
)
_holdings_mem = None  # 프로세스 내 메모이즈


def _load_cache() -> dict:
    global _holdings_mem
    if _holdings_mem is not None:
        return _holdings_mem
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            _holdings_mem = _json.load(f)
    except Exception:
        _holdings_mem = {}
    return _holdings_mem


def _save_cache(cache: dict) -> None:
    try:
        _os.makedirs(_os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            _json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 캐시 쓰기 실패는 치명적이지 않음


def _fetch_holdings(etf: str) -> list:
    """yfinance에서 ETF top holdings 심볼 목록을 가져온다(실패 시 빈 리스트)."""
    try:
        import yfinance as yf
        th = yf.Ticker(etf).funds_data.top_holdings
        if th is None or len(th) == 0:
            return []
        return [str(s).upper().strip() for s in th.index]
    except Exception:
        return []


def _holdings_for_etf(etf: str, *, force: bool = False) -> set:
    """ETF holdings 심볼 집합. 캐시 우선, TTL 만료/force 시 갱신. 실패 시 캐시(있으면) 유지."""
    if not _LIVE_HOLDINGS:
        return set()
    cache = _load_cache()
    rec = cache.get(etf)
    fresh = rec and (_time.time() - rec.get("ts", 0) < _CACHE_TTL)
    if rec and fresh and not force:
        return set(rec.get("symbols", []))
    symbols = _fetch_holdings(etf)
    if symbols:
        cache[etf] = {"ts": _time.time(), "symbols": symbols}
        _save_cache(cache)
        return set(symbols)
    # fetch 실패 → 스테일 캐시라도 있으면 사용(없으면 빈 집합)
    return set(rec.get("symbols", [])) if rec else set()


def theme_members(theme: str, *, force_refresh: bool = False) -> set:
    """테마 멤버십 집합 = (ETF 실제 holdings ∪ reps) − exclude. 전부 대문자 심볼."""
    cfg = THEME_ETF_MAP.get(theme, {})
    seed = {r.upper() for r in cfg.get("reps", [])}
    excl = {x.upper() for x in cfg.get("exclude", [])}
    live = set()
    for etf in cfg.get("etfs", []):
        live |= _holdings_for_etf(etf, force=force_refresh)
    return (seed | live) - excl


def refresh_holdings_cache() -> dict:
    """모든 테마 ETF holdings 캐시를 강제 갱신한다. {etf: 종목수} 반환."""
    seen, out = set(), {}
    for cfg in THEME_ETF_MAP.values():
        for etf in cfg.get("etfs", []):
            if etf in seen:
                continue
            seen.add(etf)
            out[etf] = len(_holdings_for_etf(etf, force=True))
    return out


def themes_for_ticker(ticker: str, sector: str = "", name: str = "") -> list:
    """티커가 속한 메가트렌드 테마 목록을 반환한다.

    판정 = ETF holdings∪reps 멤버십(theme_members) 또는 회사명 키워드 매칭.
    단, 해당 테마의 exclude에 있으면 어떤 경로로도 매칭하지 않는다(차단 우선).
    """
    if not ticker:
        return []
    t = ticker.upper().strip()
    name_l = (name or "").lower()
    matched = []
    for theme, cfg in THEME_ETF_MAP.items():
        excl = {x.upper() for x in cfg.get("exclude", [])}
        if t in excl:
            continue  # 차단 종목은 키워드로도 매칭 금지
        if t in theme_members(theme):
            matched.append(theme)
            continue
        if name_l and any(kw in name_l for kw in cfg["keywords"]):
            matched.append(theme)
    return matched


def mandate_profile_for_ticker(ticker: str, sector: str = "", name: str = "") -> str:
    """티커를 보고 적용할 mandate 프로파일명을 추천한다.

    메가트렌드 테마에 속하면 'megatrend', 아니면 'default'.
    """
    return "megatrend" if themes_for_ticker(ticker, sector, name) else "default"
