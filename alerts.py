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


def fmt_usd(v):
    if not v: return "$0"
    if v>=1_000_000: return f"${v/1_000_000:.2f}M"
    if v>=1_000:     return f"${v/1_000:.0f}K"
    return f"${v:.0f}"

def fmt_pct(v):
    return f"+{v:.1f}%" if v>=0 else f"{v:.1f}%"

def bar(v, mx=10):
    f=int((v/mx)*10); return "█"*f+"░"*(10-f)

def build_alert(gem, rank=1):
    ce   = CHAIN_EMOJI.get(gem.chain,"⬡")
    pi   = PHASE_ICON.get(gem.phase,"❓")
    ai   = ACCUM_ICON.get(gem.accumulation_level,"❓")
    se   = "🟢" if gem.pre_pump_score>=8 else "🟡" if gem.pre_pump_score>=6 else "🔴"
    re   = "🟢" if gem.rug_risk<=4 else "🟡" if gem.rug_risk<=6 else "🔴"

    # Age label
    if 1.0 <= gem.age_days <= 5.0:
        age_str = f"{gem.age_days:.1f}d 🎯"
    elif gem.age_days < 1.0:
        age_str = f"{gem.age_days*24:.0f}h ⏳"
    else:
        age_str = f"{int(gem.age_days)}d"

    lines = [
        f"💎 #{rank} {gem.trade_verdict}",
        f"${gem.ticker} {ce}{gem.chain.upper()} {pi}{gem.phase.upper()} | Age: {age_str}",
        f"",
    ]

    # Breakout badge
    if getattr(gem,"breakout_candle",False) and gem.p1h >= 15:
        lines.append(f"🚨 BREAKOUT: Vol {gem.vol_accel:.1f}x | +{gem.p1h:.0f}% 1h")
    elif getattr(gem,"stealth_accum",False):
        lines.append(f"🐋 ACCUM {getattr(gem,'stealth_hours',0)}h | B/S {gem.bs_ratio24}x")
    elif getattr(gem,"flat_base",False):
        lines.append(f"📦 FLAT BASE {getattr(gem,'flat_base_hours',0)}h")

    lines += [
        f"",
        f"MC: {fmt_usd(gem.mc)} | Liq: {fmt_usd(gem.liq)} | Vol1h: {fmt_usd(gem.vol1)}",
        f"1h: {fmt_pct(gem.p1h)} | 24h: {fmt_pct(gem.p24h)} | B/S: {gem.bs_ratio24}x",
        f"",
        f"{se} Score: {gem.pre_pump_score}/10 {bar(gem.pre_pump_score)} {re} Rug: {gem.rug_risk}/10",
        f"",
    ]

    # x20 target — luôn hiển thị
    x20_mc = getattr(gem,"x20_mc",0) or gem.mc * 20
    x20_p  = getattr(gem,"x20_prob",0)
    x20_d  = "~7 ngày"  # target 7 ngày
    lines.append(f"🚀 x20 → {fmt_usd(x20_mc)} | ETA {x20_d} | {x20_p}% xác suất")

    # Targets
    lines += [
        f"TP1: {gem.target1_x}x {fmt_usd(gem.target1_mc)} ({gem.target1_days})",
        f"TP2: {gem.target2_x}x {fmt_usd(gem.target2_mc)} ({gem.target2_days})",
        f"TP3: {gem.target3_x}x {fmt_usd(gem.target3_mc)} ({gem.target3_days})",

    ]

    # Entry
    lines += [
        f"📍 {gem.entry_zone}",
        f"MC Zone: {fmt_usd(gem.entry_mc_low)} — {fmt_usd(gem.entry_mc_high)}",
        f"",
    ]

    # GMGN security (compact)
    gmgn_lp  = getattr(gem,"gmgn_lp_burned",False)
    gmgn_rnc = getattr(gem,"gmgn_renounced",False)
    gmgn_dev = getattr(gem,"gmgn_dev_pct",0)
    gmgn_ins = getattr(gem,"gmgn_insider_pct",0)
    gmgn_sm  = getattr(gem,"gmgn_sm_wallets",0)
    if gmgn_lp or gmgn_rnc or gmgn_sm > 0 or gmgn_dev > 0:
        sec = []
        sec.append("LP🔒" if gmgn_lp else "LP⚠️")
        sec.append("RNK✅" if gmgn_rnc else "RNK❌")
        if gmgn_dev > 0: sec.append(f"Dev{gmgn_dev:.0f}%{'✅' if gmgn_dev<3 else '⚠️'}")
        if gmgn_ins > 0: sec.append(f"In{gmgn_ins:.0f}%{'✅' if gmgn_ins<10 else '🚨'}")
        if gmgn_sm > 0:  sec.append(f"SM🐋{gmgn_sm}")
        lines.append("  ".join(sec))
        lines.append("")

    # Dev verdict (compact)
    dev_s = getattr(gem,"dev_score",0)
    hold_q= getattr(gem,"hold_quality","")
    if dev_s > 0:
        dev_e = "🟢" if dev_s>=8 else "🟡" if dev_s>=6 else "🔴"
        lines.append(f"Dev: {dev_e}{dev_s}/10 | Hold: {hold_q}")
        lines.append("")

    # Top signals (max 2)
    sigs = gem.signals[:2] if gem.signals else []
    warn = gem.warnings[:1] if gem.warnings else []
    for s in sigs: lines.append(s)
    for w in warn: lines.append(w)
    if sigs or warn: lines.append("")

    # Link
    lines.append(f"🔗 {gem.dex_url}")
    if gem.chain == "solana":
        lines.append(f"🦅 birdeye.so/token/{gem.address}")

    lines.append(f"⚠️ DYOR | High risk")
    return "\n".join(lines)


def build_summary(gems, scan_num, total):
    if not gems:
        return None  # Không gửi nếu không có gem
    lines = [f"🔍 Scan #{scan_num} | {len(gems)} gems | {total} pairs"]
    for i,g in enumerate(gems[:5],1):
        se = "🟢" if g.pre_pump_score>=8 else "🟡" if g.pre_pump_score>=6 else "🔴"
        x20_str = f" | x20→{fmt_usd(g.x20_mc)}({g.x20_prob}%)" if getattr(g,"x20_feasible",False) and g.x20_prob>0 else ""
        lines.append(
            f"{i}. {se} ${g.ticker} {g.chain.upper()} {g.age_days:.1f}d | "
            f"MC:{fmt_usd(g.mc)} | {g.pre_pump_score}/10{x20_str}"
        )
        lines.append(f"   {g.dex_url}")
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
    msg = build_summary(gems,scan_num,total)
    if msg:
        await send_message(bot,chat_id,msg)
