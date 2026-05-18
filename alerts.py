"""
alerts.py v5 — Alert với TP engine cải thiện + success rate + AEON comparison
"""
import logging, asyncio
from telegram import Bot

logger = logging.getLogger(__name__)

PHASE_ICON  = {"stealth":"👁","accumulation":"🐋","expansion":"🚀",
               "euphoric":"🌕","distribution":"🚨","dead":"💀","unknown":"❓"}
CHAIN_EMOJI = {"solana":"◎","ethereum":"Ξ","base":"🔵","bsc":"🟡","arbitrum":"🔷"}
ACCUM_ICON  = {"extreme":"🔥","heavy":"🐋","moderate":"📊","light":"👀","none":"😴"}
ACCUM_LABEL = {
    "extreme": "EXTREME — Whale gom cực mạnh",
    "heavy":   "HEAVY — SM tích lũy lớn",
    "moderate":"MODERATE — Đang vào dần",
    "light":   "LIGHT — Mới bắt đầu",
    "none":    "NONE — Chưa có tín hiệu",
}

def fmt_usd(v):
    if not v: return "$0"
    if v>=1_000_000: return f"${v/1_000_000:.2f}M"
    if v>=1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def fmt_pct(v):
    return f"+{v:.1f}%" if v>=0 else f"{v:.1f}%"

def bar(v, mx=10):
    f=int((v/mx)*10); return "█"*f+"░"*(10-f)

def success_emoji(pct):
    if pct>=70: return "🟢"
    if pct>=50: return "🟡"
    return "🔴"


def get_alert_tier(gem):
    score = float(getattr(gem, "pre_pump_score", 0) or 0)
    mc = float(getattr(gem, "mc", 0) or 0)
    verdict = str(getattr(gem, "trade_verdict", "") or "").upper()

    if mc > 1_000_000 and "BUY" in verdict:
        return "LATE"
    if score >= 9.5:
        return "ULTRA"
    if "BUY ALERT" in verdict or score >= 8:
        return "BUY"
    if score >= 6:
        return "WATCH_STRONG"
    if score >= 4:
        return "WATCH"
    return "WATCH"


def tier_header(tier):
    if tier == "ULTRA":
        return "🚨🚨🚨 PARABOLIC GEM DETECTED"
    if tier == "BUY":
        return "🚀🚀🚀 BUY ALERT — EARLY GEM"
    if tier == "WATCH_STRONG":
        return "⚡ ACCUMULATION DETECTED"
    if tier == "LATE":
        return "⚠️ LATE MOMENTUM — NO CHASE"
    return "👀 EARLY WATCH"


def momentum_label(gem):
    if gem.pre_pump_score >= 9.5:
        return "PARABOLIC"
    if gem.pre_pump_score >= 8:
        return "BUILDING FAST"
    if gem.pre_pump_score >= 6:
        return "BUILDING"
    return "EARLY"


def phase_bar(tier):
    if tier == "ULTRA": return "[ BREAKOUT ██████ ]"
    if tier == "BUY": return "[ BREAKOUT █████░ ]"
    if tier == "WATCH_STRONG": return "[ ACCUMULATION █████░ ]"
    if tier == "LATE": return "[ LATE/FOMO ██████ ]"
    return "[ ACCUMULATION ███░░░ ]"


def build_alert(gem, rank=1):
    tier = get_alert_tier(gem)
    ce  = CHAIN_EMOJI.get(gem.chain,"⬡")
    pi  = PHASE_ICON.get(gem.phase,"❓")
    ai  = ACCUM_ICON.get(gem.accumulation_level,"❓")
    al  = ACCUM_LABEL.get(gem.accumulation_level,"?")
    se  = "🟢" if gem.pre_pump_score>=8 else "🟡" if gem.pre_pump_score>=6 else "🔴"
    re  = "🟢" if gem.rug_risk<=4 else "🟡" if gem.rug_risk<=6 else "🔴"
    bse = "🐋" if gem.bs_ratio24>=3 else "✅" if gem.bs_ratio24>=2 else "📊" if gem.bs_ratio24>=1 else "🚨"

    entry_low  = getattr(gem,'entry_mc_low',0) or gem.mc*0.95
    entry_high = getattr(gem,'entry_mc_high',0) or gem.mc*1.10

    lines = [
        f"{'═'*36}",
        f"{tier_header(tier)}",
        f"{'═'*36}",
        "",
        f"💎 GEM #{rank}  |  ${gem.ticker}",
        f"{ce} {gem.chain.upper()}  |  {pi} {gem.phase.upper()}",
        f"📛 {gem.name}",
        "",
        f"💰 MC: {fmt_usd(gem.mc)}  |  Liq: {fmt_usd(gem.liq)}",
        f"🔥 SCORE: {gem.pre_pump_score}/10  {bar(gem.pre_pump_score)}",
        "",
"📌 SCORE GUIDE",
"4–5   👀 WATCH",
"6–7   ⚡ WATCH STRONG",
"8–9   🚀 BUY ALERT",
"9.5+  🚨 ULTRA GEM",

"",
        f"♻️ Old ATH Risk: {getattr(gem, 'recycled_risk', 0)}/10",
        f"{re} Rug Risk: {gem.rug_risk}/10   {bar(gem.rug_risk)}",
        "",
    ]

    if tier in ("BUY", "ULTRA"):
        lines += [
            "📈 BREAKOUT DETECTED",
            f"• Sideway accumulation: YES",
            f"• Volume explosion: {gem.vol_accel}x",
            f"• Buyers dominance 24h: {gem.bs_ratio24}x  ({gem.buys24}/{gem.sells24})",
            f"• Buyers dominance 1h: {gem.bs_ratio1h}x",
            f"• Smart money flow: {'VERY STRONG' if tier == 'ULTRA' else 'STRONG'}",
            "",
            "🎯 ENTRY ZONE",
            f"NOW: {fmt_usd(entry_low)} — {fmt_usd(entry_high)} MC",
            f"DCA: {getattr(gem, 'dca_plan', 'N/A')}",
            f"Size: {gem.position_size}",
            "",
        ]
    elif tier == "WATCH_STRONG":
        lines += [
            "👀 STRONG WATCH",
            "• Sideway phase detected",
            f"• Volume increasing: {gem.vol_accel}x",
            f"• Buy pressure: {gem.bs_ratio24}x",
            "• Waiting breakout confirmation...",
            "",
            "🎯 BREAKOUT TRIGGER",
            f"BUY nếu MC vượt vùng {fmt_usd(max(gem.mc*1.10, 180000))} — {fmt_usd(max(gem.mc*1.35, 250000))}",
            "",
        ]
    elif tier == "LATE":
        lines += [
            "⚠️ TOKEN ĐÃ CHẠY XA",
            "• Không chase nếu entry đã qua vùng sớm",
            "• Chỉ canh pullback / retest",
            f"• Current MC: {fmt_usd(gem.mc)}",
            "",
        ]
    else:
        lines += [
            "👀 EARLY WATCH",
            "• Setup còn sớm",
            f"• Volume accel: {gem.vol_accel}x",
            f"• Buy pressure: {gem.bs_ratio24}x",
            "• Chờ breakout rõ hơn",
            "",
        ]

    lines += [
        f"🔥 MOMENTUM: {momentum_label(gem)}",
        "⏳ ESTIMATED PHASE:",
        phase_bar(tier),
        "",
        f"{'─'*36}",
        "📊 METRICS",
        f"MC: {fmt_usd(gem.mc)}  |  Age: {gem.age_days}d",
        f"Liq: {fmt_usd(gem.liq)}  |  DEX: {gem.dex_id}",
        f"Vol24: {fmt_usd(gem.vol24)}  |  Vol1h: {fmt_usd(gem.vol1)}",
        f"1h:{fmt_pct(gem.p1h)}  6h:{fmt_pct(gem.p6h)}  24h:{fmt_pct(gem.p24h)}",
        "",
        f"{'─'*36}",
        "💎 TARGETS",
        f"{success_emoji(gem.success_rate_tp1)} {gem.target1}",
        f"{success_emoji(gem.success_rate_tp2)} {gem.target2}",
        f"{success_emoji(gem.success_rate_tp3)} {gem.target3}",
        f"🌙 {gem.peak_estimate}",
        "",
        f"STOP: {gem.stop_loss}",
        f"R/R: {gem.risk_reward}",
        f"Hold: {gem.hold_period}",
        "",
        f"🐋 SM/WHALE ACCUMULATION",
        f"{ai} {al}",
        f"B/S 24h: {bse} {gem.bs_ratio24}x  ({gem.buys24}/{gem.sells24})",
        f"Vol Accel: {gem.vol_accel}x  |  VOL/MC: {gem.vol_mc_ratio}x",
        "",
    ]

    if gem.aeon_comparable:
        lines += [f"🔥 {gem.aeon_comparable}", ""]

    if gem.signals:
        lines.append("✅ SIGNALS")
        for s in gem.signals[:5]:
            lines.append(f"• {s}")
        lines.append("")

    if gem.warnings:
        lines.append("⚠️ WARNINGS")
        for w in gem.warnings[:4]:
            lines.append(f"• {w}")
        lines.append("")

    lines += [
        f"{'─'*36}",
        f"🔗 DexScreener:\n{gem.dex_url}",
    ]
    if gem.chain == "solana":
        lines.append(f"🦅 Birdeye:\nhttps://birdeye.so/token/{gem.address}")
    elif gem.chain in ("ethereum","base"):
        lines.append(f"🔍 Explorer:\nhttps://etherscan.io/token/{gem.address}")

    lines += [
        f"📋 {gem.address}",
        "",
        "⚠️ DYOR | Not financial advice | High risk",
    ]
    return "\n".join(lines)

def build_summary(gems, scan_num, total):
    if not gems:
        return f"🔍 Scan #{scan_num}\n{total} pairs scanned — no gems this round."
    lines = [
        f"🔍 Scan #{scan_num} — {len(gems)} gems",
        f"",
        f"TOP PRE-PUMP PICKS:",
    ]
    for i,g in enumerate(gems[:3],1):
        ai = ACCUM_ICON.get(g.accumulation_level,"❓")
        se = "🟢" if g.pre_pump_score>=8 else "🟡" if g.pre_pump_score>=6 else "🔴"
        lines += [
            f"",
            f"{i}. {se} ${g.ticker} {g.chain.upper()} | {g.pre_pump_score}/10",
            f"   MC:{fmt_usd(g.mc)} | {ai}{g.accumulation_level.upper()} | ATH Risk:{getattr(g, 'recycled_risk', 0)}/10",
            f"   B/S:{g.bs_ratio24}x | Vol↑:{g.vol_accel}x | {fmt_pct(g.p24h)}",
            f"   {g.trade_verdict}",
            f"   🎯 TP1 MC {fmt_usd(g.target1_mc)} ({g.target1_days}) | "
            f"TP2 MC {fmt_usd(g.target2_mc)} ({g.target2_days})",
            f"   🎯 TP3 MC {fmt_usd(g.target3_mc)} ({g.target3_days}) | "
            f"Peak MC {fmt_usd(g.mc * g.peak_x)} ({g.peak_days})",
            f"   {g.dex_url}",
        ]
    lines += ["", f"Scanned: {total} pairs"]
    return "\n".join(lines)


async def send_message(bot: Bot, chat_id: str, text: str):
    try:
        await bot.send_message(chat_id=chat_id,text=text,disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"send: {e}")

async def send_gem_alerts(bot,chat_id,new_gems):
    for i,gem in enumerate(new_gems[:5],1):
        await send_message(bot,chat_id,build_alert(gem,rank=i))
        await asyncio.sleep(0.8)

async def send_summary(bot,chat_id,gems,scan_num,total):
    await send_message(bot,chat_id,build_summary(gems,scan_num,total))
