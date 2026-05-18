"""
scanner.py — Pre-Pump Gem Detection Engine
Fetch data từ Dexscreener, score theo accumulation signals
"""

import aiohttp
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

DEX_BASE = "https://api.dexscreener.com"

CHAIN_LABEL = {
    "solana": "SOL", "ethereum": "ETH", "base": "BASE",
    "bsc": "BSC", "arbitrum": "ARB",
}

@dataclass
class Gem:
    id: str
    ticker: str
    name: str
    chain: str
    address: str
    pair_address: str
    dex_id: str
    price: float
    dex_url: str

    mc: float = 0
    liq: float = 0
    vol24: float = 0
    vol6: float = 0
    vol1: float = 0
    p5m: float = 0
    p1h: float = 0
    p6h: float = 0
    p24h: float = 0

    buys24: int = 0
    sells24: int = 0
    buys1h: int = 0
    sells1h: int = 0
    bs_ratio24: float = 1.0
    bs_ratio1h: float = 1.0
    vol_accel: float = 0.0
    vol_mc_ratio: float = 0.0
    liq_mc_ratio: float = 0.0
    age_days: float = 0.0

    boost_amount: float = 0
    has_website: bool = False
    has_socials: bool = False

    pre_pump_score: float = 0
    rug_risk: float = 5.0
    phase: str = "unknown"
    signals: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


async def dex_get(session: aiohttp.ClientSession, path: str):
    url = f"{DEX_BASE}{path}"
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
        if r.status == 200:
            return await r.json()
        return None


def score_gem(pair: dict, boost_map: dict) -> Optional[Gem]:
    """Score một pair theo pre-pump signals. Return None nếu không đủ điều kiện."""
    base = pair.get("baseToken", {})
    if not base.get("address"):
        return None

    mc    = pair.get("fdv") or pair.get("marketCap") or 0
    liq   = (pair.get("liquidity") or {}).get("usd", 0) or 0
    vol24 = (pair.get("volume") or {}).get("h24", 0) or 0
    vol6  = (pair.get("volume") or {}).get("h6",  0) or 0
    vol1  = (pair.get("volume") or {}).get("h1",  0) or 0
    p5m   = float((pair.get("priceChange") or {}).get("m5",  0) or 0)
    p1h   = float((pair.get("priceChange") or {}).get("h1",  0) or 0)
    p6h   = float((pair.get("priceChange") or {}).get("h6",  0) or 0)
    p24h  = float((pair.get("priceChange") or {}).get("h24", 0) or 0)

    txns   = pair.get("txns") or {}
    buys24 = (txns.get("h24") or {}).get("buys",  0) or 0
    sells24= (txns.get("h24") or {}).get("sells", 0) or 0
    buys1h = (txns.get("h1")  or {}).get("buys",  0) or 0
    sells1h= (txns.get("h1")  or {}).get("sells", 0) or 0

    created = pair.get("pairCreatedAt")
    import time
    age_ms   = (time.time() * 1000 - created) if created else None
    age_days = (age_ms / 86_400_000) if age_ms else 999

    # ── Loại ngay ──
    if liq   < 15_000:  return None
    if mc    > 20_000_000: return None
    if mc    < 30_000:  return None
    if p24h  > 600:     return None
    if p24h  < -60:     return None

    total    = 0.0
    signals  = []
    warnings = []

    bs24 = (buys24 / sells24) if sells24 > 0 else (9.0 if buys24 > 0 else 1.0)
    bs1h = (buys1h / sells1h) if sells1h > 0 else (9.0 if buys1h > 0 else 1.0)
    vol_accel   = (vol1 / (vol6 / 6)) if vol6 > 0 and vol1 > 0 else 0.0
    vol_mc      = (vol24 / mc) if mc > 0 else 0.0
    liq_mc      = (liq  / mc) if mc > 0 else 0.0

    # Signal 1: Micro cap
    if mc < 500_000:
        total += 2; signals.append("🎯 Micro cap <$500K — room 10x+")
    elif mc < 2_000_000:
        total += 1.5; signals.append("📊 Small cap $500K–$2M")
    elif mc < 5_000_000:
        total += 1; signals.append("📈 Mid cap $2M–$5M")

    # Signal 2: Volume acceleration
    if vol_accel > 3:
        total += 2.5; signals.append(f"⚡ Vol tăng {vol_accel:.1f}x — tiền đột biến")
    elif vol_accel > 1.5:
        total += 1.5; signals.append(f"📊 Vol picking up {vol_accel:.1f}x")

    # Signal 3: VOL/MC
    if vol_mc > 2:
        total += 2; signals.append(f"🔥 VOL/MC={vol_mc:.1f}x — cực active")
    elif vol_mc > 0.5:
        total += 1; signals.append(f"✅ VOL/MC={vol_mc:.1f}x — healthy")

    # Signal 4: Buy pressure
    if bs24 > 4:
        total += 2.5; signals.append(f"🐋 Buy/Sell 24h={bs24:.1f}x — whale gom")
    elif bs24 > 2:
        total += 1.5; signals.append(f"✅ Buy/Sell 24h={bs24:.1f}x — buyers dominant")
    elif bs24 > 1.2:
        total += 0.5; signals.append(f"📊 Buy/Sell 24h={bs24:.1f}x")
    if bs1h > 3:
        total += 1.5; signals.append(f"⚡ 1h B/S={bs1h:.1f}x — đang tăng tốc NOW")

    # Signal 5: Accumulation pattern
    if abs(p24h) < 30 and vol_mc > 0.3 and bs24 > 1.5:
        total += 2; signals.append("🐋 ACCUMULATION: giá flat, vol cao, buys > sells")

    # Signal 6: Liquidity
    if liq_mc > 0.15:
        total += 1; signals.append(f"💧 Liq ratio {liq_mc*100:.0f}% — safe exit")
    elif liq > 100_000:
        total += 1; signals.append(f"💧 Liq ${liq/1000:.0f}K — OK")

    # Signal 7: Token age
    if age_days < 2:
        total += 1; signals.append(f"🆕 Token <2 ngày — very early")
    elif age_days < 7:
        total += 0.5; signals.append(f"📅 Token {int(age_days)}d — early")

    # Signal 8: Price not pumped yet
    if 0 <= p24h <= 10:
        total += 1.5; signals.append(f"😴 Giá flat — chưa ai biết")
    elif 10 < p24h < 100:
        total += 1; signals.append(f"📈 +{p24h:.0f}% — nhẹ, chưa FOMO")
    elif -20 < p24h < 0:
        total += 0.5; signals.append(f"📉 Dip {p24h:.0f}% — buy zone")

    # Signal 9: 1h breakout starting
    if 15 < p1h < 100 and p24h < 200:
        total += 1.5; signals.append(f"🚀 1h bứt phá +{p1h:.0f}%")

    # Warnings
    if liq < 30_000:    warnings.append("⚠️ Liq thấp <$30K")
    if liq_mc < 0.05:   warnings.append("⚠️ Liq/MC <5%")
    if age_days < 0.5:  warnings.append("⚠️ Token <12h — cực rủi ro")
    if bs24 < 0.8:      warnings.append("🚨 Sells > Buys — phân phối")
    if p24h > 300:      warnings.append("🚨 Đã pump >300%")

    total = min(10.0, max(0.0, round(total, 1)))

    # Rug risk
    rug = 4.0
    if liq   < 20_000:  rug += 2.5
    elif liq < 50_000:  rug += 1.0
    if liq_mc < 0.05:   rug += 1.5
    if age_days < 1:    rug += 1.5
    if bs24 < 0.8:      rug += 1.0
    if liq > 150_000:   rug -= 1.5
    rug = min(10.0, max(1.0, round(rug, 1)))

    # Phase
    if p24h > 200 or mc > 10_000_000:         phase = "euphoric"
    elif p24h > 50  or mc > 3_000_000:        phase = "expansion"
    elif vol_mc > 0.3 and bs24 > 1.5:         phase = "accumulation"
    elif p24h < -30:                           phase = "distribution"
    elif mc < 500_000:                         phase = "stealth"
    else:                                      phase = "accumulation"

    chain = (pair.get("chainId") or "").lower()
    addr  = base.get("address", "")
    boost = boost_map.get(addr, {})

    return Gem(
        id           = addr + chain,
        ticker       = base.get("symbol", "???"),
        name         = base.get("name") or base.get("symbol") or "Unknown",
        chain        = chain,
        address      = addr,
        pair_address = pair.get("pairAddress", ""),
        dex_id       = pair.get("dexId", ""),
        price        = float(pair.get("priceUsd") or 0),
        dex_url      = pair.get("url") or f"https://dexscreener.com/{chain}/{pair.get('pairAddress','')}",
        mc=mc, liq=liq, vol24=vol24, vol6=vol6, vol1=vol1,
        p5m=p5m, p1h=p1h, p6h=p6h, p24h=p24h,
        buys24=buys24, sells24=sells24, buys1h=buys1h, sells1h=sells1h,
        bs_ratio24   = round(bs24,  2),
        bs_ratio1h   = round(bs1h,  2),
        vol_accel    = round(vol_accel, 2),
        vol_mc_ratio = round(vol_mc,    2),
        liq_mc_ratio = round(liq_mc,    2),
        age_days     = round(age_days,  1),
        boost_amount = boost.get("amount", 0),
        has_website  = bool((pair.get("info") or {}).get("websites")),
        has_socials  = bool((pair.get("info") or {}).get("socials")),
        pre_pump_score = total,
        rug_risk     = rug,
        phase        = phase,
        signals      = signals,
        warnings     = warnings,
    )


async def hunt(session: aiohttp.ClientSession, chains: list[str]) -> list[Gem]:
    """Main hunt function — fetch + score tất cả gems."""
    all_pairs = []
    boost_map = {}

    # 1. Boost map
    try:
        data = await dex_get(session, "/token-boosts/top/v1")
        if isinstance(data, list):
            for b in data:
                if b.get("tokenAddress"):
                    boost_map[b["tokenAddress"]] = b
    except Exception as e:
        logger.warning(f"boost fetch: {e}")

    # 2. Latest profiles
    try:
        profiles = await dex_get(session, "/token-profiles/latest/v1")
        if isinstance(profiles, list):
            by_chain = {}
            for p in profiles[:60]:
                c = p.get("chainId", "")
                if c not in chains: continue
                addr = p.get("tokenAddress", "")
                if addr:
                    by_chain.setdefault(c, []).append(addr)

            for chain, addrs in by_chain.items():
                chunk = ",".join(addrs[:25])
                try:
                    data = await dex_get(session, f"/tokens/v1/{chain}/{chunk}")
                    pairs = data if isinstance(data, list) else (data or {}).get("pairs", [])
                    all_pairs.extend(pairs or [])
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logger.warning(f"tokens fetch {chain}: {e}")
    except Exception as e:
        logger.warning(f"profiles fetch: {e}")

    # 3. Search hidden gems
    queries = ["new", "ai", "dog", "cat", "inu", "moon", "baby"]
    for q in queries[:4]:
        try:
            data = await dex_get(session, f"/latest/dex/search?q={q}")
            pairs = (data or {}).get("pairs", [])
            micro = [p for p in pairs if
                     (p.get("fdv") or p.get("marketCap") or 0) < 3_000_000 and
                     (p.get("liquidity") or {}).get("usd", 0) > 15_000]
            all_pairs.extend(micro[:8])
            await asyncio.sleep(0.25)
        except Exception as e:
            logger.warning(f"search {q}: {e}")

    # 4. Score & dedupe
    seen  = set()
    gems  = []
    for pair in all_pairs:
        if not isinstance(pair, dict): continue
        addr  = (pair.get("baseToken") or {}).get("address", "")
        chain = (pair.get("chainId") or "").lower()
        key   = addr + chain
        if key in seen or not addr: continue
        seen.add(key)
        gem = score_gem(pair, boost_map)
        if gem and gem.pre_pump_score >= 3.0:
            gems.append(gem)

    gems.sort(key=lambda g: g.pre_pump_score, reverse=True)
    logger.info(f"Hunt done: {len(all_pairs)} pairs scanned → {len(gems)} qualified gems")
    return gems[:50]
