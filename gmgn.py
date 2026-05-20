"""
gmgn.py — GMGN.ai Integration với API Key
Data: Token security, insider/sniper, smart money, KOL, new tokens
"""

import requests, time, logging, urllib3
from dataclasses import dataclass, field
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger   = logging.getLogger(__name__)
GMGN_BASE = "https://gmgn.ai"

# ── Session setup ──
SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://gmgn.ai/",
    "Origin":          "https://gmgn.ai",
})

CHAIN_MAP = {
    "solana":   "sol",
    "ethereum": "eth",
    "base":     "base",
    "bsc":      "bsc",
}

# ── API Key (set bởi main.py) ──
_API_KEY = ""

def set_api_key(key: str):
    global _API_KEY
    _API_KEY = key
    if key:
        SESSION.headers.update({"Authorization": f"Bearer {key}"})
        logger.info(f"GMGN API key set: {key[:12]}...")


@dataclass
class GMGNTokenData:
    address: str
    chain: str
    is_honeypot: bool  = False
    is_mintable: bool  = False
    is_blacklist: bool = False
    lp_burned: bool    = False
    renounced: bool    = False
    top10_holder_pct: float = 0.0
    dev_holding_pct: float  = 0.0
    insider_pct: float      = 0.0
    sniper_count: int       = 0
    bundled_pct: float      = 0.0
    smart_money_buying: bool = False
    smart_money_wallets: int = 0
    kol_buying: bool  = False
    kol_count: int    = 0
    rug_score: float  = 5.0
    quality_score: float = 5.0
    signals:  list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def gmgn_get(path: str, params: dict = None) -> Optional[dict]:
    try:
        r = SESSION.get(f"{GMGN_BASE}{path}", params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            logger.warning("GMGN rate limited, sleeping 2s")
            time.sleep(2)
        elif r.status_code == 401:
            logger.warning("GMGN 401 — API key invalid or expired")
        else:
            logger.debug(f"GMGN {r.status_code}: {path}")
    except Exception as e:
        logger.debug(f"GMGN error {path}: {e}")
    return None


# ─────────────────────────────────────────────
# TOKEN ENDPOINTS
# ─────────────────────────────────────────────

def fetch_token_security(address: str, chain: str = "sol") -> Optional[dict]:
    """Honeypot, mintable, LP burned, renounced"""
    data = gmgn_get(f"/api/v1/token_security/{chain}/{address}")
    if data and data.get("code") == 0:
        return data.get("data", {})
    return None


def fetch_token_info(address: str, chain: str = "sol") -> Optional[dict]:
    """Holders, dev holding, insider/sniper data"""
    data = gmgn_get(f"/api/v1/token_info/{chain}/{address}")
    if data and data.get("code") == 0:
        return data.get("data", {})
    return None


def fetch_smart_money(address: str, chain: str = "sol") -> Optional[dict]:
    """Smart money & KOL wallet holdings"""
    data = gmgn_get(f"/api/v1/token_smart_money/{chain}/{address}")
    if data and data.get("code") == 0:
        return data.get("data", {})
    return None


def fetch_kol_activity(chain: str = "sol") -> list:
    """KOL wallets đang mua gì — real-time"""
    data = gmgn_get(f"/api/v1/kol_activity/{chain}",
                    params={"limit": 20, "orderby": "last_active_timestamp",
                            "direction": "desc"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("activities", [])
    return []


def fetch_smart_money_activity(chain: str = "sol") -> list:
    """Smart money wallets đang mua gì"""
    data = gmgn_get(f"/api/v1/smartmoney_activity/{chain}",
                    params={"limit": 20, "orderby": "last_active_timestamp",
                            "direction": "desc"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("activities", [])
    return []


# ─────────────────────────────────────────────
# MARKET / TRENDING ENDPOINTS
# ─────────────────────────────────────────────

def fetch_new_tokens(chain: str = "sol", limit: int = 50) -> list:
    """New token launches — bắt gem từ $50-300K MC"""
    data = gmgn_get(f"/defi/quotation/v1/rank/{chain}/new_pairs/1m",
                    params={"limit": limit, "orderby": "open_timestamp",
                            "direction": "desc", "filters[]": "not_honeypot"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("rank", [])
    return []


def fetch_trending_tokens(chain: str = "sol", period: str = "1m") -> list:
    """Trending by buy count — 1m/5m/1h/6h/24h"""
    data = gmgn_get(f"/defi/quotation/v1/rank/{chain}/swaps/{period}",
                    params={"limit": 50, "orderby": "swaps",
                            "direction": "desc", "filters[]": "not_honeypot"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("rank", [])
    return []


def fetch_pump_tokens(chain: str = "sol") -> list:
    """Pumping tokens — momentum sắp breakout"""
    data = gmgn_get(f"/defi/quotation/v1/rank/{chain}/swaps/5m",
                    params={"limit": 50, "orderby": "price_change_percent",
                            "direction": "desc", "filters[]": "not_honeypot"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("rank", [])
    return []


# ─────────────────────────────────────────────
# FULL ANALYSIS
# ─────────────────────────────────────────────

def analyze_token(address: str, chain: str = "solana") -> GMGNTokenData:
    c      = CHAIN_MAP.get(chain, "sol")
    result = GMGNTokenData(address=address, chain=chain)

    # 1. Security
    sec = fetch_token_security(address, c)
    if sec:
        result.is_honeypot  = bool(sec.get("is_honeypot"))
        result.is_mintable  = bool(sec.get("mintable") or sec.get("is_mintable"))
        result.is_blacklist = bool(sec.get("blacklist") or sec.get("is_blacklist"))
        result.lp_burned    = bool(sec.get("lp_burned") or
                                   float(sec.get("burn_ratio") or 0) > 0.9)
        result.renounced    = bool(sec.get("renounced") or
                                   sec.get("owner_address") in ("", None))
        if result.is_honeypot:
            result.warnings.append("🚨 HONEYPOT — không bán được!")
        if result.is_mintable:
            result.warnings.append("⚠️ Mint chưa renounced — có thể in thêm token")
        if result.lp_burned:
            result.signals.append("✅ LP đã burn — không thể rug LP")
        if result.renounced:
            result.signals.append("✅ Contract renounced")

    # 2. Holders / Insiders
    info = fetch_token_info(address, c)
    if info:
        result.top10_holder_pct = float(info.get("top_10_holder_rate") or
                                        info.get("top10_holder_pct") or 0) * 100
        result.dev_holding_pct  = float(info.get("dev_token_burn_ratio") or
                                        info.get("dev_holding_pct") or 0) * 100
        result.insider_pct      = float(info.get("insider_rate") or
                                        info.get("insider_pct") or 0) * 100
        result.sniper_count     = int(info.get("sniper_count") or 0)
        result.bundled_pct      = float(info.get("bundle_rate") or 0) * 100

        if result.insider_pct > 50:
            result.warnings.append(f"🚨 Insider giữ {result.insider_pct:.0f}%")
        elif result.insider_pct > 20:
            result.warnings.append(f"⚠️ Insider {result.insider_pct:.0f}%")
        elif result.insider_pct < 5 and result.insider_pct >= 0:
            result.signals.append(f"✅ Insider thấp {result.insider_pct:.0f}%")

        if result.dev_holding_pct > 5:
            result.warnings.append(f"⚠️ Dev giữ {result.dev_holding_pct:.0f}%")
        elif result.dev_holding_pct == 0:
            result.signals.append("✅ Dev holding 0%")

        if result.sniper_count > 50:
            result.warnings.append(f"🚨 {result.sniper_count} snipers — dump risk")
        elif result.sniper_count > 20:
            result.warnings.append(f"⚠️ {result.sniper_count} sniper wallets")

        if result.top10_holder_pct > 60:
            result.warnings.append(f"🚨 Top10 giữ {result.top10_holder_pct:.0f}%")
        elif result.top10_holder_pct < 25:
            result.signals.append(f"✅ Top10 phân tán {result.top10_holder_pct:.0f}%")

        if result.bundled_pct > 10:
            result.warnings.append(f"⚠️ Bundle wallets {result.bundled_pct:.0f}%")

    # 3. Smart Money + KOL
    sm = fetch_smart_money(address, c)
    if sm:
        sm_list  = sm.get("smart_money") or sm.get("wallets") or []
        kol_list = sm.get("kol") or []
        result.smart_money_wallets = len(sm_list) if isinstance(sm_list, list) else int(sm_list or 0)
        result.kol_count           = len(kol_list) if isinstance(kol_list, list) else int(kol_list or 0)
        result.smart_money_buying  = result.smart_money_wallets > 0
        result.kol_buying          = result.kol_count > 0

        if result.smart_money_wallets >= 3:
            result.signals.append(f"🐋 {result.smart_money_wallets} SM wallets đang mua")
        elif result.smart_money_wallets >= 1:
            result.signals.append(f"👀 {result.smart_money_wallets} SM wallet detected")
        if result.kol_count >= 2:
            result.signals.append(f"⭐ {result.kol_count} KOL wallets đang mua")
        elif result.kol_count == 1:
            result.signals.append("⭐ 1 KOL wallet detected")

    # 4. Compute scores
    rug = 3.0
    if result.is_honeypot:          rug += 5.0
    if result.is_mintable:          rug += 1.5
    if result.insider_pct > 50:     rug += 2.0
    elif result.insider_pct > 20:   rug += 1.0
    if result.dev_holding_pct > 10: rug += 1.0
    if result.sniper_count > 30:    rug += 1.0
    if result.lp_burned:            rug -= 1.5
    if result.renounced:            rug -= 1.0
    if result.top10_holder_pct > 60:rug += 1.0
    result.rug_score = min(10.0, max(1.0, round(rug, 1)))

    quality = 5.0
    if result.smart_money_wallets >= 3: quality += 2.0
    elif result.smart_money_wallets>=1: quality += 1.0
    if result.kol_count >= 2:           quality += 1.5
    elif result.kol_count == 1:         quality += 0.5
    if result.lp_burned:                quality += 1.0
    if result.renounced:                quality += 0.5
    if result.is_honeypot:              quality -= 5.0
    if result.insider_pct > 50:         quality -= 2.0
    if result.dev_holding_pct > 10:     quality -= 1.0
    result.quality_score = min(10.0, max(1.0, round(quality, 1)))

    return result


# ─────────────────────────────────────────────
# NORMALIZE GMGN → scanner format
# ─────────────────────────────────────────────

def normalize_gmgn_token(raw: dict, chain: str = "solana") -> Optional[dict]:
    addr = raw.get("address") or raw.get("token_address") or ""
    if not addr:
        return None
    mc   = float(raw.get("market_cap") or raw.get("usd_market_cap") or 0)
    liq  = float(raw.get("liquidity") or 0)
    vol  = float(raw.get("volume") or raw.get("volume_24h") or 0)
    p1h  = float(raw.get("price_change_percent1h") or raw.get("price_change_percent") or 0)
    p24h = float(raw.get("price_change_percent24h") or 0)
    buys = int(raw.get("buy_count_h24") or raw.get("swaps") or 0)
    sells= int(raw.get("sell_count_h24") or 0)
    price= float(raw.get("price") or raw.get("usd_price") or 0)
    ts   = raw.get("open_timestamp") or raw.get("created_timestamp") or 0
    age_d= ((time.time() - ts) / 86400) if ts > 0 else 0
    ticker = (raw.get("symbol") or raw.get("token_symbol") or "???").upper()
    name   = raw.get("name") or raw.get("token_name") or ticker
    return {
        "address": addr, "ticker": ticker, "name": name, "chain": chain,
        "mc": mc, "liq": liq, "vol24": vol,
        "vol6": vol*0.25, "vol1": vol*0.04,
        "p1h": p1h, "p6h": p1h*0.6, "p24h": p24h, "p5m": 0,
        "buys24": buys, "sells24": sells,
        "price": price, "age_days": round(age_d, 2),
        "dex_url": f"https://gmgn.ai/sol/token/{addr}" if chain=="solana"
                   else f"https://dexscreener.com/{chain}/{addr}",
        "source": "gmgn",
    }


def hunt_gmgn_new_tokens(chains: list = None) -> list:
    """Scan GMGN new/trending tokens — bắt gem $50-300K MC."""
    if chains is None:
        chains = ["solana"]
    results = []
    for chain in chains:
        c = CHAIN_MAP.get(chain, "sol")
        # New pairs
        for t in fetch_new_tokens(c, 50):
            n = normalize_gmgn_token(t, chain)
            if n and 20_000 <= n["mc"] <= 3_000_000:
                results.append(n)
        time.sleep(0.5)
        # Trending 1m
        for t in fetch_trending_tokens(c, "1m"):
            n = normalize_gmgn_token(t, chain)
            if n and 30_000 <= n["mc"] <= 3_000_000:
                n["trending_1m"] = True
                results.append(n)
        time.sleep(0.5)
        # Pump 5m
        for t in fetch_pump_tokens(c):
            n = normalize_gmgn_token(t, chain)
            if n and 50_000 <= n["mc"] <= 5_000_000 and n["p1h"] < 200:
                n["pumping_5m"] = True
                results.append(n)
        time.sleep(0.5)

    # Dedupe
    seen = set(); deduped = []
    for r in results:
        if r["address"] not in seen:
            seen.add(r["address"]); deduped.append(r)
    logger.info(f"GMGN hunt: {len(deduped)} tokens across {chains}")
    return deduped