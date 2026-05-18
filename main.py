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

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("GemHunter")

# ── Config ──
BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "8866269665:AAHqlzjHQBuGu8i7NBulmlgsc5E2PBLE5To")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "-1003994722259")
CHAINS     = os.getenv("CHAINS", "solana,base,ethereum").split(",")
INTERVAL   = int(os.getenv("SCAN_INTERVAL_MINUTES", "5")) * 60
MIN_SCORE  = float(os.getenv("MIN_SCORE", "5.0"))
MIN_MC     = float(os.getenv("MIN_MC", "30000"))
MAX_MC     = float(os.getenv("MAX_MC", "5000000"))
MIN_LIQ    = float(os.getenv("MIN_LIQUIDITY", "15000"))
MIN_BS     = float(os.getenv("MIN_BS_RATIO", "1.2"))
MIN_VA     = float(os.getenv("MIN_VOL_ACCEL", "1.0"))
MAX_RUG    = float(os.getenv("MAX_RUG_RISK", "8.0"))

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
        if g.pre_pump_score < MIN_SCORE:         continue
        if g.mc < MIN_MC or g.mc > MAX_MC:       continue
        if g.liq < MIN_LIQ:                       continue
        if g.bs_ratio24 < MIN_BS:                 continue
        if g.vol_accel  < MIN_VA:                 continue
        if g.rug_risk   > MAX_RUG:                continue
        if g.phase in ("euphoric","dead","distribution"): continue
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

            if new_gems:
                await send_gem_alerts(bot, CHAT_ID, new_gems)
                for g in new_gems:
                    seen[g.id] = time.time()
                save_seen(seen)

            if scan_num % 6 == 0:
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

    # Khởi động 2 tasks song song
    tasks = [
        asyncio.create_task(
            gem_scanner_loop(bot, seen),
            name="gem_scanner"
        ),
    ]

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
