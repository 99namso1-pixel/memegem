"""
wallet_tracker.py — Whale Wallet Tracker
Quét tất cả token một ví đã trade
Phát hiện token đang accumulation chưa pump
Alert breakout signal
"""

import requests, time, logging, json, urllib3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

DEX_BASE  = "https://api.dexscreener.com"
GMGN_BASE = "https://gmgn.ai"

# File lưu tracked wallets + tokens
WALLET_FILE  = Path("logs/tracked_wallets.json")
WATCHLIST_FILE = Path("logs/wallet_watchlist.json")
WALLET_FILE.parent.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────
@dataclass
class WalletToken:
    address: str
    ticker: str
    name: str
    chain: str
    wallet: str          # wallet đã trade
    # Metrics
    mc: float = 0
    liq: float = 0
    vol24: float = 0
    vol6: float = 0
    vol1: float = 0
    p1h: float = 0
    p6h: float = 0
    p24h: float = 0
    buys24: int = 0
    sells24: int = 0
    bs_ratio: float = 1.0
    vol_accel: float = 0.0
    age_days: float = 0.0
    dex_url: str = ""
    # Wallet trade info
    wallet_avg_buy: float = 0
    wallet_pnl_pct: float = 0
    wallet_still_holding: bool = False
    wallet_position_size: float = 0
    # Status
    phase: str = "unknown"
    accum_score: float = 0.0
    is_accumulating: bool = False
    breakout_detected: bool = False
    last_checked: float = 0.0
    added_at: float = 0.0
    signals: list = field(default_factory=list)


@dataclass
class WalletScan:
    wallet: str
    chain: str
    total_tokens: int = 0
    accumulating: list = field(default_factory=list)  # WalletToken list
    pumped: list = field(default_factory=list)
    dead: list = field(default_factory=list)
    scan_time: float = 0.0


# ─────────────────────────────────────────────
# FETCH WALLET TRADES — GMGN
# ─────────────────────────────────────────────
def fetch_wallet_tokens_gmgn(wallet: str, chain: str = "base") -> list:
    """Lấy tất cả tokens wallet đã trade từ GMGN."""
    tokens = []
    chain_map = {"base": "base", "ethereum": "eth", "solana": "sol"}
    c = chain_map.get(chain, "base")

    # GMGN wallet portfolio
    endpoints = [
        f"/api/v1/wallet_holdings/{c}/{wallet}?orderby=last_active_timestamp&direction=desc&limit=50",
        f"/api/v1/wallet_token_list/{c}/{wallet}?limit=50",
        f"/defi/quotation/v1/wallet/{c}/{wallet}/tokens?limit=50",
    ]

    for ep in endpoints:
        try:
            r = SESSION.get(f"{GMGN_BASE}{ep}", timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == 0:
                    items = (data.get("data") or {})
                    if isinstance(items, dict):
                        items = items.get("holdings") or items.get("tokens") or []
                    if isinstance(items, list) and items:
                        tokens.extend(items)
                        logger.info(f"GMGN wallet {wallet[:8]}: {len(items)} tokens from {ep}")
                        break
        except Exception as e:
            logger.debug(f"GMGN wallet {ep}: {e}")
        time.sleep(0.3)

    return tokens


def fetch_wallet_trades_dex(wallet: str, chain: str = "base") -> list:
    """Lấy trades từ Dexscreener (backup)."""
    try:
        r = SESSION.get(
            f"{DEX_BASE}/latest/dex/wallets/{chain}/{wallet}",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("tokens") or data.get("trades") or []
    except Exception as e:
        logger.debug(f"Dex wallet: {e}")
    return []


def fetch_token_current_data(address: str, chain: str) -> Optional[dict]:
    """Lấy data hiện tại của token từ Dexscreener."""
    try:
        r = SESSION.get(
            f"{DEX_BASE}/tokens/v1/{chain}/{address}",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            pairs = data if isinstance(data, list) else (data or {}).get("pairs", [])
            if pairs:
                # Lấy pair có liquidity cao nhất
                best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0))
                return best
    except Exception as e:
        logger.debug(f"Token data {address}: {e}")
    return None


# ─────────────────────────────────────────────
# ACCUMULATION DETECTOR cho wallet tokens
# ─────────────────────────────────────────────
def detect_accumulation(pair: dict, wallet: str) -> Optional[WalletToken]:
    """Phát hiện token đang accumulation từ pair data."""
    if not pair or not pair.get("baseToken"):
        return None

    base = pair.get("baseToken", {})
    mc   = float(pair.get("fdv") or pair.get("marketCap") or 0)
    liq  = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24= float((pair.get("volume") or {}).get("h24") or 0)
    vol6 = float((pair.get("volume") or {}).get("h6")  or 0)
    vol1 = float((pair.get("volume") or {}).get("h1")  or 0)
    p1h  = float((pair.get("priceChange") or {}).get("h1")  or 0)
    p6h  = float((pair.get("priceChange") or {}).get("h6")  or 0)
    p24h = float((pair.get("priceChange") or {}).get("h24") or 0)
    buys = int((pair.get("txns") or {}).get("h24", {}).get("buys",  0) or 0)
    sells= int((pair.get("txns") or {}).get("h24", {}).get("sells", 0) or 0)
    created = pair.get("pairCreatedAt")
    age_days= ((time.time()*1000 - created) / 86_400_000) if created else 999
    chain = (pair.get("chainId") or "").lower()

    # Hard filter
    if mc > 50_000_000: return None   # đã quá lớn
    if liq < 5_000:     return None   # không đủ liq
    if p24h > 500:      return None   # đã pump mạnh rồi
    if p24h < -80:      return None   # đang chết

    bs = (buys/sells) if sells > 0 else (9.0 if buys > 0 else 1.0)
    va = (vol1/(vol6/6)) if vol6 > 0 and vol1 > 0 else 0.0
    vmc= (vol24/mc) if mc > 0 else 0

    score = 0.0
    signals = []
    phase = "unknown"

    # Accumulation patterns
    # 1. Flat base + vol thấp (AGENT pattern)
    if abs(p24h) < 20 and vmc < 0.15 and liq >= 30_000:
        score += 3.0
        signals.append(f"😴 Dead vol accum: giá flat, vol thấp, liq tốt")
        phase = "accumulation"

    # 2. Stealth accum (MANIFEST/TOLYBOT pattern)
    if abs(p24h) < 30 and bs >= 1.1 and vmc >= 0.2 and age_days >= 0.5:
        score += 2.5
        signals.append(f"🐋 Stealth: buys {bs:.1f}x sells, vol đều {age_days:.1f}d")
        phase = "accumulation"

    # 3. Flat base sắp bứt (MOLT/WORLDCUP pattern)
    if abs(p6h) < 15 and abs(p24h) < 40 and (vol6/max(vol24,1)) < 0.4:
        score += 2.0
        signals.append(f"📦 Flat base: giá sideways, vol thấp 6h")
        phase = "accumulation"

    # 4. MC nhỏ + liq tốt = potential
    if mc < 200_000 and liq >= 20_000:
        score += 2.0
        signals.append(f"🎯 Micro cap ${mc/1000:.0f}K với liq ${liq/1000:.0f}K")
    elif mc < 500_000 and liq >= 30_000:
        score += 1.5
        signals.append(f"📊 Small cap ${mc/1000:.0f}K")

    # 5. Vol đang build up
    if va > 1.5:
        score += 1.5
        signals.append(f"⚡ Vol accel {va:.1f}x — tiền đang vào")

    # Filters — không phải accum
    if p24h > 100:
        return None   # đã pump
    if bs < 0.8:
        score -= 1.5
        signals.append("⚠️ Sells > Buys")

    if score < 3.0 or not signals:
        return None

    score = min(10.0, round(score, 1))

    wt = WalletToken(
        address    = base.get("address", ""),
        ticker     = base.get("symbol", "???"),
        name       = base.get("name") or base.get("symbol") or "",
        chain      = chain,
        wallet     = wallet,
        mc=mc, liq=liq, vol24=vol24, vol6=vol6, vol1=vol1,
        p1h=p1h, p6h=p6h, p24h=p24h,
        buys24=buys, sells24=sells,
        bs_ratio   = round(bs, 2),
        vol_accel  = round(va, 2),
        age_days   = round(age_days, 2),
        dex_url    = pair.get("url") or f"https://dexscreener.com/{chain}/{pair.get('pairAddress','')}",
        phase      = phase,
        accum_score= score,
        is_accumulating = score >= 3.0,
        last_checked= time.time(),
        added_at   = time.time(),
        signals    = signals,
    )
    return wt


# ─────────────────────────────────────────────
# BREAKOUT DETECTOR
# ─────────────────────────────────────────────
def detect_breakout(wt: WalletToken, pair: dict) -> bool:
    """Check xem token đã breakout khỏi accumulation chưa."""
    if not pair: return False

    mc_new  = float(pair.get("fdv") or pair.get("marketCap") or 0)
    p1h_new = float((pair.get("priceChange") or {}).get("h1",  0) or 0)
    p6h_new = float((pair.get("priceChange") or {}).get("h6",  0) or 0)
    vol6_new= float((pair.get("volume") or {}).get("h6", 0) or 0)
    vol1_new= float((pair.get("volume") or {}).get("h1", 0) or 0)
    buys_new= int((pair.get("txns") or {}).get("h1", {}).get("buys", 0) or 0)
    sells_new=int((pair.get("txns") or {}).get("h1", {}).get("sells", 0) or 0)

    va_new = (vol1_new / (vol6_new/6)) if vol6_new > 0 and vol1_new > 0 else 0

    # Breakout conditions
    breakout_signals = []

    # 1. Vol đột biến
    if va_new >= 3.0:
        breakout_signals.append(f"⚡ Vol spike {va_new:.1f}x")

    # 2. Giá 1h bứt mạnh
    if p1h_new >= 15:
        breakout_signals.append(f"🚀 Giá +{p1h_new:.0f}% trong 1h")

    # 3. Buy pressure tăng
    if sells_new > 0 and (buys_new/sells_new) >= 3:
        breakout_signals.append(f"🐋 B/S 1h = {buys_new/sells_new:.1f}x")

    # 4. MC tăng đáng kể so với khi detect
    mc_change = (mc_new / max(wt.mc, 1)) - 1
    if mc_change >= 0.3:
        breakout_signals.append(f"📈 MC tăng +{mc_change*100:.0f}% từ lúc detect")

    # Cần ít nhất 2 signals để confirm breakout
    return len(breakout_signals) >= 2


# ─────────────────────────────────────────────
# MAIN WALLET SCANNER
# ─────────────────────────────────────────────
def scan_wallet(wallet: str, chains: list = None) -> WalletScan:
    """Scan tất cả tokens một wallet đã trade."""
    if chains is None:
        chains = ["base", "ethereum", "solana"]

    result = WalletScan(wallet=wallet, chain="multi", scan_time=time.time())
    all_token_addresses = set()
    all_pairs = []

    for chain in chains:
        # Lấy tokens từ GMGN
        gmgn_tokens = fetch_wallet_tokens_gmgn(wallet, chain)
        for t in gmgn_tokens:
            addr = (t.get("token") or {}).get("address") or t.get("address") or t.get("token_address") or ""
            if addr and addr not in all_token_addresses:
                all_token_addresses.add(addr)

        # Lấy từ Dexscreener backup
        dex_tokens = fetch_wallet_trades_dex(wallet, chain)
        for t in dex_tokens:
            addr = t.get("address") or t.get("tokenAddress") or ""
            if addr and addr not in all_token_addresses:
                all_token_addresses.add(addr)

        time.sleep(0.5)

    logger.info(f"Wallet {wallet[:8]}: {len(all_token_addresses)} unique tokens found")
    result.total_tokens = len(all_token_addresses)

    # Fetch current data cho mỗi token
    for addr in list(all_token_addresses)[:100]:  # max 100 tokens
        for chain in chains:
            pair = fetch_token_current_data(addr, chain)
            if pair:
                wt = detect_accumulation(pair, wallet)
                if wt:
                    result.accumulating.append(wt)
                    logger.info(f"  ACCUM: ${wt.ticker} MC=${wt.mc/1000:.0f}K score={wt.accum_score}")
                else:
                    # Check nếu đã pump
                    p24h = float((pair.get("priceChange") or {}).get("h24", 0) or 0)
                    if p24h > 100:
                        result.pumped.append(addr)
                    else:
                        result.dead.append(addr)
                break
        time.sleep(0.2)

    # Sort by accum score
    result.accumulating.sort(key=lambda x: x.accum_score, reverse=True)
    return result


# ─────────────────────────────────────────────
# WATCHLIST MANAGEMENT
# ─────────────────────────────────────────────
def load_watchlist() -> dict:
    """Load watchlist từ file."""
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except: pass
    return {"wallets": {}, "tokens": {}}


def save_watchlist(wl: dict):
    WATCHLIST_FILE.write_text(json.dumps(wl, indent=2, default=str))


def add_wallet_to_watchlist(wallet: str, chains: list = None):
    """Thêm wallet vào watchlist để theo dõi."""
    wl = load_watchlist()
    wl["wallets"][wallet] = {
        "added_at": time.time(),
        "chains": chains or ["base", "ethereum", "solana"],
        "last_scan": 0,
        "tokens_watching": [],
    }
    save_watchlist(wl)
    logger.info(f"Added wallet {wallet[:12]} to watchlist")


def add_token_to_watchlist(wt: WalletToken):
    """Thêm token đang accumulation vào watchlist."""
    wl = load_watchlist()
    key = f"{wt.address}_{wt.chain}"
    wl["tokens"][key] = {
        "address":    wt.address,
        "ticker":     wt.ticker,
        "name":       wt.name,
        "chain":      wt.chain,
        "wallet":     wt.wallet,
        "mc_at_add":  wt.mc,
        "score":      wt.accum_score,
        "phase":      wt.phase,
        "signals":    wt.signals,
        "dex_url":    wt.dex_url,
        "added_at":   time.time(),
        "breakout_alerted": False,
        "last_mc":    wt.mc,
        "last_checked": time.time(),
    }
    save_watchlist(wl)
    logger.info(f"Added ${wt.ticker} to token watchlist (MC=${wt.mc/1000:.0f}K)")


def check_watchlist_breakouts() -> list:
    """Check tất cả tokens trong watchlist có breakout không."""
    wl = load_watchlist()
    alerts = []

    for key, tok in wl["tokens"].items():
        if tok.get("breakout_alerted"):
            continue   # đã alert rồi

        pair = fetch_token_current_data(tok["address"], tok["chain"])
        if not pair: continue

        mc_new  = float(pair.get("fdv") or pair.get("marketCap") or 0)
        p1h_new = float((pair.get("priceChange") or {}).get("h1", 0) or 0)
        vol6_new= float((pair.get("volume") or {}).get("h6", 0) or 0)
        vol1_new= float((pair.get("volume") or {}).get("h1", 0) or 0)
        buys1h  = int((pair.get("txns") or {}).get("h1", {}).get("buys", 0) or 0)
        sells1h = int((pair.get("txns") or {}).get("h1", {}).get("sells", 0) or 0)
        va_new  = (vol1_new/(vol6_new/6)) if vol6_new > 0 and vol1_new > 0 else 0

        mc_change = ((mc_new / max(tok["mc_at_add"], 1)) - 1) * 100
        bs1h = (buys1h/sells1h) if sells1h > 0 else (9 if buys1h > 0 else 1)

        breakout_sigs = []
        if va_new >= 3.0:    breakout_sigs.append(f"⚡ Vol spike {va_new:.1f}x")
        if p1h_new >= 15:    breakout_sigs.append(f"🚀 +{p1h_new:.0f}% trong 1h")
        if bs1h >= 3.0:      breakout_sigs.append(f"🐋 B/S 1h = {bs1h:.1f}x")
        if mc_change >= 30:  breakout_sigs.append(f"📈 MC +{mc_change:.0f}% từ khi detect")

        if len(breakout_sigs) >= 2:
            tok["breakout_alerted"] = True
            tok["last_mc"] = mc_new
            alerts.append({
                "ticker":   tok["ticker"],
                "address":  tok["address"],
                "chain":    tok["chain"],
                "dex_url":  tok["dex_url"],
                "mc_now":   mc_new,
                "mc_add":   tok["mc_at_add"],
                "mc_change":mc_change,
                "p1h":      p1h_new,
                "va":       va_new,
                "wallet":   tok["wallet"],
                "original_signals": tok["signals"],
                "breakout_signals": breakout_sigs,
                "score":    tok["score"],
            })

        tok["last_checked"] = time.time()
        tok["last_mc"]      = mc_new
        time.sleep(0.2)

    save_watchlist(wl)
    return alerts


# ─────────────────────────────────────────────
# FORMAT ALERTS
# ─────────────────────────────────────────────
def fmt_usd(v):
    if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def format_wallet_scan_alert(result: WalletScan) -> str:
    """Format kết quả scan wallet cho Telegram."""
    lines = [
        f"{'='*36}",
        f"🔍 WALLET SCAN COMPLETE",
        f"{'='*36}",
        f"",
        f"👛 Wallet: {result.wallet[:8]}...{result.wallet[-6:]}",
        f"📊 Scanned: {result.total_tokens} tokens",
        f"🐋 Accumulating: {len(result.accumulating)}",
        f"🚀 Already pumped: {len(result.pumped)}",
        f"💀 Dead/neutral: {len(result.dead)}",
        f"",
    ]

    if result.accumulating:
        lines.append(f"{'─'*36}")
        lines.append(f"📦 TOKENS ĐANG ACCUMULATION (đã lưu watchlist):")
        lines.append("")
        for wt in result.accumulating[:10]:
            lines += [
                f"  ${wt.ticker} | {wt.chain.upper()} | Score: {wt.accum_score}/10",
                f"  MC: {fmt_usd(wt.mc)} | Liq: {fmt_usd(wt.liq)} | Age: {wt.age_days:.1f}d",
                f"  B/S: {wt.bs_ratio}x | VolAccel: {wt.vol_accel}x | 24h: {wt.p24h:+.0f}%",
            ]
            for s in wt.signals[:2]:
                lines.append(f"    {s}")
            lines.append(f"  🔗 {wt.dex_url}")
            lines.append("")

    lines += [
        f"{'─'*36}",
        f"✅ Bot sẽ alert khi bất kỳ token nào breakout!",
        f"⏱ Check mỗi 5 phút tự động",
    ]
    return "\n".join(lines)


def format_breakout_alert(alert: dict) -> str:
    """Format breakout alert cho Telegram."""
    mc_x = alert["mc_now"] / max(alert["mc_add"], 1)
    lines = [
        f"{'='*36}",
        f"🚨 BREAKOUT ALERT — WALLET WATCHLIST",
        f"{'='*36}",
        f"",
        f"${alert['ticker']} | {alert['chain'].upper()}",
        f"👛 From wallet: {alert['wallet'][:8]}...{alert['wallet'][-6:]}",
        f"",
        f"📈 BREAKOUT SIGNALS:",
    ]
    for s in alert["breakout_signals"]:
        lines.append(f"  {s}")
    lines += [
        f"",
        f"💰 MC khi detect: {fmt_usd(alert['mc_add'])}",
        f"💰 MC hiện tại:   {fmt_usd(alert['mc_now'])} (+{alert['mc_change']:.0f}%)",
        f"📊 Multiple: {mc_x:.1f}x từ khi vào watchlist",
        f"",
        f"📦 Accumulation signals lúc detect:",
    ]
    for s in alert.get("original_signals", [])[:3]:
        lines.append(f"  {s}")
    lines += [
        f"",
        f"🔗 {alert['dex_url']}",
        f"",
        f"⚠️ DYOR | High risk | Not financial advice",
    ]
    return "\n".join(lines)
