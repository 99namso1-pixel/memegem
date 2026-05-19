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


def build_alert(gem, rank=1):
    ce  = CHAIN_EMOJI.get(gem.chain,"⬡")
    pi  = PHASE_ICON.get(gem.phase,"❓")
    ai  = ACCUM_ICON.get(gem.accumulation_level,"❓")
    al  = ACCUM_LABEL.get(gem.accumulation_level,"?")
    se  = "🟢" if gem.pre_pump_score>=8 else "🟡" if gem.pre_pump_score>=6 else "🔴"
    re  = "🟢" if gem.rug_risk<=4 else "🟡" if gem.rug_risk<=6 else "🔴"
    bse = "🐋" if gem.bs_ratio24>=3 else "✅" if gem.bs_ratio24>=2 else "📊" if gem.bs_ratio24>=1 else "🚨"

    lines = [
        f"{'='*36}",
        f"💎 GEM #{rank}  {gem.trade_verdict}",
        f"{'='*36}",
        f"",
        f"${gem.ticker}  {ce}{gem.chain.upper()}  {pi}{gem.phase.upper()}",
        f"📛 {gem.name}",
        f"",
        *(
            [f"🚨 BREAKOUT CANDLE — {getattr(gem,'flat_base_hours',0)}h tích lũy VỪA VỠ!",
             f"{'─'*36}", f""]
            if getattr(gem,'breakout_candle',False) and getattr(gem,'flat_base',False)
            else [f"🏆 FLAT BASE — {getattr(gem,'flat_base_hours',0)}h tích lũy, sắp bứt",f""]
            if getattr(gem,'flat_base',False) else []
        ),
        *(
            [f"🎯 Pre-ATH: Token mới, chưa từng pump — còn nguyên room", f""]
            if getattr(gem,'pre_ath',False) and getattr(gem,'age_days',999) < 7
            and getattr(gem,'mc',0) < 1_000_000 else []
        ),
        f"🤖 {se} Pre-Pump: {gem.pre_pump_score}/10  {bar(gem.pre_pump_score)}",
        f"   {re} Rug Risk: {gem.rug_risk}/10   {bar(gem.rug_risk)}",
        f"",
        f"🐋 SM/WHALE ACCUMULATION",
        f"  {ai} {al}",
        f"  B/S 24h: {bse} {gem.bs_ratio24}x  ({gem.buys24} / {gem.sells24})",
        f"  B/S  1h: {gem.bs_ratio1h}x",
        f"  Vol Accel: {gem.vol_accel}x  |  VOL/MC: {gem.vol_mc_ratio}x",
        f"",
        f"{'─'*36}",
        f"📊 METRICS",
        f"  MC:    {fmt_usd(gem.mc)}  |  Age: {gem.age_days}d",
        f"  Liq:   {fmt_usd(gem.liq)}  |  DEX: {gem.dex_id}",
        f"  Vol24: {fmt_usd(gem.vol24)}  |  Vol1h: {fmt_usd(gem.vol1)}",
        f"  1h:{fmt_pct(gem.p1h)}  6h:{fmt_pct(gem.p6h)}  24h:{fmt_pct(gem.p24h)}",
        f"",
        f"{'─'*36}",
        f"📈 TRADE PLAN",
        f"",
        f"  ENTRY:  {gem.entry_zone}",
        f"  MC Zone: {fmt_usd(getattr(gem,'entry_mc_low',0) or gem.mc*0.95)} — {fmt_usd(getattr(gem,'entry_mc_high',0) or gem.mc*1.08)}",
        f"  DCA:    {getattr(gem, 'dca_plan', 'N/A')}",
        f"  Size:   {gem.position_size}",
        f"",
        f"  TARGETS (xác suất đạt):",
        f"  {success_emoji(gem.success_rate_tp1)} {gem.target1}",
        f"     Xác suất: {gem.success_rate_tp1}% token đạt TP1",
        f"",
        f"  {success_emoji(gem.success_rate_tp2)} {gem.target2}",
        f"     Xác suất: {gem.success_rate_tp2}% token đạt TP2",
        f"",
        f"  {success_emoji(gem.success_rate_tp3)} {gem.target3}",
        f"     Xác suất: {gem.success_rate_tp3}% token đạt TP3",
        f"",
        f"  🌙 {gem.peak_estimate}",
        f"",
        f"  STOP:   {gem.stop_loss}",
        f"  R/R:    {gem.risk_reward}",
        f"  Hold:   {gem.hold_period}",
        f"",
        f"  Median peak (historical): {gem.median_peak_x}x",
        f"  Best case (p75):          {gem.best_case_x}x",
    ]

    if gem.aeon_comparable:
        lines += [f"", f"  🔥 {gem.aeon_comparable}"]

    lines += [
        f"",
    ]

    # GMGN Security block
    gmgn_sigs  = getattr(gem,"gmgn_signals",[])
    gmgn_warns = getattr(gem,"gmgn_warnings",[])
    gmgn_rug   = getattr(gem,"gmgn_rug_score",0)
    gmgn_ins   = getattr(gem,"gmgn_insider_pct",0)
    gmgn_dev   = getattr(gem,"gmgn_dev_pct",0)
    gmgn_snp   = getattr(gem,"gmgn_sniper_count",0)
    gmgn_sm    = getattr(gem,"gmgn_sm_wallets",0)
    gmgn_kol   = getattr(gem,"gmgn_kol_count",0)
    gmgn_lp    = getattr(gem,"gmgn_lp_burned",False)
    gmgn_rnc   = getattr(gem,"gmgn_renounced",False)
    gmgn_honey = getattr(gem,"gmgn_honeypot",False)

    if gmgn_rug > 0 or gmgn_sm > 0 or gmgn_ins > 0:
        lines += [
            f"{'─'*36}",
            f"🔐 GMGN SECURITY",
            f"  🍯 Honeypot:  {'🚨 YES' if gmgn_honey else '✅ No'}",
            f"  🔒 LP Burned: {'✅ Yes' if gmgn_lp else '❌ No'}",
            f"  📜 Renounced: {'✅ Yes' if gmgn_rnc else '❌ No'}",
            f"  👤 Insider:   {gmgn_ins:.0f}%  {'🚨' if gmgn_ins>30 else '✅' if gmgn_ins<5 else '⚠️'}",
            f"  👨‍💻 Dev hold:  {gmgn_dev:.0f}%  {'✅' if gmgn_dev==0 else '⚠️'}",
            f"  🎯 Snipers:   {gmgn_snp}  {'⚠️' if gmgn_snp>20 else '✅'}",
            f"",
        ]
        if gmgn_sm > 0 or gmgn_kol > 0:
            lines += [
                f"💰 SMART MONEY (GMGN)",
                f"  🐋 SM Wallets: {gmgn_sm}  {'🔥' if gmgn_sm>=3 else '👀' if gmgn_sm>0 else '—'}",
                f"  ⭐ KOL Wallets: {gmgn_kol}  {'🔥' if gmgn_kol>=2 else '👀' if gmgn_kol>0 else '—'}",
                f"",
            ]
        if gmgn_sigs:
            for s in gmgn_sigs[:3]:
                lines.append(f"  {s}")
            lines.append("")
        if gmgn_warns:
            for w in gmgn_warns[:3]:
                lines.append(f"  {w}")
            lines.append("")

    # X/Twitter Social Score block
    x_total  = getattr(gem,"x_social_total",0)
    x_fomo   = getattr(gem,"x_fomo_score",0)
    x_viral  = getattr(gem,"x_viral_score",0)
    x_kol    = getattr(gem,"x_kol_score",0)
    x_ment   = getattr(gem,"x_mentions",0)
    x_t1     = getattr(gem,"x_tier1",0)
    x_t2     = getattr(gem,"x_tier2",0)
    x_t3     = getattr(gem,"x_tier3",0)
    x_kols   = getattr(gem,"x_kol_mentions",0)
    x_top    = getattr(gem,"x_top_kol","")
    x_sigs   = getattr(gem,"x_signals",[])
    x_viral_f= getattr(gem,"x_is_viral",False)

    if x_total > 0 or x_ment > 0:
        fomo_e  = "🔥" if x_fomo>=7  else "📊" if x_fomo>=4  else "😴"
        viral_e = "🌐" if x_viral>=7 else "📈" if x_viral>=4 else "—"
        kol_e   = "⭐" if x_kol>=5   else "—"
        lines += [
            f"{'─'*36}",
            f"🐦 X/TWITTER SOCIAL SCORE",
            f"  FOMO:    {x_fomo}/10  {fomo_e}",
            f"  Viral:   {x_viral}/10  {viral_e}",
            f"  KOL:     {x_kol}/10   {kol_e}",
            f"  TOTAL:   {x_total}/10  {'🚨VIRAL' if x_viral_f else ''}",
            f"",
            f"  Mentions: {x_ment} tweets",
            f"  KOLs: T1={x_t1} T2={x_t2} T3={x_t3}",
        ]
        if x_top:
            lines += [f"  🏆 TOP KOL: {x_top}"]
        for sig in x_sigs[:3]:
            lines.append(f"  {sig}")
        lines.append("")

    if gem.signals:
        lines.append("✅ ON-CHAIN SIGNALS")
        for s in gem.signals[:4]:
            lines.append(f"  {s}")
        lines.append("")

    if gem.warnings:
        lines.append("⚠️ WARNINGS")
        for w in gem.warnings:
            lines.append(f"  {w}")
        lines.append("")

    lines += [
        f"{'─'*36}",
        f"🔗 {gem.dex_url}",
    ]
    if gem.chain == "solana":
        lines.append(f"🦅 https://birdeye.so/token/{gem.address}")
    elif gem.chain in ("ethereum","base"):
        lines.append(f"🔍 https://etherscan.io/token/{gem.address}")

    lines += [
        f"📋 {gem.address}",
        f"",
        f"⚠️ DYOR | Not financial advice | High risk",
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
            f"   MC:{fmt_usd(g.mc)} | {ai}{g.accumulation_level.upper()}",
            f"   B/S:{g.bs_ratio24}x | Vol↑:{g.vol_accel}x | {fmt_pct(g.p24h)}",
            f"   {g.trade_verdict}",
            f"   TP1:{g.target1_x}x({g.target1_days}) "
            f"TP2:{g.target2_x}x({g.target2_days}) "
            f"TP3:{g.target3_x}x({g.target3_days})",
            f"   Peak est: {g.peak_x}x ({g.peak_days})",
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