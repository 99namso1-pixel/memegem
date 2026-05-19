"""
gmgn.py — GMGN.ai Integration Module
Data: Token security, insider/sniper detection, smart money, new tokens
API: gmgn.ai public endpoints (IP whitelist needed for heavy use)
"""

import requests
import time
import logging
import urllib3
from dataclasses import dataclass, field
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

GMGN_BASE = "https://gmgn.ai"
SESSION   = requests.Session()
SESSION.verify = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://gmgn.ai/",
    "Origin": "https://gmgn.ai",
})

# Chain mapping
CHAIN_MAP = {
    "solana": "sol",
    "ethereum": "eth",
    "base": "base",
    "bsc": "bsc",
}


@dataclass
class GMGNTokenData:
    address: str
    chain: str
    # Security
    is_honeypot: bool = False
    is_mintable: bool = False
    is_blacklist: bool = False
    lp_burned: bool = False
    renounced: bool = False
    # Holders
    top10_holder_pct: float = 0.0
    dev_holding_pct: float = 0.0
    insider_pct: float = 0.0
    sniper_count: int = 0
    bundled_pct: float = 0.0
    # Smart money
    smart_money_buying: bool = False
    smart_money_wallets: int = 0
    kol_buying: bool = False
    kol_count: int = 0
    # Quality score
    rug_score: float = 5.0       # 1=safe, 10=danger
    quality_score: float = 5.0  # 1=bad, 10=great
    signals: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def gmgn_get(path: str, params: dict = None) -> Optional[dict]:
    """GET request to GMGN API."""
    try:
        url = f"{GMGN_BASE}{path}"
        r = SESSION.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            logger.warning(f"GMGN rate limited: {path}")
            time.sleep(2)
        else:
            logger.debug(f"GMGN {r.status_code}: {path}")
    except Exception as e:
        logger.debug(f"GMGN error {path}: {e}")
    return None


def fetch_token_security(address: str, chain: str = "sol") -> Optional[dict]:
    """
    Token security check — honeypot, mintable, LP burned, etc.
    Endpoint: /api/v1/token_security/{chain}/{address}
    """
    c = CHAIN_MAP.get(chain, chain)
    data = gmgn_get(f"/api/v1/token_security/{c}/{address}")
    if data and data.get("code") == 0:
        return data.get("data", {})
    return None


def fetch_token_info(address: str, chain: str = "sol") -> Optional[dict]:
    """
    Token info — holders, dev holding, insider/sniper data
    Endpoint: /api/v1/token_info/{chain}/{address}  
    """
    c = CHAIN_MAP.get(chain, chain)
    data = gmgn_get(f"/api/v1/token_info/{c}/{address}")
    if data and data.get("code") == 0:
        return data.get("data", {})
    return None


def fetch_smart_money(address: str, chain: str = "sol") -> Optional[dict]:
    """
    Smart money & KOL holdings
    Endpoint: /api/v1/token_smart_money/{chain}/{address}
    """
    c = CHAIN_MAP.get(chain, chain)
    data = gmgn_get(f"/api/v1/token_smart_money/{c}/{address}")
    if data and data.get("code") == 0:
        return data.get("data", {})
    return None


def fetch_new_tokens(chain: str = "sol", limit: int = 50) -> list:
    """
    New token launches — bắt gem từ $50-200K MC
    Endpoint: /defi/quotation/v1/rank/{chain}/new_pairs/1m
    """
    c = CHAIN_MAP.get(chain, chain)
    data = gmgn_get(f"/defi/quotation/v1/rank/{c}/new_pairs/1m",
                    params={"limit": limit, "orderby": "open_timestamp",
                            "direction": "desc", "filters[]": "not_honeypot"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("rank", [])
    return []


def fetch_trending_tokens(chain: str = "sol", period: str = "1m") -> list:
    """
    Trending tokens by buy count
    period: 1m, 5m, 1h, 6h, 24h
    """
    c = CHAIN_MAP.get(chain, chain)
    data = gmgn_get(f"/defi/quotation/v1/rank/{c}/swaps/{period}",
                    params={"limit": 50, "orderby": "swaps",
                            "direction": "desc", "filters[]": "not_honeypot"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("rank", [])
    return []


def fetch_pump_tokens(chain: str = "sol") -> list:
    """
    Pumping tokens — bắt momentum sớm
    """
    c = CHAIN_MAP.get(chain, chain)
    data = gmgn_get(f"/defi/quotation/v1/rank/{c}/swaps/5m",
                    params={"limit": 50, "orderby": "price_change_percent",
                            "direction": "desc", "filters[]": "not_honeypot"})
    if data and data.get("code") == 0:
        return data.get("data", {}).get("rank", [])
    return []


def analyze_token(address: str, chain: str = "solana") -> GMGNTokenData:
    """
    Full GMGN analysis cho một token.
    Gộp security + info + smart money.
    """
    c_short = CHAIN_MAP.get(chain, "sol")
    result  = GMGNTokenData(address=address, chain=chain)

    # 1. Security check
    sec = fetch_token_security(address, c_short)
    if sec:
        result.raw["security"] = sec
        result.is_honeypot   = bool(sec.get("is_honeypot"))
        result.is_mintable   = bool(sec.get("mintable") or sec.get("is_mintable"))
        result.is_blacklist  = bool(sec.get("blacklist") or sec.get("is_blacklist"))
        result.lp_burned     = bool(sec.get("lp_burned") or sec.get("burn_ratio", 0) > 0.9)
        result.renounced     = bool(sec.get("renounced") or sec.get("owner_address") == "")

        if result.is_honeypot:
            result.warnings.append("🚨 HONEYPOT — không bán được!")
        if result.is_mintable:
            result.warnings.append("⚠️ Mint không renounced — team có thể in thêm")
        if result.lp_burned:
            result.signals.append("✅ LP đã burn — không thể rug LP")
        if result.renounced:
            result.signals.append("✅ Contract renounced — an toàn hơn")

    # 2. Token info — holders, insiders
    info = fetch_token_info(address, c_short)
    if info:
        result.raw["info"] = info
        result.top10_holder_pct = float(info.get("top_10_holder_rate") or
                                        info.get("top10_holder_pct") or 0) * 100
        result.dev_holding_pct  = float(info.get("dev_token_burn_ratio") or
                                        info.get("dev_holding_pct") or 0) * 100
        result.insider_pct      = float(info.get("insider_rate") or
                                        info.get("insider_pct") or 0) * 100
        result.sniper_count     = int(info.get("sniper_count") or 0)
        result.bundled_pct      = float(info.get("bundle_rate") or 0) * 100

        # Insider signals
        if result.insider_pct > 50:
            result.warnings.append(f"🚨 Insider giữ {result.insider_pct:.0f}% — rủi ro dump cao")
        elif result.insider_pct > 20:
            result.warnings.append(f"⚠️ Insider giữ {result.insider_pct:.0f}%")
        elif result.insider_pct < 5:
            result.signals.append(f"✅ Insider thấp {result.insider_pct:.0f}%")

        if result.dev_holding_pct > 5:
            result.warnings.append(f"⚠️ Dev đang giữ {result.dev_holding_pct:.0f}%")
        elif result.dev_holding_pct == 0:
            result.signals.append("✅ Dev holding 0% — không giữ token")

        if result.sniper_count > 20:
            result.warnings.append(f"⚠️ {result.sniper_count} sniper wallets")
        elif result.sniper_count > 50:
            result.warnings.append(f"🚨 {result.sniper_count} snipers — dump risk")

        if result.top10_holder_pct > 60:
            result.warnings.append(f"🚨 Top10 giữ {result.top10_holder_pct:.0f}% — concentration cao")
        elif result.top10_holder_pct < 25:
            result.signals.append(f"✅ Top10 chỉ {result.top10_holder_pct:.0f}% — phân tán tốt")

        if result.bundled_pct > 10:
            result.warnings.append(f"⚠️ Bundle wallets {result.bundled_pct:.0f}% — fake vol?")

    # 3. Smart money
    sm = fetch_smart_money(address, c_short)
    if sm:
        result.raw["smart_money"] = sm
        sm_wallets = sm.get("smart_money") or sm.get("wallets") or []
        kol_wallets= sm.get("kol") or []

        result.smart_money_wallets = len(sm_wallets) if isinstance(sm_wallets, list) else int(sm_wallets or 0)
        result.kol_count           = len(kol_wallets) if isinstance(kol_wallets, list) else int(kol_wallets or 0)
        result.smart_money_buying  = result.smart_money_wallets > 0
        result.kol_buying          = result.kol_count > 0

        if result.smart_money_wallets >= 3:
            result.signals.append(f"🐋 {result.smart_money_wallets} smart money wallets đang mua")
        elif result.smart_money_wallets >= 1:
            result.signals.append(f"👀 {result.smart_money_wallets} SM wallet detected")

        if result.kol_count >= 2:
            result.signals.append(f"⭐ {result.kol_count} KOL wallets đang mua")
        elif result.kol_count == 1:
            result.signals.append("⭐ 1 KOL wallet detected")

    # 4. Compute scores
    rug = 3.0
    if result.is_honeypot:     rug += 5.0
    if result.is_mintable:     rug += 1.5
    if result.insider_pct > 50:rug += 2.0
    elif result.insider_pct>20:rug += 1.0
    if result.dev_holding_pct>10:rug += 1.0
    if result.sniper_count > 30: rug += 1.0
    if result.lp_burned:        rug -= 1.5
    if result.renounced:        rug -= 1.0
    if result.top10_holder_pct>60: rug += 1.0
    result.rug_score = min(10.0, max(1.0, round(rug, 1)))

    quality = 5.0
    if result.smart_money_wallets >= 3: quality += 2.0
    elif result.smart_money_wallets>=1: quality += 1.0
    if result.kol_count >= 2:          quality += 1.5
    elif result.kol_count == 1:        quality += 0.5
    if result.lp_burned:               quality += 1.0
    if result.renounced:               quality += 0.5
    if result.is_honeypot:             quality -= 5.0
    if result.insider_pct > 50:        quality -= 2.0
    if result.dev_holding_pct > 10:    quality -= 1.0
    result.quality_score = min(10.0, max(1.0, round(quality, 1)))

    return result


def normalize_gmgn_token(raw: dict, chain: str = "solana") -> Optional[dict]:
    """
    Normalize GMGN rank data thành format tương thích với scanner.
    """
    addr = raw.get("address") or raw.get("token_address") or ""
    if not addr:
        return None

    mc   = float(raw.get("market_cap") or raw.get("usd_market_cap") or 0)
    liq  = float(raw.get("liquidity") or raw.get("pool_info", {}).get("liquidity") or 0)
    vol  = float(raw.get("volume") or raw.get("volume_24h") or 0)
    p1h  = float(raw.get("price_change_percent1h") or raw.get("price_change_percent") or 0)
    p24h = float(raw.get("price_change_percent24h") or 0)
    buys = int(raw.get("buy_count_h24") or raw.get("swaps") or 0)
    sells= int(raw.get("sell_count_h24") or 0)
    price= float(raw.get("price") or raw.get("usd_price") or 0)

    # Token age
    ts      = raw.get("open_timestamp") or raw.get("created_timestamp") or 0
    age_ms  = (time.time() - ts) if ts > 0 else 0
    age_d   = age_ms / 86400 if age_ms > 0 else 0

    ticker = (raw.get("symbol") or raw.get("token_symbol") or "???").upper()
    name   = raw.get("name") or raw.get("token_name") or ticker

    return {
        "address": addr, "ticker": ticker, "name": name,
        "chain": chain, "mc": mc, "liq": liq, "vol24": vol,
        "vol6": vol * 0.25, "vol1": vol * 0.04,  # estimate
        "p1h": p1h, "p6h": p1h * 0.6, "p24h": p24h, "p5m": 0,
        "buys24": buys, "sells24": sells,
        "price": price, "age_days": round(age_d, 2),
        "dex_url": f"https://gmgn.ai/sol/token/{addr}" if chain == "solana"
                   else f"https://dexscreener.com/{chain}/{addr}",
        "source": "gmgn",
        "raw": raw,
    }


def hunt_gmgn_new_tokens(chains: list = None) -> list:
    """
    Scan GMGN new tokens + trending — bắt gem $50-300K MC.
    Return list of normalized token dicts.
    """
    if chains is None:
        chains = ["solana"]

    results = []
    chain_map_r = {"solana": "sol", "ethereum": "eth", "base": "base", "bsc": "bsc"}

    for chain in chains:
        c = chain_map_r.get(chain, "sol")
        
        # New pairs
        new_tokens = fetch_new_tokens(c, limit=50)
        for t in new_tokens:
            norm = normalize_gmgn_token(t, chain)
            if norm and 20_000 <= norm["mc"] <= 3_000_000:
                results.append(norm)

        time.sleep(0.5)

        # Trending 1m — momentum đang tăng
        trending = fetch_trending_tokens(c, "1m")
        for t in trending:
            norm = normalize_gmgn_token(t, chain)
            if norm and 30_000 <= norm["mc"] <= 3_000_000:
                norm["trending_1m"] = True
                results.append(norm)

        time.sleep(0.5)

        # Pump 5m — sắp breakout
        pumping = fetch_pump_tokens(c)
        for t in pumping:
            norm = normalize_gmgn_token(t, chain)
            if norm and 50_000 <= norm["mc"] <= 5_000_000 and norm["p1h"] < 200:
                norm["pumping_5m"] = True
                results.append(norm)

        time.sleep(0.5)

    # Dedupe by address
    seen = set()
    deduped = []
    for r in results:
        if r["address"] not in seen:
            seen.add(r["address"])
            deduped.append(r)

    logger.info(f"GMGN hunt: {len(deduped)} unique tokens across {chains}")
    return deduped
