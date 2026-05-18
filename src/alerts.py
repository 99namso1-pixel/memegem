"""
alerts.py — Format và gửi Telegram alerts
"""

import logging
from telegram import Bot
from telegram.constants import ParseMode
from scanner import Gem

logger = logging.getLogger(__name__)

PHASE_ICON = {
    "stealth":      "👁",
    "accumulation": "🐋",
    "expansion":    "🚀",
    "euphoric":     "🌕",
    "distribution": "🚨",
    "dead":         "💀",
    "unknown":      "❓",
}

CHAIN_EMOJI = {
    "solana":   "◎",
    "ethereum": "Ξ",
    "base":     "🔵",
    "bsc":      "🟡",
    "arbitrum": "🔷",
}

def score_bar(score: float, max_val: float = 10) -> str:
    """Visual bar cho score."""
    filled = int((score / max_val) * 10)
    return "█" * filled + "░" * (10 - filled)


def fmt_usd(v: float) -> str:
    if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
    if v >= 1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def fmt_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def build_alert_message(gem: Gem, rank: int = 1) -> str:
    """Build Telegram message cho một gem."""
    chain_e = CHAIN_EMOJI.get(gem.chain, "⬡")
    phase_i = PHASE_ICON.get(gem.phase, "❓")
    score   = gem.pre_pump_score
    rug     = gem.rug_risk

    # Score color via emoji
    if score >= 8:   score_e = "🟢"
    elif score >= 6: score_e = "🟡"
    else:            score_e = "🔴"

    if rug <= 4:   rug_e = "🟢"
    elif rug <= 6: rug_e = "🟡"
    else:          rug_e = "🔴"

    # BS ratio color
    bs = gem.bs_ratio24
    if bs >= 3:   bs_e = "🐋"
    elif bs >= 2: bs_e = "✅"
    elif bs >= 1: bs_e = "📊"
    else:         bs_e = "🚨"

    lines = [
        f"💎 *GEM ALERT #{rank}*",
        f"",
        f"*${gem.ticker}* {chain_e} `{gem.chain.upper()}`  {phase_i} `{gem.phase.upper()}`",
        f"📛 {gem.name}",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"📊 *METRICS*",
        f"• MC:        `{fmt_usd(gem.mc)}`",
        f"• Liquidity: `{fmt_usd(gem.liq)}`",
        f"• Vol 24h:   `{fmt_usd(gem.vol24)}`",
        f"• Vol 1h:    `{fmt_usd(gem.vol1)}`",
        f"",
        f"📈 *PRICE ACTION*",
        f"• 1h:  `{fmt_pct(gem.p1h)}`",
        f"• 6h:  `{fmt_pct(gem.p6h)}`",
        f"• 24h: `{fmt_pct(gem.p24h)}`",
        f"",
        f"🔄 *ON-CHAIN*",
        f"• B/S 24h: {bs_e} `{gem.bs_ratio24}x`  (Buys: {gem.buys24} | Sells: {gem.sells24})",
        f"• B/S 1h:  `{gem.bs_ratio1h}x`",
        f"• Vol Accel: `{gem.vol_accel}x`",
        f"• VOL/MC:    `{gem.vol_mc_ratio}x`",
        f"• Age:       `{gem.age_days}d`",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🤖 *BOT SCORES*",
        f"{score_e} Pre\\-Pump: `{score}/10`  {score_bar(score)}",
        f"{rug_e} Rug Risk: `{rug}/10`   {score_bar(rug)}",
        f"",
    ]

    # Signals
    if gem.signals:
        lines.append("✅ *SIGNALS*")
        for s in gem.signals[:5]:
            lines.append(f"  {s}")
        lines.append("")

    # Warnings
    if gem.warnings:
        lines.append("⚠️ *WARNINGS*")
        for w in gem.warnings:
            lines.append(f"  {w}")
        lines.append("")

    # Links
    lines += [
        f"━━━━━━━━━━━━━━━━━━━━",
        f"🔗 [Dexscreener]({gem.dex_url})",
    ]
    if gem.chain == "solana":
        lines.append(f"🦅 [Birdeye](https://birdeye.so/token/{gem.address})")
        lines.append(f"🔍 [Solscan](https://solscan.io/token/{gem.address})")
    elif gem.chain in ("ethereum", "base"):
        lines.append(f"🔍 [Etherscan](https://etherscan.io/token/{gem.address})")

    lines += [
        f"",
        f"`{gem.address}`",
        f"",
        f"⚠️ _DYOR \\| Not financial advice \\| High risk_",
    ]

    return "\n".join(lines)


def build_scan_summary(gems: list, scan_num: int, total_scanned: int) -> str:
    """Summary message sau mỗi lần scan."""
    if not gems:
        return (
            f"🔍 *Scan \\#{scan_num} complete*\n"
            f"Scanned {total_scanned} pairs\n"
            f"No qualifying gems found this round\\."
        )

    top3 = gems[:3]
    lines = [
        f"🔍 *Scan \\#{scan_num} — {len(gems)} gems found*",
        f"",
        f"*TOP 3 PRE\\-PUMP CANDIDATES:*",
        f"",
    ]
    for i, g in enumerate(top3, 1):
        phase_i = PHASE_ICON.get(g.phase, "❓")
        score_e = "🟢" if g.pre_pump_score >= 8 else "🟡" if g.pre_pump_score >= 6 else "🔴"
        lines.append(
            f"{i}\\. {score_e} *${g.ticker}* `{g.chain.upper()}` "
            f"\\| Score: `{g.pre_pump_score}/10` "
            f"\\| MC: `{fmt_usd(g.mc)}` "
            f"\\| {phase_i} `{g.phase}`"
        )
        lines.append(
            f"   B/S: `{g.bs_ratio24}x` \\| Vol↑: `{g.vol_accel}x` "
            f"\\| 24h: `{fmt_pct(g.p24h)}`"
        )
        lines.append(f"   [Chart]({g.dex_url})")
        lines.append("")

    lines.append(f"_Scanned {total_scanned} pairs from Dexscreener_")
    return "\n".join(lines)


async def send_message(bot: Bot, chat_id: str, text: str):
    """Gửi message, tự escape nếu cần."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"send_message failed: {e}")
        # Fallback: gửi plain text
        try:
            plain = text.replace("*", "").replace("`", "").replace("_", "").replace("\\", "")
            await bot.send_message(chat_id=chat_id, text=plain, disable_web_page_preview=True)
        except Exception as e2:
            logger.error(f"plain fallback failed: {e2}")


async def send_gem_alerts(bot: Bot, chat_id: str, new_gems: list[Gem]):
    """Gửi alert cho từng gem mới."""
    for i, gem in enumerate(new_gems[:5], 1):  # max 5 alerts per scan
        msg = build_alert_message(gem, rank=i)
        await send_message(bot, chat_id, msg)
        await asyncio.sleep(0.5)  # tránh flood


async def send_summary(bot: Bot, chat_id: str, gems: list, scan_num: int, total: int):
    msg = build_scan_summary(gems, scan_num, total)
    await send_message(bot, chat_id, msg)


import asyncio
