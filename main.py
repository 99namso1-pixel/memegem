"""
main.py v5 — GEM HUNTER + TWITTER MONITOR
Chạy song song: on-chain gem scanner + KOL Twitter monitor
"""

import asyncio
import logging
import os
import time
import json
from pathlib import Path
from dotenv import load_dotenv
from telegram import Bot

from scanner         import hunt_sync
from alerts          import send_gem_alerts, send_summary, send_message
from twitter_monitor import TwitterMonitor, TOP_KOLS
try:
    from gmgn import (analyze_token as gmgn_analyze,
                      set_api_key as gmgn_set_key,
                      calc_dev_score, format_dev_score)
    GMGN_AVAILABLE = True
except ImportError:
    GMGN_AVAILABLE = False
    gmgn_set_key = None

try:
    from x_monitor import get_social_score, format_social_block
    X_AVAILABLE = True
except ImportError:
    X_AVAILABLE = False

try:
    from wallet_tracker import (
        scan_wallet, add_wallet_to_watchlist, add_token_to_watchlist,
        check_watchlist_breakouts, format_wallet_scan_alert, format_breakout_alert,
        load_watchlist, save_watchlist
    )
    WALLET_TRACKER = True
except ImportError:
    WALLET_TRACKER = False

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("GemHunter")

# ── Config ──
BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
CHAINS     = os.getenv("CHAINS", "solana,base,ethereum").split(",")
GMGN_KEY   = os.getenv("GMGN_API_KEY", "")

# Set GMGN API key ngay khi load
if GMGN_AVAILABLE and GMGN_KEY and gmgn_set_key:
    gmgn_set_key(GMGN_KEY)
INTERVAL   = int(os.getenv("SCAN_INTERVAL_MINUTES", "5")) * 60
MIN_SCORE  = float(os.getenv("MIN_SCORE", "5.5"))
MIN_MC     = float(os.getenv("MIN_MC", "20000"))
MAX_MC     = float(os.getenv("MAX_MC", "5000000"))
MIN_LIQ    = float(os.getenv("MIN_LIQUIDITY", "30000"))  # liq > $30K = ít rug
MIN_BS     = float(os.getenv("MIN_BS_RATIO", "1.2"))
MIN_VA     = float(os.getenv("MIN_VOL_ACCEL", "1.0"))
MAX_RUG    = float(os.getenv("MAX_RUG_RISK", "7.5"))     # chặt rug
MIN_AGE_H  = float(os.getenv("MIN_AGE_HOURS", "0.5"))    # cho phép token 30min+
X_ENABLED  = os.getenv("X_SOCIAL_ENABLED", "true").lower() == "true"
X_TOP_N    = int(os.getenv("X_SCAN_TOP_N", "3"))
# Wallet tracker config
TRACKED_WALLETS = [w.strip() for w in os.getenv("TRACKED_WALLETS", "").split(",") if w.strip()]
WALLET_SCAN_INTERVAL = int(os.getenv("WALLET_SCAN_MINUTES", "30")) * 60

# Twitter config
TW_ENABLED  = os.getenv("TWITTER_ENABLED", "true").lower() == "true"
TW_INTERVAL = int(os.getenv("TWITTER_CHECK_MINUTES", "2")) * 60
TW_URGENCY  = os.getenv("TWITTER_MIN_URGENCY", "medium")  # low/medium/high/critical

SEEN_FILE = Path("logs/seen_gems.json")
SEEN_FILE.parent.mkdir(exist_ok=True)

def load_seen():
    if SEEN_FILE.exists():
        try: return json.loads(SEEN_FILE.read_text())
        except: pass
    return {}

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen, indent=2))

def cleanup_seen(seen, ttl_hours=6):
    cutoff = time.time() - ttl_hours * 3600
    return {k: v for k, v in seen.items() if v > cutoff}

def apply_filters(gems):
    out = []
    for g in gems:
        # Chain-specific thresholds
        if g.chain == "solana":
            min_liq   = 10_000   # SOL liq thấp hơn
            min_score = MIN_SCORE - 0.5
            max_rug   = MAX_RUG + 0.5
            min_bs    = 1.0      # SOL pump nhanh, bs ratio thấp hơn cũng ok
        elif g.chain == "base":
            min_liq   = MIN_LIQ  # BASE giữ nguyên
            min_score = MIN_SCORE
            max_rug   = MAX_RUG
            min_bs    = MIN_BS
        else:  # ethereum
            min_liq   = 20_000
            min_score = MIN_SCORE
            max_rug   = MAX_RUG
            min_bs    = MIN_BS

        if g.pre_pump_score < min_score:                  continue
        if g.mc < MIN_MC or g.mc > MAX_MC:                continue
        if g.liq < min_liq:                                continue
        if g.bs_ratio24 < min_bs:                          continue
        if g.vol_accel  < MIN_VA:                          continue
        if g.rug_risk   > max_rug:                         continue
        if g.phase in ("euphoric","dead","distribution"):  continue
        if g.age_days < (MIN_AGE_H/24) and not g.breakout_candle:
            continue
        out.append(g)
    return out


# ─────────────────────────────────────────
# GEM SCANNER LOOP
# ─────────────────────────────────────────
async def gem_scanner_loop(bot: Bot, seen: dict):
    scan_num = 0
    while True:
        t0 = time.time()
        scan_num += 1
        logger.info(f"━━ GEM Scan #{scan_num} ━━")
        try:
            loop     = asyncio.get_event_loop()
            all_gems = await loop.run_in_executor(None, hunt_sync, CHAINS)
            filtered = apply_filters(all_gems)
            seen_ref = cleanup_seen(seen)
            seen.clear(); seen.update(seen_ref)

            new_gems = [g for g in filtered if g.id not in seen]
            logger.info(f"Scan #{scan_num}: {len(all_gems)} total → {len(filtered)} filtered → {len(new_gems)} new")

            # Enrich top gems với GMGN security data (max 3 để tránh rate limit)
            if new_gems and GMGN_AVAILABLE:
                for gem in new_gems[:3]:
                    try:
                        gd = await loop.run_in_executor(
                            None, gmgn_analyze, gem.address, gem.chain)
                        gem.gmgn_rug_score    = gd.rug_score
                        gem.gmgn_quality      = gd.quality_score
                        gem.gmgn_insider_pct  = gd.insider_pct
                        gem.gmgn_dev_pct      = gd.dev_holding_pct
                        gem.gmgn_sniper_count = gd.sniper_count
                        gem.gmgn_sm_wallets   = gd.smart_money_wallets
                        gem.gmgn_kol_count    = gd.kol_count
                        gem.gmgn_lp_burned    = gd.lp_burned
                        gem.gmgn_renounced    = gd.renounced
                        gem.gmgn_honeypot     = gd.is_honeypot
                        gem.gmgn_signals      = gd.signals
                        gem.gmgn_warnings     = gd.warnings
                        # Tính Dev Quality Score
                        ds = calc_dev_score(gd)
                        gem.dev_score    = ds.onchain_score
                        gem.dev_verdict  = ds.dev_verdict
                        gem.hold_quality = ds.hold_quality
                        gem.dev_reasons  = ds.reasons
                        gem.dev_warnings = ds.warnings
                        # Honeypot = skip alert
                        if gd.is_honeypot:
                            new_gems = [g for g in new_gems if g.id != gem.id]
                            logger.warning(f"HONEYPOT filtered: ${gem.ticker}")
                    except Exception as e:
                        logger.debug(f"GMGN enrich {gem.ticker}: {e}")
                    await asyncio.sleep(0.5)

            # X/Twitter social scan cho top gems
            if new_gems and X_AVAILABLE and X_ENABLED:
                for gem in new_gems[:X_TOP_N]:
                    try:
                        ss = await loop.run_in_executor(
                            None, get_social_score,
                            gem.ticker, gem.address, gem.chain, True
                        )
                        gem.x_fomo_score   = ss.fomo_score
                        gem.x_viral_score  = ss.viral_score
                        gem.x_kol_score    = ss.kol_score
                        gem.x_social_total = ss.social_total
                        gem.x_mentions     = ss.total_mentions
                        gem.x_kol_mentions = ss.kol_mentions
                        gem.x_tier1        = ss.tier1_mentions
                        gem.x_tier2        = ss.tier2_mentions
                        gem.x_tier3        = ss.tier3_mentions
                        gem.x_top_kol      = ss.top_kol
                        gem.x_signals      = ss.signals
                        gem.x_is_viral     = ss.is_viral
                        # Bonus score nếu có KOL mention
                        if ss.tier1_mentions >= 1:
                            gem.pre_pump_score = min(10, gem.pre_pump_score + 2.0)
                            logger.info(f"🚨 TIER1 KOL mention ${gem.ticker}!")
                        elif ss.tier2_mentions >= 2:
                            gem.pre_pump_score = min(10, gem.pre_pump_score + 1.0)
                        elif ss.kol_mentions >= 1:
                            gem.pre_pump_score = min(10, gem.pre_pump_score + 0.5)
                        if ss.is_viral:
                            gem.pre_pump_score = min(10, gem.pre_pump_score + 0.5)
                    except Exception as e:
                        logger.debug(f"X scan {gem.ticker}: {e}")
                    await asyncio.sleep(1.5)

            if new_gems:
                await send_gem_alerts(bot, CHAT_ID, new_gems)
                for g in new_gems:
                    seen[g.id] = time.time()
                save_seen(seen)

            # Summary mỗi 12 scan, và chỉ khi có gems
            if scan_num % 12 == 0 and filtered:
                await send_summary(bot, CHAT_ID, filtered[:10], scan_num, len(all_gems))

        except Exception as e:
            logger.error(f"Gem scan error: {e}", exc_info=True)
            try:
                await send_message(bot, CHAT_ID, f"⚠️ Gem scan error\n{str(e)[:200]}")
            except: pass

        elapsed = time.time() - t0
        wait    = max(10, INTERVAL - elapsed)
        logger.info(f"Gem scan done in {elapsed:.1f}s → next in {wait:.0f}s")
        await asyncio.sleep(wait)


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
async def initial_wallet_scan(bot: Bot, wallets: list):
    """Scan tất cả wallets ngay khi bot start."""
    if not WALLET_TRACKER: return
    await asyncio.sleep(5)  # đợi bot connect xong
    for wallet in wallets:
        try:
            await send_message(bot, CHAT_ID,
                f"🔍 Đang scan wallet {wallet[:8]}...{wallet[-6:]}\n⏳ Quét tất cả tokens..."
            )
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, scan_wallet, wallet, ["base","ethereum","solana"]
            )
            # Lưu tokens accumulating vào watchlist
            for wt in result.accumulating:
                add_token_to_watchlist(wt)

            # Gửi summary
            msg = format_wallet_scan_alert(result)
            await send_message(bot, CHAT_ID, msg)
            logger.info(f"Wallet scan done: {wallet[:8]} → {len(result.accumulating)} accumulating")
        except Exception as e:
            logger.error(f"Wallet scan error {wallet[:8]}: {e}")
        await asyncio.sleep(2)


async def wallet_breakout_loop(bot: Bot):
    """Check breakouts cho tất cả tokens trong watchlist."""
    if not WALLET_TRACKER: return
    logger.info(f"Wallet breakout checker started (interval={WALLET_SCAN_INTERVAL}s)")
    while True:
        await asyncio.sleep(WALLET_SCAN_INTERVAL)
        try:
            loop    = asyncio.get_event_loop()
            alerts  = await loop.run_in_executor(None, check_watchlist_breakouts)
            for alert in alerts:
                msg = format_breakout_alert(alert)
                await send_message(bot, CHAT_ID, msg)
                logger.info(f"🚨 Breakout: ${alert['ticker']} +{alert['mc_change']:.0f}%")
        except Exception as e:
            logger.error(f"Wallet breakout check: {e}")


async def run():
    if not BOT_TOKEN or "xxx" in BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN chưa set trong .env"); return
    if not CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID chưa set trong .env"); return

    bot = Bot(token=BOT_TOKEN)
    try:
        me = await bot.get_me()
        logger.info(f"Bot connected: @{me.username}")
    except Exception as e:
        logger.error(f"Bot connection failed: {e}"); return

    seen = load_seen()

    # Startup message
    tw_status = f"✅ ON (check mỗi {TW_INTERVAL//60}p, min urgency: {TW_URGENCY})" if TW_ENABLED else "❌ OFF"
    await send_message(bot, CHAT_ID,
        f"💎 GEM HUNTER v5 STARTED\n\n"
        f"🔭 Chains: {', '.join(CHAINS)}\n"
        f"⏱ Gem scan: mỗi {INTERVAL//60}p\n"
        f"🐦 Twitter KOL: {tw_status}\n"
        f"🎯 Min score: {MIN_SCORE}/10\n"
        f"💰 MC: ${MIN_MC/1000:.0f}K — ${MAX_MC/1_000_000:.1f}M\n"
        f"🐋 Min B/S: {MIN_BS}x | Vol↑: {MIN_VA}x\n\n"
        f"KOLs theo dõi: {len(TOP_KOLS)} accounts\n"
        f"  Tier 1: Elon, Vitalik, CZ, Brian Armstrong\n"
        f"  Tier 2: Hayes, Cobie, LookOnChain, Murad...\n"
        f"  Tier 3: Ansem, Dingaling, Blknoiz..."
    )

    # Init tracked wallets
    if WALLET_TRACKER and TRACKED_WALLETS:
        for w in TRACKED_WALLETS:
            add_wallet_to_watchlist(w, ["base","ethereum","solana"])
        logger.info(f"Tracking {len(TRACKED_WALLETS)} wallets: {[w[:8] for w in TRACKED_WALLETS]}")
        # Initial scan ngay khi start
        asyncio.create_task(
            initial_wallet_scan(bot, TRACKED_WALLETS),
            name="wallet_init"
        )

    # Khởi động tasks song song
    tasks = [
        asyncio.create_task(
            gem_scanner_loop(bot, seen),
            name="gem_scanner"
        ),
    ]

    # Wallet breakout checker
    if WALLET_TRACKER and TRACKED_WALLETS:
        tasks.append(asyncio.create_task(
            wallet_breakout_loop(bot),
            name="wallet_tracker"
        ))

    if TW_ENABLED:
        twitter_monitor = TwitterMonitor(
            bot=bot,
            chat_id=CHAT_ID,
            kols=TOP_KOLS,
            min_urgency=TW_URGENCY,
            check_interval=TW_INTERVAL,
        )
        tasks.append(
            asyncio.create_task(
                twitter_monitor.run_loop(),
                name="twitter_monitor"
            )
        )
        logger.info(f"Twitter monitor enabled: {len(TOP_KOLS)} KOLs, interval={TW_INTERVAL}s")

    # Chạy cả 2 song song, nếu 1 crash thì restart
    while True:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            name = task.get_name()
            try:
                task.result()
            except Exception as e:
                logger.error(f"Task {name} crashed: {e}")
                await asyncio.sleep(5)
                # Restart task
                if name == "gem_scanner":
                    tasks = [t for t in pending]
                    tasks.append(asyncio.create_task(
                        gem_scanner_loop(bot, seen), name="gem_scanner"
                    ))
                elif name == "twitter_monitor" and TW_ENABLED:
                    tasks = [t for t in pending]
                    tasks.append(asyncio.create_task(
                        twitter_monitor.run_loop(), name="twitter_monitor"
                    ))


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
