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
# etfs[0]를 대표 ETF(자금흐름 프록시)로 사용. reps는 자동 mandate 선정/피어 발굴에 사용.
THEME_ETF_MAP = {
    "AI/반도체": {
        "etfs": ["SMH", "SOXX", "BOTZ"],
        "keywords": ["artificial intelligence", "semiconductor", "gpu", "accelerator", "data center", "ai "],
        "reps": ["NVDA", "AMD", "AVGO", "TSM", "ARM", "MU", "MRVL", "SMCI", "PLTR", "ASML", "LRCX", "AMAT"],
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
        "reps": ["LMT", "RTX", "NOC", "GD", "LHX", "BWXT", "KTOS", "AVAV"],
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


def themes_for_ticker(ticker: str, sector: str = "", name: str = "") -> list:
    """티커가 속한 메가트렌드 테마 목록을 반환한다(대표종목 멤버십 + 키워드 매칭)."""
    if not ticker:
        return []
    t = ticker.upper().strip()
    name_l = (name or "").lower()
    matched = []
    for theme, cfg in THEME_ETF_MAP.items():
        if t in cfg["reps"]:
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
