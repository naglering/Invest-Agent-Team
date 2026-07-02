"""크립토 네이티브 데이터 도구 — '주식이 아닌 디지털자산'을 무엇으로 평가하는가.

주식의 PER/DCF/실적 대신, 크립토는 **토크노믹스(발행·언락 희석)·온체인 네트워크 가치
(NVT·TVL·수수료배수 P/F)·시장구조(BTC 도미넌스·섹터 로테이션·스테이블코인 유동성)**로
평가한다. 이 모듈은 그 측정의 결정론적 기반이다 — 전부 **키 불필요(keyless)** 공개 API.

데이터 소스(모두 무료·무키, 설계 단계에서 curl 검증):
  - CoinGecko      : 가격·시총·랭킹·FDV·공급(circ/total/max)·ATH·다기간 수익률·카테고리·
                     커뮤니티/개발활동·글로벌 도미넌스·크립토 섹터(category) 로테이션
  - DefiLlama      : 체인/프로토콜 TVL, 수수료·매출(→ 실질 P/F·P/S), 스테이블코인 발행량
  - Blockchain.com : BTC 온체인(활성주소·해시레이트·추정 거래량 → NVT)
  - alternative.me : Crypto Fear & Greed (시장 전체 심리)

설계 철학(macro_data와 동일): 소스별 격리 — 한 소스가 죽어도 나머지는 살린다(None degrade).
온체인 심층지표(MVRV·실현가·SOPR 등 실현가 기반)는 무료 키리스로 안 나오므로 null로 두고
crypto-analyst가 WebSearch로 보강한다. 모든 라벨은 산출 수치에서 재현 가능 — 인상비평 배격.

INVEST_CRYPTO_LIVE=0 이면 네트워크를 건너뛰고 well-formed 스켈레톤을 반환한다(오프라인 테스트).
"""

import json
import os
import subprocess
import tempfile
import time

# ── 티커 → CoinGecko id 별칭(상위 시총 ~40종). 충돌 심볼은 시총 1위 정본으로 고정. ──
# (예: STX→Stacks, UNI→Uniswap, TON→Toncoin — 이 도구는 크립토 문맥이므로 동명 주식과 무관)
ALIAS_MAP = {
    "BTC": "bitcoin", "XBT": "bitcoin",
    "ETH": "ethereum", "WETH": "weth",
    "USDT": "tether", "USDC": "usd-coin", "DAI": "dai", "USDS": "usds",
    "BNB": "binancecoin", "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "AVAX": "avalanche-2", "TRX": "tron", "TON": "the-open-network",
    "LINK": "chainlink", "DOT": "polkadot", "MATIC": "polygon-ecosystem-token",
    "POL": "polygon-ecosystem-token",
    "SHIB": "shiba-inu", "LTC": "litecoin", "BCH": "bitcoin-cash", "UNI": "uniswap",
    "XLM": "stellar", "ATOM": "cosmos", "ETC": "ethereum-classic", "XMR": "monero",
    "APT": "aptos", "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
    "NEAR": "near", "INJ": "injective-protocol", "AAVE": "aave", "MKR": "maker",
    "RNDR": "render-token", "RENDER": "render-token", "SEI": "sei-network",
    "PEPE": "pepe", "WIF": "dogwifcoin", "TAO": "bittensor", "FIL": "filecoin",
    "HBAR": "hedera-hashgraph", "IMX": "immutable-x", "STX": "blockstack", "GRT": "the-graph",
    "TIA": "celestia", "LDO": "lido-dao", "CRV": "curve-dao-token", "ENA": "ethena",
    "ICP": "internet-computer", "KAS": "kaspa", "ALGO": "algorand", "VET": "vechain",
    "FET": "fetch-ai", "IOTA": "iota", "ENS": "ethereum-name-service",
}

# yfinance(Yahoo) 심볼 오버라이드 — 단순 '{심볼}-USD'가 빈 프레임/엉뚱한 토큰을 주는 코인.
# Yahoo가 동명 심볼 충돌을 숫자 인픽스로 구분(예: TON-USD는 다른 ~$0.009 토큰 → 진짜 Toncoin은
# TON11419-USD). 검증 없이 '{base}-USD'를 쓰면 technical/risk/momentum이 '다른 자산'을 분석하게 됨.
YF_OVERRIDE = {
    "TON": "TON11419-USD", "UNI": "UNI7083-USD", "APT": "APT21794-USD",
    "SUI": "SUI20947-USD", "TAO": "TAO22974-USD", "PEPE": "PEPE24478-USD",
    "POL": "POL28321-USD", "MATIC": "POL28321-USD", "RENDER": "RENDER-USD",
    "RNDR": "RENDER-USD", "IOTA": "IOTA-USD", "FET": "FET-USD",
    # 동명 죽은 토큰 트랩(라이브 검증): GRT-USD=Golden Ratio Token, STX-USD=Stox, IMX-USD=Impermax
    "GRT": "GRT6719-USD", "STX": "STX4847-USD", "IMX": "IMX10603-USD",
}


def _yf_symbol(base: str) -> str:
    """base 심볼 → 검증된 yfinance 티커. 오버라이드 우선, 없으면 '{base}-USD'(대부분 유효)."""
    return YF_OVERRIDE.get(base.upper(), f"{base.upper()}-USD")


def _yf_price_usd(yf_sym: str):
    """Yahoo v8 chart(키리스)로 현재가 조회 — yfinance 심볼 교차검증용. 실패 시 None.

    근본 대책(#8): 오버라이드 목록 밖의 동명 심볼 충돌(신규 코인)도 CoinGecko 가격과
    ±20% 교차검증으로 구조적으로 차단하기 위한 조회 경로.
    """
    d = _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}?range=1d&interval=1d")
    try:
        p = d["chart"]["result"][0]["meta"].get("regularMarketPrice")
        return float(p) if p is not None else None
    except (KeyError, IndexError, TypeError):
        return None


def _cg_error_code(resp):
    """CoinGecko 에러 응답({'status':{'error_code':429,...}}) 감지 — truthy dict라 falsy 체크로는 못 잡음."""
    if isinstance(resp, dict):
        st = resp.get("status")
        if isinstance(st, dict) and st.get("error_code"):
            return st.get("error_code")
    return None

# 안정적 코인(스테이블) 심볼/카테고리 키워드 — 멀티플 평가 부적합 판정용
_STABLE_SYMBOLS = {"USDT", "USDC", "DAI", "USDS", "TUSD", "FDUSD", "PYUSD", "USDE", "FRAX"}

# BTC 발행 파라미터(2024-04 4차 반감기 이후 ~2028까지 유효). 스톡투플로우 산출용.
_BTC_BLOCK_REWARD = 3.125        # BTC/block (현 반감기 era)
_BTC_BLOCKS_PER_DAY = 144        # ≈ 10분/블록
_BTC_NEXT_HALVING = "2028-04(추정)"


# ─────────────────────────────────────────────────────────────────────────────
# HTTP — curl 우선(키리스 공개 API), 실패 시 urllib 폴백. 전부 None-safe.
# ─────────────────────────────────────────────────────────────────────────────
def _get_json(url, timeout=15):
    """공개 JSON 엔드포인트를 받아 파싱. 실패 시 None(소스별 격리)."""
    try:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            p = subprocess.run(
                # --retry-all-errors → CoinGecko 무료티어 429(rate-limit)도 백오프 재시도
                ["curl", "-sS", "-m", str(timeout),
                 "--retry", "3", "--retry-delay", "2", "--retry-all-errors",
                 "-o", path, "-H", "User-Agent: Mozilla/5.0", "-H", "Accept: application/json", url],
                capture_output=True, text=True, timeout=timeout * 3 + 8,
            )
            if p.returncode == 0:
                with open(path, encoding="utf-8") as f:
                    txt = f.read()
                if txt.strip():
                    return json.loads(txt)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception:
        pass
    try:  # curl 부재/실패 폴백
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _round(x, n=2):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return round(float(x), n)
    except (ValueError, TypeError):
        return None


def _safe_div(a, b):
    try:
        if a is None or b in (None, 0):
            return None
        return a / b
    except (TypeError, ZeroDivisionError):
        return None


CG = "https://api.coingecko.com/api/v3"
DL = "https://api.llama.fi"


# ─────────────────────────────────────────────────────────────────────────────
# 티커 해석
# ─────────────────────────────────────────────────────────────────────────────
def _strip_suffix(symbol: str) -> str:
    """'BTC-USD','BTCUSDT','ETH/USD' → 'BTC' 식으로 견적통화 접미사 제거."""
    s = symbol.strip().upper()
    for sep in ("-", "/", "_"):
        if sep in s:
            s = s.split(sep)[0]
            break
    for suf in ("USDT", "USDC", "USD", "PERP"):
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
    return s


def resolve_id(symbol: str) -> dict:
    """티커/심볼/id → CoinGecko id 해석.

    1) 별칭 맵(상위 시총) 우선  2) 입력이 이미 유효 id면 그대로  3) /search로 폴백
    (심볼 충돌 시 검색 결과 상위=시총 상위를 채택). 반환: {id, base, yf_symbol, method}.
    """
    raw = symbol.strip()
    base = _strip_suffix(raw)
    low = raw.lower()
    # 1) 별칭(오프라인·정본 — 충돌/리네임 심볼의 유일 안전경로)
    if base in ALIAS_MAP:
        cid = ALIAS_MAP[base]
        return {"id": cid, "base": base, "yf_symbol": _yf_symbol(base), "method": "alias"}
    # 2) markets?symbols=&include_tokens=all → 시총 최대값(argmax) 채택.
    #    (include_tokens 기본값은 동명 충돌 시 시총 1위를 안 줌 → all + argmax가 정답)
    mk = _get_json(f"{CG}/coins/markets?vs_currency=usd&symbols={base.lower()}&include_tokens=all")
    if isinstance(mk, list) and mk:
        best = max(mk, key=lambda c: c.get("market_cap") or 0)
        sym = (best.get("symbol") or base).upper()
        return {"id": best["id"], "base": sym, "yf_symbol": _yf_symbol(sym),
                "method": "markets(symbol-argmax-mcap)"}
    # 3) /search 폴백 — 심볼 정확일치 → id 일치 → 상위(시총순)
    data = _get_json(f"{CG}/search?query={raw}")
    if data:
        coins = data.get("coins", []) or []
        for c in coins:
            if (c.get("symbol") or "").upper() == base:
                sym = (c.get("symbol") or base).upper()
                return {"id": c["id"], "base": sym, "yf_symbol": _yf_symbol(sym),
                        "method": "search(symbol-match)"}
        for c in coins:
            if c.get("id") == low:
                sym = (c.get("symbol") or base).upper()
                return {"id": c["id"], "base": sym, "yf_symbol": _yf_symbol(sym), "method": "search(id)"}
        if coins:
            c = coins[0]
            sym = (c.get("symbol") or base).upper()
            return {"id": c["id"], "base": sym, "yf_symbol": _yf_symbol(sym), "method": "search(top)"}
    # 4) 전면 실패(오프라인/429): base 소문자를 id로 추정 + 불확실 플래그
    return {"id": low.replace(" ", "-"), "base": base, "yf_symbol": _yf_symbol(base),
            "method": "fallback(guess — 네트워크 실패, id 불확실)"}


# ─────────────────────────────────────────────────────────────────────────────
# 아키타입 분류 (카테고리 기반) — 평가 프레임워크 선택에 사용
# ─────────────────────────────────────────────────────────────────────────────
def _classify(coin_id, symbol, categories):
    cats = [str(c).lower() for c in (categories or [])]

    def has(*kw):
        return any(any(k in c for k in kw) for c in cats)

    if coin_id == "bitcoin" or symbol == "BTC":
        return "BTC", "비트코인 — 스톡투플로우·NVT·해시레이트·MVRV(보강)로 평가"
    if symbol in _STABLE_SYMBOLS or has("stablecoin"):
        return "stablecoin", "스테이블코인 — 멀티플 부적합. 발행량/페그/준비금/유동성으로 평가"
    if has("meme"):
        return "memecoin", "밈코인 — 펀더멘털 부재. 유동성·홀더수·소셜·거래량으로만 평가(고위험)"
    if has("layer 2", "rollup", "layer-2"):
        return "L2", "L2 — 시퀀서 수수료·정산비용·P/F·체인 TVL로 평가"
    if has("layer 1", "smart contract platform", "layer-1"):
        return "L1", "L1 — 체인 수수료/매출 P/F·P/S, TVL, mcap/TVL, 실질 스테이킹 수익률로 평가"
    if has("decentralized finance", "defi", "dex", "lending", "derivatives", "yield", "liquid staking"):
        return "DeFi", "DeFi 토큰 — 프로토콜 수수료/매출 P/F·P/S, TVL, mcap/TVL, 실질수익률로 평가"
    return "기타/토큰", "수수료/매출이 있으면 P/F·P/S, 없으면 토크노믹스·유동성·네트워크 채택으로 평가"


# ─────────────────────────────────────────────────────────────────────────────
# DefiLlama — TVL / 수수료 / 매출
# ─────────────────────────────────────────────────────────────────────────────
def _annualize(d):
    """fees/revenue summary dict → 연환산 금액(USD). total1y 우선, 없으면 30d×(365/30)."""
    if not d:
        return None
    if d.get("total1y"):
        return float(d["total1y"])
    if d.get("total30d"):
        return float(d["total30d"]) * 365.0 / 30.0
    if d.get("total24h"):
        return float(d["total24h"]) * 365.0
    return None


def _defillama_chain(coin_id):
    """coin_id가 체인이면 DefiLlama 체인명·TVL·연환산 수수료/매출을 반환(아니면 None).

    수수료는 **체인 자체(가스) 수수료**(/summary/fees/{gecko_id} — 체인이 프로토콜 엔트리로
    등록됨, 라이브 검증)만 사용한다. /overview/fees/{체인명}은 체인 위 전체 dApp(Lido·Aave 등)
    수수료 합산이라 토큰 홀더에 귀속되지 않음 — P/F 분모 금지, ecosystem_fees 참고 필드로만 분리.
    """
    chains = _get_json(f"{DL}/v2/chains")
    if not isinstance(chains, list):
        return None
    chain = next((c for c in chains if c.get("gecko_id") == coin_id), None)
    if not chain:
        return None
    name = chain.get("name")
    tvl = chain.get("tvl")
    # 체인 자체 수수료(가스) — P/F·P/S 분모
    fees = _get_json(f"{DL}/summary/fees/{coin_id}?dataType=dailyFees")
    if fees and all(fees.get(k) is None for k in ("total24h", "total30d", "total1y")):
        fees = None
    rev = _get_json(f"{DL}/summary/fees/{coin_id}?dataType=dailyRevenue") if fees else None
    # 생태계 전체 dApp 수수료 합산 — 활동 규모 참고용(홀더 귀속 아님)
    enc = name.replace(" ", "%20") if name else name
    eco = _get_json(f"{DL}/overview/fees/{enc}"
                    "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyFees")
    return {
        "kind": "chain", "name": name, "tvl_usd": _round(tvl, 0),
        "fees_24h_usd": _round((fees or {}).get("total24h"), 0) if fees else None,
        "fees_annualized_usd": _round(_annualize(fees), 0),
        "revenue_annualized_usd": _round(_annualize(rev), 0),
        "fees_scope": ("chain-native(체인 자체 가스 수수료 — P/F 분모)" if fees
                       else "체인 자체 수수료 미매칭(/summary/fees 미등록) — P/F 산출 불가"),
        "ecosystem_fees_24h_usd": _round((eco or {}).get("total24h"), 0) if eco else None,
        "ecosystem_fees_annualized_usd": _round(_annualize(eco), 0),
        "ecosystem_fees_note": "체인 위 전체 dApp 수수료 합산(Lido·Aave 등 각 토큰 홀더 귀속) — "
                               "P/F 분모 사용 금지, 생태계 활동 규모 참고용",
    }


def _defillama_protocol(coin_id):
    """DeFi 프로토콜 토큰의 수수료/매출(슬러그≈gecko id 가정, best-effort)."""
    fees = _get_json(f"{DL}/summary/fees/{coin_id}?dataType=dailyFees")
    if not fees or fees.get("total24h") is None and fees.get("total30d") is None:
        return None
    rev = _get_json(f"{DL}/summary/fees/{coin_id}?dataType=dailyRevenue")
    return {
        "kind": "protocol", "name": fees.get("displayName") or fees.get("name"),
        "tvl_usd": None,
        "fees_24h_usd": _round(fees.get("total24h"), 0),
        "fees_annualized_usd": _round(_annualize(fees), 0),
        "revenue_annualized_usd": _round(_annualize(rev), 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Blockchain.com — BTC 온체인
# ─────────────────────────────────────────────────────────────────────────────
def _bc_chart(name, days="90days"):
    d = _get_json(f"https://api.blockchain.info/charts/{name}?timespan={days}&format=json")
    vals = (d or {}).get("values") or []
    return [v.get("y") for v in vals if v.get("y") is not None] or None


def _trend_pct(series):
    if not series or len(series) < 2 or series[0] in (0, None):
        return None
    return _round((series[-1] / series[0] - 1) * 100, 1)


def _btc_onchain(market_cap):
    """BTC 온체인 지표 + NVT(= 시총 / 일일 추정 거래량)."""
    addr = _bc_chart("n-unique-addresses")
    hashr = _bc_chart("hash-rate")
    txvol = _bc_chart("estimated-transaction-volume-usd")
    miner_fees = _bc_chart("transaction-fees-usd")
    nvt = nvt_90d = None
    if txvol and market_cap:
        last_vol = txvol[-1]
        if last_vol:
            nvt = _round(market_cap / last_vol, 1)
        avg90 = sum(txvol) / len(txvol)
        if avg90:
            nvt_90d = _round(market_cap / avg90, 1)  # NVT signal(90일 MA) — 노이즈 완화
    return {
        "active_addresses": int(addr[-1]) if addr else None,
        "active_addresses_30d_trend_pct": _trend_pct(addr[-30:]) if addr else None,
        "hash_rate_30d_trend_pct": _trend_pct(hashr[-30:]) if hashr else None,
        "tx_volume_usd_daily": _round(txvol[-1], 0) if txvol else None,
        "miner_fees_usd_daily": _round(miner_fees[-1], 0) if miner_fees else None,
        "nvt": nvt,
        "nvt_signal_90d": nvt_90d,
        "nvt_note": "NVT = 시총 / 일일 온체인 거래량(USD). 높을수록 거래활동 대비 고평가. signal은 90일 MA.",
    }


def _btc_stock_to_flow(circ):
    """BTC 스톡투플로우(S2F) = 유통량 / 연간 신규발행. 모델가 아닌 비율만(과신 금지)."""
    if not circ:
        return None
    annual_flow = _BTC_BLOCK_REWARD * _BTC_BLOCKS_PER_DAY * 365
    s2f = _safe_div(circ, annual_flow)
    return {
        "stock_to_flow": _round(s2f, 1),
        "annual_new_supply_btc": int(annual_flow),
        "inflation_pct": _round(_safe_div(annual_flow, circ) * 100 if circ else None, 2),
        "next_halving": _BTC_NEXT_HALVING,
        "note": "S2F 비율만 제시(회귀 모델가는 과신 위험으로 제외). 높을수록 희소성↑.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 공개 진입점
# ─────────────────────────────────────────────────────────────────────────────
def crypto_overview(symbol: str) -> dict:
    """단일 디지털자산의 토크노믹스·시장구조·온체인 네트워크 가치·평가멀티플(키리스)."""
    if os.environ.get("INVEST_CRYPTO_LIVE") == "0":
        return {"symbol": symbol, "offline": True, "note": "INVEST_CRYPTO_LIVE=0 — 네트워크 미사용"}

    res = resolve_id(symbol)
    cid = res["id"]
    errors = []
    soft_warnings = []

    # --- CoinGecko markets(가격·시총·공급·수익률) ---
    mk = _get_json(f"{CG}/coins/markets?vs_currency=usd&ids={cid}"
                   "&price_change_percentage=24h,7d,30d,1y&sparkline=false")
    mk_err = _cg_error_code(mk)
    m = mk[0] if isinstance(mk, list) and mk else {}
    if mk_err:
        errors.append({"source": "coingecko/markets",
                       "error": f"HTTP {mk_err}(rate-limit 등) — 가격/시총 미수집"})
    elif not m:
        errors.append({"source": "coingecko/markets", "error": "데이터 없음(id 해석 실패 가능)"})

    # 신원 교차검증 — 해석된 코인 심볼 ≠ 입력 base면 오자산(추측 id가 우연히 타 코인과 일치 등).
    # 정상 데이터처럼 보이는 틀린 토크노믹스가 밸류에이션·사이징으로 흐르지 않게 결과 폐기.
    # (alias 경로는 큐레이션 정본 id라 면제 — MATIC→POL·XBT→BTC·RNDR→RENDER 등
    #  심볼 리네임/이형 표기가 정상적으로 불일치하므로 폐기 대상 아님)
    m_sym = (m.get("symbol") or "").upper()
    if m_sym and m_sym != res["base"].upper() and res["method"] != "alias":
        return {
            "input": symbol,
            "resolved": res,
            "identity": {"id": cid, "symbol": m_sym, "name": m.get("name")},
            "data_status": "identity_mismatch",
            "yfinance_symbol": None,
            "soft_warnings": [],
            "errors": errors + [{
                "source": "resolve",
                "error": (f"해석된 코인 '{m.get('name')}({m_sym})' ≠ 입력 심볼 '{res['base']}' — "
                          "오자산 분석 방지를 위해 결과 폐기. 정확한 CoinGecko id/심볼로 재시도 필요"),
            }],
        }

    # --- CoinGecko detail(카테고리·커뮤니티·개발) --- 실패 시 categories=[] → archetype 오분류 위험
    det_raw = _get_json(f"{CG}/coins/{cid}?localization=false&tickers=false&market_data=false"
                        "&community_data=true&developer_data=true&sparkline=false")
    det_err = _cg_error_code(det_raw)
    det = det_raw if isinstance(det_raw, dict) and not det_err else {}
    archetype_uncertain = False
    if det_err or not det:
        archetype_uncertain = True
        errors.append({"source": "coingecko/detail",
                       "error": (f"HTTP {det_err}(rate-limit 등)" if det_err else "데이터 없음")
                                + " — 카테고리 미수집, archetype 분류 불확실"})
    categories = [c for c in (det.get("categories") or []) if c]
    dev = det.get("developer_data") or {}

    mcap = m.get("market_cap")
    fdv = m.get("fully_diluted_valuation")
    circ = m.get("circulating_supply")
    total = m.get("total_supply")
    mx = m.get("max_supply")
    vol = m.get("total_volume")

    archetype, archetype_note = _classify(cid, res["base"], categories)
    if archetype_uncertain and archetype in ("BTC", "stablecoin"):
        archetype_uncertain = False  # id/심볼 기반 분류 — 카테고리 불필요
    if archetype_uncertain:
        archetype_note += " ⚠️ 카테고리 미수집 — 분류 신뢰 낮음(WebSearch로 확인 권장)"

    # --- 토크노믹스(희석·발행 진행·유동성) ---
    tokenomics = {
        "circulating_supply": circ, "total_supply": total, "max_supply": mx,
        "pct_supply_issued": _round(_safe_div(circ, mx) * 100 if mx else None, 1),
        "fdv_usd": fdv,
        "fdv_to_mcap": _round(_safe_div(fdv, mcap), 2),
        "dilution_overhang_note": (
            "FDV/MC≈1 → 희석 거의 없음(거의 전량 유통)" if (fdv and mcap and abs(fdv / mcap - 1) < 0.05)
            else "FDV/MC>1 → 미유통 물량 존재(향후 언락 희석 압력) — 언락 일정 WebSearch 권장"
            if (fdv and mcap and fdv / mcap > 1.05) else None),
        "max_supply_note": ("상한 없음(무한/미정 발행)" if not mx else f"상한 {mx:,.0f}"),
        "unlock_schedule": "키리스 미제공 — crypto-analyst가 WebSearch(토큰 베스팅/언락 캘린더)로 보강",
    }

    # --- 네트워크 가치 / 평가 멀티플 (아키타입별) ---
    network = {"archetype": archetype, "archetype_uncertain": archetype_uncertain,
               "note": archetype_note}
    if archetype == "BTC":
        network["onchain"] = _btc_onchain(mcap)
        network["stock_to_flow"] = _btc_stock_to_flow(circ)
    else:
        dl = _defillama_chain(cid) or _defillama_protocol(cid)
        if dl and dl.get("kind") == "chain" and archetype == "기타/토큰":
            # 2차 판정: DefiLlama 체인 매칭 → L1 승격(카테고리 미수집 시 오분류 복구)
            archetype = "L1"
            network["archetype"] = archetype
            network["note"] = ("L1 — 체인 수수료/매출 P/F·P/S, TVL, mcap/TVL, 실질 스테이킹 수익률로 평가"
                               " (DefiLlama 체인 매칭 2차 판정"
                               + ("; 카테고리 미수집 보완" if archetype_uncertain else "") + ")")
        if dl:
            fee_ann = dl.get("fees_annualized_usd")
            rev_ann = dl.get("revenue_annualized_usd")
            tvl = dl.get("tvl_usd")
            network["defillama"] = dl
            network["valuation_multiples"] = {
                "p_f_ratio": _round(_safe_div(mcap, fee_ann), 1),       # 시총/연수수료
                "ps_ratio": _round(_safe_div(mcap, rev_ann), 1),       # 시총/연매출(프로토콜 수익)
                "mcap_to_tvl": _round(_safe_div(mcap, tvl), 2),
                "fdv_to_fees": _round(_safe_div(fdv, fee_ann), 1),
                "note": "P/F=시총/연환산 수수료(체인은 자체 가스 수수료만 — 생태계 dApp 합산 제외). "
                        "낮을수록 저평가. mcap/TVL<1=예치자본 대비 저평가 경향.",
            }
        else:
            network["valuation_multiples"] = None
            network["note"] += " | DefiLlama 수수료/TVL 미매칭 — P/F·P/S는 crypto-analyst가 WebSearch 보강"
    network["onchain_deep_note"] = ("MVRV·실현가·SOPR·거래소 순유입은 키리스 미제공 — "
                                    "crypto-analyst가 WebSearch(Glassnode/CryptoQuant 공개치)로 보강")

    # --- yfinance 심볼 교차검증(근본 대책) — Yahoo 동명 심볼 충돌로 '다른 자산' 분석 차단 ---
    yf_sym = res["yf_symbol"]
    cg_price = m.get("current_price")
    yf_check = {"symbol": res["yf_symbol"], "status": "unverified",
                "yf_price_usd": None, "coingecko_price_usd": cg_price,
                "deviation_pct": None, "threshold_pct": 20}
    if yf_sym and cg_price:
        yf_price = _yf_price_usd(yf_sym)
        if yf_price is not None:
            yf_check["yf_price_usd"] = yf_price
            dev_pct = abs(yf_price / cg_price - 1) * 100
            yf_check["deviation_pct"] = _round(dev_pct, 1)
            if dev_pct > 20:
                yf_check["status"] = "mismatch(동명 타 자산 의심)"
                soft_warnings.append(
                    f"yfinance '{yf_sym}' 가격(${yf_price:,.6g})이 CoinGecko(${cg_price:,.6g})와 "
                    f"{_round(dev_pct, 0)}% 괴리 — 동명 타 토큰 의심. yfinance_symbol=null 처리. "
                    "technical/risk/momentum 실행 금지(정확한 Yahoo 심볼 수동 확인 후 YF_OVERRIDE 등록)")
                yf_sym = None
            else:
                yf_check["status"] = "validated(CoinGecko 대비 ±20% 이내)"
        else:
            yf_check["status"] = "unverified(Yahoo 조회 실패)"
            soft_warnings.append(f"yfinance 심볼 '{yf_sym}' 교차검증 불가(Yahoo 조회 실패) — "
                                 "technical/risk/momentum 실행 전 자산명 일치 확인 권장")
    elif yf_sym:
        yf_check["status"] = "unverified(CoinGecko 가격 없음 — 교차검증 불가)"

    return {
        "input": symbol,
        "resolved": res,
        "identity": {
            "id": cid, "symbol": res["base"], "name": m.get("name") or det.get("name"),
            "categories": categories[:8],
            "genesis_date": det.get("genesis_date"),
            "hashing_algorithm": det.get("hashing_algorithm"),
        },
        "market": {
            "price_usd": m.get("current_price"),
            "market_cap_usd": mcap, "market_cap_rank": m.get("market_cap_rank"),
            "volume_24h_usd": vol,
            "volume_to_mcap_pct": _round(_safe_div(vol, mcap) * 100 if mcap else None, 1),
            "ath_usd": m.get("ath"), "pct_from_ath": _round(m.get("ath_change_percentage"), 1),
            "returns_pct": {
                "24h": _round(m.get("price_change_percentage_24h_in_currency"), 1),
                "7d": _round(m.get("price_change_percentage_7d_in_currency"), 1),
                "30d": _round(m.get("price_change_percentage_30d_in_currency"), 1),
                "1y": _round(m.get("price_change_percentage_1y_in_currency"), 1),
            },
        },
        "tokenomics": tokenomics,
        "network_value": network,
        "community_dev": {
            "sentiment_up_pct": det.get("sentiment_votes_up_percentage"),
            "watchlist_users": det.get("watchlist_portfolio_users"),
            "twitter_followers": (det.get("community_data") or {}).get("twitter_followers"),
            "dev_commits_4w": dev.get("commit_count_4_weeks"),
            "github_stars": dev.get("stars"),
        },
        "yfinance_symbol": yf_sym,
        "yfinance_symbol_check": yf_check,
        "data_sources": "CoinGecko(가격·토크노믹스·카테고리) + DefiLlama(TVL·수수료·매출) + "
                        "Blockchain.com(BTC 온체인) — 전부 키리스",
        "caveats": "MVRV/실현가/SOPR/거래소순유입/언락일정은 키리스 미제공 → WebSearch 보강 필요. "
                   + (f"기술적·리스크·모멘텀은 `cli.py technical|risk|momentum {yf_sym}` 사용."
                      if yf_sym else
                      "yfinance 심볼 교차검증 실패 — technical/risk/momentum은 올바른 Yahoo 심볼 확인 후 실행."),
        "errors": errors,
        "soft_warnings": soft_warnings,
    }


def crypto_market() -> dict:
    """크립토 시장 전체 구조 — 도미넌스·ETH/BTC·섹터 로테이션·스테이블코인 유동성·심리(키리스).

    '주식의 sectors'에 해당하는 발굴 엔진 — 어느 크립토 섹터로 돈이 도는가.
    """
    if os.environ.get("INVEST_CRYPTO_LIVE") == "0":
        return {"offline": True, "note": "INVEST_CRYPTO_LIVE=0 — 네트워크 미사용"}

    errors = []
    g = (_get_json(f"{CG}/global") or {}).get("data") or {}
    if not g:
        errors.append({"source": "coingecko/global", "error": "데이터 없음"})
    mcp = g.get("market_cap_percentage") or {}
    btc_dom = mcp.get("btc")
    eth_dom = mcp.get("eth")
    total_mcap = (g.get("total_market_cap") or {}).get("usd")

    # ETH/BTC 비율(알트 상대강도 핵심) — markets에서 가격 직접 비교
    eb = _get_json(f"{CG}/coins/markets?vs_currency=usd&ids=bitcoin,ethereum")
    eth_btc = None
    if isinstance(eb, list):
        prices = {c["id"]: c.get("current_price") for c in eb}
        eth_btc = _round(_safe_div(prices.get("ethereum"), prices.get("bitcoin")), 5)

    # 크립토 섹터 로테이션 — 시총>$1B 카테고리를 7d/30d 시총가중 수익률로 랭킹(발굴).
    # 24h 단일 지표는 마이크로캡 스파이크 노이즈(하이프 꼭지 추종 위험) → 보조 컬럼으로 강등.
    # 주식 sector_scan(21/63/126일 다기간)과 규격 정렬 — 지속성 있는 자금흐름만 상위 랭크.
    cats = _get_json(f"{CG}/coins/categories")
    sectors = []
    rotation_method = None
    if isinstance(cats, list) and cats:
        big = [c for c in cats
               if (c.get("market_cap") or 0) > 1e9 and c.get("market_cap_change_24h") is not None]
        # 대표 코인(top_3_coins_id) 취합 → 벌크 1회 조회로 7d/30d 확보(레이트리밋 최소화)
        rep_ids = []
        for c in big:
            for i in (c.get("top_3_coins_id") or []):
                if i and i not in rep_ids:
                    rep_ids.append(i)
        by_id = {}
        if rep_ids:
            bulk_url = (f"{CG}/coins/markets?vs_currency=usd&ids={','.join(rep_ids[:250])}"
                        "&price_change_percentage=7d,30d&per_page=250")
            mkc = _get_json(bulk_url)
            if not isinstance(mkc, list):  # 429 등 일시 실패 — 백오프 후 1회 재시도(발굴 엔진 핵심 호출)
                time.sleep(5)
                mkc = _get_json(bulk_url)
            if isinstance(mkc, list):
                by_id = {c["id"]: c for c in mkc if c.get("id")}

        def _wavg(reps, key):
            """대표 코인들의 시총가중 평균 수익률 — 카테고리 수익률 프록시."""
            pairs = [(r.get("market_cap") or 0, r.get(key)) for r in reps]
            pairs = [(wi, v) for wi, v in pairs if v is not None and wi]
            tot = sum(wi for wi, _ in pairs)
            return _round(sum(wi * v for wi, v in pairs) / tot, 2) if tot else None

        scored = []
        for c in big:
            reps = [by_id[i] for i in (c.get("top_3_coins_id") or []) if i in by_id]
            r7 = _wavg(reps, "price_change_percentage_7d_in_currency")
            r30 = _wavg(reps, "price_change_percentage_30d_in_currency")
            if r7 is None and r30 is None:
                continue
            score = 0.6 * (r7 or 0) + 0.4 * (r30 or 0)  # 지속성 블렌드(7d 주, 30d 보조)
            scored.append((score, c, r7, r30))
        if scored:
            scored.sort(key=lambda t: t[0], reverse=True)
            rotation_method = ("시총>$1B 카테고리 대상, 대표 상위3코인 시총가중 "
                               "7d(60%)+30d(40%) 블렌드 랭킹. 24h는 보조 컬럼(단기 노이즈).")
            for score, c, r7, r30 in scored[:8]:
                sectors.append({
                    "category": c.get("name"),
                    "market_cap_usd": _round(c.get("market_cap"), 0),
                    "ret_7d_pct": r7, "ret_30d_pct": r30,
                    "rotation_score": _round(score, 2),
                    "change_24h_pct": _round(c.get("market_cap_change_24h"), 2),
                    "top_coins": [t for t in (c.get("top_3_coins_id") or c.get("top_3_coins") or [])][:3],
                })
        elif big:
            # 폴백: 7d/30d 벌크 조회 실패(429 등) — 24h 랭킹($1B 필터 유지) + degraded 명시
            errors.append({"source": "coingecko/markets(category reps)",
                           "error": "7d/30d 벌크 조회 실패 — 24h 단일 랭킹 폴백(지속성 판정 불가)"})
            rotation_method = "폴백: 시총>$1B 필터 + 24h 랭킹(7d/30d 미수집 — 신호 품질 저하)"
            for c in sorted(big, key=lambda c: c.get("market_cap_change_24h"), reverse=True)[:8]:
                sectors.append({
                    "category": c.get("name"),
                    "market_cap_usd": _round(c.get("market_cap"), 0),
                    "ret_7d_pct": None, "ret_30d_pct": None, "rotation_score": None,
                    "change_24h_pct": _round(c.get("market_cap_change_24h"), 2),
                    "top_coins": [t for t in (c.get("top_3_coins_id") or c.get("top_3_coins") or [])][:3],
                })
    else:
        errors.append({"source": "coingecko/categories", "error": "데이터 없음"})

    # 스테이블코인 총 발행량(= 시장 대기 유동성/순유입 프록시)
    sc = _get_json("https://stablecoins.llama.fi/stablecoins?includePrices=false")
    stable_total = stable_top = stable_30d_pct = None
    if sc and sc.get("peggedAssets"):
        assets = sc["peggedAssets"]

        def _peg(a, key):
            return (a.get(key, {}) or {}).get("peggedUSD", 0) or 0

        stable_total = sum(_peg(a, "circulating") for a in assets)
        stable_prev_month = sum(_peg(a, "circulatingPrevMonth") for a in assets)
        if stable_prev_month:
            stable_30d_pct = _round((stable_total / stable_prev_month - 1) * 100, 2)
        stable_top = [{"symbol": a.get("symbol"),
                       "circulating_usd": _round(_peg(a, "circulating"), 0)}
                      for a in sorted(assets, key=lambda x: -_peg(x, "circulating"))[:5]]

    # Fear & Greed (시장 전체 심리)
    fng = _get_json("https://api.alternative.me/fng/?limit=8")
    fng_now = fng_7d_ago = fng_label = None
    if fng and fng.get("data"):
        d = fng["data"]
        fng_now = int(d[0]["value"]) if d else None
        fng_label = d[0].get("value_classification") if d else None
        fng_7d_ago = int(d[7]["value"]) if len(d) > 7 else None

    # 도미넌스 해석(altseason 신호)
    dom_read = None
    if btc_dom is not None:
        dom_read = ("BTC 도미넌스 高(>55%) — 자금이 BTC에 집중, 알트 상대약세" if btc_dom > 55
                    else "BTC 도미넌스 低(<45%) — 알트로 위험선호 확산(알트시즌 경향)" if btc_dom < 45
                    else "BTC 도미넌스 중간(45-55%) — 혼조")

    return {
        "dominance": {
            "btc_pct": _round(btc_dom, 2), "eth_pct": _round(eth_dom, 2),
            "alt_pct": _round(100 - (btc_dom or 0) - (eth_dom or 0), 2) if btc_dom is not None else None,
            "read": dom_read,
        },
        "eth_btc_ratio": eth_btc,
        "total_market_cap_usd": _round(total_mcap, 0),
        "total_mcap_change_24h_pct": _round(g.get("market_cap_change_percentage_24h_usd"), 2),
        "sector_rotation": sectors,
        "sector_rotation_method": rotation_method,
        "stablecoins": {
            "total_circulating_usd": _round(stable_total, 0),
            "total_circulating_bn": _round(_safe_div(stable_total, 1e9), 1),
            "supply_30d_change_pct": stable_30d_pct,
            "dry_powder_signal": (None if stable_30d_pct is None
                                  else "🟢 발행 확대(순유입·순풍)" if stable_30d_pct > 1
                                  else "🔴 발행 축소(유출·역풍)" if stable_30d_pct < -1
                                  else "🟡 횡보"),
            "top": stable_top,
            "note": "스테이블코인 발행량 = 시장 대기 유동성(dry powder). 증가=순유입(순풍), 감소=유출(역풍).",
        },
        "fear_greed": {"now": fng_now, "label": fng_label, "d7_ago": fng_7d_ago,
                       "note": "0-24 극공포 / 25-49 공포 / 50-74 탐욕 / 75-100 극탐욕. 역발상 참고."},
        "data_sources": "CoinGecko(/global·/categories) + DefiLlama(stablecoins) + alternative.me(F&G) — 키리스",
        "errors": errors,
    }
